"""考试页目检：试卷列表（模板已并入考试页）→ 新建试卷弹窗 → 开考题流。

前置：uvicorn 在跑、前端已 build。
用法：python scripts/shoot_exam.py
"""

import sys

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8000"
SHOTS = "C:/Users/19771/WorkBuddy/2026-10-16-22-36-57/.workbuddy/shots"

PAPERS = [
    {"name": "期中模拟卷", "durationMinutes": 45},
    {"name": "期末冲刺卷", "durationMinutes": 90},
]

failures = []


def check(name, condition, extra=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f"  {extra}" if extra and not condition else ""))
    if not condition:
        failures.append(name)


with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge", args=["--disable-gpu", "--no-sandbox"])
    context = browser.new_context(viewport={"width": 1600, "height": 950})
    page = context.new_page()

    page.goto(f"{BASE}/login", wait_until="networkidle")
    page.fill('input[autocomplete="username"]', "admin")
    page.fill('input[autocomplete="current-password"]', "mojuan-dev")
    page.click('button[type="submit"]')
    page.wait_for_selector('nav[aria-label="主导航"]', timeout=10000)

    # 造两份试卷（模板即试卷，每种题型各 1 题）
    paper_ids = []
    for spec in PAPERS:
        created = page.request.post(
            f"{BASE}/api/exam-templates",
            data={
                "name": spec["name"],
                "typeDistribution": {"single_choice": 1, "multiple_choice": 1, "true_false": 1,
                                     "fill_blank": 1, "subjective": 1},
                "totalCount": 5,
                "durationMinutes": spec["durationMinutes"],
                "isShared": True,
            },
        )
        if created.ok:
            paper_ids.append(created.json()["template"]["id"])
    check("造两份试卷", len(paper_ids) == len(PAPERS))

    page.goto(f"{BASE}/exam", wait_until="networkidle")
    page.wait_for_selector(f"text={PAPERS[0]['name']}", timeout=8000)
    page.wait_for_timeout(500)
    page.screenshot(path=f"{SHOTS}/exam-paper-list.png", full_page=True)

    # 新建试卷弹窗
    page.get_by_role("button", name="新建试卷").click()
    page.wait_for_selector("text=题型分布", timeout=5000)
    page.wait_for_timeout(400)
    page.screenshot(path=f"{SHOTS}/exam-paper-editor.png", full_page=False)
    page.get_by_role("button", name="关闭").click()
    page.wait_for_timeout(300)

    # 开考：题流 + 侧栏 + 倒计时
    page.get_by_role("button", name="开考").first.click()
    page.wait_for_selector("text=剩余时间", timeout=15000)
    page.wait_for_timeout(800)
    page.screenshot(path=f"{SHOTS}/exam-taking.png", full_page=False)
    check("开考后题流渲染", page.locator("article").count() >= 5, str(page.locator("article").count()))

    # 收尾：清理进行态与造出来的试卷
    page.evaluate("localStorage.removeItem('mojuan_active_exam')")
    for paper_id in paper_ids:
        page.request.delete(f"{BASE}/api/exam-templates/{paper_id}")

    browser.close()

print(f"\n失败 {len(failures)} 项" + ("：" + "；".join(failures) if failures else ""))
sys.exit(1 if failures else 0)
