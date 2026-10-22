"""agent 主循环：模型 → 工具 → 观察 → 模型 → …… → 最终回复。

模型在这个应用里「像在家一样」：自己决定怎么把题目弄出来。循环只做
调度——解析模型的工具调用、执行、把观察喂回去，直到它给出最终回复
（JSON：reply + action，和前端约定的动作协议一致）。

思维链对用户可见：每步工具调用前模型写的 thought、推理模型的
reasoning_content、JSON 前面漏出来的话，都收进 steps / reasoning
原样展示——过程透明，用户才知道它为什么这么干。

协议用文本 JSON 而不是 OpenAI 原生 function calling：各家兼容端点
对 tools 参数的支持参差不齐，文本协议在任何兼容实现上都能跑。
"""

import json
import re
import time
import concurrent.futures as cf

from app.db import new_id
from app.lib.agent.tools import execute_tool, dispatch_task
from app.prompts import DEFAULT_AGENT_SYSTEM_PROMPT
from app.lib.ai import AiError
from app.lib.ai.client import extract_json

MAX_STEPS = 12             # 工具调用次数上限（一轮可发多个并发动作）
DEADLINE_SECONDS = 600     # 整个循环的硬时限（10 分钟）
MAX_HISTORY = 20           # 带上限轮数的前端历史
OBSERVATION_CAP = 6000     # 单次观察喂回模型时的截断
THOUGHT_CAP = 500          # 单条思考展示时的截断

# 内置默认提示词；设置里若存了自定义值则覆盖（见 effective_agent_prompt）。
AGENT_SYSTEM_PROMPT = DEFAULT_AGENT_SYSTEM_PROMPT


def _parse(reply: str):
    try:
        return extract_json(reply)
    except Exception:
        return None


def _thought_of(reply: str, payload, reasoning: str = "") -> str:
    """这一步之前模型想了什么。优先协议里的 thought 字段，再推理模型的
    reasoning_content，最后是 JSON 前面漏出来的那段话。"""
    if isinstance(payload, dict):
        raw = payload.get("thought")
        if isinstance(raw, str) and raw.strip():
            return raw.strip()[:THOUGHT_CAP]
    if reasoning:
        return reasoning[:THOUGHT_CAP]
    head = re.sub(r"```(?:json)?", "", reply.split("{", 1)[0]).strip()
    if 4 < len(head) < THOUGHT_CAP:
        return head
    return ""


def _source_lines(source_rows, selected_ids: set[str]) -> str:
    if not source_rows:
        return "（用户还没有添加材料）"
    lines = []
    for row in source_rows:
        mark = "已选" if row["id"] in selected_ids else "未选"
        lines.append(f"- （{mark}）{row['id']}｜{row['name']}")
    return "\n".join(lines)


def _final_action(raw):
    """收尾时的动作校验：形状对就行，id 真假由后续端点把关。

    支持两种动作：
    - extract_direct：直接触发提取（前端自动执行）
    - confirm：暂停等用户确认（前端只展示说明、不自动执行，用户回复后继续）
    """
    if not isinstance(raw, dict):
        return None
    action_type = raw.get("type")
    if action_type == "extract_direct":
        ids = raw.get("sourceIds")
        if not isinstance(ids, list):
            return None
        picked = [str(item) for item in ids if isinstance(item, str)][:20]
        job_id = raw.get("jobId")
        job_id = job_id if isinstance(job_id, str) and job_id else None
        if not picked and not job_id:
            return None
        instruction = raw.get("instruction")
        action = {
            "type": "extract_direct",
            "sourceIds": picked,
            "instruction": instruction.strip()[:2000] if isinstance(instruction, str) else "",
        }
        if job_id:
            action["jobId"] = job_id
        return action
    if action_type == "confirm":
        reason = raw.get("reason")
        plan = raw.get("plan")
        return {
            "type": "confirm",
            "reason": reason.strip()[:1000] if isinstance(reason, str) else "",
            "plan": plan.strip()[:1000] if isinstance(plan, str) else "",
        }
    return None


