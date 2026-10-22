"""AI-A 冒烟测试：材料上传与归一化 → 模式 A 提取逻辑 → 审核后批量入库。

分两部分：
1. HTTP 层走 TestClient：sources CRUD、提取路由的错误分支、questions/batch
2. 单元层不走 HTTP：parse_questions 的脏数据收敛、extract_json、
   run_direct 用假客户端验证提示词拼装与截断
"""

import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi.testclient import TestClient  # noqa: E402

from app.lib.normalize import NormalizeError  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
failures = []


def check(name, condition, extra=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f"  {extra}" if extra and not condition else ""))
    if not condition:
        failures.append(name)


def _raises(fn):
    try:
        fn()
        return False
    except NormalizeError:
        return True


# 1x1 透明 PNG，验证图片分支只登记不转文本
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)

# ---------------------------------------------------------------- HTTP 层

r = client.post("/api/auth/register", json={
    "username": "smoke_a", "password": "pass12345", "displayName": "冒烟A"
})
check("注册用户", r.status_code in (200, 409), r.text)
r = client.post("/api/auth/login", json={"username": "smoke_a", "password": "pass12345"})
check("登录", r.status_code == 200, r.text)

# 2. 粘贴原文
r = client.post("/api/sources", data={
    "text": "1. 中国的首都是哪座城市？\nA. 上海\nB. 北京\nC. 广州\nD. 深圳\n答案：B"
})
check("粘贴原文入库", r.status_code == 200, r.text)
pasted = r.json()["source"]
check("原文类型为 text", pasted["type"] == "text", r.text)
check("字数已统计", pasted["charCount"] > 10, r.text)
check("返回预览", "北京" in pasted.get("preview", ""), r.text)

# 3. 上传 txt
r = client.post(
    "/api/sources",
    files={"file": ("题库.txt", "2. 光速约为每秒多少公里？\n答案：30万".encode("utf-8"), "text/plain")},
)
check("上传 txt 入库", r.status_code == 200, r.text)
txt_source = r.json()["source"]
check("文档类型为 document", txt_source["type"] == "document", r.text)

# 4. 上传图片：只登记，不走归一化
r = client.post("/api/sources", files={"file": ("题目.png", PNG_BYTES, "image/png")})
check("上传图片入库", r.status_code == 200, r.text)
image_source = r.json()["source"]
check("图片类型为 image", image_source["type"] == "image", r.text)
check("图片无归一化产物", image_source.get("meta", {}).get("needsVision") is True, r.text)

# 5. 三种材料混给 → 422
r = client.post(
    "/api/sources",
    files={"file": ("a.txt", b"x", "text/plain")},
    data={"text": "同时给了原文"},
)
check("混给材料被拒", r.status_code == 422, r.text)

# 6. 不支持的扩展名 → 422
r = client.post("/api/sources", files={"file": ("病毒.exe", b"MZ", "application/octet-stream")})
check("不支持的格式被拒", r.status_code == 422, r.text)

# 7. 空粘贴 → 422
r = client.post("/api/sources", data={"text": "   "})
check("空内容被拒", r.status_code == 422, r.text)

# 8. 列表与详情
r = client.get("/api/sources")
check("材料列表", r.status_code == 200 and len(r.json()["sources"]) >= 3, r.text)

r = client.get(f"/api/sources/{pasted['id']}")
check("材料详情带预览", r.status_code == 200 and "preview" in r.json()["source"], r.text)

r = client.get(f"/api/sources/{pasted['id']}/status")
check("材料状态查询", r.status_code == 200 and r.json()["source"]["status"] == "ready", r.text)

r = client.get("/api/sources/nonexistent")
check("不存在材料 404", r.status_code == 404, r.text)

# 9. 未配置模型接口时提取 → 422 且提示去设置页
# settings 是全局配置，这里临时清掉 ai_* 再还原，避免依赖别人配好的接口
import sqlite3 as _sqlite3  # noqa: E402

from app.db import DB_PATH  # noqa: E402

_conn = _sqlite3.connect(DB_PATH)
_conn.row_factory = _sqlite3.Row
_saved_ai_settings = _conn.execute(
    "SELECT key, value FROM settings WHERE key LIKE 'ai_%'"
).fetchall()
_conn.execute("DELETE FROM settings WHERE key LIKE 'ai_%'")
_conn.commit()
_conn.close()

r = client.post("/api/extract/direct", json={"sourceIds": [pasted["id"]]})
check("未配接口提取被拒", r.status_code == 422 and "设置" in r.json()["detail"], r.text)

# 9b. 同一个「未配置」窗口里验 agent 端点：材料归属校验先于接口配置
r = client.post("/api/extract/chat", json={"message": "在吗", "sourceIds": ["nonexistent"]})
check("agent 引用不存在材料 404", r.status_code == 404, r.text)

r = client.post("/api/extract/chat", json={"message": "在吗", "sourceIds": [pasted["id"]]})
check("未配接口 agent 被拒", r.status_code == 422 and "设置" in r.json()["detail"], r.text)

