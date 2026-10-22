import csv
import io
import json
import sqlite3
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field, field_validator

from app.db import get_db, new_id
from app.deps import require_user
from app.lib.practice.permissions import can_manage
from app.lib.practice.serialize import question_row_to_dict

router = APIRouter()

QUESTION_TYPES = ("single_choice", "multiple_choice", "true_false", "fill_blank", "subjective")
_CHOICE_TYPES = ("single_choice", "multiple_choice", "true_false")


class QuestionBase(BaseModel):
    """题目本体字段。批量入库的候选题不带 bankId（由外层统一给）。"""

    type: str
    content: str = Field(min_length=1)
    options: list[dict] | None = None
    answer: list | str
    acceptableAnswers: list[list[str]] | None = None
    explanation: str | None = None
    tags: list[str] = Field(default_factory=list)
    difficulty: int = Field(default=3, ge=1, le=5)
    source: str | None = Field(default=None, max_length=100)
    confidence: float | None = Field(default=None, ge=0, le=1)
    fingerprint: str | None = Field(default=None, max_length=64)

    @field_validator("options")
    @classmethod
    def _check_options(cls, value):
        if value is None:
            return value
        for option in value:
            if not isinstance(option, dict) or "key" not in option or "text" not in option:
                raise ValueError("选项必须包含 key 与 text")
        return value


class QuestionCreate(QuestionBase):
    bankId: str


class QuestionUpdate(BaseModel):
    content: str | None = Field(default=None, min_length=1)
    options: list[dict] | None = None
    answer: list | str | None = None
    acceptableAnswers: list[list[str]] | None = None
    explanation: str | None = None
    tags: list[str] | None = None
    difficulty: int | None = Field(default=None, ge=1, le=5)
    source: str | None = Field(default=None, max_length=100)

    @field_validator("options")
    @classmethod
    def _check_options(cls, value):
        if value is None:
            return value
        for option in value:
            if not isinstance(option, dict) or "key" not in option or "text" not in option:
                raise ValueError("选项必须包含 key 与 text")
        return value


class QuestionBatch(BaseModel):
    """导入页审核确认后的一次性批量入库。候选题目里被用户去掉的不会出现在这里。"""

    bankId: str
    questions: list[QuestionBase] = Field(min_length=1, max_length=500)


def _validate_question(q_type: str, content_has_options: bool, answer) -> None:
    if q_type not in QUESTION_TYPES:
        raise HTTPException(status_code=422, detail=f"未知题型：{q_type}")
    if q_type in _CHOICE_TYPES and not content_has_options:
        raise HTTPException(status_code=422, detail="选择 / 判断题必须提供选项")
    if q_type in ("fill_blank", "subjective") and not isinstance(answer, list):
        raise HTTPException(status_code=422, detail="填空 / 主观题答案必须为数组")


def _default_true_false_options() -> list[dict]:
    return [{"key": "T", "text": "正确"}, {"key": "F", "text": "错误"}]


