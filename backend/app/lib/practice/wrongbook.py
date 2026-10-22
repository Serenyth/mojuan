"""错题本更新：答错收录 / 答对连击，掌握阈值 master_streak 来自判分配置。

对应 CONTRACT.md §5：连续答对 master_streak 次标记掌握并移出错题本。
主观题在阅卷判定后经 apply_graded 走同一套逻辑。
"""

from __future__ import annotations

from app.db import new_id
from app.lib.judge import JudgeOutcome


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