def _effective_prompt(conn) -> str:
    """设置里可覆盖的系统提示词；读不到就退回内置默认。

    局部 import：避免 settings ↔ agent 包在模块初始化阶段互相触发。
    """
    if conn is not None:
        try:
            from app import settings as settings_store

            return settings_store.get_effective_agent_prompt(conn)
        except Exception:
            pass
    return DEFAULT_AGENT_SYSTEM_PROMPT


def _build_messages(message: str, history: list, pool_rows, selected_ids: set[str], prompt: str, script_code: str | None = None) -> list[dict]:
    messages = [{"role": "system", "content": prompt}]
    for turn in history[-MAX_HISTORY:]:
        role = turn.get("role")
        content = str(turn.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content[:4000]})
    attachment = f"材料清单：\n{_source_lines(pool_rows, selected_ids)}\n\n"
    if script_code is not None:
        attachment += (
            "（你正在调试的脚本，完整代码如下，直接用 update_script 改它、用 run_script 跑它）\n"
            f"```python\n{script_code}\n```\n\n"
        )
    attachment += f"用户说：{message}"
    messages.append({"role": "user", "content": attachment})
    return messages


def _run_wait_actions(actions: list, ctx) -> list:
    """并发执行一轮里「等待」的那几个工具，按顺序收回结果。

    execute_tool 每次自己开连接，所以这里多线程并发也是线程安全的。
    返回 [(tool_name, ToolResult, ms), ...]，顺序与 actions 一致。
    """
    def _one(action):
        started = time.monotonic()
        result = execute_tool(str(action.get("tool") or ""), action.get("args") or {}, ctx)
        return str(action.get("tool") or ""), result, int((time.monotonic() - started) * 1000)

    if len(actions) <= 1:
        return [_one(actions[0])] if actions else []

    with cf.ThreadPoolExecutor(max_workers=min(len(actions), 8)) as pool:
        futures = {i: pool.submit(_one, action) for i, action in enumerate(actions)}
    return [futures[i].result() for i in range(len(actions))]


