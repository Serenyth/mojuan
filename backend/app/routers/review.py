import json
import sqlite3
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.db import get_db
from app.deps import require_user
from app.settings import get_judge_config
from app.lib.practice.scores import refresh_exam_scores
from app.lib.practice.serialize import question_row_to_dict, record_row_to_dict
from app.lib.practice.wrongbook import apply_graded

router = APIRouter()


class GradePayload(BaseModel):
    score: float = Field(ge=0)
    comment: str | None = Field(default=None, max_length=2000)


def _require_record(conn: sqlite3.Connection, record_id: str, user: dict):
    row = conn.execute(
        "SELECT * FROM practice_records WHERE id = ?", (record_id,)
    ).fetchone()
    if row is None or row["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="阅卷记录不存在")
    return row


@router.get("/api/review/pending")
def get_review_pending(
    user: Annotated[dict, Depends(require_user)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    exam_id: str | None = Query(default=None),
):
    query = "SELECT * FROM practice_records WHERE user_id = ? AND correct IS NULL"
    params: list = [user["id"]]
    if exam_id:
        query += " AND exam_id = ?"
        params.append(exam_id)
    query += " ORDER BY created_at ASC"

    rows = conn.execute(query, params).fetchall()
    items = []
    for row in rows:
        question = conn.execute(
            "SELECT * FROM questions WHERE id = ?", (row["question_id"],)
        ).fetchone()
        items.append(
            {
                "record": record_row_to_dict(row),
                # 阅卷界面需要展示参考答案，故此处带答案
                "question": question_row_to_dict(question, with_answer=True)
                if question
                else None,
            }
        )
    return {"items": items}


@router.post("/api/review/{record_id}/grade")
def post_review_by_record_id_grade(
    record_id: str,
    payload: GradePayload,
    user: Annotated[dict, Depends(require_user)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
):
    record = _require_record(conn, record_id, user)
    if record["correct"] is not None:
        raise HTTPException(status_code=409, detail="该记录已阅卷")

    max_score = record["max_score"] or 10.0
    score = min(payload.score, max_score)
    config = get_judge_config(conn)
    pass_ratio = config["subjectivePassRatio"]
    correct = score >= max_score * pass_ratio

    conn.execute(
        """UPDATE practice_records
           SET score = ?, comment = ?, judged_by = ?, judged_at = ?, correct = ?
           WHERE id = ?""",
        (
            score,
            payload.comment,
            user["id"],
            datetime.now(timezone.utc).isoformat(),
            1 if correct else 0,
            record_id,
        ),
    )
    apply_graded(conn, user["id"], record["question_id"], correct, config)
    if record["exam_id"]:
        refresh_exam_scores(conn, record["exam_id"])
    conn.commit()

    updated = conn.execute(
        "SELECT * FROM practice_records WHERE id = ?", (record_id,)
    ).fetchone()
    return {
        "record": record_row_to_dict(updated),
        "passRatio": pass_ratio,
        "correct": correct,
        "intoWrongBook": not correct,
    }
