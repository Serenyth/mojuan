"""真实浏览器验证（Playwright + 系统 Edge）：导入卡片溢出 / agent 对话驱动提取（含发链接）/ 题库页 / 翻阅式刷题与结算。

前置：uvicorn 已在 127.0.0.1:8000 跑着，且前端已重新 build。
用法：python verify_ui.py
"""

import json
import re
import sys

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8000"
LONG_TOKEN = "https://example.com/" + "averylongunbreakablepathsegment" * 12

failures = []


def check(name, condition, extra=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f"  {extra}" if extra and not condition else ""))
    if not condition:
        failures.append(name)


def login(page):
    page.goto(f"{BASE}/login", wait_until="networkidle")
    page.fill('input[autocomplete="username"]', "admin")
    page.fill('input[autocomplete="current-password"]', "mojuan-dev")
    page.click('button[type="submit"]')
    # v4 外壳没有顶部导航栏，等底部 Dock 渲染出来即登录成功
    page.wait_for_selector('nav[aria-label="主导航"]', timeout=10000)


def fake_candidates():
    """候选题：题干/选项/解析/标签里各塞一条长不断行 token，专测溢出。"""
    return [
        {
            "type": "single_choice",
            "content": f"下列关于{LONG_TOKEN}的说法正确的是？",
            "options": [
                {"key": "A", "text": f"选项A{LONG_TOKEN}"},
                {"key": "B", "text": "短选项"},
                {"key": "C", "text": "另一个短选项"},
                {"key": "D", "text": "第四个短选项"},
            ],
            "answer": ["B"],
            "explanation": f"解析：{LONG_TOKEN} 这是一条不会断行的长解释。",
            "tags": [f"#{'tag' * 40}", "普通标签"],
            "difficulty": 3,
            "confidence": 0.91,
            "fingerprint": "fp-overflow-1",
            "suspect": False,
            "issues": [],
        },
        {
            "type": "fill_blank",
            "content": f"填空：{LONG_TOKEN} 的首都是____。",
            "options": None,
            "answer": ["北京"],
            "acceptableAnswers": [["北京", "Beijing"]],
            "explanation": None,
            "tags": [],
            "difficulty": 2,
            "confidence": 0.42,
            "fingerprint": "fp-overflow-2",
            "suspect": True,
            "issues": ["结构性问题：选项缺失"],
        },
    ]


def overflow_metrics(page):
    return page.evaluate(
        """() => {
            const panels = [...document.querySelectorAll('section')].map(s => {
                const h = s.querySelector('h2');
                return h ? { el: s, title: h.textContent } : null;
            }).filter(Boolean);
            const panel = panels.find(p => p.title.includes('提取结果'));
            const scroller = panel.el.querySelector('div.overflow-y-auto');
            const all = [...panel.el.querySelectorAll('li')];
            return {
                doc: [document.documentElement.scrollWidth, document.documentElement.clientWidth],
                docHeight: [document.documentElement.scrollHeight, window.innerHeight],
                scroller: [scroller.scrollWidth, scroller.clientWidth],
                // 卡片 = 带勾选框的 li（选项 li 没有），避免把选项也当成卡片
                cards: all.filter(li => li.querySelector('[role="checkbox"]')).map(li => [li.scrollWidth, li.clientWidth]),
                allLis: all.map(li => [li.scrollWidth, li.clientWidth]),
                // 三栏各自的滚动区底边 vs 面板底边：flush Panel 断了 flex 高度链时，
                // 滚动区会按内容高撑出面板（纵向溢出回归）
                columns: panels.map(p => {
                    const sc = p.el.querySelector('.overflow-y-auto');
                    return {
                        title: p.title,
                        panelBottom: Math.round(p.el.getBoundingClientRect().bottom),
                        scrollerBottom: sc ? Math.round(sc.getBoundingClientRect().bottom) : null,
                    };
                }),
            };
        }"""
    )


