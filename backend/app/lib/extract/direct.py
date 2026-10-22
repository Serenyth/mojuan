"""模式 A：AI 直接提取。

喂进去的是归一化后的 Markdown（或图片字节），要回来的是统一题目 Schema。
解析与纠偏都收在这里，脚本模式（模式 B）跑完同样要走一遍 parse_questions。
"""

import hashlib
import json
import re
from pathlib import Path

from app.db import DATA_DIR
from app.lib.ai import AiClient, AiError
from app.lib.ai.client import extract_json

QUESTION_TYPES = ("single_choice", "multiple_choice", "true_false", "fill_blank", "subjective")
CHOICE_TYPES = ("single_choice", "multiple_choice", "true_false")

SUSPECT_CONFIDENCE = 0.6
PER_SOURCE_CHARS = 60_000
TOTAL_CHARS = 150_000

SYSTEM_PROMPT = """你是题库提取助手。从用户给的材料中抽取全部题目，严格按下面要求输出。

只输出一个 JSON 数组，不要任何解释文字、不要 Markdown 代码围栏。
材料里没有题目时输出 []。

数组每个元素是一道题，字段如下：
- type: "single_choice" | "multiple_choice" | "true_false" | "fill_blank" | "subjective"
- content: 题干原文，保留专业术语，去掉行首的题号（如 "1." "（3）"）
- options: 选项数组 [{"key":"A","text":"..."}, ...]；判断题、填空题、主观题传 null
- answer: 选择题填选项 key 的数组（单选一个元素，如 ["A"]；多选如 ["A","C"]）；
  判断题填 ["T"] 或 ["F"]；填空与主观题填字符串数组
- acceptableAnswers: 填空题的等价答案，形如 [["勾股定理", "毕达哥拉斯定理"]]；没有就 null
- explanation: 答案解析，材料里没有就 null
- tags: 主题标签数组，如 ["代数", "初二"]，没有就 []
- difficulty: 1 到 5 的整数，5 最难
- confidence: 0 到 1 的小数，你对这道题提取准确性的自评；题干或答案看不全就往低给

注意：
- 题干与选项必须原样保留，不要改写、不要补充材料里没有的信息
- 答案必须是材料里明确给出或可直接推出的，推不出来就给 confidence 低一点
- 一道题里出现多个小问，拆成多道题"""


def fingerprint(content: str) -> str:
    """题目指纹：用于查重。忽略空白与大小写差异。"""
    normalized = re.sub(r"\s+", "", content or "").lower()
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def _as_str(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (int, float, bool)):
        return str(value)
    return str(value).strip()


def _as_str_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [_as_str(item) for item in value if _as_str(item)]
    return [_as_str(value)]


def parse_questions(payload) -> list[dict]:
    """把模型返回的 JSON 收敛成统一 Schema，并标记存疑。

    模型会给出各种形状：字段缺失、类型写错、选项是字符串不是对象、
    答案是单个字符串不是数组……这里全部兜住，不让脏数据进库。
    """
    if isinstance(payload, dict):
        for key in ("questions", "items", "data", "list"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
    if not isinstance(payload, list):
        if isinstance(payload, dict):
            keys = "、".join(str(key) for key in list(payload.keys())[:10]) or "（无字段）"
            got = f"对象（字段：{keys}）"
        else:
            got = type(payload).__name__
        preview = (
            json.dumps(payload, ensure_ascii=False)[:300]
            if not isinstance(payload, str)
            else payload[:300]
        )
        raise AiError(
            "返回的题目结构无法识别：顶层应是 JSON 数组，或 {\"questions\": [...]}；"
            f"实际是{got}。收到内容：{preview}"
        )

    questions: list[dict] = []
    for index, raw in enumerate(payload):
        if not isinstance(raw, dict):
            continue

        content = _as_str(raw.get("content"))
        if not content:
            continue

        q_type = _as_str(raw.get("type"))
        if q_type not in QUESTION_TYPES:
            q_type = "subjective"

        options = None
        if q_type in CHOICE_TYPES:
            raw_options = raw.get("options")
            options = []
            if isinstance(raw_options, list):
                for offset, option in enumerate(raw_options):
                    if isinstance(option, dict):
                        key = _as_str(option.get("key")) or chr(ord("A") + offset)
                        text = _as_str(option.get("text"))
                    else:
                        key = chr(ord("A") + offset)
                        text = _as_str(option)
                    if text:
                        options.append({"key": key[:8], "text": text})
            if q_type != "true_false" and len(options) < 2:
                options = None

        answer = _as_str_list(raw.get("answer"))
        if q_type in ("fill_blank", "subjective") and not answer:
            answer = [""]

        acceptable = None
        if q_type == "fill_blank":
            raw_acceptable = raw.get("acceptableAnswers")
            if isinstance(raw_acceptable, list):
                acceptable = [
                    group for group in (_as_str_list(item) for item in raw_acceptable) if group
                ] or None

        try:
            confidence = float(raw.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        confidence = max(0.0, min(1.0, confidence))

        try:
            difficulty = int(raw.get("difficulty", 3))
        except (TypeError, ValueError):
            difficulty = 3
        difficulty = max(1, min(5, difficulty))

        tags = [tag[:24] for tag in _as_str_list(raw.get("tags"))][:8]
        explanation = _as_str(raw.get("explanation")) or None

        question = {
            "type": q_type,
            "content": content,
            "options": options,
            "answer": answer,
            "acceptableAnswers": acceptable,
            "explanation": explanation,
            "tags": tags,
            "difficulty": difficulty,
            "confidence": round(confidence, 2),
            "fingerprint": fingerprint(content),
            "suspect": confidence < SUSPECT_CONFIDENCE,
        }
        question["issues"] = _issues(question)
        questions.append(question)

    return questions


def _issues(question: dict) -> list[str]:
    """结构性问题。confidence 低只标 suspect，这里只放确定不对的。"""
    issues: list[str] = []
    if question["type"] in CHOICE_TYPES and not question["options"]:
        issues.append("缺少选项")
    if question["type"] in ("fill_blank", "subjective") and not any(question["answer"]):
        issues.append("缺少答案")
    if question["type"] in ("single_choice", "true_false") and len(question["answer"]) > 1:
        issues.append("答案数量与题型不符")
    if question["type"] == "multiple_choice" and len(question["answer"]) < 2:
        issues.append("多选却只有一个答案")
    return issues


def build_user_prompt(materials: list[tuple[str, str]], instruction: str) -> str:
    blocks = []
    for name, markdown in materials:
        blocks.append(f"===== 材料：{name} =====\n{markdown}")
    body = "\n\n".join(blocks)

    prompt = "下面是待提取的题目材料：\n\n" + body
    if instruction and instruction.strip():
        prompt += "\n\n===== 用户补充要求 =====\n" + instruction.strip()
    return prompt


def _read_markdown(row) -> str:
    if not row["normalized_path"]:
        return ""
    path = DATA_DIR / row["normalized_path"]
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _read_raw(row) -> bytes | None:
    if not row["storage_path"]:
        return None
    path = DATA_DIR / row["storage_path"]
    return path.read_bytes() if path.is_file() else None


def _row_meta(row) -> dict:
    """sqlite3.Row 与普通 dict 都要能取到 meta。"""
    try:
        raw = row["meta"]
    except (IndexError, KeyError):
        return {}
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}


def _read_image_files(row) -> list[tuple[bytes, str]]:
    """读 meta.images 里落盘的网页图片（url / document / text 行）。"""
    images: list[tuple[bytes, str]] = []
    for relative in _row_meta(row).get("images") or []:
        path = DATA_DIR / relative
        if not path.is_file():
            continue
        ext = Path(relative).suffix.lower()
        images.append((path.read_bytes(), MIME_BY_EXT.get(ext, "image/png")))
    return images


MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}


