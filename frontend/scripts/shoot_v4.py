"""v4 设计迁移的真实浏览器目检：登录 → 概览（日/夜）→ 题库 → 刷题，Edge 截图 + 溢出断言。

前置：uvicorn 已在 127.0.0.1:8000 跑着，且前端已重新 build。
用法：python scripts/shoot_v4.py
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


def no_overflow(page, label):
    size = page.evaluate(
        "() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]"
    )
    check(f"{label} 无横向溢出", size[0] <= size[1] + 1, f"{size[0]} > {size[1]}")


def login(page):
    page.goto(f"{BASE}/login", wait_until="networkidle")
    page.fill('input[autocomplete="username"]', "admin")
    page.fill('input[autocomplete="current-password"]', "mojuan-dev")
    page.click('button[type="submit"]')
    page.wait_for_selector('nav[aria-label="主导航"]', timeout=10000)


with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge", args=["--disable-gpu", "--no-sandbox"])
    context = browser.new_context(viewport={"width": 1600, "height": 950})
    page = context.new_page()

    login(page)
    page.wait_for_timeout(900)
    page.screenshot(path=f"{SHOTS}/v4-overview-light.png", full_page=True)
    no_overflow(page, "概览·日间")

    # 右上角日夜切换（浅色下显示月亮，title「切换到夜间」）
    page.click('button[title="切换到夜间"]')
    page.wait_for_timeout(500)
    theme = page.evaluate("() => document.documentElement.dataset.theme")
    check("点击后落到夜间", theme == "dark", theme or "")
    page.screenshot(path=f"{SHOTS}/v4-overview-dark.png", full_page=True)
    page.click('button[title="切换到日间"]')
    page.wait_for_timeout(400)

    # Dock 跳转：题库
    page.click('nav[aria-label="主导航"] a[title="全部题目"]')
    page.wait_for_selector("text=新建题库", timeout=8000)
    page.wait_for_timeout(600)
    page.screenshot(path=f"{SHOTS}/v4-bank-light.png", full_page=True)
    no_overflow(page, "题库·日间")

    # Dock 跳转：刷题（条件筛选）
    page.click('nav[aria-label="主导航"] a[title="开始练习"]')
    page.wait_for_selector("text=抽题条件", timeout=8000)
    page.wait_for_timeout(600)
    page.screenshot(path=f"{SHOTS}/v4-practice-light.png", full_page=True)
    no_overflow(page, "刷题·日间")

    # 窄屏：Dock 应收成图标排
    page.set_viewport_size({"width": 420, "height": 860})
    page.wait_for_timeout(500)
    page.screenshot(path=f"{SHOTS}/v4-practice-mobile.png", full_page=True)
    no_overflow(page, "刷题·窄屏")

    browser.close()

print(f"\n失败 {len(failures)} 项" + ("：" + "；".join(failures) if failures else ""))
sys.exit(1 if failures else 0)
