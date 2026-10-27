"""阶段四脚本沙盒：无网络、限时 60 秒、内存看门狗、导入白名单。

用户的「提取脚本」是给同源页面反复跑的确定性工具，和 agent 的 run_python
不是一回事：run_python 是即时动手、刻意开放网络，这边必须离线、受限。

边界（本机无容器，尽力而为；用户是脚本作者，属自部署场景的既定取舍）：
- 网络：拦截 socket / ssl / urllib / http / requests / httpx 等网络库的导入，
  并把已加载的 socket.socket 换成直接抛错；环境变量清掉代理。
- 依赖白名单：标准库默认放行（第三方解析库要靠它做内部导入），第三方只放行
  白名单（bs4 / openpyxl / pypdf / python-docx / lxml / markdown 等）。
- 危险模块：subprocess / multiprocessing / ctypes 一律拦截。
- 文件：包装 open()，只允许读「授权材料路径」或在任务临时目录内读写。
- 时间：子进程 60 秒超时。
- 内存：Windows 上用 ctypes 轮询子进程 WorkingSetSize，超限直接杀。

脚本约定（在脚本里这样用）：

    import mojuan
    for src in mojuan.sources:          # [{id, name, type, text, path, meta}]
        ...
    mojuan.emit(questions)              # 题目 dict 列表（统一 Schema）

也可以把 JSON 数组 print 到 stdout，沙盒会尽力解析。
"""

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

SCRIPT_TIMEOUT = 60                 # 单次脚本执行秒数上限
STDOUT_CAP = 20_000
STDERR_CAP = 8_000
CODE_MAX_CHARS = 60_000             # 单段脚本长度上限
MEMORY_LIMIT_MB = 600               # 子进程工作集上限（超过即杀）
PER_SOURCE_TEXT_CAP = 200_000       # 单份材料喂给脚本的文本上限
TOTAL_TEXT_CAP = 600_000            # 全部材料文本预算

# 第三方白名单：只允许这些「解析类」库；网络库一律不在其中
ALLOWED_THIRD_PARTY = [
    "bs4", "openpyxl", "pypdf", "PyPDF2", "docx", "lxml", "markdown",
    "chardet", "charset_normalizer",
]

# 明确拦截的根模块：网络、进程、底层系统调用
BLOCKED_ROOTS = [
    "socket", "ssl", "urllib", "http", "httplib", "ftplib", "smtplib",
    "telnetlib", "xmlrpc", "asyncio", "subprocess", "multiprocessing",
    "ctypes", "requests", "httpx", "aiohttp", "websocket", "websockets",
    "urllib3", "webbrowser", "pty", "pipes",
]


