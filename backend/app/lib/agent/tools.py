"""agent 的工具集：抓网页、读材料、跑代码、造工具、抽题。

设计前提：模型没有联网能力，但服务端有。工具把「本机能力」暴露给模型，
由模型自己决定用哪个、怎么组合——导入助手因此是 agent，不是客服。

run_python / run_tool 在本机真实执行代码（用户明确要求 agent 能利用
本机联网能力自己想办法抓内容）。边界：单次 45 秒超时、输出截断、
临时工作目录、不过 shell、环境变量最小化。这与阶段四「复用脚本」的
无网络沙盒是两回事：那边的脚本是给同源页面反复用的确定性情工具，
这边是 agent 的即时动手能力。
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from app.db import DATA_DIR, NORMALIZED_DIR, _connect, new_id
from app.deps import require_source
from app.lib.ai import AiError
from app.lib.extract.jobs import run_and_store, run_script_job
from app.lib.extract.sandbox import build_source_payload
from app.lib.sources import create_url_source

CODE_TIMEOUT = 45            # 单次代码执行秒数上限
STDOUT_CAP = 20_000          # stdout 截断
STDERR_CAP = 4_000           # stderr 截断
CODE_MAX_CHARS = 20_000      # 单段代码长度上限
TEXT_CAP = 400_000           # save_material 存文本上限
SCRIPT_NAME_RE = re.compile(r"^[A-Za-z0-9_\-一-龥]{1,40}$")
TOOL_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")

CODE_TIMEOUT = 45            # 单次代码执行秒数上限
STDOUT_CAP = 20_000          # stdout 截断
STDERR_CAP = 4_000           # stderr 截断
CODE_MAX_CHARS = 20_000      # 单段代码长度上限
TEXT_CAP = 400_000           # save_material 存文本上限
TOOL_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")

_EXT_MIME = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".webp": "image/webp", ".gif": "image/gif", ".bmp": "image/bmp",
}

# 视觉模型识别图片时给的指令：把图里的题逐题认成文字，不靠本地 OCR
IMAGE_RECOGNIZE_PROMPT = (
    "这是题目的图片。请逐题、完整地识别图片里的全部题目内容，尽量保留原题的题型、"
    "题干、选项（含 A/B/C/D 或 ①②③ 等标记）、以及能看清的答案或填空处。"
    "用 Markdown 输出，一题一段；不要编造图片里没有的内容；看不清的地方标注「（此处不清）」。"
)


@dataclass
class AgentContext:
    """一次 agent 循环的共享上下文。"""

    conn: object
    user_id: str
    client: object
    is_admin: bool = False
    script_id: str | None = None
    selected_ids: "set | None" = field(default=None)


@dataclass
class ToolResult:
    ok: bool
    output: object          # 喂回模型的观察（循环里会再截断）
    note: str               # 给前端轨迹的一行短说明


def _meta(row) -> dict:
    try:
        return json.loads(row["meta"]) if row["meta"] else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _read_normalized(row) -> str:
    if not row["normalized_path"]:
        return ""
    path = DATA_DIR / row["normalized_path"]
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------- 各工具

def _tool_list_sources(args, ctx):
    rows = ctx.conn.execute(
        "SELECT * FROM sources WHERE owner_id = ? ORDER BY created_at DESC, id LIMIT 50",
        (ctx.user_id,),
    ).fetchall()
    items = [
        {
            "id": row["id"],
            "name": row["name"],
            "type": row["type"],
            "chars": row["char_count"],
            "images": _meta(row).get("imageCount", 0),
            "status": row["status"],
        }
        for row in rows
    ]
    return ToolResult(True, {"sources": items}, f"查看材料清单（{len(items)} 份）")


def _tool_read_source(args, ctx):
    source_id = str(args.get("id") or "")
    if not source_id:
        return ToolResult(False, {"error": "缺少材料 id"}, "读取材料失败")
    try:
        row = require_source(ctx.conn, source_id, {"id": ctx.user_id})
    except Exception as error:
        return ToolResult(False, {"error": str(getattr(error, "detail", error))}, "材料不存在")

    text = _read_normalized(row)
    cap = args.get("maxChars") or 4000
    try:
        cap = min(max(int(cap), 500), 20_000)
    except (TypeError, ValueError):
        cap = 4000
    images = _meta(row).get("imageCount", 0)
    if not text.strip():
        return ToolResult(
            True,
            {"id": row["id"], "name": row["name"], "chars": 0, "images": images,
             "text": "", "hint": "这份材料没有文字（图片型，走视觉通道）"},
            f"读取材料「{row['name'][:20]}」（无文字）",
        )
    return ToolResult(
        True,
        {"id": row["id"], "name": row["name"], "chars": len(text), "images": images,
         "text": text[:cap], "truncated": len(text) > cap},
        f"读取材料「{row['name'][:20]}」{len(text)} 字",
    )


def _tool_read_image(args, ctx):
    """把图片型材料的图片交给云端视觉模型识别成文字。

    图片可能落在两处：
    - 网页/材料内嵌图：meta.images（相对 DATA_DIR 的路径，由 persist_images 落盘）
    - 直接上传 / 直链图片：原文件在 storage_path（type=image）
    两处都不在就说明这份材料没有可识别的图片。
    """
    source_id = str(args.get("id") or "")
    if not source_id:
        return ToolResult(False, {"error": "缺少材料 id"}, "读取图片失败")
    try:
        row = require_source(ctx.conn, source_id, {"id": ctx.user_id})
    except Exception as error:
        return ToolResult(False, {"error": str(getattr(error, "detail", error))}, "材料不存在")

    meta = _meta(row)
    files: list[tuple[bytes, str]] = []
    for rel in meta.get("images") or []:
        path = DATA_DIR / rel
        if path.is_file():
            files.append((path.read_bytes(), _EXT_MIME.get(path.suffix.lower(), "image/png")))
    if not files and (row["type"] == "image" or meta.get("kind") == "image"):
        storage_path = row["storage_path"]
        if storage_path:
            path = DATA_DIR / storage_path
            if path.is_file():
                files.append((path.read_bytes(), _EXT_MIME.get(path.suffix.lower(), "image/png")))

    if not files:
        return ToolResult(
            False,
            {"error": "这份材料没有可识别的图片文件",
             "hint": "图片可能没成功落盘，或这份材料其实是纯文字"},
            "没有可识别图片",
        )

    try:
        recognized = ctx.client.chat_vision(IMAGE_RECOGNIZE_PROMPT, files)
    except AiError as error:
        return ToolResult(False, {"error": f"视觉识别失败：{error}"}, "视觉识别失败")
    except Exception as error:
        return ToolResult(False, {"error": f"视觉识别异常：{error}"}, "视觉识别异常")

    return ToolResult(
        True,
        {"id": row["id"], "name": row["name"], "images": len(files), "recognized": recognized},
        f"视觉识别「{row['name'][:20]}」{len(files)} 张图",
    )


def _tool_fetch_url(args, ctx):
    url = str(args.get("url") or "").strip()
    if not re.match(r"^https?://", url, re.IGNORECASE):
        return ToolResult(False, {"error": "只支持 http/https 链接"}, "链接格式不对")

    before = ctx.conn.execute(
        "SELECT id FROM sources WHERE owner_id = ? AND name = ?", (ctx.user_id, url)
    ).fetchone()
    row, error = create_url_source(ctx.conn, ctx.user_id, url)
    if error is not None:
        return ToolResult(False, {"error": error}, f"抓取失败：{urlparse(url).netloc}")

    meta = _meta(row)
    images = meta.get("imageCount", 0)
    reused = before is not None
    text = _read_normalized(row)
    preview = text[:1500]
    output = {
        "sourceId": row["id"],
        "name": url,
        "chars": row["char_count"],
        "images": images,
        "title": meta.get("title"),
        "reused": reused,
        "preview": preview,
    }
    host = urlparse(url).netloc
    if row["char_count"]:
        note = f"抓取链接 {host}：{row['char_count']} 字"
    else:
        note = f"抓取链接 {host}：图片材料"
    if images:
        note += f" · {images} 张图"
    if reused:
        note += "（复用已有材料）"
    return ToolResult(True, output, note)


def _tool_save_material(args, ctx):
    name = str(args.get("name") or "").strip()[:200] or "agent 抓取的内容"
    text = str(args.get("text") or "")
    if not text.strip():
        return ToolResult(False, {"error": "text 不能为空"}, "空内容")

    truncated = len(text) > TEXT_CAP
    text = text[:TEXT_CAP]
    source_id = new_id()
    NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)
    path = NORMALIZED_DIR / f"{source_id}.md"
    path.write_text(text, encoding="utf-8")
    normalized_path = path.relative_to(DATA_DIR).as_posix()

    meta = {"kind": "text", "chars": len(text), "truncated": truncated, "fromAgent": True}
    ctx.conn.execute(
        """INSERT INTO sources
           (id, owner_id, type, name, storage_path, normalized_path, status, char_count, meta)
           VALUES (?, ?, 'text', ?, NULL, ?, 'ready', ?, ?)""",
        (source_id, ctx.user_id, name, normalized_path, len(text),
         json.dumps(meta, ensure_ascii=False)),
    )
    ctx.conn.commit()
    return ToolResult(
        True,
        {"sourceId": source_id, "name": name, "chars": len(text), "truncated": truncated},
        f"存成材料「{name[:20]}」{len(text)} 字",
    )


def _run_snippet(code: str, args: dict, note_prefix: str) -> ToolResult:
    """在本机跑一段 Python。有网络（agent 的即时动手能力），边界见模块 docstring。"""
    if not code.strip():
        return ToolResult(False, {"error": "code 不能为空"}, f"{note_prefix}失败（空代码）")
    if len(code) > CODE_MAX_CHARS:
        return ToolResult(False, {"error": f"代码超过 {CODE_MAX_CHARS} 字符"}, f"{note_prefix}失败（代码过长）")

    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="mojuan-agent-") as tmp:
        script = Path(tmp) / "snippet.py"
        script.write_text(code, encoding="utf-8")
        env = {
            "PATH": os.environ.get("PATH", ""),
            "SystemRoot": os.environ.get("SystemRoot", ""),
            "TEMP": tmp,
            "TMP": tmp,
            "PYTHONIOENCODING": "utf-8",
            "AGENT_ARGS": json.dumps(args or {}, ensure_ascii=False),
        }
        try:
            proc = subprocess.run(
                [sys.executable, str(script)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=CODE_TIMEOUT,
                cwd=tmp,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(False, {"error": f"超过 {CODE_TIMEOUT} 秒被终止"},
                              f"{note_prefix}超时（{CODE_TIMEOUT}s）")

    duration = time.monotonic() - started
    stdout = (proc.stdout or "")[:STDOUT_CAP]
    stderr = (proc.stderr or "")[:STDERR_CAP]
    ok = proc.returncode == 0
    return ToolResult(
        ok,
        {"exitCode": proc.returncode, "stdout": stdout, "stderr": stderr,
         "truncated": len(proc.stdout or "") > STDOUT_CAP},
        f"{note_prefix}（{duration:.1f}s，退出码 {proc.returncode}）",
    )


def _tool_run_python(args, ctx):
    code = str(args.get("code") or "")
    return _run_snippet(code, {}, "运行 Python")


def _tool_create_tool(args, ctx):
    name = str(args.get("name") or "").strip()
    if not TOOL_NAME_RE.match(name):
        return ToolResult(False, {"error": "工具名只能含字母数字_-，1-40 字符"}, "工具名不合法")
    code = str(args.get("code") or "")
    if not code.strip():
        return ToolResult(False, {"error": "code 不能为空"}, "空代码")
    description = str(args.get("description") or "")[:500]

    ctx.conn.execute(
        """INSERT INTO agent_tools (id, owner_id, name, description, code, created_at)
           VALUES (?, ?, ?, ?, ?, datetime('now'))
           ON CONFLICT(owner_id, name) DO UPDATE SET
             description = excluded.description, code = excluded.code""",
        (new_id(), ctx.user_id, name, description, code[:CODE_MAX_CHARS]),
    )
    ctx.conn.commit()
    return ToolResult(
        True,
        {"name": name, "description": description},
        f"创建工具 {name}",
    )


def _tool_list_tools(args, ctx):
    rows = ctx.conn.execute(
        "SELECT name, description, created_at FROM agent_tools WHERE owner_id = ? ORDER BY created_at DESC, id LIMIT 50",
        (ctx.user_id,),
    ).fetchall()
    items = [{"name": r["name"], "description": r["description"]} for r in rows]
    return ToolResult(True, {"tools": items}, f"查看工具清单（{len(items)} 个）")


def _tool_run_tool(args, ctx):
    name = str(args.get("name") or "").strip()
    row = ctx.conn.execute(
        "SELECT code FROM agent_tools WHERE owner_id = ? AND name = ?", (ctx.user_id, name)
    ).fetchone()
    if row is None:
        return ToolResult(False, {"error": f"工具 {name} 不存在，先 create_tool"}, f"工具 {name} 不存在")
    tool_args = args.get("args")
    return _run_snippet(row["code"], tool_args if isinstance(tool_args, dict) else {}, f"运行工具 {name}")


def _tool_extract_questions(args, ctx):
    raw_ids = args.get("sourceIds")
    if not isinstance(raw_ids, list) or not raw_ids:
        return ToolResult(False, {"error": "sourceIds 不能为空"}, "提取失败（没给材料）")
    source_ids = [str(item) for item in raw_ids if isinstance(item, str)][:20]
    instruction = str(args.get("instruction") or "")[:2000]

    try:
        outcome = run_and_store(ctx.conn, ctx.user_id, ctx.client, source_ids, instruction)
    except AiError as error:
        return ToolResult(False, {"error": str(error)}, f"提取失败：{error}")
    except Exception as error:
        detail = str(getattr(error, "detail", error))
        return ToolResult(False, {"error": detail}, f"提取失败：{detail}")

    questions = outcome["questions"]
    suspect = sum(1 for q in questions if q.get("suspect") or q.get("issues"))
    sample = [{"type": q["type"], "content": q["content"][:80]} for q in questions[:5]]
    return ToolResult(
        True,
        {"jobId": outcome["jobId"], "stats": outcome["stats"], "sample": sample},
        f"提取到 {len(questions)} 题" + (f"（{suspect} 存疑）" if suspect else ""),
    )


# ───────────────────────────── 脚本管理（阶段四 · 同源复用） ─────────────────────────────

def _script_visible(row, ctx) -> bool:
    return bool(row["is_shared"]) or row["owner_id"] == ctx.user_id or ctx.is_admin


def _script_editable(row, ctx) -> bool:
    return row["owner_id"] == ctx.user_id or ctx.is_admin


def _tool_list_scripts(args, ctx):
    rows = ctx.conn.execute(
        "SELECT * FROM extraction_scripts ORDER BY created_at DESC, id"
    ).fetchall()
    items = [
        {
            "id": row["id"], "name": row["name"], "platform": row["platform"] or "",
            "version": row["version"], "isShared": bool(row["is_shared"]),
            "canEdit": _script_editable(row, ctx),
        }
        for row in rows if _script_visible(row, ctx)
    ]
    return ToolResult(True, {"scripts": items}, f"查看脚本清单（{len(items)} 个）")


def _tool_get_script(args, ctx):
    script_id = str(args.get("id") or ctx.script_id or "")
    if not script_id:
        return ToolResult(False, {"error": "缺少脚本 id，也没有正在调试的脚本"}, "读取脚本失败")
    row = ctx.conn.execute("SELECT * FROM extraction_scripts WHERE id = ?", (script_id,)).fetchone()
    if row is None or not _script_visible(row, ctx):
        return ToolResult(False, {"error": "脚本不存在或无权限"}, "读取脚本失败")
    return ToolResult(
        True,
        {
            "id": row["id"], "name": row["name"], "platform": row["platform"] or "",
            "version": row["version"], "isShared": bool(row["is_shared"]),
            "code": row["code"], "canEdit": _script_editable(row, ctx),
        },
        f"读取脚本「{row['name'][:20]}」v{row['version']}",
    )


def _tool_create_script(args, ctx):
    name = str(args.get("name") or "").strip()
    if not name:
        return ToolResult(False, {"error": "name 不能为空"}, "创建脚本失败")
    if not SCRIPT_NAME_RE.match(name):
        return ToolResult(False, {"error": "名称只含字母数字 _- 或中文，1-40 字符"}, "创建脚本失败")
    code = str(args.get("code") or "")
    if not code.strip():
        return ToolResult(False, {"error": "code 不能为空"}, "创建脚本失败")
    script_id = new_id()
    ctx.conn.execute(
        """INSERT INTO extraction_scripts
           (id, name, platform, code, version, io_spec, owner_id, is_shared)
           VALUES (?, ?, ?, ?, 1, NULL, ?, ?)""",
        (script_id, name, str(args.get("platform") or "")[:60], code[:60_000], ctx.user_id,
         1 if bool(args.get("isShared", True)) else 0),
    )
    ctx.conn.commit()
    return ToolResult(True, {"id": script_id, "name": name, "version": 1}, f"创建脚本 {name}")


def _tool_update_script(args, ctx):
    script_id = str(args.get("id") or ctx.script_id or "")
    if not script_id:
        return ToolResult(False, {"error": "缺少脚本 id，也没有正在调试的脚本"}, "更新脚本失败")
    row = ctx.conn.execute("SELECT * FROM extraction_scripts WHERE id = ?", (script_id,)).fetchone()
    if row is None or not _script_visible(row, ctx):
        return ToolResult(False, {"error": "脚本不存在或无权限"}, "更新脚本失败")
    if not _script_editable(row, ctx):
        return ToolResult(False, {"error": "只能修改自己创建的脚本"}, "更新脚本失败")
    updates: dict = {}
    if args.get("name") not in (None, ""):
        updates["name"] = str(args["name"]).strip()[:100]
    if args.get("platform") is not None:
        updates["platform"] = str(args["platform"])[:60]
    if args.get("code") not in (None, ""):
        updates["code"] = str(args["code"])[:60_000]
        updates["version"] = int(row["version"]) + 1
    if args.get("isShared") is not None:
        updates["is_shared"] = 1 if args["isShared"] else 0
    if not updates:
        return ToolResult(False, {"error": "没有可更新的字段"}, "更新脚本失败")
    assignments = ", ".join(f"{key} = ?" for key in updates)
    ctx.conn.execute(
        f"UPDATE extraction_scripts SET {assignments} WHERE id = ?",
        (*updates.values(), script_id),
    )
    ctx.conn.commit()
    new_row = ctx.conn.execute("SELECT * FROM extraction_scripts WHERE id = ?", (script_id,)).fetchone()
    return ToolResult(
        True,
        {"id": script_id, "name": new_row["name"], "version": new_row["version"], "code": new_row["code"]},
        f"更新脚本「{new_row['name'][:20]}」→ v{new_row['version']}",
    )


def _tool_run_script(args, ctx):
    script_id = str(args.get("id") or ctx.script_id or "")
    if not script_id:
        return ToolResult(False, {"error": "缺少脚本 id，也没有正在调试的脚本"}, "运行脚本失败")
    row = ctx.conn.execute("SELECT * FROM extraction_scripts WHERE id = ?", (script_id,)).fetchone()
    if row is None or not _script_visible(row, ctx):
        return ToolResult(False, {"error": "脚本不存在或无权限"}, "运行脚本失败")
    source_ids = args.get("sourceIds") or (list(ctx.selected_ids) if ctx.selected_ids else [])
    source_ids = [str(x) for x in source_ids if isinstance(x, str)][:20]
    if not source_ids:
        return ToolResult(False, {"error": "没有可用的材料，请先给出 sourceIds"}, "运行脚本失败")
    outcome = run_script_job(ctx.conn, ctx.user_id, script_id, source_ids)
    if not outcome["ok"]:
        return ToolResult(
            False,
            {"ok": False, "error": outcome.get("error"), "log": outcome.get("log") or "", "jobId": None},
            f"脚本运行失败：{outcome.get('error') or '见日志'}",
        )
    questions = outcome["questions"]
    suspect = sum(1 for q in questions if q.get("suspect") or q.get("issues"))
    return ToolResult(
        True,
        {"ok": True, "count": len(questions), "suspect": suspect,
         "jobId": outcome["job"]["id"], "log": outcome.get("log") or ""},
        f"脚本跑出 {len(questions)} 题" + (f"（{suspect} 存疑）" if suspect else ""),
    )


# ───────────────────────────── 题库管理 ─────────────────────────────

def _tool_list_banks(args, ctx):
    rows = ctx.conn.execute(
        "SELECT id, name, platform, is_shared FROM banks ORDER BY created_at DESC, id LIMIT 50"
    ).fetchall()
    items = [
        {"id": r["id"], "name": r["name"], "platform": r["platform"] or "", "isShared": bool(r["is_shared"])}
        for r in rows
    ]
    return ToolResult(True, {"banks": items}, f"查看题库清单（{len(items)} 个）")


def _tool_create_bank(args, ctx):
    name = str(args.get("name") or "").strip()
    if not name:
        return ToolResult(False, {"error": "name 不能为空"}, "创建题库失败")
    bank_id = new_id()
    ctx.conn.execute(
        "INSERT INTO banks (id, name, platform, owner_id, is_shared) VALUES (?, ?, '', ?, 1)",
        (bank_id, name[:100], ctx.user_id),
    )
    ctx.conn.commit()
    return ToolResult(True, {"id": bank_id, "name": name}, f"创建题库 {name}")


# ───────────────────────────── 后台任务（fire-and-forget） ─────────────────────────────

_TASKS: dict = {}
_TASKS_LOCK = threading.Lock()


def get_task_result(task_id: str) -> dict | None:
    with _TASKS_LOCK:
        return dict(_TASKS.get(task_id)) if task_id in _TASKS else None


def dispatch_task(action: dict, ctx: AgentContext, task_id: str) -> str:
    """把一个不等待的工具调用丢到后台线程跑，立即返回 task_id。

    结果写进 _TASKS，模型之后用 get_task 取。工具自己会开独立连接，线程安全。
    """
    def _worker() -> None:
        result = execute_tool(str(action.get("tool") or ""), action.get("args") or {}, ctx)
        with _TASKS_LOCK:
            _TASKS[task_id] = {
                "status": "done", "ok": result.ok, "note": result.note, "output": result.output,
            }

    with _TASKS_LOCK:
        _TASKS[task_id] = {"status": "running"}
    threading.Thread(target=_worker, daemon=True).start()
    return task_id


def _tool_get_task(args, ctx):
    task_id = str(args.get("taskId") or "")
    result = get_task_result(task_id)
    if result is None:
        return ToolResult(False, {"error": f"任务 {task_id} 不存在"}, "取任务结果失败")
    return ToolResult(True, {"taskId": task_id, **result}, f"任务 {task_id}：{result.get('status')}")


_TOOLS = {
    "list_sources": _tool_list_sources,
    "read_source": _tool_read_source,
    "read_image": _tool_read_image,
    "fetch_url": _tool_fetch_url,
    "save_material": _tool_save_material,
    "run_python": _tool_run_python,
    "create_tool": _tool_create_tool,
    "list_tools": _tool_list_tools,
    "run_tool": _tool_run_tool,
    "extract_questions": _tool_extract_questions,
    "list_scripts": _tool_list_scripts,
    "get_script": _tool_get_script,
    "create_script": _tool_create_script,
    "update_script": _tool_update_script,
    "run_script": _tool_run_script,
    "list_banks": _tool_list_banks,
    "create_bank": _tool_create_bank,
    "get_task": _tool_get_task,
}


def execute_tool(name: str, args, ctx: AgentContext) -> ToolResult:
    """执行一个工具。**每次调用都自己开一条 DB 连接**（默认连接会被并发线程共享、
    而 sqlite 连接不是线程安全的），所以对同一个 ctx 的并发/后台调用也安全。"""
    db = _connect()
    try:
        local = AgentContext(
            conn=db, user_id=ctx.user_id, client=ctx.client,
            is_admin=ctx.is_admin, script_id=ctx.script_id, selected_ids=ctx.selected_ids,
        )
        handler = _TOOLS.get(name)
        if handler is None:
            return ToolResult(
                False,
                {"error": f"未知工具 {name}", "available": sorted(_TOOLS)},
                f"未知工具 {name}",
            )
        if not isinstance(args, dict):
            args = {}
        try:
            return handler(args, local)
        except Exception as error:  # 工具自己炸了也别把循环带崩
            return ToolResult(False, {"error": f"工具执行异常：{error}"}, f"{name} 执行异常")
    finally:
        db.close()
