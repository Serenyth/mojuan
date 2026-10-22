import json
import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.db import get_db, new_id
from app.deps import require_user
from app.lib.practice.permissions import can_manage
from app.lib.practice.serialize import bank_row_to_dict, question_row_to_dict

router = APIRouter()


class BankCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    platform: str | None = Field(default=None, max_length=50)
    description: str | None = Field(default=None, max_length=500)
    isShared: bool = True


class BankUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    platform: str | None = Field(default=None, max_length=50)
    description: str | None = Field(default=None, max_length=500)
    isShared: bool | None = None


def _require_bank(conn: sqlite3.Connection, bank_id: str):
    row = conn.execute("SELECT * FROM banks WHERE id = ?", (bank_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="题库不存在")
    return row


def _require_manage(bank_row, user: dict) -> None:
    if not can_manage(bank_row["owner_id"], bool(bank_row["is_shared"]), user):
        raise HTTPException(status_code=403, detail="无权管理该题库")


@router.get("/api/banks")
def get_banks(
    user: Annotated[dict, Depends(require_user)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
):
    rows = conn.execute(
        """SELECT b.*, COUNT(q.id) AS question_count
           FROM banks b LEFT JOIN questions q ON q.bank_id = b.id
           GROUP BY b.id
           ORDER BY b.created_at DESC, b.name"""
    ).fetchall()
    # 题型分布：组卷时要按题型核对够不够抽，列表里一次带回来
    type_rows = conn.execute(
        "SELECT bank_id, type, COUNT(*) AS c FROM questions GROUP BY bank_id, type"
    ).fetchall()
    type_counts: dict[str, dict[str, int]] = {}
    for row in type_rows:
        type_counts.setdefault(row["bank_id"], {})[row["type"]] = row["c"]
    return {
        "banks": [
            bank_row_to_dict(
                row,
                question_count=row["question_count"],
                type_counts=type_counts.get(row["id"], {}),
            )
            for row in rows
        ]
    }


@router.post("/api/banks")
def post_banks(
    payload: BankCreate,
    user: Annotated[dict, Depends(require_user)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
):
    bank_id = new_id()
    conn.execute(
        "INSERT INTO banks (id, name, platform, description, owner_id, is_shared) VALUES (?, ?, ?, ?, ?, ?)",
        (
            bank_id,
            payload.name,
            payload.platform,
            payload.description,
            user["id"],
            1 if payload.isShared else 0,
        ),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM banks WHERE id = ?", (bank_id,)).fetchone()
    return {"bank": bank_row_to_dict(row, question_count=0)}


@router.get("/api/banks/{bank_id}")
def get_banks_by_bank_id(
    bank_id: str,
    user: Annotated[dict, Depends(require_user)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
):
    row = _require_bank(conn, bank_id)
    count = conn.execute(
        "SELECT COUNT(*) AS c FROM questions WHERE bank_id = ?", (bank_id,)
    ).fetchone()["c"]
    return {"bank": bank_row_to_dict(row, question_count=count)}


@router.patch("/api/banks/{bank_id}")
def patch_banks_by_bank_id(
    bank_id: str,
    payload: BankUpdate,
    user: Annotated[dict, Depends(require_user)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
):
    row = _require_bank(conn, bank_id)
    _require_manage(row, user)
    patch = payload.model_dump(exclude_none=True)
    if "isShared" in patch:
        patch["is_shared"] = 1 if patch.pop("isShared") else 0
    if patch:
        assignments = ", ".join(f"{column} = ?" for column in patch)
        conn.execute(
            f"UPDATE banks SET {assignments} WHERE id = ?",
            (*patch.values(), bank_id),
        )
        conn.commit()
    updated = conn.execute("SELECT * FROM banks WHERE id = ?", (bank_id,)).fetchone()
    return {"bank": bank_row_to_dict(updated)}


@router.delete("/api/banks/{bank_id}")
def delete_banks_by_bank_id(
    bank_id: str,
    user: Annotated[dict, Depends(require_user)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
):
    row = _require_bank(conn, bank_id)
    _require_manage(row, user)
    conn.execute("DELETE FROM banks WHERE id = ?", (bank_id,))
    conn.commit()
    return {"ok": True}


@router.get("/api/banks/{bank_id}/questions")
def get_banks_by_bank_id_questions(
    bank_id: str,
    user: Annotated[dict, Depends(require_user)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    type: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    _require_bank(conn, bank_id)

    where = ["q.bank_id = ?"]
    params: list = [bank_id]
    if type:
        where.append("q.type = ?")
        params.append(type)
    if tag:
        where.append("q.tags LIKE ?")
        params.append(f'%"{tag}"%')
    if keyword:
        where.append("q.content LIKE ?")
        params.append(f"%{keyword}%")
    clause = "WHERE " + " AND ".join(where)

    total = conn.execute(
        f"SELECT COUNT(*) AS c FROM questions q {clause}", params
    ).fetchone()["c"]
    rows = conn.execute(
        f"SELECT q.* FROM questions q {clause} ORDER BY q.created_at DESC, q.id LIMIT ? OFFSET ?",
        params + [page_size, (page - 1) * page_size],
    ).fetchall()

    tag_rows = conn.execute(
        "SELECT tags FROM questions WHERE bank_id = ?", (bank_id,)
    ).fetchall()
    tags = sorted(
        {tag for r in tag_rows for tag in (json.loads(r["tags"]) if r["tags"] else [])}
    )
    type_rows = conn.execute(
        "SELECT type, COUNT(*) AS c FROM questions WHERE bank_id = ? GROUP BY type",
        (bank_id,),
    ).fetchall()

    return {
        "items": [question_row_to_dict(row, with_answer=True) for row in rows],
        "total": total,
        "page": page,
        "pageSize": page_size,
        "tags": tags,
        "typeCounts": {row["type"]: row["c"] for row in type_rows},
    }