# 子进程引导：装导入守卫 / 注入 mojuan / 执行用户脚本 / 结果写文件。
# 这段代码在独立进程里跑，导入守卫只作用在子进程，不影响服务端。
_BOOTSTRAP = r'''# -*- coding: utf-8 -*-
import json as _json
import os as _os
import sys as _sys
import builtins as _builtins
import types as _types
import io as _io
import contextlib as _contextlib
import traceback as _traceback

_code_file = _os.environ["MOJ_CODE_FILE"]
_sources_file = _os.environ["MOJ_SOURCES_FILE"]
_out_file = _os.environ["MOJ_OUT_FILE"]
_tmp_dir = _os.path.abspath(_os.environ.get("MOJ_TMP", _os.getcwd()))
_allowed_modules = set(_json.loads(_os.environ.get("MOJ_ALLOWED", "[]")))
_allowed_read = set(_os.environ.get("MOJ_READ", "").split(_os.pathsep)) - {""}
_blocked = set(_json.loads(_os.environ.get("MOJ_BLOCKED", "[]")))

with _io.open(_sources_file, "r", encoding="utf-8") as _fh:
    _sources = _json.load(_fh)
with _io.open(_code_file, "r", encoding="utf-8") as _fh:
    _code = _fh.read()

# —— 注入 mojuan 模块 ——
_moj = _types.ModuleType("mojuan")
_moj.sources = _sources
_emitted = []
def _emit(items):
    if isinstance(items, dict):
        _emitted.append(items)
    elif isinstance(items, (list, tuple)):
        _emitted.extend(items)
    else:
        raise TypeError("mojuan.emit 需要传入题目列表（list[dict]）或单个 dict")
_moj.emit = _emit
_moj.emitted = _emitted
_sys.modules["mojuan"] = _moj

# —— 导入守卫 ——
_stdlib = getattr(_sys, "stdlib_module_names", frozenset())
_orig_import = _builtins.__import__
def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    if level == 0 and name:
        root = name.split(".")[0]
        if root == "mojuan":
            return _orig_import(name, globals, locals, fromlist, level)
        if root in _blocked:
            raise ImportError("脚本沙盒内禁止导入「%s」（无网络 / 受限环境）" % root)
        if root not in _stdlib and root not in _allowed_modules:
            raise ImportError("「%s」不在脚本沙盒的依赖白名单内" % root)
    return _orig_import(name, globals, locals, fromlist, level)
_builtins.__import__ = _guarded_import

# —— open 守卫：只读授权材料 / 临时目录内可读写 ——
_orig_open = _builtins.open
def _guarded_open(file, mode="r", *args, **kwargs):
    try:
        path = _os.path.abspath(_os.fspath(file))
    except Exception:
        path = None
    if path is not None:
        if path in _allowed_read:
            return _orig_open(file, mode, *args, **kwargs)
        if path == _tmp_dir or path.startswith(_tmp_dir + _os.sep):
            return _orig_open(file, mode, *args, **kwargs)
    raise PermissionError("沙盒只允许读取授权材料，或在任务临时目录内读写：%s" % (file,))
_builtins.open = _guarded_open

# —— 执行用户脚本 ——
_buf = _io.StringIO()
_result = {"ok": False, "questions": [], "error": None, "log": ""}
try:
    _globals = {"__name__": "__main__", "__builtins__": _builtins, "mojuan": _moj}
    with _contextlib.redirect_stdout(_buf):
        exec(compile(_code, "<extraction-script>", "exec"), _globals)
    _questions = list(_emitted)
    if not _questions:
        # 兼容「print(JSON 数组)」的写法：从输出里找最后一个能解析成列表的 JSON
        _text = _buf.getvalue().strip()
        if _text:
            try:
                _parsed = _json.loads(_text)
                if isinstance(_parsed, list):
                    _questions = _parsed
            except Exception:
                pass
    _result = {"ok": True, "questions": _questions, "error": None, "log": _buf.getvalue()}
except BaseException as _exc:
    _result = {
        "ok": False,
        "questions": [],
        "error": "%s: %s" % (type(_exc).__name__, _exc),
        "log": (_buf.getvalue() + "\n" + _traceback.format_exc()),
    }

try:
    _log = (_result.get("log") or "")[-20000:]
    _result["log"] = _log
    with _io.open(_out_file, "w", encoding="utf-8") as _fh:
        _json.dump(_result, _fh, ensure_ascii=False)
    if _log:
        _sys.stdout.write(_log)
except Exception:
    pass
'''


def _mem_bytes(pid: int):
    """读取子进程工作集大小（Windows）。拿不到返回 None。"""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        PROCESS_QUERY_INFORMATION = 0x0400
        PROCESS_VM_READ = 0x0010
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
        if not handle:
            return None
        try:
            counters = PROCESS_MEMORY_COUNTERS()
            counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
            if ctypes.windll.psapi.GetProcessMemoryInfo(
                handle, ctypes.byref(counters), counters.cb
            ):
                return int(counters.WorkingSetSize)
            return None
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return None


