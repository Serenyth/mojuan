"""给 README 生成界面截图（概览 / 导入 / 数据格式 / 题库 / 刷题 / 网格 / 考试 / 答卷）。

前置：后端跑在 127.0.0.1:8000 且前端已 build（dist 为最新）。

    python frontend/scripts/shoot_readme.py

想拍在另一份库上（比如临时演示库）就用环境变量指过去：

    MOJUAN_BASE=http://127.0.0.1:8010 MOJUAN_DB=demo.db python frontend/scripts/shoot_readme.py

产出：docs/screenshots/*.png，宽 1200、PNG 压缩。

为了截图里有内容，脚本会先用 API 造三条刷题记录和一场考试（分数按本地库里的标准答案凑），
拍完再删掉；导入页的材料与候选题走「原文」+「数据格式」两条真实入口铺出来。
"""

import json
import os
import sqlite3
import sys
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

BASE = os.environ.get("MOJUAN_BASE", "http://127.0.0.1:8000")
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "screenshots"
DB = ROOT / "data" / os.environ.get("MOJUAN_DB", "quiz.db")
OUT.mkdir(parents=True, exist_ok=True)
MAX_WIDTH = 1200

created = []
failures = []
seeded_practice: list[str] = []
seeded_exams: list[str] = []

# 导入页：贴进去的材料原文（走「原文」入口，进数据源列表）
DEMO_MARKDOWN = """计算机网络 · 期末复习

1. HTTP 协议默认使用的端口号是？
   A. 21   B. 80   C. 443   D. 8080

2. 下列属于传输层协议的有？
   A. TCP   B. UDP   C. IP   D. ICMP

3. DNS 的作用是把域名解析为 IP 地址。（判断）

4. TCP 建立连接需要______次握手。
"""

# 导入页：粘进「数据格式」弹窗的 JSON（模拟已经从外部 AI 拿回结构化结果）
DEMO_JSON = [
    {
        "type": "single_choice",
        "content": "HTTP 协议默认使用的端口号是？",
        "options": [{"key": "A", "text": "21"}, {"key": "B", "text": "80"},
                    {"key": "C", "text": "443"}, {"key": "D", "text": "8080"}],
        "answer": ["B"],
        "explanation": "HTTP 默认 80 端口；HTTPS 走 TLS，默认 443。",
        "tags": ["计算机网络"],
        "difficulty": 2,
        "confidence": 0.97,
    },
    {
        "type": "multiple_choice",
        "content": "下列属于传输层协议的有？",
        "options": [{"key": "A", "text": "TCP"}, {"key": "B", "text": "UDP"},
                    {"key": "C", "text": "IP"}, {"key": "D", "text": "ICMP"}],
        "answer": ["A", "B"],
        "explanation": "IP 与 ICMP 在网络层，TCP / UDP 属于传输层。",
        "tags": ["计算机网络"],
        "difficulty": 3,
        "confidence": 0.92,
    },
    {
        "type": "true_false",
        "content": "DNS 的作用是把域名解析为 IP 地址。",
        "options": None,
        "answer": ["T"],
        "explanation": "域名系统负责域名与 IP 之间的映射。",
        "tags": ["计算机网络"],
        "difficulty": 1,
        "confidence": 0.95,
    },
    {
        "type": "fill_blank",
        "content": "TCP 建立连接需要______次握手。",
        "options": None,
        "answer": ["三"],
        "acceptableAnswers": [["三", "3", "三次"]],
        "explanation": "三次握手，四次挥手。",
        "tags": ["计算机网络"],
        "difficulty": 2,
        "confidence": 0.88,
    },
]


def check(name, cond, extra=""):
    print(("[PASS] " if cond else "[FAIL] ") + name + ("" if cond else f"  {extra}"))
    if not cond:
        failures.append(name)


def shoot(page, name, full_page=False):
    """截图 + 缩放：README 里放原尺寸会太重，缩到 1200 宽仍清晰。"""
    path = OUT / f"{name}.png"
    page.screenshot(path=str(path), full_page=full_page)
    with Image.open(path) as image:
        if image.width > MAX_WIDTH:
            ratio = MAX_WIDTH / image.width
            image = image.resize((MAX_WIDTH, int(image.height * ratio)), Image.LANCZOS)
        image.save(path, optimize=True)
    created.append(path.name)
    print(f"       {path.name}  {path.stat().st_size // 1024} KB")