def verify_import_overflow(page):
    print("\n── 1. 提取结果卡片溢出 ──")
    page.goto(f"{BASE}/import", wait_until="networkidle")

    # 先贴一份原文，否则「开始提取」不可点
    page.get_by_role("button", name="原文", exact=True).click()
    page.locator("textarea").first.fill("1. 中国的首都是哪里？\nA. 上海 B. 北京 C. 广州 D. 深圳")
    page.get_by_role("button", name=re.compile(r"^加入")).click()
    page.wait_for_selector("text=就绪", timeout=10000)

    # 拦截提取接口注入候选题（不依赖模型配置）
    def fulfill(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "job": {"id": "job-ui", "sourceIds": [], "mode": "direct",
                            "status": "review", "scriptId": None, "stats": {},
                            "createdAt": "2026-10-17T00:00:00Z"},
                    "questions": fake_candidates(),
                }
            ),
        )

    page.route("**/api/extract/direct", fulfill)
    page.get_by_role("button", name="开始提取").click()
    page.locator("section", has=page.locator("h2", has_text="提取结果")).last.locator("li").first.wait_for(timeout=10000)

    metrics = overflow_metrics(page)
    check("桌面端页面无横向溢出", metrics["doc"][0] <= metrics["doc"][1], str(metrics["doc"]))
    check("桌面端右栏容器无横向溢出", metrics["scroller"][0] <= metrics["scroller"][1], str(metrics["scroller"]))
    check(
        "桌面端候选题卡片无横向溢出",
        len(metrics["cards"]) == 2 and all(w <= c for w, c in metrics["cards"]),
        str(metrics["cards"]),
    )
    check(
        "桌面端面板内所有条目无横向溢出",
        all(w <= c for w, c in metrics["allLis"]),
        str([x for x in metrics["allLis"] if x[0] > x[1]]),
    )
    check(
        "桌面端三栏滚动区均不超出面板",
        all(c["scrollerBottom"] is None or c["scrollerBottom"] <= c["panelBottom"] + 1 for c in metrics["columns"]),
        str(metrics["columns"]),
    )
    check("桌面端导入页整页无纵向溢出", metrics["docHeight"][0] <= metrics["docHeight"][1] + 1, str(metrics["docHeight"]))

    # 窄屏（手机宽度）再测一次
    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_timeout(300)
    narrow = overflow_metrics(page)
    check("窄屏页面无横向溢出", narrow["doc"][0] <= narrow["doc"][1], str(narrow["doc"]))
    check(
        "窄屏候选题卡片无横向溢出",
        all(w <= c for w, c in narrow["cards"]),
        str(narrow["cards"]),
    )
    check(
        "窄屏面板内所有条目无横向溢出",
        all(w <= c for w, c in narrow["allLis"]),
        str([x for x in narrow["allLis"] if x[0] > x[1]]),
    )
    page.set_viewport_size({"width": 1600, "height": 950})