def run_script(
    code: str,
    sources: list[dict],
    timeout: int = SCRIPT_TIMEOUT,
    read_paths: list[str] | None = None,
) -> dict:
    """在沙盒子进程里跑一段脚本，返回 {ok, questions, log, error, duration_ms}。

    sources: [{id, name, type, text, path, meta}]，脚本里通过 mojuan.sources 读取。
    read_paths: 额外允许脚本读取的绝对路径（材料的原始文件）。
    """
    code = code or ""
    if not code.strip():
        return {"ok": False, "questions": [], "log": "", "error": "脚本内容为空", "duration_ms": 0}
    if len(code) > CODE_MAX_CHARS:
        return {
            "ok": False, "questions": [], "log": "",
            "error": f"脚本超过 {CODE_MAX_CHARS} 字符", "duration_ms": 0,
        }

    allowed_read = [p for p in (read_paths or []) if p]
    for src in sources:
        path = src.get("path")
        if path:
            allowed_read.append(path)

    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="mojuan-script-") as tmp:
        tmp_path = Path(tmp)
        (tmp_path / "runner.py").write_text(_BOOTSTRAP, encoding="utf-8")
        (tmp_path / "code.py").write_text(code, encoding="utf-8")
        (tmp_path / "sources.json").write_text(
            json.dumps(sources, ensure_ascii=False), encoding="utf-8"
        )
        out_file = tmp_path / "result.json"

        env = {
            "PATH": os.environ.get("PATH", ""),
            "SystemRoot": os.environ.get("SystemRoot", ""),
            "TEMP": str(tmp_path),
            "TMP": str(tmp_path),
            "PYTHONIOENCODING": "utf-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "MOJ_CODE_FILE": str(tmp_path / "code.py"),
            "MOJ_SOURCES_FILE": str(tmp_path / "sources.json"),
            "MOJ_OUT_FILE": str(out_file),
            "MOJ_TMP": str(tmp_path),
            "MOJ_ALLOWED": json.dumps(ALLOWED_THIRD_PARTY),
            "MOJ_BLOCKED": json.dumps(BLOCKED_ROOTS),
            "MOJ_READ": os.pathsep.join(allowed_read),
        }
        # 清掉可能让子进程走代理上网的变量（无网络语义）
        for key in list(env):
            if key.lower() in ("http_proxy", "https_proxy", "all_proxy", "no_proxy"):
                env.pop(key, None)

        proc = subprocess.Popen(
            [sys.executable, str(tmp_path / "runner.py")],
            cwd=str(tmp_path),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        over_memory = {"hit": False}

        def _watch_memory():
            limit = MEMORY_LIMIT_MB * 1024 * 1024
            while proc.poll() is None:
                usage = _mem_bytes(proc.pid)
                if usage is not None and usage > limit:
                    over_memory["hit"] = True
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    return
                time.sleep(0.25)

        watcher = threading.Thread(target=_watch_memory, daemon=True)
        watcher.start()

        timed_out = False
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            proc.kill()
            stdout, stderr = proc.communicate()

        duration_ms = int((time.monotonic() - started) * 1000)

        if over_memory["hit"]:
            return {
                "ok": False, "questions": [], "duration_ms": duration_ms,
                "log": (stderr or "")[:STDERR_CAP],
                "error": f"脚本占用内存超过 {MEMORY_LIMIT_MB}MB，已终止",
            }
        if timed_out:
            return {
                "ok": False, "questions": [], "duration_ms": duration_ms,
                "log": (stdout or "")[:STDOUT_CAP] + (stderr or "")[:STDERR_CAP],
                "error": f"脚本超过 {timeout} 秒被终止",
            }

        result = None
        if out_file.is_file():
            try:
                result = json.loads(out_file.read_text(encoding="utf-8", errors="replace"))
            except (json.JSONDecodeError, OSError):
                result = None

        if result is None:
            tail = ((stdout or "")[-2000:] + (stderr or "")[-4000:]).strip()
            return {
                "ok": False, "questions": [], "duration_ms": duration_ms,
                "log": tail,
                "error": f"脚本执行失败（退出码 {proc.returncode}），未产生结果",
            }

        log = (result.get("log") or "")[:STDOUT_CAP]
        if stderr:
            log = (log + "\n--- stderr ---\n" + stderr)[:STDOUT_CAP]
        questions = result.get("questions")
        if not isinstance(questions, list):
            questions = []
        return {
            "ok": bool(result.get("ok")),
            "questions": questions,
            "log": log,
            "error": result.get("error"),
            "duration_ms": duration_ms,
        }


def build_source_payload(rows, data_dir) -> list[dict]:
    """把 sources 行整理成喂给脚本的结构（文本封顶 + 原始文件路径）。"""
    payload: list[dict] = []
    budget = TOTAL_TEXT_CAP
    for row in rows:
        text = ""
        if row["normalized_path"]:
            path = data_dir / row["normalized_path"]
            if path.is_file():
                text = path.read_text(encoding="utf-8", errors="replace")
        if text:
            take = min(len(text), PER_SOURCE_TEXT_CAP, max(budget, 0))
            text = text[:take]
            budget -= take
        meta = {}
        try:
            meta = json.loads(row["meta"]) if row["meta"] else {}
        except (json.JSONDecodeError, TypeError):
            meta = {}
        raw_path = None
        if row["storage_path"]:
            candidate = data_dir / row["storage_path"]
            if candidate.is_file():
                raw_path = str(candidate.resolve())
        payload.append({
            "id": row["id"],
            "name": row["name"],
            "type": row["type"],
            "text": text,
            "chars": len(text),
            "path": raw_path,
            "meta": meta,
        })
    return payload
