"""翻阅式答题冒烟：会话带全量题目、乱序作答、光标前进到下一道、判分反馈带答案、顺序刷题、考试答案开关。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)
failures = []


def check(name, condition, extra=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f"  {extra}" if extra and not condition else ""))
    if not condition:
        failures.append(name)


r = client.post("/api/auth/login", json={"username": "smoke_b", "password": "pass12345"})
check("登录", r.status_code == 200, r.text)

# 自建题库与四道题，保证顺序确定
r = client.post("/api/banks", json={"name": "翻阅题库", "isShared": True})
check("创建题库", r.status_code == 200, r.text)
feed_bank = r.json()["bank"]["id"]

specs = [
    {"type": "single_choice", "content": "翻阅单选：1+1=？",
     "options": [{"key": "A", "text": "1"}, {"key": "B", "text": "2"}, {"key": "C", "text": "3"}, {"key": "D", "text": "4"}],
     "answer": ["B"]},
    {"type": "true_false", "content": "翻阅判断：太阳从西边升起。",
     "options": [{"key": "T", "text": "正确"}, {"key": "F", "text": "错误"}], "answer": ["F"]},
    {"type": "fill_blank", "content": "翻阅填空：中国首都是____。", "answer": ["北京"]},
    {"type": "subjective", "content": "翻阅主观：谈谈你对翻页刷题的看法。", "answer": ["流畅", "聚焦"]},
]
question_ids = []
for spec in specs:
    payload = {"bankId": feed_bank, "tags": ["翻阅"], "difficulty": 3, **spec}
    r = client.post("/api/questions", json=payload)
    check(f"创建{spec['type']}", r.status_code == 200, r.text)
    if r.status_code == 200:
        question_ids.append(r.json()["question"]["id"])

# 1. 创建会话：一次拿到全量题目
r = client.post("/api/practice/sessions", json={"scope": "all", "order": "shuffle", "bankId": feed_bank, "limit": 5})
check("创建会话", r.status_code == 200, r.text)
body = r.json()
sid = body["session"]["id"]
questions = body.get("questions")
check("会话带全量题目", isinstance(questions, list) and len(questions) == body["session"]["total"] == 4, r.text)
check("全量题目不泄漏答案", bool(questions) and all("answer" not in q for q in questions), r.text)
check("会话初始无记录", body.get("records") == [], r.text)
check("会话带顺序字段", body["session"]["order"] == "shuffle", r.text)

by_id = {q["id"]: q for q in questions}

# 2. 乱序作答：先答填空题（随机模式会打乱顺序，按题型定位而非下标）
fill = next(q for q in questions if q["type"] == "fill_blank")
subjective = next(q for q in questions if q["type"] == "subjective")
r = client.post(f"/api/practice/sessions/{sid}/answer", json={"questionId": fill["id"], "answer": ["北京"]})
check("乱序作答（先答填空题）", r.status_code == 200 and r.json()["outcome"]["correct"] is True, r.text)
# 光标应前进到「顺序上的下一道」：答完第 i 题落在第 i+1 题，不回头补空
fill_index = questions.index(fill)
if fill_index + 1 < len(questions):
    check("光标前进到下一道", r.json()["current"]["id"] == questions[fill_index + 1]["id"], r.text)
else:
    check("光标在末题后越界", r.json()["current"] is None, r.text)
check("判分反馈带正确答案", r.json()["outcome"]["answer"] == ["北京"], r.text)
check("作答后带记录", len(r.json()["records"]) == 1 and r.json()["records"][0]["questionId"] == fill["id"], r.text)
check("记录带正确答案", r.json()["records"][0]["answer"] == ["北京"], r.text)

r = client.post(f"/api/practice/sessions/{sid}/answer", json={"questionId": fill["id"], "answer": ["北京"]})
check("重复作答被拒", r.status_code == 409, r.text)

r = client.post(f"/api/practice/sessions/{sid}/answer", json={"questionId": "no-such-question", "answer": "Z"})
check("会话外题目 404", r.status_code == 404, r.text)

# 3. 主观题提交后待阅，finish 汇总只计已答
r = client.post(f"/api/practice/sessions/{sid}/answer",
                json={"questionId": subjective["id"], "answer": "我觉得翻页更流畅"})
check("主观题待阅", r.status_code == 200 and r.json()["outcome"]["correct"] is None, r.text)

r = client.post(f"/api/practice/sessions/{sid}/finish")
check("结束会话", r.status_code == 200, r.text)
result = r.json()
check("结算汇总只计已答", result["summary"]["answered"] == 2 and result["summary"]["pending"] == 1, r.text)
check("结算逐题记录", len(result["records"]) == 2, r.text)
check("结算题目带答案", len(result["questions"]) == 4 and all("answer" in q for q in result["questions"]), r.text)
check("结算题目集合与入库一致", {q["id"] for q in result["questions"]} == set(question_ids), r.text)

r = client.post(f"/api/practice/sessions/{sid}/answer", json={"questionId": questions[0]["id"], "answer": "B"})
check("已结束会话拒答", r.status_code == 409, r.text)

# 3.5 顺序刷题：按入库正序出题；旧 mode 入口仍兼容
r = client.post("/api/practice/sessions", json={"scope": "all", "order": "sequential", "bankId": feed_bank, "limit": 10})
check("顺序会话创建", r.status_code == 200, r.text)
if r.status_code == 200:
    check("顺序会话按入库正序", [q["id"] for q in r.json()["questions"]] == question_ids, r.text)
    check("顺序字段透传", r.json()["session"]["order"] == "sequential", r.text)
    client.post(f"/api/practice/sessions/{r.json()['session']['id']}/finish")

r = client.post("/api/practice/sessions", json={"mode": "infinite", "bankId": feed_bank, "limit": 3})
check("旧 mode 入口兼容", r.status_code == 200 and r.json()["session"]["mode"] == "infinite", r.text)
if r.status_code == 200:
    client.post(f"/api/practice/sessions/{r.json()['session']['id']}/finish")

r = client.post("/api/practice/sessions", json={"scope": "nope"})
check("未知范围被拒", r.status_code == 422, r.text)
r = client.post("/api/practice/sessions", json={"order": "nope"})
check("未知顺序被拒", r.status_code == 422, r.text)

# 4. 考试：进行中不发答案，交卷后才发
r = client.post("/api/exam-templates", json={
    "name": "翻阅模板",
    "scopeBankId": feed_bank,
    "typeDistribution": {"single_choice": 1, "true_false": 1, "fill_blank": 1, "subjective": 1},
    "totalCount": 4,
    "durationMinutes": 30,
    "isShared": True,
})
check("创建模板", r.status_code == 200, r.text)
template_id = r.json()["template"]["id"]

r = client.post("/api/exams/start", json={"templateId": template_id})
check("开考", r.status_code == 200, r.text)
exam_id = r.json()["exam"]["id"]
check("开考不发答案", all("answer" not in q for q in r.json()["questions"]), r.text)

r = client.get(f"/api/exams/{exam_id}/result", params={"include_answer": True})
check("进行中拒给答案", r.status_code == 409, r.text)
r = client.get(f"/api/exams/{exam_id}/result")
check("进行中快照无答案", r.status_code == 200 and all("answer" not in q for q in r.json()["questions"]), r.text)

r = client.post(f"/api/exams/{exam_id}/submit", json={"answers": []})
check("交卷", r.status_code == 200, r.text)
r = client.get(f"/api/exams/{exam_id}/result", params={"include_answer": True})
check("交卷后给答案", r.status_code == 200 and all("answer" in q for q in r.json()["questions"]), r.text)

# 清理：删模板与题库，避免反复运行堆积
client.delete(f"/api/exam-templates/{template_id}")
client.delete(f"/api/banks/{feed_bank}")

print()
if failures:
    print(f"共 {len(failures)} 项失败：{failures}")
    sys.exit(1)
print("翻阅式冒烟全部通过")