def verify_chat_driven_extract(page):
    print("\n── 1b. agent 对话驱动提取 ──")
    page.goto(f"{BASE}/import", wait_until="networkidle")

    # 先贴一份原文，保证有选中材料
    page.get_by_role("button", name="原文", exact=True).click()
    page.locator("textarea").first.fill("1. 中国的首都是哪里？\nA. 上海 B. 北京 C. 广州 D. 深圳")
    page.get_by_role("button", name=re.compile(r"^加入")).click()
    page.wait_for_selector("text=就绪", timeout=10000)

    chat_body = {}

    def fulfill_chat(route):
        chat_body.update(route.request.post_data_json or {})
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "reply": "我先看了材料清单，确认结构后抽了题，候选题在右栏。",
                "reasoning": "用户只要单选题，先抓链接再跑代码清洗，最后交给抽题。",
                "steps": [
                    {"tool": "fetch_url", "ok": True,
                     "note": "抓取链接 127.0.0.1：820 字 · 3 张图",
                     "thought": "链接不在左侧材料里，我先自己抓一份"},
                    {"tool": "run_python", "ok": True,
                     "note": "运行 Python（1.2s，退出码 0）",
                     "thought": "正文里有表格噪声，写十行代码清洗成纯题干"},
                    {"tool": "extract_questions", "ok": True,
                     "note": "提取到 2 题（1 存疑）",
                     "thought": "题干干净了，按用户只要单选题的要求抽题"},
                ],
                "action": {"type": "extract_direct", "sourceIds": [],
                           "jobId": "job-agent", "instruction": "只要单选题"},
            }),
        )

    def fulfill_job(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "job": {"id": "job-agent", "sourceIds": [], "mode": "direct", "status": "review",
                        "scriptId": None,
                        "stats": {"extracted": 2, "suspect": 1, "images": 3, "skipped": []},
                        "createdAt": "2026-10-18T11:00:00Z"},
                "questions": fake_candidates(),
            }),
        )

    def fulfill_direct(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "job": {"id": "job-ui", "sourceIds": [], "mode": "direct",
                        "status": "review", "scriptId": None, "stats": {},
                        "createdAt": "2026-10-17T00:00:00Z"},
                "questions": fake_candidates(),
            }),
        )

    page.route("**/api/extract/chat", fulfill_chat)
    page.route("**/api/extract/jobs/*", fulfill_job)
    page.route("**/api/extract/direct", fulfill_direct)

    composer = page.get_by_placeholder(re.compile("发链接，或说怎么拆"))
    composer.fill("把左边这份抽成题")
    page.get_by_role("button", name="发送", exact=True).click()

    # 工具轨迹铺在回复前面：用户能看见它抓了链接、跑了代码、抽了题
    page.wait_for_selector("text=运行 Python（1.2s，退出码 0）", timeout=15000)
    check("agent 步骤轨迹可见", True)
    page.wait_for_selector("text=抓取链接 127.0.0.1", timeout=10000)
    check("agent 抓取步骤可见", True)
    page.wait_for_selector("text=我先看了材料清单", timeout=15000)
    check("agent 回复可见", True)
    check("对话请求带上了材料 id", bool(chat_body.get("sourceIds")), str(chat_body))

    # 思维链：每步工具调用前的「为什么这么做」要铺在同一条目里、位于备注上方
    page.wait_for_selector("text=链接不在左侧材料里，我先自己抓一份", timeout=10000)
    check("步骤思考可见", True)
    order_ok = page.evaluate(
        """() => {
            const leaves = [...document.querySelectorAll('p, span, div')]
                .filter(n => n.children.length === 0);
            const thought = leaves.find(n => n.textContent.includes('链接不在左侧材料里'));
            const note = leaves.find(n => n.textContent.includes('抓取链接 127.0.0.1'));
            if (!thought || !note) return false;
            return Boolean(thought.compareDocumentPosition(note) & Node.DOCUMENT_POSITION_FOLLOWING);
        }"""
    )
    check("思考排在步骤备注上方", bool(order_ok))

    # 最终回复带推理模型的思考，同样铺在气泡上方
    page.wait_for_selector("text=用户只要单选题，先抓链接再跑代码清洗", timeout=10000)
    check("回复的思考可见", True)

    results = page.locator("section", has=page.locator("h2", has_text="提取结果")).last
    results.locator("li").first.wait_for(timeout=15000)
    check("agent 抽题结果进右栏", True)

    # 「开始提取」按钮仍是快捷方式：不经过对话直接出候选
    before = page.locator("text=提取到").count()
    page.get_by_role("button", name="开始提取").click()
    page.wait_for_timeout(800)
    check("开始提取按钮仍可用", page.locator("text=提取到").count() > before)


