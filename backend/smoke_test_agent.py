"""agent 工具集 + 并行/不等待 的集成冒烟。

用假 AiClient 把模型回包脚本化，跑 run_agent_stream，断言：
- 新增脚本工具（list_scripts / get_script / create_script / update_script / run_script /
  list_banks / create_bank / get_task）可用、且能真正读写库；
- 一轮发多个 action 会并发执行并各出一步轨迹；
- detach:true 的任务后台跑、本轮不阻塞，之后 get_task 取到结果；
- run_script 在沙盒里真把材料跑成候选题（落 extraction_jobs）。

不依赖真实 AI / 网络。直接 `python smoke_test_agent.py` 运行。
"""

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import threading

# 在导入 app 之前把数据目录重定向到临时目录，避免污染真实库
TMP = tempfile.mkdtemp(prefix="mojuan-agent-smoke-")
os.environ.setdefault("MOJUAN_TEST", "1")

import app.db as db_mod

for name in ("DATA_DIR", "DB_PATH", "UPLOAD_DIR", "NORMALIZED_DIR", "SCRIPTS_DIR"):
    if name == "DB_PATH":
        setattr(db_mod, name, None)  # 下面单独设置
    else:
        setattr(db_mod, name, None)

db_mod.DATA_DIR = __import__("pathlib").Path(TMP)
db_mod.UPLOAD_DIR = db_mod.DATA_DIR / "uploads"
db_mod.NORMALIZED_DIR = db_mod.DATA_DIR / "normalized"
db_mod.SCRIPTS_DIR = db_mod.DATA_DIR / "scripts"
db_mod.DB_PATH = db_mod.DATA_DIR / "quiz.db"

# 其它模块已经 import 了 DATA_DIR 的引用，逐个补丁
import app.lib.agent.tools as tools_mod
import app.lib.extract.jobs as jobs_mod
import app.lib.extract.sandbox as sandbox_mod

for mod in (tools_mod, jobs_mod, sandbox_mod):
    if hasattr(mod, "DATA_DIR"):
        mod.DATA_DIR = db_mod.DATA_DIR

db_mod.init_db()

from app.lib.agent.loop import run_agent_stream
from app.lib.agent.tools import AgentContext, get_task_result


class FakeClient:
    """脚本化的模型：每次 chat 返回序列里的下一个 (reply, reasoning)。"""

    def __init__(self, replies):
        self._replies = list(replies)
        self._idx = 0

    def chat(self, messages, temperature=0.2, max_tokens=8000, return_reasoning=False):
        if self._idx >= len(self._replies):
            # 兜底：没脚本了就结束
            return '{"reply": "done", "action": null}', ""
        reply = self._replies[self._idx]
        self._idx += 1
        return reply, ""

    def chat_vision(self, *args, **kwargs):
        return "（视觉识别占位）"


def seed():
    conn = db_mod._connect()
    conn.execute(
        "INSERT INTO users (id, username, display_name, password_hash, is_admin) VALUES ('u1', 'agent', 'agent', 'x', 1)"
    )
    conn.execute(
        "INSERT INTO users (id, username, display_name, password_hash, is_admin) VALUES ('u2', 'member', 'member', 'x', 0)"
    )
    # 一份材料 + 归一化文本
    db_mod.NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)
    npath = db_mod.NORMALIZED_DIR / "src1.md"
    npath.write_text(
        "1. 中国的首都是？\nA. 上海 B. 北京 C. 广州\n答案：B\n"
        "2. 1+1=？\nA. 1 B. 2 C. 3\n答案：B\n",
        encoding="utf-8",
    )
    rel = npath.relative_to(db_mod.DATA_DIR).as_posix()
    conn.execute(
        "INSERT INTO sources (id, owner_id, type, name, storage_path, normalized_path, status, char_count, meta) "
        "VALUES ('s1', 'u1', 'text', 'sample', NULL, ?, 'ready', 60, '{}')",
        (rel,),
    )
    conn.execute(
        "INSERT INTO banks (id, name, platform, owner_id, is_shared) VALUES ('b1', '默认题库', '', 'u1', 1)"
    )
    conn.commit()
    conn.close()


def new_ctx(client, user_id="u1", is_admin=True, script_id=None, selected_ids=None):
    conn = db_mod._connect()
    return AgentContext(
        conn=conn, user_id=user_id, client=client,
        is_admin=is_admin, script_id=script_id, selected_ids=selected_ids or {"s1"},
    )


def run_until_done(ctx, message, script_id=None, selected_ids=None):
    events = []
    conn = db_mod._connect()
    for ev in run_agent_stream(
        ctx, message, [], [], [],
        script_id=script_id, selected_ids=selected_ids,
    ):
        events.append(ev)
    conn.close()
    return events


def assert_eq(label, got, want):
    if got != want:
        print(f"  ✗ {label}: got {got!r}, want {want!r}")
        raise SystemExit(1)
    print(f"  ✓ {label}")


