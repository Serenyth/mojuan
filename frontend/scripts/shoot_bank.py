"""目检：题库管理页（吸顶筛选条 / 列表-网格切换 / 显示选项与答案高光 / 分页-滚动切换 / 弹窗居中）。

前置：uvicorn 在 127.0.0.1:8000 跑着，前端已 build（dist 为最新）。
"""

import re
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
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    login(page)

    # 每次目检从「列表 + 分页」起步，避免上一次留下的 localStorage 干扰断言
    page.goto(f"{BASE}/bank", wait_until="networkidle")
    page.evaluate("localStorage.setItem('mojuan:bank-layout','list')")
    page.evaluate("localStorage.setItem('mojuan:bank-pager','pages')")
    page.reload(wait_until="networkidle")
    page.get_by_text("题库管理").first.wait_for(timeout=10000)
    check("题库页渲染", page.get_by_role("heading", name="题库管理").count() >= 1)
    check("筛选项在（全部题型）", page.get_by_text("全部题型").count() >= 1)
    check("有选项开关", page.get_by_role("button", name="选项").count() >= 1)
    check("默认是分页模式", page.get_by_title("分页浏览").get_attribute("aria-pressed") == "true")

    matched = re.search(r"共\s*(\d+)\s*题", page.inner_text("body"))
    total = int(matched.group(1)) if matched else 0
    check("读到题库总题数", total > 20, f"total={total}")

    # 吸顶：滚动后筛选条仍在视口顶部
    page.mouse.wheel(0, 1200)
    page.wait_for_timeout(400)
    top = page.evaluate("document.querySelector('.sticky')?.getBoundingClientRect().top ?? -999")
    check("筛选条吸顶（滚动后仍在顶部）", abs(top - 60) <= 2, f"top={top}")
    page.evaluate("window.scrollTo(0,0)")
    page.wait_for_timeout(200)
    page.screenshot(path=str(SHOTS / "v6-bank-list.png"), full_page=False)

    # —— 弹窗应该贴在视口中间（页面滚到哪都居中）——
    page.mouse.wheel(0, 1200)
    page.wait_for_timeout(300)
    page.get_by_label("编辑题目").first.click()
    page.wait_for_timeout(400)
    box = page.evaluate(
        """() => {
          const dlg = document.querySelector('[role="dialog"], .fixed.inset-0');
          const panel = dlg.firstElementChild.getBoundingClientRect();
          const r = dlg.getBoundingClientRect();
          return { ox: r.left, oy: r.top, ow: r.width, oh: r.height,
                   topGap: panel.top, bottomGap: innerHeight - panel.bottom,
                   vw: innerWidth, vh: innerHeight };
        }"""
    )
    check(
        "浮层铺满视口",
        abs(box["ow"] - box["vw"]) <= 1 and abs(box["oh"] - box["vh"]) <= 1,
        str(box),
    )
    check(
        "弹窗上下留白接近（视口居中）",
        abs(box["topGap"] - box["bottomGap"]) <= 2,
        f"top={box['topGap']} bottom={box['bottomGap']}",
    )
    page.screenshot(path=str(SHOTS / "v6-bank-modal.png"), full_page=False)
    page.get_by_role("button", name="关闭").click()
    page.wait_for_timeout(300)
    page.evaluate("window.scrollTo(0,0)")

    # 打开「选项」→ 正确项应有 success 高光
    page.get_by_role("button", name="选项").click()
    page.get_by_role("button", name="答案").click()
    page.wait_for_timeout(300)
    highlighted = page.locator("li.bg-success\\/10").count()
    check("选项高光出现", highlighted >= 1, f"count={highlighted}")
    page.screenshot(path=str(SHOTS / "v6-bank-list-options.png"), full_page=False)

    # 切网格
    page.get_by_title("网格布局").click()
    page.wait_for_timeout(400)
    cols = page.evaluate(
        "getComputedStyle(document.querySelector('main div.grid') || document.body).gridTemplateColumns"
    )
    check("网格布局生效（多列）", len(str(cols).split()) >= 2, f"cols={cols}")
    check("布局偏好写入 localStorage", page.evaluate("localStorage.getItem('mojuan:bank-layout')") == "grid")
    page.screenshot(path=str(SHOTS / "v6-bank-grid.png"), full_page=False)

    # —— 无限滚动 ——
    page.get_by_title("滚到底自动加载").click()
    page.wait_for_timeout(600)
    first_batch = page.locator("article").count()
    check("切成滚动模式", page.get_by_title("滚到底自动加载").get_attribute("aria-pressed") == "true")
    check("首屏只加载一页", first_batch == 20, f"count={first_batch}")
    check("底部提示已加载数", "已加载" in page.inner_text("body"))

    for _ in range(8):
        if page.locator("article").count() >= total:
            break
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(600)
    loaded = page.locator("article").count()
    check("滚到底继续加载", loaded > first_batch, f"{first_batch} -> {loaded}")
    check("最终加载全部题目", loaded >= total, f"loaded={loaded} total={total}")
    check("到底后提示已全部加载", "已全部加载" in page.inner_text("body"))
    page.screenshot(path=str(SHOTS / "v6-bank-infinite.png"), full_page=False)

    # 刷新后仍是滚动模式
    page.reload(wait_until="networkidle")
    page.wait_for_timeout(600)
    check("刷新后保持滚动模式", page.evaluate("localStorage.getItem('mojuan:bank-pager')") == "infinite")

    # 滚到底 → 存一次（不改内容）→ 不该把列表缩回一页
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(700)
    before = page.locator("article").count()
    page.get_by_label("编辑题目").first.click()
    page.wait_for_timeout(400)
    page.get_by_role("button", name="保存", exact=True).click()
    page.wait_for_timeout(1500)
    check("保存后弹窗关闭", page.locator(".fixed.inset-0").count() == 0)
    after = page.locator("article").count()
    check("增删改后保留已加载页数", after >= before - 1, f"{before} -> {after}")

    # 切回分页
    page.get_by_title("分页浏览").click()
    page.wait_for_timeout(600)
    check("切回分页后只剩一页", page.locator("article").count() <= 20, f"count={page.locator('article').count()}")

    # —— 夜间（同一套令牌，选项高光在暗色下也要看得清） ——
    page.get_by_title("网格布局").click()
    page.get_by_role("button", name="选项").click()
    page.get_by_role("button", name="答案").click()
    page.get_by_label("切换到夜间").click()
    page.wait_for_timeout(400)
    check("切到夜间", page.evaluate("document.documentElement.dataset.theme") == "dark")
    page.screenshot(path=str(SHOTS / "v6-bank-grid-dark.png"), full_page=False)
    page.get_by_label("切换到日间").click()
    page.wait_for_timeout(300)
    check("切回日间", page.evaluate("document.documentElement.dataset.theme") == "light")

    browser.close()

if failures:
    print("FAILED:", failures)
    raise SystemExit(1)
print("SCREENSHOTS OK")
