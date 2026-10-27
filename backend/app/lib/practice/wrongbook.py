"""错题本更新：答错收录 / 答对连击，掌握阈值 master_streak 来自判分配置。

对应 CONTRACT.md §5：连续答对 master_streak 次标记掌握并移出错题本。
主观题在阅卷判定后经 apply_graded 走同一套逻辑。
"""

from __future__ import annotations

import sqlite3

from app.db import new_id
from app.lib.judge import JudgeOutcome

# 内置错题本题库：每个用户一份，在题库页置顶且不可改名 / 删除。
# 它不存题目副本——列表是 wrong_questions（未掌握）的投影，删掉一条 = 移出错题本。
WRONGBOOK_KIND = "wrongbook"
WRONGBOOK_NAME = "错题本"
WRONGBOOK_DESC = "自动收录做错且还没掌握的题，在题库页置顶显示"


def ensure_bank(conn: sqlite3.Connection, user_id: str):
    """取（没有就建）当前用户的内置错题本题库。列表接口每次都调，保证它永远在。"""
    row = conn.execute(
        "SELECT * FROM banks WHERE kind = ? AND owner_id = ?", (WRONGBOOK_KIND, user_id)
    ).fetchone()
    if row is not None:
        return row
    bank_id = new_id()
    conn.execute(
        """INSERT INTO banks (id, name, description, owner_id, is_shared, kind)
           VALUES (?, ?, ?, ?, 0, ?)""",
        (bank_id, WRONGBOOK_NAME, WRONGBOOK_DESC, user_id, WRONGBOOK_KIND),
    )
    conn.commit()
    return conn.execute("SELECT * FROM banks WHERE id = ?", (bank_id,)).fetchone()


def is_wrongbook(bank_row) -> bool:
    return bank_row is not None and bank_row["kind"] == WRONGBOOK_KIND


def question_rows(
    conn: sqlite3.Connection,
    user_id: str,
    where: list[str],
    params: list,
    order_by: str,
    limit: int | None = None,
    offset: int = 0,
):
    """错题本题库的题目：按当前用户未掌握的错题投影出来（不复制题目）。"""
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    sql = f"""SELECT w.id AS wrong_id, w.wrong_count, w.correct_streak, w.last_wrong_at, q.*
              FROM wrong_questions w JOIN questions q ON q.id = w.question_id
              {clause} {order_by}"""
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params = params + [limit, offset]
    return conn.execute(sql, params).fetchall()


def add_wrong(conn, user_id: str, question_id: str) -> None:
    row = conn.execute(
        "SELECT id FROM wrong_questions WHERE user_id = ? AND question_id = ?",
        (user_id, question_id),
    ).fetchone()
    if row:
        conn.execute(
            """UPDATE wrong_questions
               SET wrong_count = wrong_count + 1, correct_streak = 0,
                   mastered = 0, last_wrong_at = datetime('now')
               WHERE id = ?""",
            (row["id"],),
        )
    else:
        conn.execute(
            "INSERT INTO wrong_questions (id, user_id, question_id) VALUES (?, ?, ?)",
            (new_id(), user_id, question_id),
        )
    conn.commit()


def apply_correct(conn, user_id: str, question_id: str, master_streak: int) -> None:
    row = conn.execute(
        "SELECT id, correct_streak, mastered FROM wrong_questions WHERE user_id = ? AND question_id = ?",
        (user_id, question_id),
    ).fetchone()
    if row is None or row["mastered"]:
        return
    streak = row["correct_streak"] + 1
    mastered = 1 if streak >= master_streak else 0
    conn.execute(
        "UPDATE wrong_questions SET correct_streak = ?, mastered = ? WHERE id = ?",
        (streak, mastered, row["id"]),
    )
    conn.commit()


def apply_judge_outcome(conn, user_id: str, question_id: str, outcome: JudgeOutcome, config: dict) -> None:
    """客观题判分后更新错题本。主观题（correct 为 None）不处理，等阅卷。"""
    if outcome.correct is None:
        return
    if outcome.correct:
        apply_correct(conn, user_id, question_id, config["masterStreak"])
    else:
        add_wrong(conn, user_id, question_id)


def apply_graded(conn, user_id: str, question_id: str, correct: bool, config: dict) -> None:
    """主观题阅卷判定后更新错题本（得分率 ≥ 阈值视为正确，走连击逻辑）。"""
    if correct:
        apply_correct(conn, user_id, question_id, config["masterStreak"])
    else:
        add_wrong(conn, user_id, question_id)