def answers_of(question_ids):
    """只读打开库文件拿标准答案——用于把演示数据答对，让截图里的分数像回事。"""
    if not question_ids:
        return {}
    placeholders = ",".join("?" * len(question_ids))
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            f"SELECT id, answer FROM questions WHERE id IN ({placeholders})", question_ids
        ).fetchall()
    finally:
        conn.close()
    return {qid: (json.loads(text) if text else None) for qid, text in rows}


def seed_practice(page, right_ratio=1.0):
    """造一条已结束的刷题记录：前段按标准答案答对，后段故意答错。"""
    created_session = page.request.post(
        f"{BASE}/api/practice/sessions", data={"limit": 8, "order": "shuffle", "scope": "all"}
    )
    if not created_session.ok:
        return None
    session_id = created_session.json()["session"]["id"]
    questions = page.request.get(f"{BASE}/api/practice/sessions/{session_id}/result").json()["questions"]
    keep = max(1, round(len(questions) * right_ratio))
    for index, question in enumerate(questions):
        answer = question.get("answer") if index < keep else ["__wrong__"]
        page.request.post(
            f"{BASE}/api/practice/sessions/{session_id}/answer",
            data={"questionId": question["id"], "answer": answer},
        )
    page.request.post(f"{BASE}/api/practice/sessions/{session_id}/finish")
    seeded_practice.append(session_id)
    return session_id


def seed_exam(page):
    """造一场已交卷的考试，答案按标准答案填，分数好看一点。"""
    templates = page.request.get(f"{BASE}/api/exam-templates").json()["templates"]
    for template in templates:
        started = page.request.post(f"{BASE}/api/exams/start", data={"templateId": template["id"]})
        if not started.ok:
            continue
        payload = started.json()
        exam_id = payload["exam"]["id"]
        key = answers_of([question["id"] for question in payload["questions"]])
        answers = [
            {"questionId": question["id"], "answer": key.get(question["id"])}
            for question in payload["questions"]
        ]
        page.request.post(f"{BASE}/api/exams/{exam_id}/submit", data={"answers": answers})
        seeded_exams.append(exam_id)
        return exam_id
    return None