r = client.post("/api/extract/chat", json={"message": "", "sourceIds": []})
check("空消息被拒", r.status_code == 422, r.text)

_conn = _sqlite3.connect(DB_PATH)
_conn.executemany(
    "INSERT INTO settings (key, value) VALUES (?, ?) "
    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
    [(row["key"], row["value"]) for row in _saved_ai_settings],
)
_conn.commit()
_conn.close()

# 10. 提取不存在的材料 → 404（先于接口配置校验）
r = client.post("/api/extract/direct", json={"sourceIds": ["nonexistent"]})
check("提取不存在材料 404", r.status_code == 404, r.text)

r = client.post("/api/extract/direct", json={"sourceIds": []})
check("空材料列表被拒", r.status_code == 422, r.text)

# 11. 提取记录查询
r = client.get("/api/extract/jobs/nonexistent")
check("不存在提取记录 404", r.status_code == 404, r.text)

# 11b. 外部 AI 结果粘贴解析（不调模型、不入库）
r = client.post(
    "/api/extract/parse",
    json={
        "text": '[{"type":"single_choice","content":"1+1=？",'
        '"options":[{"key":"A","text":"1"},{"key":"B","text":"2"}],"answer":["B"]}]'
    },
)
check("粘贴解析返回候选题", r.status_code == 200 and len(r.json()["questions"]) == 1, r.text)
_parsed = r.json()["questions"][0]
check("粘贴解析收敛题型/答案", _parsed["type"] == "single_choice" and _parsed["answer"] == ["B"], r.text)

r = client.post("/api/extract/parse", json={"text": "这不是 JSON"})
check(
    "无 JSON 文本被拒且带原文",
    r.status_code == 422 and "没找到可解析的 JSON" in r.json()["detail"],
    r.text,
)

r = client.post("/api/extract/parse", json={"text": '{"foo": 1, "bar": 2}'})
check(
    "顶层结构不对时报字段名",
    r.status_code == 422 and "结构不对" in r.json()["detail"] and "foo" in r.json()["detail"],
    r.text,
)

r = client.post("/api/extract/parse", json={"text": '[{"type":"single_choice","answer":["A"]}]'})
check(
    "全部缺 content 时报清原因",
    r.status_code == 422 and "没有一条能解析" in r.json()["detail"],
    r.text,
)

r = client.post("/api/extract/parse", json={"text": ""})
check("空文本被拒", r.status_code == 422, r.text)

# 12. 审核后批量入库
r = client.post("/api/banks", json={"name": "冒烟导入题库", "isShared": True})
check("创建题库", r.status_code == 200, r.text)
import_bank = r.json()["bank"]["id"]

candidates = [
    {
        "type": "single_choice", "content": "中国的首都是哪座城市？",
        "options": [{"key": "A", "text": "上海"}, {"key": "B", "text": "北京"}],
        "answer": ["B"], "tags": ["地理"], "difficulty": 1,
        "confidence": 0.95, "fingerprint": "fp-1",
    },
    {
        "type": "fill_blank", "content": "北京是____的首都。",
        "answer": ["中国"], "acceptableAnswers": [["中国", "中华人民共和国"]],
        "tags": ["地理"], "difficulty": 2, "confidence": 0.88, "fingerprint": "fp-2",
    },
    {
        # 与第一条同指纹：模拟模型把同一道题输出两遍，批内应去重
        "type": "single_choice", "content": "中国的首都是哪座城市？",
        "options": [{"key": "A", "text": "上海"}, {"key": "B", "text": "北京"}],
        "answer": ["B"], "tags": ["地理"], "difficulty": 1,
        "confidence": 0.9, "fingerprint": "fp-1",
    },
]
r = client.post("/api/questions/batch", json={"bankId": import_bank, "questions": candidates})
check("批量入库", r.status_code == 200, r.text)
body = r.json()
check("批内去重后入 2 条", body["created"] == 2, r.text)
check("confidence 已落库", all(q["confidence"] for q in body["questions"]), r.text)
check("fingerprint 已落库", all(q["fingerprint"] for q in body["questions"]), r.text)
check("返回带答案", all("answer" in q for q in body["questions"]), r.text)

r = client.post("/api/questions/batch", json={"bankId": "nonexistent", "questions": candidates})
check("批量到不存在题库 404", r.status_code == 404, r.text)

r = client.post("/api/questions/batch", json={"bankId": import_bank, "questions": []})
check("空批量被拒", r.status_code == 422, r.text)

r = client.post("/api/questions/batch", json={
    "bankId": import_bank,
    "questions": [{"type": "single_choice", "content": "没选项的选择题", "answer": ["A"]}],
})
check("缺选项的批量被拒", r.status_code == 422, r.text)

# 13. 删除材料（含磁盘清理）
r = client.delete(f"/api/sources/{txt_source['id']}")
check("删除材料", r.status_code == 200, r.text)
r = client.get(f"/api/sources/{txt_source['id']}")
check("删除后 404", r.status_code == 404, r.text)

# ---------------------------------------------------------------- 单元层

