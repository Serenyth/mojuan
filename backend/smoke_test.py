"""AI-B 冒烟测试：注册 → 题库/题目 → 刷题判分 → 错题本 → 阅卷 → 考试模板 → 组卷交卷出分。"""

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


# 1. 注册登录（允许重复运行：用户已存在则直接登录）
r = client.post("/api/auth/register", json={
    "username": "smoke_b", "password": "pass12345", "displayName": "冒烟B"
})
check("注册用户", r.status_code in (200, 409), r.text)
r = client.post("/api/auth/login", json={"username": "smoke_b", "password": "pass12345"})
check("登录", r.status_code == 200, r.text)

# 2. 题库列表（seed 的 50 题）
r = client.get("/api/banks")
check("题库列表", r.status_code == 200 and len(r.json()["banks"]) >= 1, r.text)
bank_id = r.json()["banks"][0]["id"]

r = client.post("/api/banks", json={"name": "冒烟题库", "isShared": True})
check("创建题库", r.status_code == 200, r.text)
smoke_bank = r.json()["bank"]["id"]

# 3. 题目增删改查
r = client.post("/api/questions", json={
    "bankId": smoke_bank, "type": "single_choice", "content": "1+1=?",
    "options": [{"key": "A", "text": "1"}, {"key": "B", "text": "2"}, {"key": "C", "text": "3"}, {"key": "D", "text": "4"}],
    "answer": ["B"], "tags": ["数学"], "difficulty": 1,
})
check("创建单选", r.status_code == 200, r.text)
q_single = r.json()["question"]["id"]

r = client.post("/api/questions", json={
    "bankId": smoke_bank, "type": "multiple_choice", "content": "偶数有？",
    "options": [{"key": "A", "text": "2"}, {"key": "B", "text": "3"}, {"key": "C", "text": "4"}],
    "answer": ["A", "C"], "tags": ["数学"],
})
check("创建多选", r.status_code == 200, r.text)
q_multi = r.json()["question"]["id"]

r = client.post("/api/questions", json={
    "bankId": smoke_bank, "type": "true_false", "content": "水是湿的。",
    "answer": ["T"], "tags": ["常识"],
})
check("创建判断（自动补 T/F 选项）", r.status_code == 200, r.text)
q_tf = r.json()["question"]["id"]

r = client.post("/api/questions", json={
    "bankId": smoke_bank, "type": "fill_blank", "content": "北京是____的首都。",
    "answer": ["中国"], "acceptableAnswers": [["中国", "中华人民共和国"]], "tags": ["常识"],
})
check("创建填空", r.status_code == 200, r.text)
q_fill = r.json()["question"]["id"]

r = client.post("/api/questions", json={
    "bankId": smoke_bank, "type": "subjective", "content": "谈谈你对 AI 的看法。",
    "answer": ["有见地", "有结构"], "tags": ["综合"],
})
check("创建主观题", r.status_code == 200, r.text)
q_sub = r.json()["question"]["id"]

r = client.patch(f"/api/questions/{q_single}", json={"difficulty": 2})
check("编辑题目", r.status_code == 200, r.text)

# 4. 检索
r = client.get(f"/api/banks/{smoke_bank}/questions", params={"keyword": "偶数"})
check("关键词检索", r.status_code == 200 and r.json()["total"] == 1, r.text)
r = client.get(f"/api/banks/{smoke_bank}/questions", params={"type": "multiple_choice"})
check("题型筛选", r.status_code == 200 and r.json()["total"] == 1, r.text)
r = client.get(f"/api/banks/{smoke_bank}/questions", params={"tag": "数学"})
check("标签筛选", r.status_code == 200 and r.json()["total"] == 2, r.text)

# 5. 导出
r = client.get("/api/questions/export", params={"bank_id": smoke_bank, "format": "csv"})
check("导出 CSV", r.status_code == 200 and "content" in r.text, r.text)
r = client.get("/api/questions/export", params={"bank_id": smoke_bank, "format": "json"})
check("导出 JSON", r.status_code == 200 and len(r.json()) == 5, r.text)

# 6. 无限刷题会话（冒烟题库 5 题）
r = client.post("/api/practice/sessions", json={"mode": "infinite", "bankId": smoke_bank})
check("创建刷题会话", r.status_code == 200, r.text)
session = r.json()["session"]
sid = session["id"]
check("会话 5 题且无答案泄漏", session["total"] == 5 and "answer" not in r.json()["current"], r.text)

answers = [
    (q_single, "B", True),
    (q_multi, ["A", "C"], True),
    (q_tf, "T", True),
    (q_fill, "中华人民共和国", True),
]
# 逐题作答前 4 道：客观题全部答对，主观题提交待阅
for _ in range(4):
    cur = r.json()["current"]
    qid = cur["id"]
    expected = next((a for q, a, _ in answers if q == qid), None)
    if expected is not None:
        r = client.post(f"/api/practice/sessions/{sid}/answer", json={"questionId": qid, "answer": expected})
        check(f"判分正确 {cur['type']}", r.json()["outcome"]["correct"] is True, r.text)
    else:
        r = client.post(f"/api/practice/sessions/{sid}/answer", json={"questionId": qid, "answer": "我对 AI 充满期待。"})
        check("主观题作答（待阅）", r.json()["outcome"]["correct"] is None, r.text)