def verify_chat_url_extract(page):
    print("\n── 1c. 对话里直接发链接 ──")
    page.goto(f"{BASE}/import", wait_until="networkidle")

    fake_url_source = {
        "id": "s-url", "type": "url", "name": "https://example.com/paper",
        "status": "ready", "error": None, "charCount": 0,
        "createdAt": "2026-10-18T10:00:00Z",
        "meta": {"kind": "url", "imageCount": 2, "images": ["uploads/s-url/url-img-1.png"]},
    }

    def handle_sources(route):
        # 链接材料的创建走 POST /api/sources；拦截掉，不打外网
        if route.request.method == "POST":
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"source": fake_url_source}))
        else:
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"sources": []}))

    def fulfill_chat(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "reply": "好，我去读这个页面，只抽单选题。",
                "action": {"type": "extract_direct", "sourceIds": [],
                           "urls": ["https://example.com/paper"], "instruction": "只要单选题"},
            }),
        )

    def fulfill_direct(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "job": {"id": "job-url", "sourceIds": ["s-url"], "mode": "direct",
                        "status": "review", "scriptId": None,
                        "stats": {"extracted": 1, "suspect": 0, "images": 2, "skipped": []},
                        "createdAt": "2026-10-18T10:01:00Z"},
                "questions": fake_candidates(),
            }),
        )

    page.route("**/api/sources", handle_sources)
    page.route("**/api/extract/chat", fulfill_chat)
    page.route("**/api/extract/direct", fulfill_direct)

    # 不往左侧加任何材料，直接在对话里发链接
    composer = page.get_by_placeholder(re.compile("发链接，或说怎么拆"))
    composer.fill("提取 https://example.com/paper 里的题，只要单选")
    page.get_by_role("button", name="发送", exact=True).click()

    page.wait_for_selector("text=好，我去读这个页面", timeout=15000)
    check("对话里发链接有回复", True)

    sources_panel = page.locator("section", has=page.locator("h2", has_text="数据源"))
    sources_panel.locator("text=https://example.com/paper").wait_for(timeout=10000)
    check("对话里的链接被抓成材料", True)
    check("链接材料标注视觉读取", "视觉读取" in sources_panel.inner_text())

    results = page.locator("section", has=page.locator("h2", has_text="提取结果")).last
    results.locator("li").first.wait_for(timeout=15000)
    check("链接材料进入提取", True)


def verify_bank_page(page):
    print("\n── 2. 题库管理页 ──")
    page.goto(f"{BASE}/bank", wait_until="networkidle")

    bank_select = page.locator("select").first
    check("题库切换是下拉框", bank_select.is_visible())

    # 切到题数非空的题库，保证有题目可验
    values = bank_select.locator("option").evaluate_all("els => els.map(e => e.value)")
    texts = bank_select.locator("option").all_text_contents()
    target = None
    for value, text in zip(values, texts):
        match = re.search(r"（(\d+) 题）", text)
        if match and int(match.group(1)) > 0:
            target = value
            break
    check("存在题数非空的题库", target is not None, str(texts[:4]))
    if target:
        bank_select.select_option(target)
        page.wait_for_timeout(400)

    body_text = page.locator("body").inner_text()
    # v4 起答案行是「答案」粗体小标签紧接值，不再用「 · 」分隔
    check("答案默认隐藏", not re.search(r"答案\S", body_text))
    page.get_by_role("button", name="显示答案").click()
    page.wait_for_timeout(300)
    check("显示答案后出现答案行", bool(re.search(r"答案\S", page.locator("body").inner_text())))
    page.get_by_role("button", name="隐藏答案").click()
    page.wait_for_timeout(300)
    check("可再隐藏答案", not re.search(r"答案\S", page.locator("body").inner_text()))

    # 大屏：题型/标签/搜索同一行
    rows = page.evaluate(
        """() => {
            const picks = [...document.querySelectorAll('select, input')]
                .filter(el => el.offsetParent !== null);
            const type = picks.find(el => el.tagName === 'SELECT' && el.textContent.includes('全部题型'));
            const tag = picks.find(el => el.tagName === 'SELECT' && el.textContent.includes('全部标签'));
            const kw = picks.find(el => el.placeholder && el.placeholder.includes('搜索题干'));
            const box = el => { const r = el.getBoundingClientRect(); return [Math.round(r.top), Math.round(r.left)]; };
            return { type: box(type), tag: box(tag), kw: box(kw) };
        }"""
    )
    check("大屏筛选同一行", rows["type"][0] == rows["tag"][0] == rows["kw"][0], str(rows))

    # 小屏：三个筛选各自成行且占满宽度
    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_timeout(300)
    rows = page.evaluate(
        """() => {
            const picks = [...document.querySelectorAll('select, input')]
                .filter(el => el.offsetParent !== null);
            const type = picks.find(el => el.tagName === 'SELECT' && el.textContent.includes('全部题型'));
            const tag = picks.find(el => el.tagName === 'SELECT' && el.textContent.includes('全部标签'));
            const kw = picks.find(el => el.placeholder && el.placeholder.includes('搜索题干'));
            const box = el => { const r = el.getBoundingClientRect(); return [Math.round(r.top), Math.round(r.width)]; };
            return { type: box(type), tag: box(tag), kw: box(kw) };
        }"""
    )
    check("小屏筛选各自成行", rows["type"][0] < rows["tag"][0] < rows["kw"][0], str(rows))
    check("小屏筛选占满宽度", all(row[1] > 300 for row in rows.values()), str(rows))
    page.set_viewport_size({"width": 1600, "height": 950})