from app.lib.ai.client import extract_json  # noqa: E402
from app.lib.extract.direct import fingerprint, parse_questions, run_direct  # noqa: E402
from app.lib.normalize import normalize_bytes, normalize_pasted  # noqa: E402

# 14. extract_json 容忍围栏与前后废话
check("裸数组解析", extract_json('[{"a":1}]') == [{"a": 1}])
check("剥 json 围栏", extract_json('```json\n[{"a":1}]\n```') == [{"a": 1}])
check("容忍解释文字", extract_json('好的，结果如下：\n[{"a":1}]\n以上。') == [{"a": 1}])
check("容忍对象包裹", extract_json('{"questions":[{"a":1}]}') == {"questions": [{"a": 1}]})
try:
    extract_json("完全没有 JSON")
    check("无 JSON 抛错", False)
except Exception as error:
    check("无 JSON 抛错", "JSON" in str(error))

# 15. parse_questions 收敛脏数据
dirty = {
    "questions": [
        {"type": "single_choice", "content": "  题干一  ", "options": ["选项A", "选项B"],
         "answer": "A", "difficulty": "9", "confidence": "高"},
        {"type": "不存在的题型", "content": "题干二", "answer": ["随便"]},
        {"type": "fill_blank", "content": "题干三", "answer": [], "acceptableAnswers": ["a", ["b", "c"]]},
        {"content": ""},  # 空题干应被丢弃
        "不是对象",
        {"type": "multiple_choice", "content": "题干四", "options": [{"key": "A", "text": "x"}],
         "answer": ["A"], "confidence": 0.2},
    ]
}
parsed = parse_questions(dirty)
check("脏数据收敛为 4 条", len(parsed) == 4, str(len(parsed)))
first = parsed[0]
check("题型合法化", first["type"] == "single_choice")
check("选项字符串转对象", first["options"] == [{"key": "A", "text": "选项A"}, {"key": "B", "text": "选项B"}])
check("单答案转数组", first["answer"] == ["A"])
check("难度越界钳回 5", first["difficulty"] == 5)
check("置信度非法回落 0.5", first["confidence"] == 0.5)
check("未知题型回落主观题", parsed[1]["type"] == "subjective")
check("填空无答案补空串", parsed[2]["answer"] == [""])
check("等价答案裸字符串恢复成组", parsed[2]["acceptableAnswers"] == [["a"], ["b", "c"]])
check("低置信度标记存疑", parsed[3]["suspect"] is True)
check("结构性问题标记", "多选却只有一个答案" in parsed[3]["issues"])
check("全部带指纹", all(q["fingerprint"] for q in parsed))

# 16. 指纹忽略空白与大小写
check("指纹忽略空白大小写", fingerprint("Hello  World") == fingerprint("helloworld"))
check("指纹区分内容", fingerprint("题A") != fingerprint("题B"))

# 17. run_direct 用假客户端：验证材料拼装与查重标记
class FakeClient:
    def __init__(self):
        self.seen_messages = None

    def chat_json(self, messages, **kwargs):
        self.seen_messages = messages
        return [
            {"type": "true_false", "content": "地球是圆的。", "answer": ["T"],
             "confidence": 0.9, "difficulty": 1},
        ]

    def chat_vision(self, prompt, images, **kwargs):
        raise AssertionError("文本材料不该走视觉通道")


fake = FakeClient()
fake_rows = [
    {"type": "text", "name": "材料一", "normalized_path": "normalized/不存在.md",
     "storage_path": None},
]
# normalized_path 指向不存在的文件 → 无文字内容 → 应报错
try:
    run_direct(fake, fake_rows)
    check("空材料被拒", False)
except Exception as error:
    check("空材料被拒", "没有可用内容" in str(error))

# 造一份真实的归一化文件
from app.db import DATA_DIR, NORMALIZED_DIR  # noqa: E402

NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)
(NORMALIZED_DIR / "smoke_source.md").write_text(
    "1. 地球是圆的。\n答案：正确", encoding="utf-8"
)
real_rows = [
    {"type": "text", "name": "材料一",
     "normalized_path": "normalized/smoke_source.md", "storage_path": None},
]
outcome = run_direct(fake, real_rows, instruction="只要判断题", existing_fingerprints={"abc"})
check("假客户端返回 1 题", outcome["stats"]["extracted"] == 1, str(outcome["stats"]))
user_msg = fake.seen_messages[-1]["content"]
check("用户提示词含材料内容", "地球是圆的" in user_msg)
check("用户提示词含补充要求", "只要判断题" in user_msg)
check("系统提示词要求 JSON 数组", "JSON 数组" in fake.seen_messages[0]["content"])

# 查重：构造与库里指纹相同的题目
dup_rows = [
    {"type": "text", "name": "材料一",
     "normalized_path": "normalized/smoke_source.md", "storage_path": None},
]
outcome = run_direct(fake, dup_rows, existing_fingerprints={
    outcome["questions"][0]["fingerprint"]
})
check("命中指纹标重复", outcome["questions"][0].get("duplicate") is True)

