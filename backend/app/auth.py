import hashlib
import hmac
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

from app.db import new_id

SESSION_COOKIE = "quiz_session"
SESSION_TTL_DAYS = 30

_SCRYPT = dict(n=16384, r=8, p=1, dklen=64, maxmem=64 * 1024 * 1024)


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    derived = hashlib.scrypt(password.encode("utf8"), salt=salt.encode("utf8"), **_SCRYPT)
    return f"scrypt${salt}${derived.hex()}"


def verify_password(password: str, stored: str) -> bool:
    parts = stored.split("$")
    if len(parts) != 3 or parts[0] != "scrypt":
        return False
    _, salt, expected = parts
    derived = hashlib.scrypt(password.encode("utf8"), salt=salt.encode("utf8"), **_SCRYPT)
    return hmac.compare_digest(derived.hex(), expected)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf8")).hexdigest()


def create_session(conn: sqlite3.Connection, user_id: str) -> tuple[str, datetime]:
    token = secrets.token_hex(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=SESSION_TTL_DAYS)
    conn.execute(
        "INSERT INTO sessions (id, user_id, token_hash, expires_at) VALUES (?, ?, ?, ?)",
        (new_id(), user_id, hash_token(token), expires_at.isoformat()),
    )
    conn.commit()
    return token, expires_at


def resolve_session(conn: sqlite3.Connection, token: str | None) -> dict | None:
    if not token:
        return None

    row = conn.execute(
        """SELECT u.id, u.username, u.display_name, u.is_admin, u.created_at, s.expires_at
           FROM sessions s JOIN users u ON u.id = s.user_id
           WHERE s.token_hash = ?""",
        (hash_token(token),),
    ).fetchone()

    if row is None:
        return None

    expires_at = datetime.fromisoformat(row["expires_at"])
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (hash_token(token),))
        conn.commit()
        return None

    return {
        "id": row["id"],
        "username": row["username"],
        "displayName": row["display_name"],
        "isAdmin": bool(row["is_admin"]),
        "createdAt": row["created_at"],
    }


def destroy_session(conn: sqlite3.Connection, token: str | None) -> None:
    if not token:
        return
    conn.execute("DELETE FROM sessions WHERE token_hash = ?", (hash_token(token),))
    conn.commit()


def is_first_user(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT COUNT(*) AS count FROM users").fetchone()
    return row["count"] == 0
