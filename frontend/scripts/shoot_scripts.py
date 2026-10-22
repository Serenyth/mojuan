"""目检：脚本页 + 编辑器 + 设置页的提示词面板。

前置：uvicorn 在 127.0.0.1:8000 跑着，前端已 build（dist 为最新）。
"""

from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8000"
ROOT = Path(__file__).resolve().parents[2]
SHOTS = ROOT / ".workbuddy" / "shots"
SHOTS.mkdir(parents=True, exist_ok=True)

failures = []


def check(name, cond, extra=""):
    print(("[PASS] " if cond else "[FAIL] ") + name + ("" if cond else f"  {extra}"))
    if not cond:
        failures.append(name)


def login(page):
    page.goto(f"{BASE}/login", wait_until="networkidle")
    page.fill('input[autocomplete="username"]', "admin")
    page.fill('input[autocomplete="current-password"]', "mojuan-dev")
    page.click('button[type="submit"]')
    page.wait_for_selector('nav[aria-label="主导航"]', timeout=15000)


with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge", headless=True)
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    login(page)

    # —— 脚本页 ——
    page.goto(f"{BASE}/scripts", wait_until="networkidle")
    page.get_by_role("button", name="新建脚本").first.wait_for(timeout=10000)
    check("脚本页渲染", page.get_by_text("同源页面反复用的提取脚本").count() >= 1)
    check("脚本列表有共享数据", page.get_by_text("冒烟提取脚本").count() >= 1, page.content()[:200])
    page.screenshot(path=str(SHOTS / "v5-scripts-light.png"), full_page=True)

    # —— 编辑器 ——
    page.get_by_role("button", name="新建脚本").first.click()
    page.get_by_text("脚本代码").first.wait_for(timeout=10000)
    check("编辑器打开", page.get_by_text("脚本代码").count() >= 1)
    check("有 AI 生成入口", page.get_by_role("button", name="AI 生成").count() >= 1)
    page.screenshot(path=str(SHOTS / "v5-scripts-editor-light.png"), full_page=True)

    # —— 设置页提示词面板 ——
    page.goto(f"{BASE}/settings", wait_until="networkidle")
    page.get_by_text("导入助手提示词").first.wait_for(timeout=10000)
    check("设置页有提示词面板", page.get_by_text("导入助手提示词").count() >= 1)
    check("有恢复默认按钮", page.get_by_role("button", name="恢复默认").count() >= 1)
    page.get_by_text("导入助手提示词").first.scroll_into_view_if_needed()
    page.screenshot(path=str(SHOTS / "v5-settings-prompt-light.png"), full_page=True)

    # —— 保存自定义提示词 → 恢复默认（验证 PUT 回包带三字段，保存后不丢） ——
    textarea = page.locator("textarea").first
    textarea.scroll_into_view_if_needed()
    textarea.fill("UI 目检自定义提示词：只抽单选题")
    page.get_by_role("button", name="保存", exact=True).click()
    page.get_by_text("已保存", exact=True).first.wait_for(timeout=10000)
    check("保存后提示词保留", textarea.input_value().startswith("UI 目检自定义提示词"), textarea.input_value())
    check("保存后标记已自定义", page.get_by_text("已自定义").count() >= 1)

    page.get_by_role("button", name="恢复默认", exact=True).click()
    page.get_by_role("button", name="保存", exact=True).click()
    page.get_by_text("已保存", exact=True).first.wait_for(timeout=10000)
    check("恢复默认后标记内置", page.get_by_text("内置默认").count() >= 1)

    browser.close()

if failures:
    print("FAILED:", failures)
    raise SystemExit(1)
print("SCREENSHOTS OK")