# 18. 归一化：csv 转表格、html 提文字、不支持格式报错
csv_md = normalize_bytes("t.csv", "题干,答案\n1+1,2\n".encode("utf-8")).markdown
check("CSV 转 Markdown 表格", csv_md.startswith("| 题干 | 答案 |") and "| 1+1 | 2 |" in csv_md, csv_md)

html_md = normalize_bytes(
    "page.html",
    "<html><body><h1>标题</h1><p>段落文字</p><ul><li>选项A</li><li>选项B</li></ul></body></html>".encode("utf-8"),
).markdown
check("HTML 提取标题", "# 标题" in html_md, html_md)
check("HTML 保留列表", "选项A" in html_md and "选项B" in html_md, html_md)

try:
    normalize_bytes("x.exe", b"MZ")
    check("不支持的扩展名报错", False)
except NormalizeError as error:
    check("不支持的扩展名报错", "暂不支持" in str(error))

check("粘贴空内容报错", _raises(lambda: normalize_pasted("  ")))

# 19. 网页图片收集：补全、过滤、上限
from app.lib.normalize import _collect_image_urls, _from_html  # noqa: E402
import app.lib.normalize as _normalize  # noqa: E402

img_html = """
<html><body>
<img data-src="/upload/q1.png">
<img src="https://cdn.example.com/a.jpg">
<img src="data:image/png;base64,AAAA">
<img src="/icon.svg">
<img src="https://cdn.example.com/a.jpg">
<img src="/pixel.gif">
</body></html>
"""
collected = _collect_image_urls(img_html, "https://site.example.com/exam/1.html")
check("相对路径补全为绝对地址", "https://site.example.com/upload/q1.png" in collected, str(collected))
check("绝对地址原样保留", "https://cdn.example.com/a.jpg" in collected, str(collected))
check("data: 内联图跳过", not any(u.startswith("data:") for u in collected))
check("svg 跳过", not any(u.endswith(".svg") for u in collected))
check("重复图去重", collected.count("https://cdn.example.com/a.jpg") == 1)
check("追踪像素跳过", not any("pixel" in u for u in collected))

many = "".join(f'<img src="/img/{i}.png">' for i in range(60))
check("图片数量封顶 40", len(_collect_image_urls(many, "https://s.com/")) == 40)

# _from_html 有图就不再以「没文字」拒掉；下载本身不打网络，桩掉
_real_fetch = _normalize._fetch_page_images
_normalize._fetch_page_images = lambda html, base: [(PNG_BYTES, "image/png")]
try:
    page = _from_html("<html><body><img src='/q.png'></body></html>".encode("utf-8"), base_url="https://s.com/")
    check("纯图片网页不抛错", page.markdown == "" and len(page.images) == 1, str(page))
    check("图片数写进 meta", page.meta.get("imageCount") == 1, str(page.meta))
    page2 = _from_html(
        "<html><body><p>1. 题干</p><img src='/q.png'></body></html>".encode("utf-8"),
        base_url="https://s.com/",
    )
    check("有文字有图都保留", "题干" in page2.markdown and len(page2.images) == 1)
finally:
    _normalize._fetch_page_images = lambda html, base: []
try:
    _from_html(b"<html><body></body></html>", base_url="https://s.com/")
    check("无文字无图仍报错", False)
except NormalizeError:
    check("无文字无图仍报错", True)
finally:
    _normalize._fetch_page_images = _real_fetch

# 20. run_direct 读 meta.images：网页图片进视觉通道
from app.db import UPLOAD_DIR  # noqa: E402

_page_dir = UPLOAD_DIR / "smoke_page"
_page_dir.mkdir(parents=True, exist_ok=True)
(_page_dir / "url-img-1.png").write_bytes(PNG_BYTES)


class VisionFake:
    def __init__(self):
        self.seen_images = None

    def chat_json(self, messages, **kwargs):
        raise AssertionError("有图片不该走纯文本通道")

    def chat_vision(self, prompt, images, **kwargs):
        self.seen_images = images
        return '[{"type": "true_false", "content": "见图。", "answer": ["T"], "confidence": 0.8, "difficulty": 1}]'


vision_fake = VisionFake()
page_row = {
    "type": "url", "name": "图片网页",
    "normalized_path": None, "storage_path": None,
    "meta": json.dumps({"images": ["uploads/smoke_page/url-img-1.png"]}),
}
outcome = run_direct(vision_fake, [page_row])
check("网页图片走视觉通道", bool(vision_fake.seen_images) and len(vision_fake.seen_images) == 1)
check("视觉通道收到图片字节", vision_fake.seen_images[0][0] == PNG_BYTES)
check("统计计入图片数", outcome["stats"]["images"] == 1, str(outcome["stats"]))
check("无文字不判跳过", not any("无文字" in item for item in outcome["stats"]["skipped"]))

# 21. agent 循环：工具调用、观察回喂、最终回复
from app.lib.agent.loop import MAX_STEPS, run_agent  # noqa: E402
from app.lib.agent.tools import AgentContext  # noqa: E402

_agent_conn = _sqlite3.connect(DB_PATH)
_agent_conn.row_factory = _sqlite3.Row
_smoke_user = _agent_conn.execute(
    "SELECT id FROM users WHERE username = 'smoke_a'"
).fetchone()
_smoke_uid = _smoke_user["id"] if _smoke_user else None


