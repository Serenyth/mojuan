"""导入助手会话记录：列表 / 详情 / 新建 / 删除 / 追加消息。

会话与消息都按用户隔离。消息落库由两处写入：
- 流式对话端点（/api/extract/chat/stream）：user 消息、工具轨迹（step，带
  耗时）、最终回复（带思考与总耗时）
- 前端补写的系统气泡（「提取到 N 题」「链接抓取失败」等）走追加消息端点

历史重建只取 kind='text' 的 user/assistant 消息——工具轨迹是给用户看的，
不需要再喂回模型。
"""

import sqlite3
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.db import get_db, new_id
from app.deps import require_user

router = APIRouter()

MAX_TITLE = 40
MAX_TEXT = 4000


class CreateConversationBody(BaseModel):
    title: str = Field(default="", max_length=MAX_TITLE)


class AppendMessageBody(BaseModel):
    role: Literal["user", "assistant", "system"]
    kind: Literal["text", "step", "system"] = "text"
    text: str = Field(min_length=1, max_length=MAX_TEXT)
    thought: str = Field(default="", max_length=1000)
    tool: str = Field(default="", max_length=40)
    ok: bool | None = None
    ms: int | None = Field(default=None, ge=0, le=86_400_000)


def _conversation_row(conn, conversation_id: str, user_id: str):
    row = conn.execute(
        "SELECT * FROM agent_conversations WHERE id = ? AND owner_id = ?",
        (conversation_id, user_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return row


def _message_dict(row) -> dict:
    return {
        "id": row["id"],
        "role": row["role"],
        "kind": row["kind"],
        "text": row["text"],
        "thought": row["thought"] or "",
        "tool": row["tool"] or "",
        "ok": None if row["ok"] is None else bool(row["ok"]),
        "ms": row["ms"],
        "createdAt": row["created_at"],
    }


def save_message(
    conn: sqlite3.Connection,
    conversation_id: str,
    role: str,
    kind: str,
    text: str,
    *,
    thought: str = "",
    tool: str = "",
    ok: bool | None = None,
    ms: int | None = None,
) -> None:
    """落一条会话消息并刷新会话时间。流式端点与追加端点共用。"""
    conn.execute(
        """
        INSERT INTO agent_messages (id, conversation_id, role, kind, text, thought, tool, ok, ms)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            new_id(),
            conversation_id,
            role,
            kind,
            text[:MAX_TEXT],
            (thought or "")[:1000],
            tool or "",
            None if ok is None else int(ok),
            ms,
        ),
    )
    conn.execute(
        "UPDATE agent_conversations SET updated_at = datetime('now') WHERE id = ?",
        (conversation_id,),
    )
    conn.commit()


@router.get("/api/conversations")
def list_conversations(
    user: Annotated[dict, Depends(require_user)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
):
    rows = conn.execute(
        """
        SELECT c.id, c.title, c.updated_at,
               (SELECT COUNT(*) FROM agent_messages m WHERE m.conversation_id = c.id) AS message_count,
               (SELECT m.text FROM agent_messages m WHERE m.conversation_id = c.id
                 ORDER BY m.rowid DESC LIMIT 1) AS last_message
        FROM agent_conversations c
        WHERE c.owner_id = ?
        ORDER BY c.updated_at DESC, c.rowid DESC
        LIMIT 50
        """,
        (user["id"],),
    ).fetchall()
    return {
        "conversations": [
            {
                "id": row["id"],
                "title": row["title"],
                "updatedAt": row["updated_at"],
                "messageCount": row["message_count"] or 0,
                "lastMessage": row["last_message"] or "",
            }
            for row in rows
        ]
    }


@router.post("/api/conversations")
def create_conversation(
    payload: CreateConversationBody,
    user: Annotated[dict, Depends(require_user)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
):
    conversation_id = new_id()
    conn.execute(
        "INSERT INTO agent_conversations (id, owner_id, title) VALUES (?, ?, ?)",
        (conversation_id, user["id"], payload.title.strip()[:MAX_TITLE] or "新会话"),
    )
    conn.commit()
    return {"conversation": {"id": conversation_id, "title": payload.title.strip()[:MAX_TITLE] or "新会话"}}


@router.get("/api/conversations/{conversation_id}")
def get_conversation(
    conversation_id: str,
    user: Annotated[dict, Depends(require_user)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
):
    _conversation_row(conn, conversation_id, user["id"])
    rows = conn.execute(
        "SELECT * FROM agent_messages WHERE conversation_id = ? ORDER BY rowid",
        (conversation_id,),
    ).fetchall()
    return {"messages": [_message_dict(row) for row in rows]}


@router.delete("/api/conversations/{conversation_id}")
def delete_conversation(
    conversation_id: str,
    user: Annotated[dict, Depends(require_user)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
):
    _conversation_row(conn, conversation_id, user["id"])
    conn.execute("DELETE FROM agent_conversations WHERE id = ?", (conversation_id,))
    conn.commit()
    return {"ok": True}


@router.post("/api/conversations/{conversation_id}/messages")
def append_message(
    conversation_id: str,
    payload: AppendMessageBody,
    user: Annotated[dict, Depends(require_user)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
):
    """前端补写一条消息（系统气泡）。工具轨迹与回复由流式端点自己落，不走这里。"""
    _conversation_row(conn, conversation_id, user["id"])
    save_message(
        conn,
        conversation_id,
        payload.role,
        payload.kind,
        payload.text,
        thought=payload.thought,
        tool=payload.tool,
        ok=payload.ok,
        ms=payload.ms,
    )
    return {"ok": True}