# 第 5 道：按题型决定答法
r = client.get(f"/api/practice/sessions/{sid}")
cur = r.json()["current"]
if cur:
    if cur["type"] == "subjective":
        r = client.post(f"/api/practice/sessions/{sid}/answer", json={"questionId": cur["id"], "answer": "补充作答"})
        check("主观题作答（待阅）", r.json()["outcome"]["correct"] is None, r.text)
    else:
        r = client.post(f"/api/practice/sessions/{sid}/answer", json={"questionId": cur["id"], "answer": "Z"})
        check("错答判分", r.json()["outcome"]["correct"] is False, r.text)

r = client.post(f"/api/practice/sessions/{sid}/finish")
check("结束会话", r.status_code == 200, r.text)

# 7. 错题本：另开按题型会话故意答错，确定性构造一道错题
r = client.post("/api/practice/sessions", json={"mode": "by_type", "bankId": smoke_bank, "filters": {"type": "single_choice"}})
check("按题型刷题会话", r.status_code == 200, r.text)
wrong_sid = r.json()["session"]["id"]
cur = r.json()["current"]
r = client.post(f"/api/practice/sessions/{wrong_sid}/answer", json={"questionId": cur["id"], "answer": "Z"})
check("错答进错题本", r.json()["outcome"]["correct"] is False, r.text)
r = client.get("/api/wrong-questions")
items = r.json()["items"]
check("错题本收录", len(items) >= 1, r.text)
if items:
    r = client.delete(f"/api/wrong-questions/{items[0]['id']}")
    check("删除错题", r.status_code == 200, r.text)

# 8. 待阅列表 + 阅卷
r = client.get("/api/review/pending")
pending = r.json()["items"]
check("待阅列表有主观题", len(pending) >= 1, r.text)
if pending:
    rec = pending[0]["record"]
    r = client.post(f"/api/review/{rec['id']}/grade", json={"score": 4, "comment": "结构清晰"})
    check("阅卷打分（4/10 < 60% → 错题本）", r.status_code == 200 and r.json()["correct"] is False, r.text)
    r = client.post(f"/api/review/{rec['id']}/grade", json={"score": 8})
    check("重复阅卷被拒", r.status_code == 409, r.text)

# 9. 考试模板 CRUD
r = client.post("/api/exam-templates", json={
    "name": "冒烟模板", "scopeBankId": smoke_bank,
    "typeDistribution": {"single_choice": 1, "multiple_choice": 1, "true_false": 1, "fill_blank": 1, "subjective": 1},
    "totalCount": 5, "durationMinutes": 30, "shuffle": True,
})
check("创建考试模板", r.status_code == 200, r.text)
tpl = r.json()["template"]["id"]
r = client.post("/api/exam-templates", json={
    "name": "坏模板", "typeDistribution": {"single_choice": 2}, "totalCount": 5,
})
check("分布与总量不一致被拒", r.status_code == 422, r.text)

# 10. 开考 → 交卷 → 出分
r = client.post("/api/exams/start", json={"templateId": tpl})
check("开考组卷", r.status_code == 200, r.text)
exam = r.json()["exam"]
eid = exam["id"]
questions = r.json()["questions"]
check("组卷 5 题且无答案泄漏", len(questions) == 5 and all("answer" not in q for q in questions), r.text)

payload_answers = []
for q in questions:
    if q["type"] == "subjective":
        ans = "我的长篇大论。"
    elif q["type"] == "fill_blank":
        ans = ["中国"]
    elif q["type"] in ("single_choice", "true_false"):
        ans = "A" if q["type"] == "single_choice" else "T"
    else:
        ans = [q["options"][0]["key"]]
    payload_answers.append({"questionId": q["id"], "answer": ans})
r = client.post(f"/api/exams/{eid}/submit", json={"answers": payload_answers})
check("交卷", r.status_code == 200, r.text)
body = r.json()
check("状态为 grading（含主观题）", body["exam"]["status"] == "grading", r.text)
check("客观题已出分", body["scores"]["objectiveScore"] >= 0 and body["scores"]["pendingSubjective"] == 1, r.text)

# 11. 阅卷后自动补齐总分
r = client.get(f"/api/exams/{eid}/result")
check("考试结果可查", r.status_code == 200, r.text)
pending = [x for x in r.json()["records"] if x["correct"] is None]
check("主观题待判", len(pending) == 1, r.text)
if pending:
    r = client.post(f"/api/review/{pending[0]['id']}/grade", json={"score": 10, "comment": "完美"})
    check("考试主观题阅卷", r.status_code == 200, r.text)
r = client.get(f"/api/exams/{eid}/result")
check("阅完状态 graded", r.json()["exam"]["status"] == "graded", r.text)
check("总分 = 客观 + 主观", r.json()["exam"]["scores"]["totalScore"] == r.json()["exam"]["scores"]["objectiveScore"] + 10, r.text)

# 12. 越权与异常
r = client.post("/api/practice/sessions", json={"mode": "unknown_mode"})
check("未知模式被拒", r.status_code == 422, r.text)
r = client.get("/api/practice/sessions/nonexistent")
check("不存在会话 404", r.status_code == 404, r.text)
r = client.get("/api/banks/nonexistent")
check("不存在题库 404", r.status_code == 404, r.text)

print()
if failures:
    print(f"共 {len(failures)} 项失败：{failures}")
    sys.exit(1)
print("全部冒烟测试通过")
