from fastapi import Cookie, Depends, HTTPException
from typing import Annotated
import sqlite3

from app.auth import SESSION_COOKIE, resolve_session
from app.db import get_db


def get_optional_user(
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    quiz_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> dict | None:
    return resolve_session(conn, quiz_session)


def require_user(
    user: Annotated[dict | None, Depends(get_optional_user)],
) -> dict:
    if user is None:
        raise HTTPException(status_code=401, detail="未登录")
    return user


def require_admin(user: Annotated[dict, Depends(require_user)]) -> dict:
    if not user["isAdmin"]:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def require_source(
    conn: sqlite3.Connection,
    source_id: str,
    user: dict,
):
    """取一条属于本人的材料，否则 404（不泄露他人存在性）。"""
    row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
    if row is None or row["owner_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="材料不存在")
    return row
