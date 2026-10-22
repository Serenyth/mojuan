"""提取任务的执行与落库：路由与 agent 工具共用。

POST /api/extract/direct、POST /api/extract/script 和 agent 的
extract_questions / run_script 工具都走这里，保证「按钮触发」「对话触发」
两条入口行为一致：候选题进 extraction_jobs，不写 questions 表（契约：AI
产出必须经人工审核）。
"""

import json

from app.db import DATA_DIR, new_id
from app.deps import require_source
from app.lib.ai import AiError
from app.lib.extract.direct import run_direct
from app.lib.extract.sandbox import build_source_payload, run_script

MAX_SCRIPT_QUESTIONS = 500


def _existing_fingerprints(conn) -> set[str]:
    rows = conn.execute("SELECT fingerprint FROM questions WHERE fingerprint IS NOT NULL").fetchall()
    return {row["fingerprint"] for row in rows}


def run_and_store(
    conn,
    owner_id: str,
    client,
    source_ids: list[str],
    instruction: str = "",
) -> dict:
    """跑一次模式 A，候选题存进 extraction_jobs。

    返回 {jobId, questions, stats}。source_ids 先过归属校验（404），
    再建客户端之外的提取流程，与直接端点的错误顺序保持一致。
    """
    if not source_ids:
        raise AiError("没有可提取的材料")

    source_rows = [require_source(conn, source_id, {"id": owner_id}) for source_id in source_ids]

    outcome = run_direct(
        client,
        source_rows,
        instruction=instruction,
        existing_fingerprints=_existing_fingerprints(conn),
    )
    questions = outcome["questions"]
    stats = outcome["stats"]

    job_id = new_id()
    conn.execute(
        """INSERT INTO extraction_jobs
           (id, owner_id, source_ids, mode, status, stats, result)
           VALUES (?, ?, ?, 'direct', 'review', ?, ?)""",
        (
            job_id,
            owner_id,
            json.dumps(source_ids, ensure_ascii=False),
            json.dumps(stats, ensure_ascii=False),
            json.dumps(questions, ensure_ascii=False),
        ),
    )
    conn.commit()

    return {"jobId": job_id, "questions": questions, "stats": stats}


def run_script_job(
    conn,
    owner_id: str,
    script_id: str,
    source_ids: list[str],
) -> dict:
    """用提取脚本把材料跑成候选题（沙盒执行），落 extraction_jobs + script_runs。

    与 POST /api/extract/script 完全一致：脚本代码在无网络沙盒里执行，
    输出经 parse_questions 收敛成统一 Schema，候选题存进 extraction_jobs
    （仍不写 questions 表）。返回 {ok, job, questions, log, error}。
    """
    from app.lib.extract.direct import parse_questions

    source_rows = [require_source(conn, source_id, {"id": owner_id}) for source_id in source_ids]
    script = conn.execute(
        "SELECT * FROM extraction_scripts WHERE id = ?", (script_id,)
    ).fetchone()
    if script is None:
        return {"ok": False, "job": None, "questions": [], "log": "", "error": "脚本不存在"}

    sources_payload = build_source_payload(source_rows, DATA_DIR)
    outcome = run_script(script["code"], sources_payload)
    log = outcome.get("log") or ""
    duration_ms = outcome.get("duration_ms") or 0
    run_id = new_id()

    if not outcome.get("ok"):
        conn.execute(
            """INSERT INTO script_runs
               (id, script_id, job_id, status, log, duration_ms)
               VALUES (?, ?, NULL, 'failed', ?, ?)""",
            (run_id, script["id"], log, duration_ms),
        )
        conn.commit()
        return {
            "ok": False,
            "job": None,
            "questions": [],
            "log": log,
            "error": outcome.get("error") or "脚本执行失败",
        }

    questions = parse_questions(outcome.get("questions") or [])[:MAX_SCRIPT_QUESTIONS]
    existing = {
        row["fingerprint"]
        for row in conn.execute("SELECT fingerprint FROM questions WHERE fingerprint IS NOT NULL").fetchall()
    }
    for question in questions:
        question["duplicate"] = question["fingerprint"] in existing

    stats = {
        "extracted": len(questions),
        "suspect": sum(1 for q in questions if q["suspect"] or q["issues"]),
        "mode": "script",
        "script": script["name"],
        "version": script["version"],
        "log": log[:2000],
    }

    job_id = new_id()
    conn.execute(
        """INSERT INTO extraction_jobs
           (id, owner_id, source_ids, mode, status, script_id, stats, result)
           VALUES (?, ?, ?, 'script', 'review', ?, ?, ?)""",
        (
            job_id,
            owner_id,
            json.dumps(source_ids, ensure_ascii=False),
            script["id"],
            json.dumps(stats, ensure_ascii=False),
            json.dumps(questions, ensure_ascii=False),
        ),
    )
    conn.execute(
        """INSERT INTO script_runs
           (id, script_id, job_id, status, log, duration_ms)
           VALUES (?, ?, ?, 'ok', ?, ?)""",
        (run_id, script["id"], job_id, log, duration_ms),
    )
    conn.commit()

    return {
        "ok": True,
        "job": {"id": job_id, "stats": stats},
        "questions": questions,
        "log": log,
        "error": None,
    }
