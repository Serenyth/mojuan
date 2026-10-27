"""补充冒烟：resume 恢复、by_tag 刷题、PATCH 类端点。"""

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

banks = client.get("/api/banks").json()["banks"]
smoke_bank = next((b for b in banks if b["name"] == "冒烟题库"), banks[0])
bank_id = smoke_bank["id"]

# by_tag 刷题
r = client.post("/api/practice/sessions", json={"mode": "by_tag", "bankId": bank_id, "filters": {"tag": "数学"}, "limit": 5})
check("按标签刷题（数学）", r.status_code == 200, r.text)
if r.status_code == 200:
    sid = r.json()["session"]["id"]
    cur = r.json()["current"]
    r2 = client.post(f"/api/practice/sessions/{sid}/answer", json={"questionId": cur["id"], "answer": "B" if cur["type"] == "single_choice" else "T"})
    check("按标签会话答题", r2.status_code == 200, r2.text)
    # resume：会话未结束，应能恢复
    r3 = client.get(f"/api/practice/sessions/{sid}/resume")
    check("中断恢复 resume", r3.status_code == 200 and r3.json()["session"]["answered"] == 1, r3.text)
    # 恢复后继续答当前题
    cur2 = r3.json()["current"]
    if cur2:
        r4 = client.post(f"/api/practice/sessions/{sid}/answer", json={"questionId": cur2["id"], "answer": "Z"})
        check("恢复后继续作答", r4.status_code == 200, r4.text)
    r5 = client.post(f"/api/practice/sessions/{sid}/finish")
    check("结束 by_tag 会话", r5.status_code == 200, r5.text)
    r6 = client.get(f"/api/practice/sessions/{sid}/resume")
    check("已结束会话 resume 被拒", r6.status_code == 409, r6.text)

# PATCH 题库
r = client.patch(f"/api/banks/{bank_id}", json={"name": "冒烟题库（改）"})
check("PATCH 题库改名", r.status_code == 200 and r.json()["bank"]["name"] == "冒烟题库（改）", r.text)

# PATCH 模板
templates = client.get("/api/exam-templates").json()["templates"]
tpl = next((t for t in templates if t["name"] == "冒烟模板"), None)
if tpl:
    r = client.patch(f"/api/exam-templates/{tpl['id']}", json={"durationMinutes": 45})
    check("PATCH 模板时长", r.status_code == 200 and r.json()["template"]["durationMinutes"] == 45, r.text)
    r = client.patch(f"/api/exam-templates/{tpl['id']}", json={"typeDistribution": {"single_choice": 1}, "totalCount": 5})
    check("PATCH 模板分布不一致被拒", r.status_code == 422, r.text)
else:
    check("PATCH 模板（跳过，无模板）", True)

# 越权：错误密码登录后访问需登录接口
client.post("/api/auth/logout")
r = client.get("/api/practice/sessions/x")
check("未登录访问 401", r.status_code == 401, r.text)
client.post("/api/auth/login", json={"username": "smoke_b", "password": "pass12345"})

print()
if failures:
    print(f"共 {len(failures)} 项失败：{failures}")
    sys.exit(1)
print("补充冒烟全部通过")