class ScriptedClient:
    """按剧本回复的假客户端。剧本项可以是字符串或 callable(messages)->str。

    reasonings 与 replies 对齐：return_reasoning=True 时返回 (正文, 思考)，
    模拟推理模型的 reasoning_content。
    """

    def __init__(self, replies, reasonings=None):
        self.replies = list(replies)
        self.reasonings = list(reasonings or [])
        self.calls = []

    def chat(self, messages, **kwargs):
        self.calls.append(messages)
        if self.replies:
            item = self.replies.pop(0)
            reasoning = self.reasonings.pop(0) if self.reasonings else ""
        else:
            item = '{"reply": "（剧本结束）", "action": null}'
            reasoning = ""
        text = item(messages) if callable(item) else item
        if kwargs.get("return_reasoning"):
            return text, reasoning
        return text

    def chat_json(self, messages, **kwargs):
        return [
            {"type": "true_false", "content": "地球是圆的。", "answer": ["T"],
             "confidence": 0.9, "difficulty": 1},
        ]


def _ctx(client):
    return AgentContext(conn=_agent_conn, user_id=_smoke_uid, client=client)


def _observations(messages):
    return [
        m["content"] for m in messages
        if m["role"] == "user" and m["content"].startswith("观察（")
    ]


# 21a. 工具循环：两步工具 + 观察回喂 + 最终回复
scripted = ScriptedClient([
    json.dumps({"tool": "list_sources", "args": {}}),
    json.dumps({"tool": "run_python", "args": {"code": "print(6 * 7)"}}),
    json.dumps({"reply": "搞定，材料都看过了。", "action": None}),
])
outcome = run_agent(_ctx(scripted), "看看有什么材料", [], [], [])
check("agent 记录两步工具", [s["tool"] for s in outcome["steps"]] == ["list_sources", "run_python"], str(outcome["steps"]))
check("agent 最终回复", outcome["reply"] == "搞定，材料都看过了。", outcome["reply"])
check("agent 无动作", outcome["action"] is None)
observations = _observations(scripted.calls[-1])
check("观察回喂给模型", any("run_python" in o and "42" in o for o in observations), str(observations)[:200])
check("系统提示是 agent 提示词", "create_tool" in scripted.calls[0][0]["content"])
# 注意：循环里 messages 是同一个 list 被反复追加，calls 各次引用同一对象，
# 首轮的用户消息固定在下标 1（0 是系统提示）
check("用户原话进上下文", "看看有什么材料" in scripted.calls[0][1]["content"])

# 21b. fetch_url 真抓取：起个本地 HTTP 服务器，不打外网
import threading  # noqa: E402
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: E402

PAGE_HTML = (
    "<html><head><title>数学试卷</title></head><body><h1>单选题</h1>"
    "<p>1. 中国的首都是哪里？</p>"
    "<img src='/q.png'><img src='/dot.gif'><img src='data:image/png;base64,AAAA'>"
    "</body></html>"
)


class _PageHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/q.png":
            body = PNG_BYTES * 20  # 1.4KB，过「小于 1KB 判图标」的线
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
        elif self.path == "/dot.gif":
            body = b"GIF89a" + b"\x00" * 20  # 26 字节，应被大小下限滤掉
            self.send_response(200)
            self.send_header("Content-Type", "image/gif")
        else:
            body = PAGE_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


_page_server = ThreadingHTTPServer(("127.0.0.1", 0), _PageHandler)
threading.Thread(target=_page_server.serve_forever, daemon=True).start()
page_url = f"http://127.0.0.1:{_page_server.server_address[1]}/page.html"


def _final_with_source(messages):
    """从 fetch_url 的观察里取出刚建的材料 id，拼出收尾动作。"""
    observation = [m["content"] for m in messages if "观察（fetch_url）" in m["content"]][-1]
    payload = json.loads(observation.split("观察（fetch_url）：", 1)[1])
    return json.dumps({
        "reply": "抓到了，一段文字加 1 张图。",
        "action": {"type": "extract_direct", "sourceIds": [payload["sourceId"]],
                   "instruction": ""},
    }, ensure_ascii=False)


scripted = ScriptedClient([
    json.dumps({"tool": "fetch_url", "args": {"url": page_url}}),
    _final_with_source,
])
outcome = run_agent(_ctx(scripted), f"提取 {page_url} 里的题", [], [], [])
fetched = _agent_conn.execute(
    "SELECT * FROM sources WHERE owner_id = ? AND name = ?", (_smoke_uid, page_url)
).fetchone()
check("fetch_url 建成材料", fetched is not None, page_url)
check("抓取轨迹带域名与图数", "127.0.0.1" in outcome["steps"][0]["note"] and "1 张图" in outcome["steps"][0]["note"], outcome["steps"][0]["note"])
check("网页文字已归一化", "中国的首都是哪里" in (NORMALIZED_DIR / f"{fetched['id']}.md").read_text(encoding="utf-8"))
check("图片数写进 meta", json.loads(fetched["meta"]).get("imageCount") == 1, fetched["meta"])
check("动作带上新材料 id", outcome["action"]["sourceIds"] == [fetched["id"]], str(outcome["action"]))
_page_server.shutdown()

