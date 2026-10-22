"""阶段四：可复用提取脚本的管理。

脚本是「同源页面反复跑」的确定性工具：用户写一段 Python，把材料的归一化
文本转成题目。脚本存 extraction_scripts，运行时进无网络沙盒（见
app/lib/extract/sandbox.py），候选题仍走人工审核、不直接入库。

归属：脚本默认共享（is_shared=1），可标私有；作者与管理员能改，其他人只能看/用。
"""

import json
import sqlite3
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.db import get_db, new_id
from app.deps import require_user
from app.lib.ai import AiClient, AiError
from app.lib.extract.sandbox import CODE_MAX_CHARS

router = APIRouter()

MAX_NAME = 100
MAX_PLATFORM = 60


class ScriptBody(BaseModel):
    name: str = Field(min_length=1, max_length=MAX_NAME)
    platform: str = Field(default="", max_length=MAX_PLATFORM)
    code: str = Field(min_length=1, max_length=CODE_MAX_CHARS)
    ioSpec: Any | None = None
    isShared: bool = True


class ScriptPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=MAX_NAME)
    platform: str | None = Field(default=None, max_length=MAX_PLATFORM)
    code: str | None = Field(default=None, min_length=1, max_length=CODE_MAX_CHARS)
    ioSpec: Any | None = None
    isShared: bool | None = None


class GenerateBody(BaseModel):
    description: str = Field(min_length=1, max_length=2000)
    platform: str = Field(default="", max_length=MAX_PLATFORM)


def _io_spec_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    return json.dumps(value, ensure_ascii=False)


def _can_view(row, user: dict) -> bool:
    return bool(row["is_shared"]) or row["owner_id"] == user["id"] or bool(user["isAdmin"])


def _can_edit(row, user: dict) -> bool:
    return row["owner_id"] == user["id"] or bool(user["isAdmin"])


def _script_dict(row, user: dict | None = None) -> dict:
    try:
        io_spec = json.loads(row["io_spec"]) if row["io_spec"] else None
    except (json.JSONDecodeError, TypeError):
        io_spec = row["io_spec"]
    return {
        "id": row["id"],
        "name": row["name"],
        "platform": row["platform"] or "",
        "code": row["code"],
        "version": row["version"],
        "ioSpec": io_spec,
        "ownerId": row["owner_id"],
        "isShared": bool(row["is_shared"]),
        "createdAt": row["created_at"],
        "canEdit": _can_edit(row, user) if user else False,
    }


def _load(conn, script_id: str, user: dict):
    row = conn.execute(
        "SELECT * FROM extraction_scripts WHERE id = ?", (script_id,)
    ).fetchone()
    if row is None or not _can_view(row, user):
        raise HTTPException(status_code=404, detail="脚本不存在")
    return row