def verify_practice_feed(page):
    print("\n── 3. 翻阅式刷题与结算 ──")
    page.goto(f"{BASE}/practice", wait_until="networkidle")
    page.get_by_role("button", name="开始刷题").click()
    # 等会话视图渲染出来（建会话是异步的）
    page.wait_for_selector("text=刷题中", timeout=15000)

    rail = page.locator('nav[aria-label="题目跳转"]')
    check("侧栏题号导航存在", rail.is_visible())
    check("侧栏题号数量正确", rail.locator("button").count() >= 2, str(rail.locator("button").count()))

    # 大屏只保留侧栏：底部横排题号条在 lg 起隐藏，两者不同时出现
    jump = page.locator('[aria-label="底部题目跳转"]')
    check("大屏隐藏底部题号条", jump.count() == 0 or not jump.is_visible())

    centered = page.evaluate(
        """() => {
            const cards = [...document.querySelectorAll('article')].filter(el => el.offsetParent !== null);
            const first = cards[0].getBoundingClientRect();
            return [Math.round(first.left + first.width / 2), Math.round(window.innerWidth / 2)];
        }"""
    )
    check("题流居中", abs(centered[0] - centered[1]) < 40, str(centered))

    # 找第一道单选/判断题：点选即判，不再按「提交答案」
    cards = page.locator("article")
    target = None
    for i in range(cards.count()):
        card = cards.nth(i)
        text = card.inner_text()
        if ("单选" in text or "判断" in text) and card.locator("button").count() > 0:
            target = card
            break
    check("找到可作答的题", target is not None)
    if target:
        wrapper = target.locator("xpath=..")
        target.locator("button").first.click()
        page.wait_for_timeout(900)
        body = page.locator("body").inner_text()
        wrong = any(text in body for text in ("与答案不一致", "与答案不符", "回答错误"))
        check("点选即判出现反馈", ("回答正确" in body) or wrong or ("待阅卷" in body))
        check("反馈带正确答案", bool(re.search(r"正确答案\S", body)))
        check("点选后无提交按钮", wrapper.get_by_role("button", name="提交答案").count() == 0)
        # 用卡片自身位置判断跳转：Playwright 点击前会自行滚动，scrollY 不可靠
        answered_top = target.evaluate("el => el.getBoundingClientRect().top")
        if wrong:
            # 答错停在原题：卡片仍在视口内，没有被滚走
            check("答错不跳题（停在原题）", answered_top < page.evaluate("() => window.innerHeight"), str(answered_top))
        elif rail.locator('button[title*="下一题"]').count() == 1:
            # 答对顺到下一道：当前题被滚过视口顶端
            check("答对跳到下一题", answered_top < 0, str(answered_top))

        # 侧栏跳转：跳到最后一题
        rail.locator("button").last.click()
        page.wait_for_timeout(900)
        last_visible = page.evaluate(
            """() => {
                const cards = [...document.querySelectorAll('article')].filter(el => el.offsetParent !== null);
                const last = cards[cards.length - 1].getBoundingClientRect();
                return last.top < window.innerHeight && last.bottom > 0;
            }"""
        )
        check("侧栏跳转滚动到位", last_visible)

    # 小屏只有底部横排条：侧栏隐藏、底栏可见
    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_timeout(500)
    check("小屏隐藏侧栏题号栏", not rail.is_visible())
    check("小屏显示底部题号条", jump.is_visible())
    page.set_viewport_size({"width": 1600, "height": 950})
    page.wait_for_timeout(500)

    # 结算
    page.get_by_role("button", name="查看结算").click()
    page.wait_for_selector("text=本轮结算", timeout=10000)
    check("结算页展示做过的题", page.locator("text=本轮结算").count() > 0)
    check("结算有逐题对照", bool(re.search(r"我的作答\S", page.locator("body").inner_text())))
    check("结算有正确答案行", bool(re.search(r"正确答案\S", page.locator("body").inner_text())))
    check("结算有再刷一轮", page.get_by_role("button", name="再刷一轮").count() > 0)


