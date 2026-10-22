"""共享资源管理权限：共享资源任何登录用户可维护；私有资源仅 owner 或管理员。

对应 CONTRACT.md §6：题库 / 提取脚本 / 考试模板默认共享（is_shared = true），可标私有。
"""

from __future__ import annotations


def can_manage(owner_id: str | None, is_shared: bool, user: dict) -> bool:
    if user["isAdmin"]:
        return True
    if is_shared:
        return True
    return owner_id == user["id"]