# 21c. create_tool + run_tool：造工具、跑工具、落库复用
scripted = ScriptedClient([
    json.dumps({"tool": "create_tool", "args": {
        "name": "greet", "description": "打招呼",
        "code": "import os, json; print('hi ' + str(json.loads(os.environ.get('AGENT_ARGS') or '{}').get('who', 'world')))",
    }}),
    json.dumps({"tool": "run_tool", "args": {"name": "greet", "args": {"who": "墨卷"}}}),
    json.dumps({"reply": "工具造好了，也跑通了。", "action": None}),
])
outcome = run_agent(_ctx(scripted), "造个打招呼的工具试试", [], [], [])
check("造工具两步", [s["tool"] for s in outcome["steps"]] == ["create_tool", "run_tool"], str(outcome["steps"]))
check("工具输出回喂", any("hi 墨卷" in o for o in _observations(scripted.calls[-1])))
tool_row = _agent_conn.execute(
    "SELECT code FROM agent_tools WHERE owner_id = ? AND name = 'greet'", (_smoke_uid,)
).fetchone()
check("工具落库可复用", tool_row is not None and "AGENT_ARGS" in tool_row["code"])

# 21d. extract_questions：agent 抽题落 job，候选题不入库
questions_before = _agent_conn.execute("SELECT COUNT(*) AS c FROM questions").fetchone()["c"]


def _final_with_job(messages):
    observation = [m["content"] for m in messages if "观察（extract_questions）" in m["content"]][-1]
    payload = json.loads(observation.split("观察（extract_questions）：", 1)[1])
    return json.dumps({
        "reply": "抽好了，候选题在右栏等你过目。",
        "action": {"type": "extract_direct", "sourceIds": [pasted["id"]],
                   "jobId": payload["jobId"], "instruction": "只要判断题"},
    }, ensure_ascii=False)


scripted = ScriptedClient([
    json.dumps({"tool": "extract_questions", "args": {"sourceIds": [pasted["id"]], "instruction": "只要判断题"}}),
    _final_with_job,
])
outcome = run_agent(_ctx(scripted), "把粘贴那份抽成题", [], [], [])
job_id = (outcome["action"] or {}).get("jobId")
job_row = _agent_conn.execute("SELECT * FROM extraction_jobs WHERE id = ?", (job_id,)).fetchone()
check("agent 抽题落 job", job_row is not None, str(job_id))
check("job 属主正确", job_row["owner_id"] == _smoke_uid)
check("候选题进 job", "地球是圆的" in job_row["result"], job_row["result"][:120])
check("候选题不入库", _agent_conn.execute("SELECT COUNT(*) AS c FROM questions").fetchone()["c"] == questions_before)
check("抽题轨迹带数量", "提取到 1 题" in outcome["steps"][0]["note"], outcome["steps"][0]["note"])

# 21e. 步骤上限：模型一直调工具也要被收住
loopy = ScriptedClient([json.dumps({"tool": "list_sources", "args": {}})] * 50)
outcome = run_agent(_ctx(loopy), "一直循环", [], [], [])
check("步骤上限生效", len(outcome["steps"]) == MAX_STEPS, str(len(outcome["steps"])))
check("超限后有收尾回复", bool(outcome["reply"].strip()), outcome["reply"])

# 21f. 未知工具不中断循环
scripted = ScriptedClient([
    json.dumps({"tool": "不存在的工具", "args": {}}),
    json.dumps({"reply": "那个工具没有，我直接说结论。", "action": None}),
])
outcome = run_agent(_ctx(scripted), "用个没见过的工具", [], [], [])
check("未知工具不中断循环", outcome["steps"][0]["ok"] is False and outcome["reply"].startswith("那个工具"), str(outcome))

# 21g. 模型不调工具 / 不说 JSON 时的兜底
outcome = run_agent(_ctx(ScriptedClient([json.dumps({"reply": "好的", "action": None})])), "在吗", [], [], [])
check("不调工具直接收尾", outcome["steps"] == [] and outcome["reply"] == "好的", str(outcome))
outcome = run_agent(_ctx(ScriptedClient(["我只会说人话，不会说 JSON"])), "在吗", [], [], [])
check("非 JSON 兜底为纯文本", outcome["action"] is None and outcome["reply"] == "我只会说人话，不会说 JSON", str(outcome))

# 21h. 思维链可见：thought 字段 / JSON 前的话 / 推理模型 reasoning / 最终思考
scripted = ScriptedClient([
    json.dumps({"thought": "先看看有哪些材料", "tool": "list_sources", "args": {}}),
    json.dumps({"reply": "看完了。", "action": None}),
])
outcome = run_agent(_ctx(scripted), "看看材料", [], [], [])
check("工具思考进轨迹", outcome["steps"][0]["thought"] == "先看看有哪些材料", str(outcome["steps"]))

