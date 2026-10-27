"""刷题侧共享：数据库行 → 前端 JSON 的序列化。

with_answer=False 的产物用于刷题 / 考试响应，避免提前泄漏答案；
with_answer=True 用于题库管理与阅卷界面。
"""

import json


def question_row_to_dict(row, *, with_answer: bool = False, extra: dict | None = None) -> dict:
    question = {
        "id": row["id"],
        "bankId": row["bank_id"],
        "type": row["type"],
        "content": row["content"],
        "options": json.loads(row["options"]) if row["options"] else None,
        "explanation": row["explanation"],
        "tags": json.loads(row["tags"]) if row["tags"] else [],
        "difficulty": row["difficulty"],
        "confidence": row["confidence"],
        "fingerprint": row["fingerprint"],
        "createdAt": row["created_at"],
    }
    if with_answer:
        question["answer"] = json.loads(row["answer"]) if row["answer"] else None
        question["acceptableAnswers"] = (
            json.loads(row["acceptable_answers"]) if row["acceptable_answers"] else None
        )
    if extra:
        question.update(extra)
    return question


def bank_row_to_dict(
    row, question_count: int | None = None, type_counts: dict[str, int] | None = None
) -> dict:
    bank = {
        "id": row["id"],
        "name": row["name"],
        "platform": row["platform"],
        "description": row["description"],
        "ownerId": row["owner_id"],
        "isShared": bool(row["is_shared"]),
        "createdAt": row["created_at"],
        "kind": row["kind"] if "kind" in row.keys() else None,
    }
    if question_count is not None:
        bank["questionCount"] = question_count
    if type_counts is not None:
        bank["typeCounts"] = type_counts
    return bank


def record_row_to_dict(row) -> dict:
    return {
        "id": row["id"],
        "sessionId": row["session_id"],
        "examId": row["exam_id"],
        "userId": row["user_id"],
        "questionId": row["question_id"],
        "userAnswer": json.loads(row["user_answer"]) if row["user_answer"] else None,
        "correct": None if row["correct"] is None else bool(row["correct"]),
        "score": row["score"],
        "maxScore": row["max_score"],
        "comment": row["comment"],
        "judgedBy": row["judged_by"],
        "judgedAt": row["judged_at"],
        "timeSpent": row["time_spent"],
        "createdAt": row["created_at"],
    }