def run_agent_stream(ctx, message: str, history: list, selected_rows: list, pool_rows: list,
                     script_id: str | None = None, selected_ids: set[str] | None = None):
    """跑一轮 agent 循环，**每完成一步就 yield 一个事件**（流式）。

    事件类型：
    - {"type": "step", "tool", "ok", "note", "thought", "ms"}：一步工具调用，
      ms 是这一步的总耗时（模型思考 + 工具执行）
    - {"type": "reply", "reply", "thought", "action", "ms_total"}：最终回复
    - {"type": "error", "message"}：模型调用失败

    流式是为了让用户实时看见思维链在长——老写法是整个循环跑完才返回，
    慢模型下界面几分钟没有动静，过程全憋在最后一次性倒出来。
    """
    selected_ids = selected_ids or getattr(ctx, "selected_ids", None) or {row["id"] for row in selected_rows}
    # 调试模式：把正在调试的脚本代码注入对话，模型就能直接改它、跑它
    script_code = None
    script_id = script_id or getattr(ctx, "script_id", None)
    if script_id and getattr(ctx, "conn", None) is not None:
        row = ctx.conn.execute(
            "SELECT code FROM extraction_scripts WHERE id = ?", (script_id,)
        ).fetchone()
        if row is not None:
            script_code = row["code"]
    messages = _build_messages(
        message, history, pool_rows, selected_ids, _effective_prompt(ctx.conn), script_code
    )

    started = time.monotonic()
    deadline = started + DEADLINE_SECONDS
    final = None
    final_reasoning = ""
    exhausted = False

    for _ in range(MAX_STEPS):
        if time.monotonic() > deadline:
            exhausted = True
            break
        step_started = time.monotonic()
        try:
            reply, reasoning = ctx.client.chat(
                messages, temperature=0.2, max_tokens=8000, return_reasoning=True
            )
        except AiError as error:
            yield {"type": "error", "message": str(error)}
            return
        payload = _parse(reply)

        if isinstance(payload, dict) and (payload.get("tool") or payload.get("actions")):
            thought = _thought_of(reply, payload, reasoning)
            if payload.get("actions"):
                actions = [a for a in payload["actions"] if isinstance(a, dict) and a.get("tool")]
            else:
                actions = [{"tool": payload.get("tool"), "args": payload.get("args"), "detach": payload.get("detach")}]
            if not actions:
                # 没有合法的工具调用：当成最终回复收尾
                final = payload if isinstance(payload, dict) else {"reply": reply.strip(), "action": None}
                final_reasoning = thought
                break

            wait_actions = [a for a in actions if not a.get("detach")]
            detach_actions = [a for a in actions if a.get("detach")]

            if wait_actions:
                wait_results = _run_wait_actions(wait_actions, ctx)
                messages.append({"role": "assistant", "content": reply.strip()[:4000]})
                for tool_name, result, ms in wait_results:
                    yield {
                        "type": "step",
                        "tool": tool_name,
                        "ok": result.ok,
                        "note": result.note,
                        "thought": thought,
                        "ms": ms,
                    }
                    observation = json.dumps(result.output, ensure_ascii=False)
                    messages.append({
                        "role": "user",
                        "content": f"观察（{tool_name}）：{observation[:OBSERVATION_CAP]}",
                    })

            for action in detach_actions:
                task_id = new_id()
                dispatch_task(action, ctx, task_id)
                yield {
                    "type": "step",
                    "tool": str(action.get("tool") or ""),
                    "ok": True,
                    "note": f"后台运行（taskId={task_id}）",
                    "thought": thought,
                    "ms": int((time.monotonic() - step_started) * 1000),
                }
                messages.append({"role": "assistant", "content": reply.strip()[:4000]})
                messages.append({
                    "role": "user",
                    "content": f"观察：后台任务已启动 taskId={task_id}，之后用 get_task 取结果",
                })
            continue

        # 不是工具调用：就是最终回复（协议 JSON，或没协议的纯文本）
        final = payload if isinstance(payload, dict) else {"reply": reply.strip(), "action": None}
        final_reasoning = _thought_of(reply, payload, reasoning)
        break
    else:
        exhausted = True

    if final is None:
        # 步骤用尽或超时：收尾一次，禁止再调工具
        messages.append({
            "role": "user",
            "content": "工具步骤已用尽。不要再调用工具，基于已有观察直接给出最终 JSON："
                       '{"reply": "...", "action": ...}',
        })
        fallback = ""
        try:
            reply, reasoning = ctx.client.chat(
                messages, temperature=0.2, max_tokens=4000, return_reasoning=True
            )
            final = _parse(reply)
            final_reasoning = _thought_of(reply, final, reasoning)
            if not isinstance(final, dict):
                fallback = reply.strip()
        except AiError:
            final = None
            final_reasoning = ""
        if not isinstance(final, dict):
            final = {"reply": fallback or "这次没能完成，换个说法再试试。", "action": None}

    reply_text = str(final.get("reply") or "").strip()
    if not reply_text:
        # 步骤用尽后模型给了个没 reply 的 JSON：也不能让界面空着
        reply_text = "步骤用尽或超时，先按已有观察收尾。" if exhausted else "（无回复）"
    yield {
        "type": "reply",
        "reply": reply_text,
        "thought": final_reasoning,
        "action": _final_action(final.get("action")),
        "ms_total": int((time.monotonic() - started) * 1000),
    }


def run_agent(ctx, message: str, history: list, selected_rows: list, pool_rows: list) -> dict:
    """跑一轮 agent 循环，收集成 dict 返回 {reply, action, steps, reasoning, ms}。

    selected_rows 是左侧勾选的材料（标注「已选」）；pool_rows 是可选池
    （默认用户全部材料），模型可以点名池里任意一份。
    非流式路径（测试、兼容旧端点）走这里；线上前端用流式。
    """
    steps: list[dict] = []
    reply = ""
    thought = ""
    action = None
    ms_total = 0
    for event in run_agent_stream(ctx, message, history, selected_rows, pool_rows):
        if event["type"] == "step":
            steps.append({
                "tool": event["tool"],
                "ok": event["ok"],
                "note": event["note"],
                "thought": event["thought"],
                "ms": event["ms"],
            })
        elif event["type"] == "reply":
            reply = event["reply"]
            thought = event["thought"]
            action = event["action"]
            ms_total = event["ms_total"]
        elif event["type"] == "error":
            raise AiError(event["message"])
    return {
        "reply": reply or "（无回复）",
        "action": action,
        "steps": steps,
        "reasoning": thought,
        "ms": ms_total,
    }