with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge", headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 900})

    page.goto(f"{BASE}/login", wait_until="networkidle")
    page.fill('input[autocomplete="username"]', "admin")
    page.fill('input[autocomplete="current-password"]', "mojuan-dev")
    page.click('button[type="submit"]')
    page.wait_for_selector('nav[aria-label="主导航"]', timeout=15000)

    # 预热：三条刷题记录（答对率各不相同）+ 一场考试
    seed_practice(page, 1.0)
    seed_practice(page, 0.6)
    seed_practice(page, 0.3)
    seed_exam(page)

    # 1. 概览：视口拉到整页高，悬浮 Dock 才会落在页面底部而不是压住「记录」
    page.set_viewport_size({"width": 1440, "height": 1340})
    page.goto(f"{BASE}/", wait_until="networkidle")
    page.wait_for_timeout(1500)
    shoot(page, "overview")
    check("概览渲染出记录", "记录" in page.inner_text("body"))
    page.set_viewport_size({"width": 1440, "height": 900})

    # 2. 导入：先「原文」加一份材料，再用「数据格式」把候选题铺进右栏
    page.goto(f"{BASE}/import", wait_until="networkidle")
    page.wait_for_timeout(800)
    page.get_by_role("button", name="原文", exact=True).click()
    page.fill('textarea[placeholder="把题目原文贴在这里"]', DEMO_MARKDOWN)
    page.get_by_role("button", name="加入 · ", exact=False).first.click()
    page.wait_for_timeout(1200)

    page.get_by_role("button", name="数据格式").click()
    page.wait_for_timeout(600)
    dialog = page.locator('[role="dialog"]')
    dialog.locator("textarea").fill(json.dumps(DEMO_JSON, ensure_ascii=False, indent=2))
    dialog.get_by_role("button", name="解析并载入").click()
    page.wait_for_timeout(1500)
    shoot(page, "import-format")
    dialog.get_by_role("button", name="关闭").click()
    page.wait_for_timeout(700)
    shoot(page, "import")
    check(
        "导入页铺出材料与候选题",
        all(word in page.inner_text("body") for word in ("数据源", "AI 对话", "提取结果"))
        and "计算机网络 · 期末复习" in page.inner_text("body"),
    )

    # 3. 题库（换成示例题库，打开选项与答案，把答案高亮也拍进去）
    page.goto(f"{BASE}/bank", wait_until="networkidle")
    page.evaluate("localStorage.setItem('mojuan:bank-layout','list')")
    page.evaluate("localStorage.setItem('mojuan:bank-pager','pages')")
    page.reload(wait_until="networkidle")
    page.wait_for_timeout(800)
    banks = page.request.get(f"{BASE}/api/banks").json()["banks"]
    demo_bank = next((bank for bank in banks if bank["name"].startswith("计算机基础")), banks[0])
    page.locator("select").first.select_option(value=demo_bank["id"])
    page.wait_for_timeout(1200)
    for label in ("选项", "答案"):
        button = page.get_by_role("button", name=label, exact=True).first
        if button.count():
            button.click()
            page.wait_for_timeout(300)
    page.wait_for_timeout(600)
    shoot(page, "bank")
    check("题库有题目卡", page.locator("article").count() >= 3)

    # 4. 刷题（答一道，把判分反馈也拍进去；回到顶部让题面完整）
    page.goto(f"{BASE}/practice", wait_until="networkidle")
    page.evaluate("localStorage.setItem('mojuan:question-layout','list')")
    page.reload(wait_until="networkidle")
    page.get_by_role("button", name="开始刷题").click()
    page.wait_for_selector('nav[aria-label="题目跳转"]', timeout=15000)
    page.wait_for_timeout(800)
    first_option = page.locator("article button").first
    if first_option.count():
        first_option.click()
        page.wait_for_timeout(1200)
    page.evaluate("() => window.scrollTo(0, 0)")
    page.wait_for_timeout(400)
    shoot(page, "practice")
    check("刷题在答题中", "刷题中" in page.inner_text("body"))

    # 5. 刷题网格布局
    page.get_by_title("网格布局").click()
    page.wait_for_timeout(800)
    page.evaluate("() => window.scrollTo(0, 0)")
    page.wait_for_timeout(400)
    shoot(page, "practice-grid")
    check(
        "网格两列",
        page.evaluate(
            """() => {
                const box = document.querySelector('article')?.parentElement?.parentElement;
                if (!box) return false;
                const cols = getComputedStyle(box).gridTemplateColumns;
                return !!cols && cols.trim().split(/\\s+/).length === 2;
            }"""
        ),
    )
    page.get_by_title("列表布局").click()
    page.wait_for_timeout(400)
    practice_session = page.evaluate("() => window.localStorage.getItem('mojuan_last_practice_session')")

    # 6. 考试作答（吸顶状态条 + 侧栏交卷）
    page.goto(f"{BASE}/exam", wait_until="networkidle")
    page.wait_for_timeout(800)
    start = page.get_by_role("button", name="开考").first
    exam_id = None
    if start.count():
        start.click()
        page.wait_for_selector('nav[aria-label="题目跳转"]', timeout=20000)
        page.wait_for_timeout(900)
        page.evaluate("() => window.scrollTo(0, 0)")
        page.wait_for_timeout(400)
        shoot(page, "exam-taking")
        check("考试在作答中", page.get_by_role("button", name="交卷").count() >= 1)

        # 7. 交卷后的答卷与分数（用预热的考试记录，直接看历史答卷）
        if seeded_exams:
            page.goto(f"{BASE}/exam?exam={seeded_exams[0]}", wait_until="networkidle")
            page.wait_for_timeout(1200)
            shoot(page, "exam-result")
            check("考试结果有总分", "总分" in page.inner_text("body"))
        exam_id = page.evaluate("() => window.localStorage.getItem('mojuan_active_exam')")

    # 清掉本次为截图造的记录（演示库整份是临时的，这里只是让脚本对任何库都安全）
    cleanup = {
        "practice": seeded_practice + ([practice_session] if practice_session else []),
        "exams": seeded_exams + ([exam_id] if exam_id else []),
    }
    page.request.post(f"{BASE}/api/history/delete", data=cleanup)
    page.evaluate("() => window.localStorage.setItem('mojuan:question-layout','list')")
    browser.close()

print("\n生成：" + "、".join(created))
print("\n" + ("OK" if not failures else f"FAILED: {failures}"))
sys.exit(0 if not failures else 1)
