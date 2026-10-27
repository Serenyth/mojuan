import json
import random
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.db import get_db, new_id
from app.deps import require_user
from app.settings import get_judge_config
from app.lib.judge import judge_answer
from app.lib.practice.permissions import can_manage
from app.lib.practice.scores import compute_exam_scores
from app.lib.practice.serialize import question_row_to_dict, record_row_to_dict
from app.lib.practice import wrongbook
from app.lib.practice.wrongbook import apply_judge_outcome

router = APIRouter()

QUESTION_TYPES = ("single_choice", "multiple_choice", "true_false", "fill_blank", "subjective")


class TemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    scopeBankId: str | None = None
    scopeTags: list[str] | None = None
    typeDistribution: dict[str, int]
    totalCount: int = Field(ge=1)
    durationMinutes: int = Field(default=60, ge=1)
    shuffle: bool = True
    isShared: bool = True


class TemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    scopeBankId: str | None = None
    scopeTags: list[str] | None = None
    typeDistribution: dict[str, int] | None = None
    totalCount: int | None = Field(default=None, ge=1)
    durationMinutes: int | None = Field(default=None, ge=1)
    shuffle: bool | None = None
    isShared: bool | None = None


class ExamStart(BaseModel):
    templateId: str


class ExamAnswer(BaseModel):
    questionId: str
    answer: str | list | None = None
    timeSpent: int | None = Field(default=None, ge=0)


class ExamSubmit(BaseModel):
    answers: list[ExamAnswer] = Field(default_factory=list)


def _validate_distribution(distribution: dict, total_count: int) -> None:
    for q_type in distribution:
        if q_type not in QUESTION_TYPES:
            raise HTTPException(status_code=422, detail=f"模板包含未知题型：{q_type}")
    if any(count < 0 for count in distribution.values()):
        raise HTTPException(status_code=422, detail="题型分布不能为负数")
    if sum(distribution.values()) != total_count:
        raise HTTPException(
            status_code=422,
            detail=f"题型分布合计 {sum(distribution.values())} 与总题量 {total_count} 不一致",
        )
    if total_count <= 0 or sum(distribution.values()) <= 0:
        raise HTTPException(status_code=422, detail="总题量必须大于 0")


def _template_dict(row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "ownerId": row["owner_id"],
        "isShared": bool(row["is_shared"]),
        "scopeBankId": row["scope_bank_id"],
        "scopeTags": json.loads(row["scope_tags"]) if row["scope_tags"] else [],
        "typeDistribution": json.loads(row["type_distribution"]),
        "totalCount": row["total_count"],
        "durationMinutes": row["duration_minutes"],
        "shuffle": bool(row["shuffle"]),
        "createdAt": row["created_at"],
    }


