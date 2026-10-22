import json
import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.db import get_db
from app.deps import require_user

router = APIRouter()


class HistoryDelete(BaseModel):
    practice: list[str] = Field(default_factory=list)
    exams: list[str] = Field(default_factory=list)


@router.get("/api/history")
def get_history(
    user: Annotated[dict, Depends(require_user)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    limit: int | None = Query(default=None, ge=1, le=500),
):
    """记录列表：刷题会话与考试，默认**全量**（不传 limit）。

    只读聚合，不返回题目内容与答案；刷题的答对/答题数靠 practice_records 现算，
    考试的最高分靠记录的 max_score 求和（客观+主观按满分算）。
    """
    practice_sql = """SELECT s.id, s.started_at, s.finished_at, s.bank_id, s.question_ids,
                  s.filters, s.config, b.name AS bank_name,
                  COUNT(r.id) AS answered,
                  COALESCE(SUM(CASE WHEN r.correct = 1 THEN 1 ELSE 0 END), 0) AS correct
           FROM practice_sessions s
           LEFT JOIN banks b ON b.id = s.bank_id
           LEFT JOIN practice_records r ON r.session_id = s.id
           WHERE s.user_id = ?
           GROUP BY s.id
           ORDER BY s.started_at DESC, s.id DESC"""
    practice_params: tuple = (user["id"],)
    if limit is not None:
        practice_sql += " LIMIT ?"
        practice_params += (limit,)
    practice_rows = conn.execute(practice_sql, practice_params).fetchall()

    practice = []
    for row in practice_rows:
        ids = json.loads(row["question_ids"]) if row["question_ids"] else []
        filters = json.loads(row["filters"]) if row["filters"] else {}
        config = json.loads(row["config"]) if row["config"] else {}
        practice.append(
            {
                "id": row["id"],
                "bankId": row["bank_id"],
                "bankName": row["bank_name"],
                "filters": filters,
                "order": config.get("order", "shuffle"),
                "total": len(ids),
                "answered": row["answered"],
                "correct": row["correct"],
                "startedAt": row["started_at"],
                "finishedAt": row["finished_at"],
            }
        )

    exam_sql = """SELECT e.*, t.name AS template_name, t.duration_minutes,
                  (SELECT SUM(max_score) FROM practice_records r WHERE r.exam_id = e.id) AS max_score
           FROM exams e LEFT JOIN exam_templates t ON t.id = e.template_id
           WHERE e.user_id = ?
           ORDER BY e.started_at DESC, e.id DESC"""
    exam_params: tuple = (user["id"],)
    if limit is not None:
        exam_sql += " LIMIT ?"
        exam_params += (limit,)
    exam_rows = conn.execute(exam_sql, exam_params).fetchall()

    exams = [
        {
            "id": row["id"],
            "templateId": row["template_id"],
            "templateName": row["template_name"],
            "questionCount": len(json.loads(row["question_ids"]))
            if row["question_ids"]
            else 0,
            "durationMinutes": row["duration_minutes"],
            "startedAt": row["started_at"],
            "submittedAt": row["submitted_at"],
            "status": row["status"],
            "objectiveScore": row["objective_score"],
            "subjectiveScore": row["subjective_score"],
            "totalScore": row["total_score"],
            "maxScore": row["max_score"],
        }
        for row in exam_rows
    ]

    return {"practice": practice, "exams": exams}


@router.post("/api/history/delete")
def post_history_delete(
    payload: HistoryDelete,
    user: Annotated[dict, Depends(require_user)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
):
    """清除选中的记录。只删自己的会话 / 考试与其作答记录，别人的或不存在的 id 静默跳过。"""
    deleted_practice = 0
    deleted_exams = 0

    for session_id in dict.fromkeys(payload.practice):
        row = conn.execute(
            "SELECT id, user_id FROM practice_sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if row is None or row["user_id"] != user["id"]:
            continue
        conn.execute("DELETE FROM practice_records WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM practice_sessions WHERE id = ?", (session_id,))
        deleted_practice += 1

    for exam_id in dict.fromkeys(payload.exams):
        row = conn.execute(
            "SELECT id, user_id FROM exams WHERE id = ?", (exam_id,)
        ).fetchone()
        if row is None or row["user_id"] != user["id"]:
            continue
        conn.execute("DELETE FROM practice_records WHERE exam_id = ?", (exam_id,))
        conn.execute("DELETE FROM exams WHERE id = ?", (exam_id,))
        deleted_exams += 1

    conn.commit()
    return {"deleted": {"practice": deleted_practice, "exams": deleted_exams}}
