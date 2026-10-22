"""agent 思维链目检：登录 → 导入页 → 发一句话 → 看步骤思考与回复思考（日/夜）。

前置：uvicorn 在跑、前端已 build。
假响应在本地拦掉 /api/extract/chat，不消耗真实 AI，只验前端呈现。
用法：python scripts/shoot_agent_thought.py
"""

import json
import re
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


FAKE_STEPS = [
    {"tool": "list_sources", "ok": True, "note": "查看材料清单：1 份材料",
     "thought": "先看看左侧有什么材料，别重复抓"},
    {"tool": "fetch_url", "ok": True, "note": "抓取链接 127.0.0.1：820 字 · 3 张图",
     "thought": "消息里的链接不在左侧，我自己抓一份"},
    {"tool": "run_python", "ok": True, "note": "运行 Python（1.2s，退出码 0）",
     "thought": "正文里有表格噪声，写十行代码清洗成纯题干"},
    {"tool": "extract_questions", "ok": True, "note": "提取到 2 题（1 存疑）",
     "thought": "题干干净了，按用户只要单选题的要求抽题"},
]


def shoot(page, theme_label):
    page.goto(f"{BASE}/import", wait_until="networkidle")

    EXTRACT_EVENTS = (
        [{"type": "conversation", "id": "conv-1"}]
        + [
            {"type": "step", "tool": s["tool"], "ok": s["ok"], "note": s["note"],
             "thought": s["thought"], "ms": 120 + idx * 60}
            for idx, s in enumerate(FAKE_STEPS)
        ]
        + [
            {"type": "reply", "reply": "我先看了材料清单，把消息里的链接也抓了下来，跑代码洗掉表格噪声后抽了 2 题，候选题在右栏。",
             "thought": "用户只要单选题；链接不在左侧材料里，需要自己抓；抓完先清洗再抽题。",
             "action": {"type": "extract_direct", "sourceIds": [], "jobId": "job-thought", "instruction": "只要单选题"},
             "ms_total": 1820},
        ]
    )
    CONFIRM_EVENTS = [
        {"type": "conversation", "id": "conv-c"},
        {"type": "reply", "reply": "这个站点结构和普通网页不一样，我打算先写一个可复用抓取工具来解析。要我先建这个工具吗？",
         "thought": "直接抓拿不到题，得写脚本",
         "action": {"type": "confirm", "reason": "需要新增可复用工具", "plan": "用 create_tool 写一个解析脚本"},
         "ms_total": 900},
    ]

    def fulfill_stream(route, request):
        try:
            payload = json.loads(request.post_data or "{}")
        except Exception:
            payload = {}
        msg = (payload.get("message") or "")
        events = CONFIRM_EVENTS if ("工具" in msg or "新" in msg or "确认" in msg) else EXTRACT_EVENTS
        sse = "".join(f"data: {json.dumps(e, ensure_ascii=False)}\n\n" for e in events)
        route.fulfill(status=200, content_type="text/event-stream", body=sse)

    def fulfill_job(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "job": {"id": "job-thought", "sourceIds": [], "mode": "direct", "status": "review",
                        "scriptId": None,
                        "stats": {"extracted": 2, "suspect": 1, "images": 3, "skipped": []},
                        "createdAt": "2026-10-18T20:00:00Z"},
                "questions": [
                    {"id": "q-1", "type": "single_choice", "content": "中国的首都是哪里？",
                     "options": {"A": "上海", "B": "北京", "C": "广州", "D": "深圳"},
                     "answer": "B", "explanation": "北京是中华人民共和国首都。",
                     "tags": ["地理"], "difficulty": 1, "confidence": 0.98,
                     "suspect": False, "duplicate": False, "issues": []},
                    {"id": "q-2", "type": "multiple_choice", "content": "下列属于直辖市的有？",
                     "options": {"A": "北京", "B": "上海", "C": "广州", "D": "天津"},
                     "answer": ["A", "B", "D"], "explanation": "广州是省会，不是直辖市。",
                     "tags": ["地理"], "difficulty": 2, "confidence": 0.52,
                     "suspect": True, "duplicate": False, "issues": ["多选题答案置信度偏低"]},
                ],
            }),
        )

    page.route("**/api/extract/chat/stream", fulfill_stream)
    page.route("**/api/extract/jobs/*", fulfill_job)

    composer = page.get_by_placeholder(re.compile("发链接，或说怎么拆"))
    composer.fill("把 https://127.0.0.1:8200/demo 里的题抽成单选题")
    page.get_by_role("button", name="发送", exact=True).click()

    page.wait_for_selector("text=写十行代码清洗成纯题干", timeout=15000)
    check(f"思维链·{theme_label}：步骤思考可见", True)
    page.wait_for_selector("text=链接不在左侧，我自己抓一份", timeout=10000)
    page.wait_for_selector("text=用户只要单选题", timeout=10000)
    page.wait_for_selector("text=我先看了材料清单", timeout=10000)
    check(f"思维链·{theme_label}：回复思考可见", True)
    # 每步耗时与整轮总耗时都该显示
    check(f"思维链·{theme_label}：单步耗时可见", page.locator("text=/\\d+(\\.\\d+)?s/").count() > 0)
    check(f"思维链·{theme_label}：整轮耗时可见", page.locator("text=本轮").count() > 0)

    # 等右栏候选题落位，过程与结果同框
    page.wait_for_selector("text=中国的首都是哪里", timeout=15000)
    page.wait_for_timeout(600)
    page.screenshot(path=f"{SHOTS}/v4-agent-thought-{theme_label}.png", full_page=False)

    # 窄屏也看一眼：思考行不撑破对话面板
    page.set_viewport_size({"width": 480, "height": 900})
    page.wait_for_timeout(400)
    overflow = page.evaluate(
        "() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]"
    )
    check(f"思维链·{theme_label}：窄屏无横向溢出", overflow[0] <= overflow[1] + 1,
          f"{overflow[0]} > {overflow[1]}")
    page.screenshot(path=f"{SHOTS}/v4-agent-thought-{theme_label}-mobile.png", full_page=False)
    page.set_viewport_size({"width": 1600, "height": 950})

    # confirm 暂停：发一句触发确认的话，验证不自动提取、提示等待确认
    composer.fill("要不要新工具来解析这个站点？")
    page.get_by_role("button", name="发送", exact=True).click()
    page.wait_for_selector("text=已暂停", timeout=15000)
    check(f"确认暂停·{theme_label}：提示等待确认", True)
    page.wait_for_selector("text=我打算先写一个可复用抓取工具来解析", timeout=10000)
    check(f"确认暂停·{theme_label}：说明文案可见", True)
    page.wait_for_timeout(400)
    page.screenshot(path=f"{SHOTS}/v4-agent-confirm-{theme_label}.png", full_page=False)


