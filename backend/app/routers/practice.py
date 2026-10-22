import json
import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.db import get_db, new_id
from app.deps import require_user
from app.settings import get_judge_config
from app.lib.judge import judge_answer
from app.lib.practice.selection import DEFAULT_SESSION_SIZE, ORDERS, SCOPES, select_question_rows
from app.lib.practice.serialize import question_row_to_dict, record_row_to_dict
from app.lib.practice.wrongbook import apply_judge_outcome

router = APIRouter()

# 旧入口的四种模式，映射到 scope × order 后仅用于兼容与展示
_LEGACY_MODES = ("infinite", "by_type", "by_tag", "wrong")


class SessionCreate(BaseModel):
    scope: str = "all"
    order: str = "shuffle"
    bankId: str | None = None
    filters: dict = Field(default_factory=dict)
    limit: int = Field(default=DEFAULT_SESSION_SIZE, ge=1, le=100)
    # 旧入口字段：带上时按四模式映射到 scope / filters，忽略 scope 与 order
    mode: str | None = None


class AnswerPayload(BaseModel):
    questionId: str
    answer: str | list | None = None
    timeSpent: int | None = Field(default=None, ge=0)


def _load_session(conn: sqlite3.Connection, session_id: str, user: dict):
    row = conn.execute(
        "SELECT * FROM practice_sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="刷题会话不存在")
    if row["user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="无权访问该会话")
    return row


def _question_ids(session_row) -> list[str]:
    return json.loads(session_row["question_ids"] or "[]")


def _current_question(conn: sqlite3.Connection, session_row):
    ids = _question_ids(session_row)
    cursor = session_row["cursor"]
    if cursor >= len(ids):
        return None
    row = conn.execute("SELECT * FROM questions WHERE id = ?", (ids[cursor],)).fetchone()
    return question_row_to_dict(row) if row else None


def _session_questions(conn: sqlite3.Connection, session_row) -> list[dict]:
    """会话全量题目（按出题顺序，不带答案）——翻阅式作答要一次拿到整卷。"""
    questions = []
    for qid in _question_ids(session_row):
        row = conn.execute("SELECT * FROM questions WHERE id = ?", (qid,)).fetchone()
        if row:
            questions.append(question_row_to_dict(row))
    return questions


def _session_records(conn: sqlite3.Connection, session_row) -> list[dict]:
    """本会话的作答记录，按题目顺序排列（刷新后据此恢复翻页状态）。"""
    rows = conn.execute(
        "SELECT * FROM practice_records WHERE session_id = ?", (session_row["id"],)
    ).fetchall()
    by_question = {row["question_id"]: row for row in rows}
    records: list[dict] = []
    for qid in _question_ids(session_row):
        row = by_question.get(qid)
        if row is None:
            continue
        record = record_row_to_dict(row)
        # 已作答的题才带答案：刷新后判分反馈里的「正确答案」不会丢，
        # 未作答的题依旧不泄漏（with_answer=False 的 questions 不含答案）。
        answer_row = conn.execute(
            "SELECT answer FROM questions WHERE id = ?", (qid,)
        ).fetchone()
        record["answer"] = (
            json.loads(answer_row["answer"]) if answer_row and answer_row["answer"] else None
        )
        records.append(record)
    return records


def _answered_ids(conn: sqlite3.Connection, session_id: str) -> set[str]:
    rows = conn.execute(
        "SELECT question_id FROM practice_records WHERE session_id = ?", (session_id,)
    ).fetchall()
    return {row["question_id"] for row in rows}


def _session_stats(conn: sqlite3.Connection, session_id: str) -> dict:
    rows = conn.execute(
        "SELECT correct FROM practice_records WHERE session_id = ?", (session_id,)
    ).fetchall()
    return {
        "answered": len(rows),
        "correct": sum(1 for row in rows if row["correct"] == 1),
        "pending": sum(1 for row in rows if row["correct"] is None),
    }


def _session_payload(conn: sqlite3.Connection, session_id: str, user: dict) -> dict:
    row = _load_session(conn, session_id, user)
    ids = _question_ids(row)
    stats = _session_stats(conn, session_id)
    config = json.loads(row["config"] or "{}")
    return {
        "session": {
            "id": row["id"],
            "mode": row["mode"],
            "order": config.get("order", "shuffle"),
            "bankId": row["bank_id"],
            "filters": json.loads(row["filters"] or "{}"),
            "total": len(ids),
            "answered": stats["answered"],
            "correct": stats["correct"],
            "pending": stats["pending"],
            "cursor": row["cursor"],
            "startedAt": row["started_at"],
            "finishedAt": row["finished_at"],
            "finished": row["finished_at"] is not None,
        },
        "current": _current_question(conn, row),
        "questions": _session_questions(conn, row),
        "records": _session_records(conn, row),
    }


@router.post("/api/practice/sessions")
def post_practice_sessions(
    payload: SessionCreate,
    user: Annotated[dict, Depends(require_user)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
):
    if payload.mode is not None:
        # 旧入口：四模式映射到 scope / filters
        if payload.mode not in _LEGACY_MODES:
            raise HTTPException(status_code=422, detail=f"未知刷题模式：{payload.mode}")
        if payload.mode == "wrong":
            scope = "wrong"
        else:
            scope = "all"
            if payload.mode == "by_type" and not payload.filters.get("type"):
                raise HTTPException(status_code=422, detail="按题型刷题必须指定题型")
            if payload.mode == "by_tag" and not payload.filters.get("tag"):
                raise HTTPException(status_code=422, detail="按标签刷题必须指定标签")
    else:
        scope = payload.scope
    if scope not in SCOPES:
        raise HTTPException(status_code=422, detail=f"未知刷题范围：{scope}")
    if payload.order not in ORDERS:
        raise HTTPException(status_code=422, detail=f"未知刷题顺序：{payload.order}")

    try:
        rows = select_question_rows(
            conn, user["id"], scope, payload.bankId, payload.filters, payload.limit, payload.order
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if not rows:
        raise HTTPException(status_code=422, detail="没有符合条件的题目")

    session_id = new_id()
    question_ids = [row["id"] for row in rows]
    mode = "wrong" if scope == "wrong" else "infinite"
    conn.execute(
        """INSERT INTO practice_sessions
           (id, user_id, mode, bank_id, filters, config, question_ids, cursor)
           VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
        (
            session_id,
            user["id"],
            mode,
            payload.bankId,
            json.dumps(payload.filters, ensure_ascii=False),
            json.dumps({"limit": payload.limit, "order": payload.order}, ensure_ascii=False),
            json.dumps(question_ids, ensure_ascii=False),
        ),
    )
    conn.commit()
    return _session_payload(conn, session_id, user)


@router.get("/api/practice/sessions/{session_id}")
def get_practice_sessions_by_session_id(
    session_id: str,
    user: Annotated[dict, Depends(require_user)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
):
    return _session_payload(conn, session_id, user)


@router.post("/api/practice/sessions/{session_id}/answer")
def post_practice_sessions_by_session_id_answer(
    session_id: str,
    payload: AnswerPayload,
    user: Annotated[dict, Depends(require_user)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
):
    session = _load_session(conn, session_id, user)
    if session["finished_at"] is not None:
        raise HTTPException(status_code=409, detail="该会话已结束")

    ids = _question_ids(session)
    if payload.questionId not in ids:
        raise HTTPException(status_code=404, detail="该题不属于本会话")
    if payload.questionId in _answered_ids(conn, session_id):
        raise HTTPException(status_code=409, detail="该题已作答")

    question = conn.execute(
        "SELECT * FROM questions WHERE id = ?", (payload.questionId,)
    ).fetchone()
    if question is None:
        raise HTTPException(status_code=404, detail="题目不存在")

    question_data = question_row_to_dict(question, with_answer=True)
    config = get_judge_config(conn)
    outcome = judge_answer(question_data, payload.answer, config)

    record_id = new_id()
    conn.execute(
        """INSERT INTO practice_records
           (id, session_id, user_id, question_id, user_answer, correct, score, max_score, time_spent)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            record_id,
            session_id,
            user["id"],
            payload.questionId,
            json.dumps(payload.answer, ensure_ascii=False),
            1 if outcome.correct else (0 if outcome.correct is False else None),
            outcome.score,
            outcome.max_score,
            payload.timeSpent,
        ),
    )
    apply_judge_outcome(conn, user["id"], payload.questionId, outcome, config)
    # 翻阅式作答不要求按顺序答：答完一题，光标前进到顺序上的下一道，
    # 答错也停在原题（由用户看完解析自行决定），不回头补前面没答的题。
    cursor = ids.index(payload.questionId) + 1
    conn.execute(
        "UPDATE practice_sessions SET cursor = ? WHERE id = ?", (cursor, session_id)
    )
    conn.commit()

    response = _session_payload(conn, session_id, user)
    response["outcome"] = {
        "correct": outcome.correct,
        "score": outcome.score,
        "maxScore": outcome.max_score,
        "detail": outcome.detail,
        "explanation": question["explanation"],
        "answer": question_data["answer"],
    }
    response["recordId"] = record_id
    return response


@router.post("/api/practice/sessions/{session_id}/finish")
def post_practice_sessions_by_session_id_finish(
    session_id: str,
    user: Annotated[dict, Depends(require_user)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
):
    _load_session(conn, session_id, user)
    conn.execute(
        "UPDATE practice_sessions SET finished_at = datetime('now') WHERE id = ? AND finished_at IS NULL",
        (session_id,),
    )
    conn.commit()
    return _result_payload(conn, session_id, user)


def _result_payload(conn: sqlite3.Connection, session_id: str, user: dict) -> dict:
    """结算 / 答卷回顾共用的完整 payload：逐题带答案，会话既已结束（或用户在主动回顾）不再有泄漏风险。"""
    response = _session_payload(conn, session_id, user)
    stats = _session_stats(conn, session_id)
    response["summary"] = {
        "answered": stats["answered"],
        "correct": stats["correct"],
        "pending": stats["pending"],
        "accuracy": round(stats["correct"] / stats["answered"], 4) if stats["answered"] else None,
    }
    session_row = conn.execute(
        "SELECT * FROM practice_sessions WHERE id = ?", (session_id,)
    ).fetchone()
    response["questions"] = [
        question_row_to_dict(
            conn.execute("SELECT * FROM questions WHERE id = ?", (qid,)).fetchone(),
            with_answer=True,
        )
        for qid in _question_ids(session_row)
    ]
    return response


@router.get("/api/practice/sessions/{session_id}/result")
def get_practice_sessions_by_session_id_result(
    session_id: str,
    user: Annotated[dict, Depends(require_user)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
):
    """回顾历史答卷：概览的记录列表点进来时用，不改动会话状态。"""
    _load_session(conn, session_id, user)
    return _result_payload(conn, session_id, user)


@router.get("/api/practice/sessions/{session_id}/resume")
def get_practice_sessions_by_session_id_resume(
    session_id: str,
    user: Annotated[dict, Depends(require_user)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
):
    session = _load_session(conn, session_id, user)
    if session["finished_at"] is not None:
        raise HTTPException(status_code=409, detail="该会话已结束")
    return _session_payload(conn, session_id, user)


@router.get("/api/wrong-questions")
def get_wrong_questions(
    user: Annotated[dict, Depends(require_user)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    type: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    bank_id: str | None = Query(default=None),
    mastered: bool = Query(default=False),
):
    query = """
        SELECT w.id AS wrong_id, w.wrong_count, w.correct_streak, w.mastered, w.last_wrong_at,
               q.*
        FROM wrong_questions w JOIN questions q ON q.id = w.question_id
        WHERE w.user_id = ? AND w.mastered = ?
    """
    params: list = [user["id"], 1 if mastered else 0]
    if type:
        query += " AND q.type = ?"
        params.append(type)
    if tag:
        query += " AND q.tags LIKE ?"
        params.append(f'%"{tag}"%')
    if bank_id:
        query += " AND q.bank_id = ?"
        params.append(bank_id)
    query += " ORDER BY w.last_wrong_at DESC"

    rows = conn.execute(query, params).fetchall()
    return {
        "items": [
            {
                "id": row["wrong_id"],
                "wrongCount": row["wrong_count"],
                "correctStreak": row["correct_streak"],
                "mastered": bool(row["mastered"]),
                "lastWrongAt": row["last_wrong_at"],
                "question": question_row_to_dict(row),
            }
            for row in rows
        ]
    }


@router.delete("/api/wrong-questions/{wrong_id}")
def delete_wrong_questions_by_wrong_id(
    wrong_id: str,
    user: Annotated[dict, Depends(require_user)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
):
    row = conn.execute(
        "SELECT * FROM wrong_questions WHERE id = ?", (wrong_id,)
    ).fetchone()
    if row is None or row["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="错题记录不存在")
    conn.execute("DELETE FROM wrong_questions WHERE id = ?", (wrong_id,))
    conn.commit()
    return {"ok": True}
