"""v4 答题链路目检：开一场刷题 → 选答案提交 → 看判分反馈 → 结算页。

前置：uvicorn 在跑、前端已 build、库里至少有题（seed.py 灌过）。
用法：python scripts/shoot_v4_flow.py
"""

import sys

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8000"
SHOTS = "C:/Users/19771/WorkBuddy/2026-10-16-22-36-57/.workbuddy/shots"

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

    page.click('nav[aria-label="主导航"] a[title="开始练习"]')
    page.wait_for_selector("text=抽题条件", timeout=8000)
    page.click("text=开始刷题")
    page.wait_for_selector("text=刷题中", timeout=15000)
    page.wait_for_timeout(800)
    page.screenshot(path=f"{SHOTS}/v4-session-light.png", full_page=False)

    # 找第一道单选/判断题：点选即判，不再按「提交答案」
    cards = page.locator("article")
    target = None
    for i in range(cards.count()):
        card = cards.nth(i)
        text = card.inner_text()
        if ("单选" in text or "判断" in text) and card.locator("button").count() > 0:
            target = card
            break
    check("找到可即点即判的题", target is not None)
    if target:
        target.locator("button").first.click()
        page.wait_for_timeout(900)

        # 判分反馈条：对（success）或错（danger）都应出现
        feedback = sum(
            page.locator(f"text={t}").count()
            for t in ("回答正确", "与答案不一致", "与答案不符", "回答错误", "待阅卷")
        )
        check("点选后出现判分反馈", feedback > 0)
        page.screenshot(path=f"{SHOTS}/v4-outcome-light.png", full_page=False)

    # 结算
    page.locator("button", has_text="查看结算").first.click()
    page.wait_for_selector("text=本轮结算", timeout=10000)
    page.wait_for_timeout(800)
    page.screenshot(path=f"{SHOTS}/v4-settlement-light.png", full_page=True)

    overflow = page.evaluate(
        "() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]"
    )
    check("结算页无横向溢出", overflow[0] <= overflow[1] + 1, f"{overflow[0]} > {overflow[1]}")

    browser.close()

print(f"\n失败 {len(failures)} 项" + ("：" + "；".join(failures) if failures else ""))
sys.exit(1 if failures else 0)
