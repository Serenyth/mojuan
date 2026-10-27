"""判分引擎。规则以 CONTRACT.md §5 为唯一事实来源：

- 单选 / 判断：严格等于答案 key
- 多选：默认漏选即错（0 分）；multiple_partial_credit 开启后，漏选（无错选）按
  multiple_partial_ratio 给分（默认 50%）；错选恒 0
- 填空：逐空比对；每空取可接受答案集合；默认忽略首尾空白；fill_ignore_case 控制大小写
- 主观题：不自动判分，correct 为 None，max_score 取 subjective_max_score，等待人工阅卷

配置统一由调用方经 app.settings.get_judge_config(conn) 获取后传入，本模块不直接读库。
客观题统一按 1 分计（OBJECTIVE_MAX_SCORE），多选部分分按比例落在 0~1。
"""

from __future__ import annotations

from dataclasses import dataclass

OBJECTIVE_MAX_SCORE = 1.0


@dataclass
class JudgeOutcome:
    """判分结果。主观题阅卷前 correct/score 均为 None。"""

    correct: bool | None
    score: float | None
    max_score: float | None
    detail: str


def judge_answer(question: dict, user_answer, config: dict) -> JudgeOutcome:
    """question 为 serialize 模块产出的题目 dict（含 type / answer / acceptableAnswers）。"""
    q_type = question.get("type")
    if q_type in ("single_choice", "true_false"):
        return _judge_exact(question, user_answer)
    if q_type == "multiple_choice":
        return _judge_multiple(question, user_answer, config)
    if q_type == "fill_blank":
        return _judge_fill(question, user_answer, config)
    if q_type == "subjective":
        return JudgeOutcome(
            None,
            None,
            config["subjectiveMaxScore"],
            "主观题，待人工阅卷",
        )
    return JudgeOutcome(None, None, None, f"未知题型：{q_type}")


def _as_key_list(value) -> list[str]:
    """把用户答案规整为 key 列表（前端可能传字符串或数组）。"""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value]


def _judge_exact(question: dict, user_answer) -> JudgeOutcome:
    answer = _as_key_list(question.get("answer"))
    user = _as_key_list(user_answer)
    if not user:
        return JudgeOutcome(False, 0.0, OBJECTIVE_MAX_SCORE, "未作答")
    expected = answer[0] if answer else None
    correct = len(user) == 1 and user[0] == expected
    return JudgeOutcome(
        correct,
        1.0 if correct else 0.0,
        OBJECTIVE_MAX_SCORE,
        "回答正确" if correct else "与答案不一致",
    )


def _judge_multiple(question: dict, user_answer, config: dict) -> JudgeOutcome:
    answer = set(_as_key_list(question.get("answer")))
    user = set(_as_key_list(user_answer))
    if not user:
        return JudgeOutcome(False, 0.0, OBJECTIVE_MAX_SCORE, "未作答")
    if user - answer:
        return JudgeOutcome(False, 0.0, OBJECTIVE_MAX_SCORE, "包含错选，恒为 0 分")
    if user == answer:
        return JudgeOutcome(True, 1.0, OBJECTIVE_MAX_SCORE, "全部正确")
    if config["multiplePartialCredit"]:
        ratio = config["multiplePartialRatio"]
        return JudgeOutcome(
            False,
            ratio,
            OBJECTIVE_MAX_SCORE,
            f"漏选，按 {ratio:.0%} 给分",
        )
    return JudgeOutcome(False, 0.0, OBJECTIVE_MAX_SCORE, "漏选，默认不给分")


def _judge_fill(question: dict, user_answer, config: dict) -> JudgeOutcome:
    expected_sets = question.get("acceptableAnswers") or []
    if not expected_sets:
        answer = question.get("answer")
        if isinstance(answer, list):
            expected_sets = [[str(item)] for item in answer]
    if not expected_sets:
        return JudgeOutcome(False, 0.0, OBJECTIVE_MAX_SCORE, "题目缺少参考答案")

    user = _as_fill_list(user_answer, len(expected_sets))
    if not any(text.strip() for text in user):
        return JudgeOutcome(False, 0.0, OBJECTIVE_MAX_SCORE, "未作答")

    ignore_case = config["fillIgnoreCase"]
    results = [
        _blank_matches(expected, user[i] if i < len(user) else "", ignore_case)
        for i, expected in enumerate(expected_sets)
    ]
    correct = all(results)
    filled = sum(1 for r in results if r)
    return JudgeOutcome(
        correct,
        1.0 if correct else 0.0,
        OBJECTIVE_MAX_SCORE,
        "全部正确" if correct else f"{filled}/{len(results)} 空正确",
    )


def _as_fill_list(user_answer, blank_count: int) -> list[str]:
    if user_answer is None:
        return [""] * blank_count
    if isinstance(user_answer, str):
        return [user_answer]
    return [str(item) for item in user_answer]


def _blank_matches(expected_options, given: str, ignore_case: bool) -> bool:
    text = given.strip()
    for option in expected_options:
        candidate = str(option).strip()
        if ignore_case:
            if candidate.casefold() == text.casefold():
                return True
        elif candidate == text:
            return True
    return False
