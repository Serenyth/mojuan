"""模式 A：AI 直接提取。

流程：选中的材料 → run_direct 跑模型 → 候选题目存进 extraction_jobs（不入库）
→ 人工在导入页审核、编辑、勾选 → 确认时走 POST /api/questions/batch 才落库。

契约要求「AI 产出必须经人工审核预览才能入库」，所以这里刻意不碰 questions 表。
job 记录留着是为了刷新页面后能恢复候选（GET /api/extract/jobs/{id}）。

POST /api/extract/chat 是导入助手 agent：模型自己决定怎么把题目弄出来
（抓网页 / 写代码 / 造工具 / 抽题），循环在 app.lib.agent.loop。
"""

import json
import sqlite3
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.db import DATA_DIR, _connect, get_db, new_id
from app.deps import require_source, require_user
from app.lib.agent import AgentContext
from app.lib.agent.loop import run_agent, run_agent_stream
from app.lib.ai import AiClient, AiError
from app.lib.ai.client import extract_json
from app.lib.extract.direct import parse_questions
from app.lib.extract.jobs import run_and_store, run_script_job
from app.routers.conversations import save_message

router = APIRouter()

MAX_HISTORY_TURNS = 20   # 从会话记录重建历史时取的消息轮数


class DirectExtractBody(BaseModel):
    sourceIds: list[str] = Field(min_length=1, max_length=20)
    instruction: str = Field(default="", max_length=2000)


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)


class ChatBody(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=40)
    sourceIds: list[str] = Field(default_factory=list, max_length=20)
    scriptId: str | None = None


class ChatStreamBody(BaseModel):
    """流式对话：history 由服务端按 conversationId 从会话记录重建，
    前端只带消息与勾选的材料。"""
    message: str = Field(min_length=1, max_length=2000)
    conversationId: str | None = None
    sourceIds: list[str] = Field(default_factory=list, max_length=20)
    scriptId: str | None = None


class ScriptExtractBody(BaseModel):
    """阶段四：用某个提取脚本跑一组材料。"""
    scriptId: str = Field(min_length=1, max_length=64)
    sourceIds: list[str] = Field(min_length=1, max_length=20)


def _job_dict(row) -> dict:
    return {
        "id": row["id"],
        "sourceIds": json.loads(row["source_ids"]) if row["source_ids"] else [],
        "mode": row["mode"],
        "status": row["status"],
        "scriptId": row["script_id"],
        "stats": json.loads(row["stats"]) if row["stats"] else {},
        "createdAt": row["created_at"],
    }


@router.post("/api/extract/direct")
def post_extract_direct(
    payload: DirectExtractBody,
    user: Annotated[dict, Depends(require_user)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
):
    # 先验材料归属（404），再验接口配置（422）——顺序与旧版一致
    for source_id in payload.sourceIds:
        require_source(conn, source_id, user)

    try:
        client = AiClient.from_conn(conn)
    except AiError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    try:
        outcome = run_and_store(
            conn, user["id"], client, payload.sourceIds, payload.instruction
        )
    except AiError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    row = conn.execute(
        "SELECT * FROM extraction_jobs WHERE id = ?", (outcome["jobId"],)
    ).fetchone()
    return {"job": _job_dict(row), "questions": outcome["questions"]}


class ParseBody(BaseModel):
    text: str = Field(min_length=1, max_length=200_000)


@router.post("/api/extract/parse")
def post_extract_parse(
    payload: ParseBody,
    user: Annotated[dict, Depends(require_user)],
):
    """把外部 AI 整理好的题目文本（JSON 数组）解析成统一候选题：不调模型、不入库。

    前端「数据格式 / 粘贴导入」用：用户把可复制的提示词交给外部 AI，再把结果粘回来。
    失败时尽量说清「哪一步、收到什么」——是 JSON 语法问题、结构不对，还是字段名不对。
    """
    try:
        data = extract_json(payload.text)
    except Exception as error:  # 脱围栏/找平衡 JSON 失败时抛 AiResponseError
        raise HTTPException(status_code=422, detail=str(error)) from error

    # 兼容 [] 与 {"questions": [...]} 两种顶层；顺便给出可诊断的报错
    raw_list: list | None = data if isinstance(data, list) else None
    if raw_list is None and isinstance(data, dict):
        for key in ("questions", "items", "data", "list"):
            if isinstance(data.get(key), list):
                raw_list = data[key]
                break
    if raw_list is None:
        if isinstance(data, dict):
            keys = "、".join(str(key) for key in list(data.keys())[:10]) or "（无字段）"
            got = f"顶层是对象（字段：{keys}），期待 JSON 数组或 {{\"questions\": [...]}}"
        else:
            got = f"顶层是 {type(data).__name__}，期待 JSON 数组"
        preview = (
            json.dumps(data, ensure_ascii=False)[:300]
            if not isinstance(data, str)
            else data[:300]
        )
        raise HTTPException(status_code=422, detail=f"结构不对：{got}。收到内容：{preview}")

    try:
        questions = parse_questions(raw_list)
    except AiError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    if not questions:
        if not raw_list:
            raise HTTPException(status_code=422, detail="JSON 是空数组，里面没有题目。")
        first = raw_list[0]
        preview = (
            json.dumps(first, ensure_ascii=False)[:300]
            if isinstance(first, (dict, list))
            else str(first)[:300]
        )
        raise HTTPException(
            status_code=422,
            detail=(
                f"共 {len(raw_list)} 条记录，但没有一条能解析：每条都要是对象且包含 "
                f"content（题干）字段。首条收到：{preview}"
            ),
        )
    return {"questions": questions}


@router.post("/api/extract/chat")
def post_extract_chat(
    payload: ChatBody,
    user: Annotated[dict, Depends(require_user)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
):
    """导入助手 agent：模型自己决定怎么把题目弄出来。

    循环内部可能抓网页、跑代码、创建工具、触发提取；这里只负责组装
    上下文（勾选的材料 + 用户全部材料作可选池）并把最终回复与步骤
    轨迹返回给前端。一次循环最长 10 分钟、最多 8 次工具调用。
    """
    for source_id in payload.sourceIds:
        require_source(conn, source_id, user)

    pool_rows = conn.execute(
        "SELECT * FROM sources WHERE owner_id = ? ORDER BY created_at DESC, id LIMIT 50",
        (user["id"],),
    ).fetchall()

    try:
        client = AiClient.from_conn(conn)
    except AiError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    selected_ids = set(payload.sourceIds)
    ctx = AgentContext(
        conn=conn, user_id=user["id"], client=client,
        is_admin=bool(user.get("isAdmin")), script_id=payload.scriptId, selected_ids=selected_ids,
    )
    try:
        outcome = run_agent(
            ctx,
            payload.message,
            [turn.model_dump() for turn in payload.history],
            [row for row in pool_rows if row["id"] in selected_ids],
            pool_rows,
        )
    except AiError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    return outcome


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _conversation_history(conn, conversation_id: str) -> list[dict]:
    """从会话记录重建模型历史：只要对话文本，工具轨迹不喂回模型。"""
    rows = conn.execute(
        """
        SELECT role, text FROM agent_messages
        WHERE conversation_id = ? AND kind = 'text' AND role IN ('user', 'assistant')
        ORDER BY rowid DESC LIMIT ?
        """,
        (conversation_id, MAX_HISTORY_TURNS),
    ).fetchall()
    return [{"role": row["role"], "content": row["text"]} for row in reversed(rows)]


@router.post("/api/extract/chat/stream")
def post_extract_chat_stream(
    payload: ChatStreamBody,
    user: Annotated[dict, Depends(require_user)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
):
    """流式版导入助手：每完成一步就推一个 SSE 事件。

    思维链随跑随长，不用等整个循环憋完才看见；每步带耗时 ms，收尾带
    总耗时，全部落进会话记录。事件序列：
    conversation（会话 id）→ step*（工具轨迹）→ reply（最终回复+动作）。
    出错时最后一个事件是 error。
    """
    for source_id in payload.sourceIds:
        require_source(conn, source_id, user)

    pool_rows = conn.execute(
        "SELECT * FROM sources WHERE owner_id = ? ORDER BY created_at DESC, id LIMIT 50",
        (user["id"],),
    ).fetchall()

    try:
        client = AiClient.from_conn(conn)
    except AiError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    conversation_id = payload.conversationId
    if conversation_id:
        row = conn.execute(
            "SELECT id FROM agent_conversations WHERE id = ? AND owner_id = ?",
            (conversation_id, user["id"]),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="会话不存在")
    else:
        conversation_id = new_id()
        conn.execute(
            "INSERT INTO agent_conversations (id, owner_id, title) VALUES (?, ?, ?)",
            (conversation_id, user["id"], payload.message.strip()[:24] or "新会话"),
        )
        conn.commit()

    history = _conversation_history(conn, conversation_id)
    selected_ids = set(payload.sourceIds)
    # 流式生成器在依赖关闭之后、由线程池驱动，因此不能用注入的 conn；
    # 它自己开一条连接（工具执行也要用 conn），跑完关闭。
    pool_subset = [row for row in pool_rows if row["id"] in selected_ids]

    def events():
        db = _connect()
        try:
            yield _sse({"type": "conversation", "id": conversation_id})
            save_message(db, conversation_id, "user", "text", payload.message)
            ctx = AgentContext(
                conn=db, user_id=user["id"], client=client,
                is_admin=bool(user.get("isAdmin")), script_id=payload.scriptId,
                selected_ids=selected_ids,
            )
            try:
                for event in run_agent_stream(
                    ctx,
                    payload.message,
                    history,
                    pool_subset,
                    pool_rows,
                ):
                    if event["type"] == "step":
                        save_message(
                            db, conversation_id, "assistant", "step", event["note"],
                            thought=event.get("thought", ""),
                            tool=event.get("tool", ""),
                            ok=bool(event.get("ok")),
                            ms=event.get("ms"),
                        )
                    elif event["type"] == "reply":
                        save_message(
                            db, conversation_id, "assistant", "text", event["reply"],
                            thought=event.get("thought", ""),
                            ms=event.get("ms_total"),
                        )
                    yield _sse(event)
            except AiError as error:
                yield _sse({"type": "error", "message": str(error)})
        except Exception as error:  # 循环内部意外：不能把半截流挂在那儿
            yield _sse({"type": "error", "message": f"对话出了点状况：{error}"})
        finally:
            db.close()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


MAX_SCRIPT_QUESTIONS = 500


@router.post("/api/extract/script")
def post_extract_script(
    payload: ScriptExtractBody,
    user: Annotated[dict, Depends(require_user)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
):
    """用提取脚本把材料跑成候选题（阶段四 · 模式 B）。

    脚本在无网络沙盒里执行，输出经 parse_questions 收敛成统一 Schema，
    候选题存进 extraction_jobs（仍不写 questions 表）。返回 {ok, job,
    questions, log, error}：脚本失败时 ok=false、带 log，前端脚本页据此
    展示运行日志，方便用户调脚本。
    """
    source_rows = [require_source(conn, source_id, user) for source_id in payload.sourceIds]

    script = conn.execute(
        "SELECT * FROM extraction_scripts WHERE id = ?", (payload.scriptId,)
    ).fetchone()
    if script is None or not (
        script["is_shared"]
        or script["owner_id"] == user["id"]
        or bool(user["isAdmin"])
    ):
        raise HTTPException(status_code=404, detail="脚本不存在")

    outcome = run_script_job(conn, user["id"], script["id"], payload.sourceIds)

    if not outcome["ok"]:
        return {
            "ok": False,
            "job": None,
            "questions": [],
            "log": outcome.get("log") or "",
            "error": outcome.get("error") or "脚本执行失败",
        }

    row = conn.execute(
        "SELECT * FROM extraction_jobs WHERE id = ?", (outcome["job"]["id"],)
    ).fetchone()
    return {
        "ok": True,
        "job": _job_dict(row),
        "questions": outcome["questions"],
        "log": outcome.get("log") or "",
        "error": None,
    }


@router.get("/api/extract/jobs/{job_id}")
def get_extract_jobs_by_job_id(
    job_id: str,
    user: Annotated[dict, Depends(require_user)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
):
    row = conn.execute("SELECT * FROM extraction_jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None or row["owner_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="提取记录不存在")
    questions = []
    if row["result"]:
        try:
            questions = json.loads(row["result"])
        except json.JSONDecodeError:
            questions = []
    return {"job": _job_dict(row), "questions": questions}