@router.get("/api/scripts")
def list_scripts(
    user: Annotated[dict, Depends(require_user)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> dict:
    rows = conn.execute(
        "SELECT * FROM extraction_scripts ORDER BY created_at DESC, id"
    ).fetchall()
    items = [_script_dict(row, user) for row in rows if _can_view(row, user)]
    return {"scripts": items}


@router.post("/api/scripts")
def create_script(
    payload: ScriptBody,
    user: Annotated[dict, Depends(require_user)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> dict:
    script_id = new_id()
    conn.execute(
        """INSERT INTO extraction_scripts
           (id, name, platform, code, version, io_spec, owner_id, is_shared)
           VALUES (?, ?, ?, ?, 1, ?, ?, ?)""",
        (
            script_id,
            payload.name.strip(),
            payload.platform.strip(),
            payload.code,
            _io_spec_text(payload.ioSpec),
            user["id"],
            1 if payload.isShared else 0,
        ),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM extraction_scripts WHERE id = ?", (script_id,)
    ).fetchone()
    return {"script": _script_dict(row, user)}


@router.get("/api/scripts/{script_id}")
def get_script(
    script_id: str,
    user: Annotated[dict, Depends(require_user)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> dict:
    row = _load(conn, script_id, user)
    return {"script": _script_dict(row, user)}


@router.patch("/api/scripts/{script_id}")
def update_script(
    script_id: str,
    payload: ScriptPatch,
    user: Annotated[dict, Depends(require_user)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> dict:
    row = _load(conn, script_id, user)
    if not _can_edit(row, user):
        raise HTTPException(status_code=403, detail="只能修改自己创建的脚本")

    updates: dict[str, Any] = {}
    if payload.name is not None:
        updates["name"] = payload.name.strip()
    if payload.platform is not None:
        updates["platform"] = payload.platform.strip()
    if payload.code is not None:
        updates["code"] = payload.code
        updates["version"] = int(row["version"]) + 1
    if payload.ioSpec is not None:
        updates["io_spec"] = _io_spec_text(payload.ioSpec)
    if payload.isShared is not None:
        updates["is_shared"] = 1 if payload.isShared else 0

    if not updates:
        raise HTTPException(status_code=400, detail="没有可保存的改动")

    assignments = ", ".join(f"{key} = ?" for key in updates)
    conn.execute(
        f"UPDATE extraction_scripts SET {assignments} WHERE id = ?",
        (*updates.values(), script_id),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM extraction_scripts WHERE id = ?", (script_id,)
    ).fetchone()
    return {"script": _script_dict(row, user)}


@router.delete("/api/scripts/{script_id}")
def delete_script(
    script_id: str,
    user: Annotated[dict, Depends(require_user)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> dict:
    row = _load(conn, script_id, user)
    if not _can_edit(row, user):
        raise HTTPException(status_code=403, detail="只能删除自己创建的脚本")
    conn.execute("DELETE FROM extraction_scripts WHERE id = ?", (script_id,))
    conn.commit()
    return {"ok": True}


_GENERATE_PROMPT = """你在为一个刷题工具写「提取脚本」。脚本运行在无网络的沙盒里，
输入是材料文本，输出是题目数组。请严格按下面的约定写一段 Python：

- 用 `import mojuan` 拿到输入：`mojuan.sources` 是列表，每项含
  `id`、`name`、`type`、`text`（材料的归一化 Markdown 文本）、`path`（原始文件路径，可能为 None）、`meta`。
- 解析文本，把题目整理成 dict 列表，调用 `mojuan.emit(questions)` 输出。
- 每道题字段：`type`（single_choice / multiple_choice / true_false / fill_blank / subjective）、
  `content`（题干）、`options`（[{"key":"A","text":"..."}]，非选择题为 None）、
  `answer`（选择题为选项 key 数组；判断题为 ["T"]/["F"]；填空与主观题为字符串数组）、
  `acceptableAnswers`（填空等价答案，可 None）、`explanation`、`tags`、`difficulty`(1-5)、`confidence`(0-1)。
- 只能使用标准库与这些第三方库：bs4、openpyxl、pypdf、python-docx、lxml、markdown。
  禁止导入 socket / requests / httpx / urllib / subprocess 等网络或进程模块。
- 代码要能直接运行，带少量注释，不要输出解释文字。

只输出 Python 代码本身，不要 Markdown 代码围栏。"""


@router.post("/api/scripts/generate")
def generate_script(
    payload: GenerateBody,
    user: Annotated[dict, Depends(require_user)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> dict:
    """让模型按描述生成一段脚本脚手架（不落库，前端拿到后可编辑再保存）。"""
    try:
        client = AiClient.from_conn(conn)
    except AiError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    messages = [
        {"role": "system", "content": _GENERATE_PROMPT},
        {
            "role": "user",
            "content": (
                (f"目标平台：{payload.platform.strip()}\n" if payload.platform.strip() else "")
                + f"需求描述：{payload.description.strip()}"
            ),
        },
    ]
    try:
        text = client.chat(messages, temperature=0.2, max_tokens=4000)
    except AiError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    code = _strip_fences(text)[:CODE_MAX_CHARS]
    if not code.strip():
        raise HTTPException(status_code=422, detail="模型没有返回可用脚本")
    return {"code": code}


def _strip_fences(text: str) -> str:
    candidate = (text or "").strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        candidate = "\n".join(lines)
    return candidate.strip()