def _require_question(conn: sqlite3.Connection, question_id: str):
    row = conn.execute("SELECT * FROM questions WHERE id = ?", (question_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="题目不存在")
    return row


def _require_question_manage(conn: sqlite3.Connection, question_row, user: dict) -> None:
    bank = conn.execute(
        "SELECT * FROM banks WHERE id = ?", (question_row["bank_id"],)
    ).fetchone()
    if bank is None or not can_manage(bank["owner_id"], bool(bank["is_shared"]), user):
        raise HTTPException(status_code=403, detail="无权修改该题目")


def _require_bank_manage(conn: sqlite3.Connection, bank_id: str, user: dict):
    bank = conn.execute("SELECT * FROM banks WHERE id = ?", (bank_id,)).fetchone()
    if bank is None:
        raise HTTPException(status_code=404, detail="题库不存在")
    if not can_manage(bank["owner_id"], bool(bank["is_shared"]), user):
        raise HTTPException(status_code=403, detail="无权向该题库添加题目")
    return bank


def _insert_question(conn: sqlite3.Connection, bank_id: str, payload: QuestionBase):
    """校验并插入一条，不 commit——批量时由外层包在一个事务里。"""
    _validate_question(
        payload.type, bool(payload.options or payload.type == "true_false"), payload.answer
    )
    options = payload.options
    if payload.type == "true_false" and not options:
        options = _default_true_false_options()

    question_id = new_id()
    conn.execute(
        """INSERT INTO questions
           (id, bank_id, type, content, options, answer, acceptable_answers,
            explanation, tags, difficulty, source, confidence, fingerprint)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            question_id,
            bank_id,
            payload.type,
            payload.content,
            json.dumps(options, ensure_ascii=False) if options else None,
            json.dumps(payload.answer, ensure_ascii=False),
            json.dumps(payload.acceptableAnswers, ensure_ascii=False)
            if payload.acceptableAnswers
            else None,
            payload.explanation,
            json.dumps(payload.tags, ensure_ascii=False),
            payload.difficulty,
            payload.source,
            payload.confidence,
            payload.fingerprint,
        ),
    )
    return conn.execute("SELECT * FROM questions WHERE id = ?", (question_id,)).fetchone()


@router.post("/api/questions")
def post_questions(
    payload: QuestionCreate,
    user: Annotated[dict, Depends(require_user)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
):
    _require_bank_manage(conn, payload.bankId, user)
    row = _insert_question(conn, payload.bankId, payload)
    conn.commit()
    return {"question": question_row_to_dict(row, with_answer=True)}


@router.post("/api/questions/batch")
def post_questions_batch(
    payload: QuestionBatch,
    user: Annotated[dict, Depends(require_user)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
):
    _require_bank_manage(conn, payload.bankId, user)

    # 批内按指纹去重：模型偶尔会把同一道题拆成两条几乎一样的输出
    seen: set[str] = set()
    accepted: list[QuestionBase] = []
    for question in payload.questions:
        mark = question.fingerprint
        if mark:
            if mark in seen:
                continue
            seen.add(mark)
        accepted.append(question)

    rows = []
    try:
        for question in accepted:
            rows.append(_insert_question(conn, payload.bankId, question))
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    return {
        "created": len(rows),
        "questions": [question_row_to_dict(row, with_answer=True) for row in rows],
    }


@router.patch("/api/questions/{question_id}")
def patch_questions_by_question_id(
    question_id: str,
    payload: QuestionUpdate,
    user: Annotated[dict, Depends(require_user)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
):
    row = _require_question(conn, question_id)
    _require_question_manage(conn, row, user)

    patch = payload.model_dump(exclude_none=True)
    if "answer" in patch:
        _validate_question(row["type"], bool(patch.get("options", row["options"])), patch["answer"])
    for column in ("options", "answer", "acceptableAnswers", "tags"):
        if column in patch and patch[column] is not None:
            patch[column] = json.dumps(patch[column], ensure_ascii=False)
    patch.pop("acceptableAnswers", None)
    if payload.acceptableAnswers is not None:
        patch["acceptable_answers"] = json.dumps(payload.acceptableAnswers, ensure_ascii=False)

    if patch:
        assignments = ", ".join(f"{column} = ?" for column in patch)
        conn.execute(
            f"UPDATE questions SET {assignments} WHERE id = ?",
            (*patch.values(), question_id),
        )
        conn.commit()
    updated = conn.execute("SELECT * FROM questions WHERE id = ?", (question_id,)).fetchone()
    return {"question": question_row_to_dict(updated, with_answer=True)}


@router.delete("/api/questions/{question_id}")
def delete_questions_by_question_id(
    question_id: str,
    user: Annotated[dict, Depends(require_user)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
):
    row = _require_question(conn, question_id)
    _require_question_manage(conn, row, user)
    conn.execute("DELETE FROM questions WHERE id = ?", (question_id,))
    conn.commit()
    return {"ok": True}


@router.get("/api/questions/export")
def get_questions_export(
    user: Annotated[dict, Depends(require_user)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    bank_id: str | None = Query(default=None),
    format: Literal["csv", "json"] = Query(default="csv"),
):
    where: list[str] = []
    params: list = []
    if bank_id:
        where.append("q.bank_id = ?")
        params.append(bank_id)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    rows = conn.execute(
        f"SELECT q.* FROM questions q {clause} ORDER BY q.created_at", params
    ).fetchall()

    if format == "json":
        data = [question_row_to_dict(row, with_answer=True) for row in rows]
        return PlainTextResponse(
            json.dumps(data, ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="questions.json"'},
        )

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "id",
            "bank_id",
            "type",
            "content",
            "options",
            "answer",
            "acceptable_answers",
            "explanation",
            "tags",
            "difficulty",
            "source",
            "created_at",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                row["id"],
                row["bank_id"],
                row["type"],
                row["content"],
                row["options"] or "",
                row["answer"],
                row["acceptable_answers"] or "",
                row["explanation"] or "",
                row["tags"] or "",
                row["difficulty"],
                row["source"] or "",
                row["created_at"],
            ]
        )
    return PlainTextResponse(
        "\ufeff" + buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="questions.csv"'},
    )