def verify_exam_feed(page):
    print("\n── 4. 翻阅式考试与结果页阅卷 ──")
    # 准备一份试卷（模板即试卷，每种题型各 1 题）
    created = page.request.post(
        f"{BASE}/api/exam-templates",
        data={
            "name": "UI验证试卷",
            "typeDistribution": {"single_choice": 1, "multiple_choice": 1, "true_false": 1,
                                 "fill_blank": 1, "subjective": 1},
            "totalCount": 5,
            "durationMinutes": 30,
            "isShared": True,
        },
    )
    template_id = created.json()["template"]["id"] if created.ok else None
    check("创建试卷（API）", template_id is not None, created.text()[:200])

    page.goto(f"{BASE}/exam", wait_until="networkidle")
    # 试卷管理已并入考试页：列表里直接有开考与编辑入口，无独立模板页
    check("试卷列表含开考入口", page.get_by_role("button", name="开考").count() >= 1)
    check("试卷列表含编辑入口", page.get_by_role("button", name="编辑").count() >= 1)
    check("试卷列表有新建入口", page.get_by_role("button", name="新建试卷").count() >= 1)
    page.get_by_role("button", name="开考").first.click()
    page.wait_for_selector("text=剩余时间", timeout=15000)

    check("考试侧栏存在", page.locator('nav[aria-label="题目跳转"]').is_visible())
    check("考试倒计时存在", page.locator("text=剩余时间").count() > 0)
    check("考试题流 5 题", page.locator("article").count() == 5, str(page.locator("article").count()))

    # 答一道题，看「已作答」标记
    first = page.locator("article").first
    if first.locator("button").count() > 0:
        first.locator("button").first.click()
        page.wait_for_timeout(300)
        check("作答后出现已答标记", page.locator("text=✓ 已作答").count() > 0)

    page.get_by_role("button", name="交卷").first.click()
    page.wait_for_timeout(400)
    page.get_by_role("button", name="确认交卷").click()
    # 「返回试卷列表」只在结果页出现（确认弹窗里也有「客观题」字样，不能拿它当信号）
    page.wait_for_selector("text=返回试卷列表", timeout=20000)
    page.wait_for_timeout(300)

    body = page.locator("body").inner_text()
    check("结果页出分", ("客观题" in body) and ("总分" in body))
    check("结果页逐题对照", bool(re.search(r"我的作答\S", body)))
    check("结果页可内联阅卷", page.locator("text=提交阅卷").count() > 0)
    check("无独立阅卷入口", "去阅卷" not in body)

    # 清理：交卷后的考试与模板
    page.evaluate("localStorage.removeItem('mojuan_active_exam')")
    if template_id:
        page.request.delete(f"{BASE}/api/exam-templates/{template_id}")


with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge", headless=True)
    page = browser.new_page(viewport={"width": 1600, "height": 950})
    login(page)
    verify_import_overflow(page)
    verify_chat_driven_extract(page)
    verify_chat_url_extract(page)
    verify_bank_page(page)
    verify_practice_feed(page)
    verify_exam_feed(page)
    browser.close()

print()
if failures:
    print(f"共 {len(failures)} 项失败：{failures}")
    sys.exit(1)
print("浏览器验证全部通过")
