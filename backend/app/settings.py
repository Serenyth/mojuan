import sqlite3

from app.prompts import DEFAULT_AGENT_SYSTEM_PROMPT

SETTING_DEFAULTS: dict[str, str] = {
    "ai_base_url": "",
    "ai_api_key": "",
    "ai_model": "",
    "ai_vision_model": "",
    "multiple_partial_credit": "false",
    "multiple_partial_ratio": "0.5",
    "fill_ignore_case": "false",
    "subjective_max_score": "10",
    "subjective_pass_ratio": "0.6",
    "master_streak": "2",
    # 导入助手（AI 对话）的系统提示词：空值 = 用内置默认（DEFAULT_AGENT_SYSTEM_PROMPT）
    "agent_system_prompt": "",
}

# 同步给前端做「是否等于默认」判断与恢复默认用
AGENT_SYSTEM_PROMPT_DEFAULT = DEFAULT_AGENT_SYSTEM_PROMPT

SECRET_KEYS = {"ai_api_key"}
MASK = "********"


def get_settings(conn: sqlite3.Connection) -> dict[str, str]:
    merged = dict(SETTING_DEFAULTS)
    for row in conn.execute("SELECT key, value FROM settings"):
        merged[row["key"]] = row["value"]
    return merged


def get_public_settings(conn: sqlite3.Connection) -> dict[str, str]:
    current = get_settings(conn)
    masked = {
        key: (MASK if key in SECRET_KEYS and value else value)
        for key, value in current.items()
    }
    masked["ai_api_key_configured"] = "true" if current.get("ai_api_key") else "false"
    return masked


def get_setting(conn: sqlite3.Connection, key: str) -> str:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else SETTING_DEFAULTS.get(key, "")


def get_effective_agent_prompt(conn: sqlite3.Connection) -> str:
    """导入助手实际用的系统提示词：存了自定义就用自定义，否则内置默认。"""
    custom = get_setting(conn, "agent_system_prompt")
    return custom if custom else DEFAULT_AGENT_SYSTEM_PROMPT


def set_settings(conn: sqlite3.Connection, patch: dict[str, str]) -> None:
    for key, value in patch.items():
        if key not in SETTING_DEFAULTS:
            continue
        # 系统提示词：等于内置默认或清空都视作「恢复默认」，直接删掉覆盖值
        if key == "agent_system_prompt":
            if value == DEFAULT_AGENT_SYSTEM_PROMPT or value == "":
                conn.execute("DELETE FROM settings WHERE key = ?", (key,))
            else:
                conn.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, value),
                )
            continue
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
    conn.commit()


def get_judge_config(conn: sqlite3.Connection) -> dict:
    return {
        "multiplePartialCredit": get_setting(conn, "multiple_partial_credit") == "true",
        "multiplePartialRatio": _to_float(get_setting(conn, "multiple_partial_ratio"), 0.5),
        "fillIgnoreCase": get_setting(conn, "fill_ignore_case") == "true",
        "subjectiveMaxScore": _to_float(get_setting(conn, "subjective_max_score"), 10.0),
        "subjectivePassRatio": _to_float(get_setting(conn, "subjective_pass_ratio"), 0.6),
        "masterStreak": int(_to_float(get_setting(conn, "master_streak"), 2)),
    }


def _to_float(value: str, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback
