"""阶段四冒烟：提取脚本 CRUD / 无网络沙盒 / 运行脚本抽题 / 可编辑系统提示词。

走 TestClient 打真实端点，另用 run_script 单元验证沙盒的拦截能力。
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi.testclient import TestClient  # noqa: E402

from app.db import DATA_DIR, _connect  # noqa: E402
from app.lib.extract.sandbox import build_source_payload, run_script  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
failures = []


def check(name, condition, extra=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f"  {extra}" if extra and not condition else ""))
    if not condition:
        failures.append(name)


SCRIPT_CODE = '''import mojuan

questions = []
for src in mojuan.sources:
    for line in src["text"].splitlines():
        if "|" not in line:
            continue
        stem, answer = line.split("|", 1)
        if not stem.strip():
            continue
        questions.append({
            "type": "true_false",
            "content": stem.strip(),
            "answer": ["T"] if answer.strip() in ("对", "T", "true") else ["F"],
            "confidence": 0.9,
            "difficulty": 2,
        })
mojuan.emit(questions)
'''

NET_CODE = "import socket\n"
LOOP_CODE = "while True: pass"

# ---------------------------------------------------------------- 登录
r = client.post("/api/auth/register", json={
    "username": "smoke_script", "password": "pass12345", "displayName": "脚本冒烟"
})
check("脚本用户注册", r.status_code in (200, 409), r.text)
r = client.post("/api/auth/login", json={"username": "smoke_script", "password": "pass12345"})
check("脚本用户登录", r.status_code == 200, r.text)

# ---------------------------------------------------------------- 材料
r = client.post("/api/sources", data={"text": "天空是蓝色的|对\n水的沸点是50度|错\n"})
check("建文本材料", r.status_code == 200, r.text)
source_id = r.json()["source"]["id"]

# ---------------------------------------------------------------- 脚本 CRUD
r = client.post("/api/scripts", json={
    "name": "冒烟提取脚本", "platform": "本地", "code": SCRIPT_CODE,
})
check("创建脚本", r.status_code == 200, r.text)
script = r.json()["script"]
script_id = script["id"]
check("脚本版本为 1", script["version"] == 1, r.text)
check("脚本可编辑", script["canEdit"] is True, r.text)

r = client.get("/api/scripts")
check("脚本列表包含新建", any(s["id"] == script_id for s in r.json()["scripts"]), r.text)

r = client.patch(f"/api/scripts/{script_id}", json={"code": SCRIPT_CODE + "\n# v2\n"})
check("编辑脚本版本递增", r.status_code == 200 and r.json()["script"]["version"] == 2, r.text)

# ---------------------------------------------------------------- 运行脚本抽题
r = client.post("/api/extract/script", json={"scriptId": script_id, "sourceIds": [source_id]})
check("运行脚本 200", r.status_code == 200, r.text)
outcome = r.json()
check("运行成功", outcome.get("ok") is True, r.text)
check("抽出 2 道题", len(outcome.get("questions") or []) == 2, r.text)
check("job 模式为 script", (outcome.get("job") or {}).get("mode") == "script", r.text)
job_id = (outcome.get("job") or {}).get("id")

r = client.get(f"/api/extract/jobs/{job_id}")
check("按 job 取回候选题", r.status_code == 200 and len(r.json()["questions"]) == 2, r.text)

# script_runs 落了一条 ok 记录
conn = _connect()
run_row = conn.execute(
    "SELECT status, duration_ms FROM script_runs WHERE script_id = ? ORDER BY rowid DESC LIMIT 1",
    (script_id,),
).fetchone()
check("script_runs 记录 ok", run_row is not None and run_row["status"] == "ok", str(dict(run_row) if run_row else None))

# ---------------------------------------------------------------- 沙盒拦截
bad = client.post("/api/scripts", json={"name": "坏脚本", "code": NET_CODE})
check("创建坏脚本", bad.status_code == 200, bad.text)
bad_id = bad.json()["script"]["id"]
r = client.post("/api/extract/script", json={"scriptId": bad_id, "sourceIds": [source_id]})
check("网络脚本被拦", r.status_code == 200 and r.json().get("ok") is False, r.text)
check("拦截原因含禁止导入", "禁止导入" in (r.json().get("error") or ""), r.text)

src_rows = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchall()
payload = build_source_payload(src_rows, DATA_DIR)
timeout_out = run_script(LOOP_CODE, payload, timeout=1)
check("死循环超时被终止", timeout_out["ok"] is False and "被终止" in (timeout_out.get("error") or ""), str(timeout_out))

# 材料路径授权：读未授权文件应被拒
escape = run_script(
    "open(r'C:/Windows/win.ini').read()", payload,
)
check("未授权文件读取被拒", escape["ok"] is False and "PermissionError" in (escape.get("error") or ""), str(escape))

# ---------------------------------------------------------------- 可编辑系统提示词
r = client.post("/api/auth/login", json={"username": "admin", "password": "mojuan-dev"})
check("管理员登录", r.status_code == 200, r.text)

r = client.get("/api/settings")
check("设置含提示词字段", "agent_system_prompt" in r.json()["settings"], r.text)
base = r.json()["settings"]
default_text = base["agent_system_prompt_default"]
check("默认即内置", base["agent_system_prompt_is_default"] == "true", r.text)

r = client.put("/api/settings", json={"agent_system_prompt": "自定义的系统提示词 v1"})
check("保存自定义提示词", r.status_code == 200, r.text)
check("PUT 响应带生效提示词", r.json()["settings"].get("agent_system_prompt") == "自定义的系统提示词 v1", r.text)
check("PUT 响应带内置默认", bool(r.json()["settings"].get("agent_system_prompt_default")), r.text)
r = client.get("/api/settings")
check("生效值为自定义", r.json()["settings"]["agent_system_prompt"] == "自定义的系统提示词 v1", r.text)
check("标记为非默认", r.json()["settings"]["agent_system_prompt_is_default"] == "false", r.text)

# 直接读库确认 loop 的 effective 拿到自定义
from app.lib.agent.loop import _effective_prompt  # noqa: E402

check("loop 用自定义提示词", _effective_prompt(conn) == "自定义的系统提示词 v1")

r = client.put("/api/settings", json={"agent_system_prompt": default_text})
check("恢复默认", r.status_code == 200, r.text)
r = client.get("/api/settings")
check("恢复后即内置", r.json()["settings"]["agent_system_prompt_is_default"] == "true", r.text)
check("恢复后等于默认文本", r.json()["settings"]["agent_system_prompt"] == default_text, r.text)

# 非管理员不能改（同一 client 重新登录即换 cookie）
r = client.post("/api/auth/login", json={"username": "smoke_script", "password": "pass12345"})
r = client.put("/api/settings", json={"agent_system_prompt": "普通用户想改"})
check("普通用户改提示词被拒 403", r.status_code == 403, r.text)

conn.close()

print()
if failures:
    print(f"FAILED {len(failures)}: {failures}")
    sys.exit(1)
print("ALL PASS")