scripted = ScriptedClient([
    "这个页面要翻页，我先写代码探一下接口\n" + json.dumps({"tool": "list_sources", "args": {}}),
    json.dumps({"reply": "好", "action": None}),
])
outcome = run_agent(_ctx(scripted), "探一下", [], [], [])
check("JSON 前的话当作思考", outcome["steps"][0]["thought"] == "这个页面要翻页，我先写代码探一下接口", str(outcome["steps"]))

scripted = ScriptedClient(
    [
        json.dumps({"tool": "list_sources", "args": {}}),
        json.dumps({"reply": "推理完了。", "action": None}),
    ],
    reasonings=["模型内部独白：用户要看材料，先列一下", "收尾前的推理：材料都看过了"],
)
outcome = run_agent(_ctx(scripted), "看看材料", [], [], [])
check("推理模型思维链进轨迹", outcome["steps"][0]["thought"] == "模型内部独白：用户要看材料，先列一下", str(outcome["steps"]))
check("最终思考带回响应", outcome["reasoning"] == "收尾前的推理：材料都看过了", str(outcome.get("reasoning")))

scripted = ScriptedClient([json.dumps({"thought": "不用工具，直接回", "reply": "好的。", "action": None})])
outcome = run_agent(_ctx(scripted), "在吗", [], [], [])
check("最终回复的思考", outcome["reasoning"] == "不用工具，直接回", str(outcome.get("reasoning")))
check("无工具时无轨迹", outcome["steps"] == [], str(outcome["steps"]))

# 22. agent 端点：monkeypatch 掉 AiClient，验 HTTP 层的步骤轨迹
import app.routers.extract as _extract_router  # noqa: E402

_real_ai = _extract_router.AiClient


class _StubAi:
    @classmethod
    def from_conn(cls, conn):
        return ScriptedClient([
            json.dumps({"tool": "list_sources", "args": {}}),
            json.dumps({"reply": "看完了，材料都在。", "action": None}),
        ])


_extract_router.AiClient = _StubAi
try:
    r = client.post("/api/extract/chat", json={"message": "看看材料", "sourceIds": []})
    check("agent 端点跑通", r.status_code == 200, r.text)
    body = r.json()
    check("端点返回步骤轨迹", len(body.get("steps", [])) == 1, r.text)
    check("端点返回回复", "看完了" in body.get("reply", ""), r.text)
finally:
    _extract_router.AiClient = _real_ai


# 23. 流式对话 + 会话记录落库：事件是逐条推的，ms 真在计时
import time as _time  # noqa: E402

_original_ai = _extract_router.AiClient


class _DelayedScripted:
    def __init__(self, replies, reasonings=None):
        self.replies = list(replies)
        self.reasonings = list(reasonings or [])

    def chat(self, messages, **kwargs):
        _time.sleep(0.02)
        item = self.replies.pop(0) if self.replies else '{"reply": "（剧本结束）", "action": null}'
        reasoning = self.reasonings.pop(0) if self.reasonings else ""
        if kwargs.get("return_reasoning"):
            return item, reasoning
        return item


class _StreamStubAi:
    @classmethod
    def from_conn(cls, conn):
        return _DelayedScripted([
            json.dumps({"thought": "先列一下材料", "tool": "list_sources", "args": {}}),
            json.dumps({"reply": "看完了，材料都在。", "action": None}),
        ])


_extract_router.AiClient = _StreamStubAi
try:
    r = client.post("/api/conversations", json={"title": "冒烟流式"})
    check("新建会话", r.status_code == 200, r.text)
    conv_id = r.json()["conversation"]["id"]

    events = []
    with client.stream("POST", "/api/extract/chat/stream", json={
        "message": "看看材料", "conversationId": conv_id, "sourceIds": []
    }) as resp:
        check("流式端点 200", resp.status_code == 200, str(resp.status_code))
        for line in resp.iter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:].strip()))
    types = [e.get("type") for e in events]
    check("事件以 conversation 开头", bool(events) and events[0].get("type") == "conversation", str(types))
    check("事件含 step", "step" in types, str(types))
    check("事件含 reply", "reply" in types, str(types))
    step = next(e for e in events if e.get("type") == "step")
    check("step 带思考", step.get("thought") == "先列一下材料", str(step))
    check("step 带耗时", isinstance(step.get("ms"), int) and step["ms"] >= 0, str(step))
    reply = next(e for e in events if e.get("type") == "reply")
    check("reply 带总耗时", isinstance(reply.get("ms_total"), int) and reply["ms_total"] >= 0, str(reply))

    r = client.get(f"/api/conversations/{conv_id}")
    check("会话记录可查", r.status_code == 200, r.text)
    msgs = r.json()["messages"]
    check("落了用户消息", any(m["role"] == "user" for m in msgs), str([m["role"] for m in msgs]))
    check("落了工具轨迹", any(m["kind"] == "step" for m in msgs), str([m["kind"] for m in msgs]))
    check("落了回复消息", any(m["role"] == "assistant" and m["kind"] == "text" for m in msgs), str(msgs))

    r = client.get("/api/conversations")
    check("会话出现在列表", any(c["id"] == conv_id for c in r.json()["conversations"]), r.text)

    r = client.delete(f"/api/conversations/{conv_id}")
    check("会话可删除", r.status_code == 200, r.text)
    r = client.get(f"/api/conversations/{conv_id}")
    check("删除后查不到", r.status_code == 404, r.text)
