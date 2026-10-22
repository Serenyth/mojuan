"""刷题组题策略：条件筛选（范围 × 题库/题型/标签 × 随机/顺序）。

- 范围 scope：all 全部题目 / wrong 错题本未掌握
- 筛选 filters：题库（bank_id 单独传）+ 题型 + 标签
- 顺序 order：shuffle 随机刷题（保留三级优先级）/ sequential 顺序刷题（按入库时间正序）

随机刷题的抽题优先级（设计方案 §4）：未做过 > 答错过（错题本未掌握）> 已答对（降权）。
模拟考试的组卷在 routers/exams.py 内直接实现（按模板题型分布抽样）。
"""

from __future__ import annotations

import sqlite3

DEFAULT_SESSION_SIZE = 20

QUESTION_TYPES = ("single_choice", "multiple_choice", "true_false", "fill_blank", "subjective")

SCOPES = ("all", "wrong")

ORDERS = ("shuffle", "sequential")


def select_question_rows(
    conn: sqlite3.Connection,
    user_id: str,
    scope: str = "all",
    bank_id: str | None = None,
    filters: dict | None = None,
    limit: int = DEFAULT_SESSION_SIZE,
    order: str = "shuffle",
) -> list:
    if scope not in SCOPES:
        raise ValueError(f"未知刷题范围：{scope}")
    if order not in ORDERS:
        raise ValueError(f"未知刷题顺序：{order}")
    filters = filters or {}
    if scope == "wrong":
        return _select_wrong(conn, user_id, bank_id, filters, limit, order)
    return _select_all(conn, user_id, bank_id, filters, limit, order)


def _filter_clause(filters: dict) -> tuple[list[str], list]:
    """题型 / 标签筛选转 WHERE 片段（题库由调用方单独拼）。"""
    where: list[str] = []
    params: list = []
    q_type = filters.get("type")
    if q_type:
        if q_type not in QUESTION_TYPES:
            raise ValueError(f"未知题型：{q_type}")
        where.append("q.type = ?")
        params.append(q_type)
    tag = filters.get("tag")
    if tag:
        where.append("q.tags LIKE ?")
        params.append(f'%"{tag}"%')
    return where, params


def _run(
    conn: sqlite3.Connection,
    bank_id: str | None,
    filters: dict,
    limit: int,
    order: str,
    extra_where: str = "",
    extra_params: tuple = (),
) -> list:
    where, params = _filter_clause(filters)
    if bank_id:
        where.insert(0, "q.bank_id = ?")
        params.insert(0, bank_id)
    if extra_where:
        where.append(f"({extra_where})")
        params.extend(extra_params)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    if order == "sequential":
        # created_at 只有秒级精度，批量入库会同秒；rowid 单调递增，作次级排序
        # 才能保证「顺序刷题」真的是入库顺序
        tail = "ORDER BY q.created_at ASC, q.rowid ASC"
    else:
        tail = "ORDER BY RANDOM()"
    return conn.execute(
        f"SELECT q.* FROM questions q {clause} {tail} LIMIT ?",
        params + [limit],
    ).fetchall()


def _select_all(conn, user_id, bank_id, filters, limit, order) -> list:
    if order == "sequential":
        return _run(conn, bank_id, filters, limit, order)
    # 随机刷题保留三级优先：未做过 > 错题未掌握 > 其余
    answered = "SELECT question_id FROM practice_records WHERE user_id = ?"
    wrong = "SELECT question_id FROM wrong_questions WHERE user_id = ? AND mastered = 0"

    never = _run(conn, bank_id, filters, limit, order, f"q.id NOT IN ({answered})", (user_id,))
    unmastered = _run(conn, bank_id, filters, limit, order, f"q.id IN ({wrong})", (user_id,))
    rest = _run(conn, bank_id, filters, limit, order)

    picked: list = []
    seen: set[str] = set()
    for row in (*never, *unmastered, *rest):
        if row["id"] not in seen:
            seen.add(row["id"])
            picked.append(row)
        if len(picked) >= limit:
            break
    return picked


def _select_wrong(conn, user_id, bank_id, filters, limit, order) -> list:
    where = ["w.user_id = ?", "w.mastered = 0"]
    params: list = [user_id]
    if bank_id:
        where.append("q.bank_id = ?")
        params.append(bank_id)
    cond, cond_params = _filter_clause(filters)
    where.extend(cond)
    params.extend(cond_params)
    clause = "WHERE " + " AND ".join(where)
    if order == "sequential":
        # 顺序刷错题：最早做错的先复习
        tail = "ORDER BY w.last_wrong_at ASC, q.created_at ASC, q.rowid ASC"
    else:
        tail = "ORDER BY RANDOM()"
    return conn.execute(
        f"""SELECT q.* FROM wrong_questions w
           JOIN questions q ON q.id = w.question_id
           {clause} {tail} LIMIT ?""",
        params + [limit],
    ).fetchall()