def clear_conversations(page):
    """每轮开始前删掉库里的会话，避免上一轮落库的 ⏸ 被「恢复最近会话」带回顶部。"""
    try:
        data = page.request.get(f"{BASE}/api/conversations").json()
        for conv in data.get("conversations", []):
            page.request.delete(f"{BASE}/api/conversations/{conv['id']}")
    except Exception:
        pass


with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge", args=["--disable-gpu", "--no-sandbox"])
    context = browser.new_context(viewport={"width": 1600, "height": 950})
    page = context.new_page()

    page.goto(f"{BASE}/login", wait_until="networkidle")
    page.fill('input[autocomplete="username"]', "admin")
    page.fill('input[autocomplete="current-password"]', "mojuan-dev")
    page.click('button[type="submit"]')
    page.wait_for_selector('nav[aria-label="主导航"]', timeout=10000)

    clear_conversations(page)
    shoot(page, "light")

    # 切夜间再走一遍：清会话 + 刷新，避免恢复上一轮
    page.click('button[title="切换到夜间"]')
    theme = page.evaluate("() => document.documentElement.dataset.theme")
    check("点击后落到夜间", theme == "dark", theme or "")
    clear_conversations(page)
    page.reload(wait_until="networkidle")
    clear_conversations(page)
    shoot(page, "dark")

    browser.close()

print(f"\n失败 {len(failures)} 项" + ("：" + "；".join(failures) if failures else ""))
sys.exit(1 if failures else 0)