finally:
    _extract_router.AiClient = _original_ai


# 24. read_image 视觉识别工具 + confirm 暂停动作
from app.db import new_id  # noqa: E402
from app.lib.agent.loop import _final_action  # noqa: E402
from app.lib.agent.tools import execute_tool  # noqa: E402


class _VisionStub:
    """带 chat_vision 的假客户端：把图片交给云端视觉模型识别。"""
    def chat(self, messages, **kwargs):
        return '{"reply": "（不会走到这里）", "action": null}'
    def chat_vision(self, prompt, images):
        return f"识别到 {len(images)} 张图：1. 题目一 ...（此处不清）"


# 建一份图片型材料：图落盘 + meta.images 指向它
_vid = new_id()
(_upload_dir := UPLOAD_DIR / _vid).mkdir(parents=True, exist_ok=True)
(_upload_dir / "url-img-1.png").write_bytes(PNG_BYTES)
_vrel = (_upload_dir / "url-img-1.png").relative_to(DATA_DIR).as_posix()
_agent_conn.execute(
    """INSERT INTO sources (id, owner_id, type, name, storage_path, normalized_path, status, char_count, meta)
       VALUES (?, ?, 'image', ?, NULL, NULL, 'ready', 0, ?)""",
    (_vid, _smoke_uid, "图片材料", json.dumps({"images": [_vrel], "imageCount": 1}, ensure_ascii=False)),
)
_agent_conn.commit()

_vctx = AgentContext(conn=_agent_conn, user_id=_smoke_uid, client=_VisionStub())
_vres = execute_tool("read_image", {"id": _vid}, _vctx)
check("read_image 调用成功", _vres.ok, str(_vres.output))
check("read_image 返回识别文本", "识别到 1 张图" in str(_vres.output.get("recognized", "")), str(_vres.output))
check("read_image 轨迹带图数", "1 张图" in _vres.note, _vres.note)

# 没图的纯文字材料：read_image 应报错提示没有可识别图片
_vid2 = new_id()
_agent_conn.execute(
    "INSERT INTO sources (id, owner_id, type, name, storage_path, normalized_path, status, char_count, meta) "
    "VALUES (?, ?, 'text', ?, NULL, NULL, 'ready', 0, ?)",
    (_vid2, _smoke_uid, "纯文字", json.dumps({}, ensure_ascii=False)),
)
_agent_conn.commit()
_vres2 = execute_tool("read_image", {"id": _vid2}, _vctx)
check("无图时 read_image 提示无图", (not _vres2.ok) and "没有可识别的图片" in str(_vres2.output.get("error", "")), str(_vres2.output))

# confirm 动作：_final_action 透传
_conf = _final_action({"type": "confirm", "reason": "要加新工具", "plan": "先写抓取脚本"})
check("confirm 动作透传", bool(_conf) and _conf.get("type") == "confirm", str(_conf))
check("confirm 带 reason", _conf.get("reason") == "要加新工具", str(_conf))
check("confirm 带 plan", _conf.get("plan") == "先写抓取脚本", str(_conf))
check("未知动作不通过", _final_action({"type": "weird"}) is None, "")

# confirm 经流式循环收尾：agent 第一句就 confirm
class _ConfirmStubAi:
    @classmethod
    def from_conn(cls, conn):
        return ScriptedClient([
            json.dumps({"thought": "这个站点要写个工具才能解析", "reply": "说明一下，等你确认。", "action": {"type": "confirm", "reason": "需要新增可复用工具", "plan": "create_tool 写解析脚本"}}),
        ])

_original_ai2 = _extract_router.AiClient
_extract_router.AiClient = _ConfirmStubAi
try:
    _cr = client.post("/api/conversations", json={"title": "冒烟确认"})
    _conv_id = _cr.json()["conversation"]["id"]
    _cevents = []
    with client.stream("POST", "/api/extract/chat/stream", json={"message": "帮我处理这份", "conversationId": _conv_id, "sourceIds": []}) as _resp:
        for _line in _resp.iter_lines():
            if _line.startswith("data:"):
                _cevents.append(json.loads(_line[5:].strip()))
    _creply = next((e for e in _cevents if e.get("type") == "reply"), None)
    check("confirm 经流式收尾", _creply is not None, str([e.get("type") for e in _cevents]))
    check("reply 动作为 confirm", bool(_creply) and _creply.get("action", {}).get("type") == "confirm", str(_creply))
    check("confirm reason 透传", bool(_creply) and _creply.get("action", {}).get("reason") == "需要新增可复用工具", str(_creply))
finally:
    _extract_router.AiClient = _original_ai2

print()
if failures:
    print(f"共 {len(failures)} 项失败：{failures}")
    sys.exit(1)
print("导入侧冒烟测试全部通过")