def _require_template(conn: sqlite3.Connection, template_id: str):
    row = conn.execute(
        "SELECT * FROM exam_templates WHERE id = ?", (template_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="考试模板不存在")
    return row


def _require_template_manage(template_row, user: dict) -> None:
    if not can_manage(template_row["owner_id"], bool(template_row["is_shared"]), user):
        raise HTTPException(status_code=403, detail="无权管理该考试模板")


def _require_exam(conn: sqlite3.Connection, exam_id: str, user: dict):
    row = conn.execute("SELECT * FROM exams WHERE id = ?", (exam_id,)).fetchone()
    if row is None or row["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="考试不存在")
    return row


def _exam_dict(conn: sqlite3.Connection, exam_id: str) -> dict:
    exam = conn.execute(
        """SELECT e.*, t.name AS template_name, t.duration_minutes
           FROM exams e LEFT JOIN exam_templates t ON t.id = e.template_id
           WHERE e.id = ?""",
        (exam_id,),
    ).fetchone()
    scores = compute_exam_scores(conn, exam_id)
    started = datetime.fromisoformat(exam["started_at"])
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    duration = exam["duration_minutes"] or 60
    return {
        "id": exam["id"],
        "templateId": exam["template_id"],
        "templateName": exam["template_name"],
        "questionCount": len(json.loads(exam["question_ids"])),
        "durationMinutes": duration,
        "startedAt": exam["started_at"],
        "deadline": (started + timedelta(minutes=duration)).isoformat(),
        "submittedAt": exam["submitted_at"],
        "status": exam["status"],
        "scores": scores,
    }


def _reject_wrongbook_scope(conn, bank_id: str | None) -> None:
    """错题本是虚拟集合（题目的引用），组卷按题库抽题抽不到，直接挡在前面。"""
    if not bank_id:
        return
    bank = conn.execute("SELECT * FROM banks WHERE id = ?", (bank_id,)).fetchone()
    if wrongbook.is_wrongbook(bank):
        raise HTTPException(status_code=400, detail="试卷不能从错题本组卷")


@router.get("/api/exam-templates")
def get_exam_templates(
    user: Annotated[dict, Depends(require_user)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
):
    rows = conn.execute(
        "SELECT * FROM exam_templates ORDER BY created_at DESC, name"
    ).fetchall()
    return {"templates": [_template_dict(row) for row in rows]}


@router.post("/api/exam-templates")
def post_exam_templates(
    payload: TemplateCreate,
    user: Annotated[dict, Depends(require_user)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
):
    _validate_distribution(payload.typeDistribution, payload.totalCount)
    _reject_wrongbook_scope(conn, payload.scopeBankId)
    template_id = new_id()
    conn.execute(
        """INSERT INTO exam_templates
           (id, name, owner_id, is_shared, scope_bank_id, scope_tags,
            type_distribution, total_count, duration_minutes, shuffle)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            template_id,
            payload.name,
            user["id"],
            1 if payload.isShared else 0,
            payload.scopeBankId,
            json.dumps(payload.scopeTags, ensure_ascii=False)
            if payload.scopeTags
            else None,
            json.dumps(payload.typeDistribution, ensure_ascii=False),
            payload.totalCount,
            payload.durationMinutes,
            1 if payload.shuffle else 0,
        ),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM exam_templates WHERE id = ?", (template_id,)
    ).fetchone()
    return {"template": _template_dict(row)}


@router.get("/api/exam-templates/{template_id}")
def get_exam_templates_by_template_id(
    template_id: str,
    user: Annotated[dict, Depends(require_user)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
):
    row = _require_template(conn, template_id)
    return {"template": _template_dict(row)}


@router.patch("/api/exam-templates/{template_id}")
def patch_exam_templates_by_template_id(
    template_id: str,
    payload: TemplateUpdate,
    user: Annotated[dict, Depends(require_user)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
):
    row = _require_template(conn, template_id)
    _require_template_manage(row, user)

    patch = payload.model_dump(exclude_none=True)
    if "typeDistribution" in patch or "totalCount" in patch:
        distribution = patch.get(
            "typeDistribution", json.loads(row["type_distribution"])
        )
        total = patch.get("totalCount", row["total_count"])
        _validate_distribution(distribution, total)
    for column in ("scopeTags", "typeDistribution"):
        if column in patch and patch[column] is not None:
            value = patch.pop(column)
            renamed = {"scopeTags": "scope_tags", "typeDistribution": "type_distribution"}[
                column
            ]
            patch[renamed] = json.dumps(value, ensure_ascii=False)
    for column in ("shuffle", "isShared"):
        if column in patch:
            patch[{"shuffle": "shuffle", "isShared": "is_shared"}[column]] = (
                1 if patch.pop(column) else 0
            )
    if "scopeBankId" in patch:
        _reject_wrongbook_scope(conn, patch["scopeBankId"])
        patch["scope_bank_id"] = patch.pop("scopeBankId")
    if "totalCount" in patch:
        patch["total_count"] = patch.pop("totalCount")
    if "durationMinutes" in patch:
        patch["duration_minutes"] = patch.pop("durationMinutes")

    if patch:
        assignments = ", ".join(f"{column} = ?" for column in patch)
        conn.execute(
            f"UPDATE exam_templates SET {assignments} WHERE id = ?",
            (*patch.values(), template_id),
        )
        conn.commit()
    updated = conn.execute(
        "SELECT * FROM exam_templates WHERE id = ?", (template_id,)
    ).fetchone()
    return {"template": _template_dict(updated)}


@router.delete("/api/exam-templates/{template_id}")
def delete_exam_templates_by_template_id(
    template_id: str,
    user: Annotated[dict, Depends(require_user)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
):
    row = _require_template(conn, template_id)
    _require_template_manage(row, user)
    conn.execute("DELETE FROM exam_templates WHERE id = ?", (template_id,))
    conn.commit()
    return {"ok": True}


@router.post("/api/exams/start")
def post_exams_start(
    payload: ExamStart,
    user: Annotated[dict, Depends(require_user)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
):
    template = _require_template(conn, payload.templateId)
    distribution = json.loads(template["type_distribution"])
    scope_tags = json.loads(template["scope_tags"]) if template["scope_tags"] else []
    shuffle = bool(template["shuffle"])

    conditions: list[str] = []
    params: list = []
    if template["scope_bank_id"]:
        conditions.append("q.bank_id = ?")
        params.append(template["scope_bank_id"])
    if scope_tags:
        conditions.append("(" + " OR ".join(["q.tags LIKE ?"] * len(scope_tags)) + ")")
        params.extend(f'%"{tag}"%' for tag in scope_tags)
    clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    missing: list[dict] = []
    picked_ids: list[str] = []
    # 无抽题条件时 clause 为空，不能直接拼 " AND q.type = ?"（悬空 AND）
    where = f"WHERE {clause[6:]} AND q.type = ?" if clause else "WHERE q.type = ?"
    for q_type, count in distribution.items():
        if count <= 0:
            continue
        rows = conn.execute(
            f"SELECT q.id FROM questions q {where} ORDER BY RANDOM() LIMIT ?",
            params + [q_type, count],
        ).fetchall()
        if len(rows) < count:
            missing.append({"type": q_type, "need": count, "have": len(rows)})
        picked_ids.extend(row["id"] for row in rows)
    if missing:
        detail = "；".join(f"{item['type']} 需要 {item['need']} 道，仅有 {item['have']} 道" for item in missing)
        raise HTTPException(status_code=422, detail=f"抽题范围内题目不足：{detail}")

    if shuffle:
        random.shuffle(picked_ids)

    exam_id = new_id()
    started = datetime.now(timezone.utc)
    conn.execute(
        """INSERT INTO exams (id, template_id, user_id, question_ids, started_at, status)
           VALUES (?, ?, ?, ?, ?, 'ongoing')""",
        (
            exam_id,
            payload.templateId,
            user["id"],
            json.dumps(picked_ids, ensure_ascii=False),
            started.isoformat(),
        ),
    )
    conn.commit()

    questions = [
        question_row_to_dict(
            conn.execute("SELECT * FROM questions WHERE id = ?", (qid,)).fetchone()
        )
        for qid in picked_ids
    ]
    return {"exam": _exam_dict(conn, exam_id), "questions": questions}


@router.post("/api/exams/{exam_id}/submit")
def post_exams_by_exam_id_submit(
    exam_id: str,
    payload: ExamSubmit,
    user: Annotated[dict, Depends(require_user)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
):
    exam = _require_exam(conn, exam_id, user)
    if exam["status"] != "ongoing":
        raise HTTPException(status_code=409, detail="该考试已交卷")

    question_ids = set(json.loads(exam["question_ids"]))
    submitted = {item.questionId for item in payload.answers}
    unknown = submitted - question_ids
    if unknown:
        raise HTTPException(status_code=422, detail="提交中包含不属于本考试的题目")

    config = get_judge_config(conn)
    for item in payload.answers:
        question = conn.execute(
            "SELECT * FROM questions WHERE id = ?", (item.questionId,)
        ).fetchone()
        if question is None:
            continue
        outcome = judge_answer(
            question_row_to_dict(question, with_answer=True), item.answer, config
        )
        conn.execute(
            """INSERT INTO practice_records
               (id, exam_id, user_id, question_id, user_answer, correct, score, max_score, time_spent)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                new_id(),
                exam_id,
                user["id"],
                item.questionId,
                json.dumps(item.answer, ensure_ascii=False),
                1 if outcome.correct else (0 if outcome.correct is False else None),
                outcome.score,
                outcome.max_score,
                item.timeSpent,
            ),
        )
        apply_judge_outcome(conn, user["id"], item.questionId, outcome, config)

    started = datetime.fromisoformat(exam["started_at"])
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    template = conn.execute(
        "SELECT duration_minutes FROM exam_templates WHERE id = ?", (exam["template_id"],)
    ).fetchone()
    duration = template["duration_minutes"] if template else 60
    overtime = datetime.now(timezone.utc) > started + timedelta(minutes=duration)

    conn.execute(
        "UPDATE exams SET submitted_at = ? WHERE id = ?",
        (datetime.now(timezone.utc).isoformat(), exam_id),
    )
    scores = compute_exam_scores(conn, exam_id)
    status = "submitted" if scores["subjectiveCount"] == 0 else "grading"
    conn.execute(
        "UPDATE exams SET objective_score = ?, subjective_score = ?, total_score = ?, status = ? WHERE id = ?",
        (
            scores["objectiveScore"],
            scores["subjectiveScore"],
            scores["totalScore"],
            status,
            exam_id,
        ),
    )
    conn.commit()

    return {
        "exam": _exam_dict(conn, exam_id),
        "scores": scores,
        "unanswered": sorted(question_ids - submitted),
        "overtime": overtime,
    }


@router.get("/api/exams/{exam_id}/result")
def get_exams_by_exam_id_result(
    exam_id: str,
    user: Annotated[dict, Depends(require_user)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    include_answer: bool = Query(default=False),
):
    exam = _require_exam(conn, exam_id, user)
    # 进行中的考试只用于恢复答题，不能把答案发出去
    if include_answer and exam["status"] == "ongoing":
        raise HTTPException(status_code=409, detail="考试进行中不提供答案")
    ids = json.loads(exam["question_ids"])

    question_map = {
        qid: question_row_to_dict(
            conn.execute("SELECT * FROM questions WHERE id = ?", (qid,)).fetchone(),
            with_answer=include_answer,
        )
        for qid in ids
    }
    records = conn.execute(
        "SELECT * FROM practice_records WHERE exam_id = ?", (exam_id,)
    ).fetchall()
    record_map = {row["question_id"]: record_row_to_dict(row) for row in records}

    return {
        "exam": _exam_dict(conn, exam_id),
        "questions": [question_map[qid] for qid in ids if qid in question_map],
        "records": [record_map[qid] for qid in ids if qid in record_map],
        "scores": compute_exam_scores(conn, exam_id),
    }
