from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from pydantic import BaseModel
from typing import Annotated
import sqlite3

from app.auth import (
    SESSION_COOKIE,
    SESSION_TTL_DAYS,
    create_session,
    destroy_session,
    hash_password,
    is_first_user,
    resolve_session,
    verify_password,
)
from app.db import get_db, new_id

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterIn(BaseModel):
    username: str
    password: str
    displayName: str | None = None


class LoginIn(BaseModel):
    username: str
    password: str


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        max_age=SESSION_TTL_DAYS * 24 * 3600,
        path="/",
    )


@router.post("/register")
def register(
    payload: RegisterIn,
    response: Response,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> dict:
    username = payload.username.strip()
    password = payload.password
    display_name = (payload.displayName or "").strip() or username

    if len(username) < 2:
        raise HTTPException(status_code=400, detail="用户名至少 2 个字符")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="密码至少 6 位")

    if conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone():
        raise HTTPException(status_code=409, detail="用户名已存在")

    is_admin = 1 if is_first_user(conn) else 0
    user_id = new_id()
    conn.execute(
        "INSERT INTO users (id, username, password_hash, display_name, is_admin) "
        "VALUES (?, ?, ?, ?, ?)",
        (user_id, username, hash_password(password), display_name, is_admin),
    )
    conn.commit()

    token, _ = create_session(conn, user_id)
    _set_session_cookie(response, token)

    return {
        "ok": True,
        "user": {
            "id": user_id,
            "username": username,
            "displayName": display_name,
            "isAdmin": bool(is_admin),
        },
    }


@router.post("/login")
def login(
    payload: LoginIn,
    response: Response,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> dict:
    row = conn.execute(
        "SELECT * FROM users WHERE username = ?", (payload.username.strip(),)
    ).fetchone()

    if row is None or not verify_password(payload.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    token, _ = create_session(conn, row["id"])
    _set_session_cookie(response, token)

    return {
        "ok": True,
        "user": {
            "id": row["id"],
            "username": row["username"],
            "displayName": row["display_name"],
            "isAdmin": bool(row["is_admin"]),
        },
    }


@router.post("/logout")
def logout(
    response: Response,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    quiz_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> dict:
    destroy_session(conn, quiz_session)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    quiz_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> dict:
    user = resolve_session(conn, quiz_session)
    if user is None:
        raise HTTPException(status_code=401, detail="未登录")
    return {"user": user}