def test_basic_scripts():
    print("[1] 脚本工具 + 并发 batch + update_script")
    client = FakeClient([
        # 第一轮：并发两个等待动作
        json.dumps({"thought": "看脚本清单并读其中一个", "actions": [
            {"tool": "list_scripts", "args": {}},
            {"tool": "get_script", "args": {}},
        ]}),
        # 第二轮：改脚本代码（version 应 +1）
        json.dumps({"thought": "把代码改成更稳的版本", "tool": "update_script", "args": {
            "code": "import mojuan\nmojuan.emit([])\n",
        }}),
        json.dumps({"reply": "已查看并更新脚本。", "action": None}),
    ])
    # 先建一个脚本给 get_script 读
    c0 = new_ctx(client)
    sid = db_mod.new_id()
    c0.conn.execute(
        "INSERT INTO extraction_scripts (id, name, platform, code, version, owner_id, is_shared) "
        "VALUES (?, '测试脚本', '', 'import mojuan\nmojuan.emit([])\n', 1, 'u1', 1)",
        (sid,),
    )
    c0.conn.commit()
    c0.conn.close()

    events = run_until_done(new_ctx(client, script_id=sid), "调试这个脚本", script_id=sid)
    steps = [e for e in events if e["type"] == "step"]
    reply = [e for e in events if e["type"] == "reply"]
    tool_names = [s["tool"] for s in steps]
    assert_eq("batch 含 list_scripts+get_script", {"list_scripts", "get_script"} <= set(tool_names), True)
    assert_eq("有 update_script 步", "update_script" in tool_names, True)
    assert_eq("最终回复存在", len(reply) == 1, True)

    # 验证 version 真的 +1
    conn = db_mod._connect()
    v = conn.execute("SELECT version FROM extraction_scripts WHERE id=?", (sid,)).fetchone()["version"]
    conn.close()
    assert_eq("脚本版本自增到 2", v, 2)


def test_detach_and_run_script():
    print("[2] detach 不等待 + run_script 沙盒抽题")
    sid = db_mod.new_id()
    c0 = new_ctx(FakeClient([]))
    c0.conn.execute(
        "INSERT INTO extraction_scripts (id, name, platform, code, version, owner_id, is_shared) "
        "VALUES (?, '抽题脚本', '', ?, 1, 'u1', 1)",
        (sid, SCRIPT_THAT_EXTRACTS),
    )
    c0.conn.commit()
    c0.conn.close()

    client = FakeClient([
        # 第一轮：detach 跑脚本（不阻塞），同时建个题库（等待）
        json.dumps({"thought": "后台跑脚本抽题，同时建个题库", "actions": [
            {"tool": "run_script", "args": {"id": sid, "sourceIds": ["s1"]}, "detach": True},
            {"tool": "create_bank", "args": {"name": "脚本产出题库"}},
        ]}),
        # 第二轮：取后台任务结果
        json.dumps({"thought": "看后台脚本跑得怎样", "tool": "get_task", "args": {"taskId": "__DETACH__"}}),
        json.dumps({"reply": "脚本跑完，题库也建好了。", "action": None}),
    ])

    # 我们需要把第一轮产出的 taskId 喂给第二轮的 get_task。用一个外壳替换：
    ctx = new_ctx(client, script_id=sid, selected_ids={"s1"})
    events = []
    captured_task = {"id": None}
    conn = db_mod._connect()
    # 手动驱动，方便在中间抓 taskId
    # 复制 run_agent_stream 的调度太重，这里直接调用但拦截：用 monkey 记录 dispatch
    import app.lib.agent.loop as loop_mod
    orig_dispatch = loop_mod.dispatch_task

    def spy_dispatch(action, c, task_id):
        captured_task["id"] = task_id
        return orig_dispatch(action, c, task_id)

    loop_mod.dispatch_task = spy_dispatch
    try:
        for ev in run_agent_stream(ctx, "跑脚本", [], [], [], script_id=sid, selected_ids={"s1"}):
            events.append(ev)
    finally:
        loop_mod.dispatch_task = orig_dispatch
    conn.close()

    steps = [e for e in events if e["type"] == "step"]
    detach_step = [s for s in steps if "后台运行" in s.get("note", "")]
    assert_eq("有 detach 步骤", len(detach_step) == 1, True)
    assert_eq("抓到 taskId", bool(captured_task["id"]), True)

    # 后台任务应当已 done
    import time as _t
    _t.sleep(1)
    res = get_task_result(captured_task["id"])
    assert_eq("后台任务状态 done", res["status"], "done")
    assert_eq("后台 run_script 成功", res["output"]["ok"], True)
    assert_eq("后台脚本抽到题", res["output"]["count"] >= 1, True)

    # 验证落库：extraction_jobs 有 mode=script 的记录
    c1 = db_mod._connect()
    n = c1.execute("SELECT COUNT(*) AS c FROM extraction_jobs WHERE mode='script'").fetchone()["c"]
    c1.close()
    assert_eq("脚本抽题落库 extraction_jobs", n >= 1, True)


SCRIPT_THAT_EXTRACTS = (
    "import mojuan\n"
    "questions = []\n"
    "for src in mojuan.sources:\n"
    "    import re\n"
    "    blocks = re.split(r'\\n(?=\\d+\\.)', src['text'])\n"
    "    for blk in blocks:\n"
    "        m = re.search(r'(.+?)\\n(.+?)答案：(.+)', blk, re.S)\n"
    "        if not m: continue\n"
    "        stem = m.group(1).strip()\n"
    "        opts = [o.strip() for o in m.group(2).split('\\n') if o.strip()]\n"
    "        ans = m.group(3).strip()\n"
    "        questions.append({'type':'single_choice','content':stem,\n"
    "            'options':[{'key':o[0],'text':o[2:].strip()} for o in opts if len(o)>=2],\n"
    "            'answer':[ans],'confidence':0.9,'difficulty':2})\n"
    "mojuan.emit(questions)\n"
)


def main():
    seed()
    test_basic_scripts()
    test_detach_and_run_script()
    print("\nALL AGENT SMOKE TESTS PASSED")
    shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    main()