def run_direct(
    client: AiClient,
    source_rows: list,
    instruction: str = "",
    existing_fingerprints: set[str] | None = None,
) -> dict:
    """跑一次模式 A。返回 {questions, stats}，不落 questions 表。"""
    if not source_rows:
        raise AiError("没有可提取的材料")

    images: list[tuple[bytes, str]] = []
    texts: list[tuple[str, str]] = []
    skipped: list[str] = []

    for row in source_rows:
        if row["type"] == "image":
            raw = _read_raw(row)
            if not raw:
                skipped.append(f"{row['name']}（原图缺失）")
                continue
            ext = Path(row["name"]).suffix.lower()
            images.append((raw, MIME_BY_EXT.get(ext, "image/png")))
            continue

        markdown = _read_markdown(row)
        # 网页里下载的题目图片：和上传的图片走同一个视觉通道
        page_images = _read_image_files(row)
        images.extend(page_images)
        if not markdown.strip():
            if page_images:
                continue  # 纯图片网页：没文字，图已经进视觉通道
            skipped.append(f"{row['name']}（无文字内容）")
            continue
        texts.append((row["name"], markdown[:PER_SOURCE_CHARS]))

    if not images and not texts:
        raise AiError("所有材料都没有可用内容：" + "、".join(skipped))

    budget = TOTAL_CHARS - sum(len(text) for _, text in texts)
    trimmed: list[tuple[str, str]] = []
    for name, markdown in texts:
        if budget <= 0:
            skipped.append(f"{name}（超出长度上限已跳过）")
            continue
        trimmed.append((name, markdown[:budget]))
        budget -= len(markdown)

    if images:
        # 图片走多模态直读：文字材料作为上下文一并给模型
        context = "\n\n".join(f"===== 材料：{name} =====\n{text}" for name, text in trimmed)
        vision_prompt = (
            "请读取这些图片里的题目，按系统提示的 JSON 格式输出。"
            + (f"\n\n另外还有这些文字材料可作参考：\n{context}" if context else "")
            + (f"\n\n用户补充要求：{instruction.strip()}" if instruction.strip() else "")
        )
        reply = client.chat_vision(vision_prompt, images, system=SYSTEM_PROMPT)
        payload = extract_json(reply)
    else:
        payload = client.chat_json(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(trimmed, instruction)},
            ]
        )

    questions = parse_questions(payload)

    if existing_fingerprints:
        for question in questions:
            question["duplicate"] = question["fingerprint"] in existing_fingerprints

    return {
        "questions": questions,
        "stats": {
            "extracted": len(questions),
            "suspect": sum(1 for q in questions if q["suspect"] or q["issues"]),
            "images": len(images),
            "skipped": skipped,
        },
    }


def stats_json(stats: dict) -> str:
    return json.dumps(stats, ensure_ascii=False)
