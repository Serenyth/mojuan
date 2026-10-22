"""考试得分汇总：objective / subjective / total 实时从 practice_records 重算。

对应设计方案 §2.5：主观题未阅前先出客观题分并标记「待判」，阅完自动补齐总分。
"""

from __future__ import annotations

import sqlite3


def compute_exam_scores(conn: sqlite3.Connection, exam_id: str) -> dict:
    rows = conn.execute(
        """SELECT q.type AS q_type, r.correct, r.score, r.max_score
           FROM practice_records r JOIN questions q ON q.id = r.question_id
           WHERE r.exam_id = ?""",
        (exam_id,),
    ).fetchall()

    objective_rows = [r for r in rows if r["q_type"] != "subjective"]
    subjective_rows = [r for r in rows if r["q_type"] == "subjective"]
    graded = [r for r in subjective_rows if r["correct"] is not None]

    return {
        "objectiveScore": sum(r["score"] or 0 for r in objective_rows),
        "subjectiveScore": sum(r["score"] or 0 for r in graded),
        "totalScore": sum(r["score"] or 0 for r in objective_rows) + sum(r["score"] or 0 for r in graded),
        "objectiveMax": float(len(objective_rows)),
        "subjectiveMax": sum(r["max_score"] or 0 for r in subjective_rows),
        "objectiveCount": len(objective_rows),
        "subjectiveCount": len(subjective_rows),
        "gradedSubjective": len(graded),
        "pendingSubjective": len(subjective_rows) - len(graded),
    }


def refresh_exam_scores(conn: sqlite3.Connection, exam_id: str) -> dict:
    """阅卷后刷新考试分数列。未交卷（ongoing）的考试不动分数列。"""
    scores = compute_exam_scores(conn, exam_id)
    exam = conn.execute("SELECT status FROM exams WHERE id = ?", (exam_id,)).fetchone()
    if exam is None or exam["status"] == "ongoing":
        return scores
    status = "graded" if scores["pendingSubjective"] == 0 else "grading"
    conn.execute(
        "UPDATE exams SET objective_score = ?, subjective_score = ?, total_score = ?, status = ? WHERE id = ?",
        (scores["objectiveScore"], scores["subjectiveScore"], scores["totalScore"], status, exam_id),
    )
    return scores
