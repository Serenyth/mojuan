import sqlite3
import uuid
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "quiz.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "db" / "schema.sql"

UPLOAD_DIR = DATA_DIR / "uploads"
NORMALIZED_DIR = DATA_DIR / "normalized"
SCRIPTS_DIR = DATA_DIR / "scripts"

# schema.sql 用 CREATE TABLE IF NOT EXISTS，早期建的库不会自动长出新列。
# 这里按需补列，让老的 data/quiz.db 也能跟上契约演进。
# 新增列必须可空或带默认值，SQLite 的 ADD COLUMN 不允许 otherwise。
_MIGRATIONS: dict[str, dict[str, str]] = {
    "sources": {
        "owner_id": "TEXT REFERENCES users(id) ON DELETE CASCADE",
        "char_count": "INTEGER NOT NULL DEFAULT 0",
        "meta": "TEXT",
    },
    "extraction_jobs": {
        "owner_id": "TEXT REFERENCES users(id) ON DELETE CASCADE",
        "result": "TEXT",
    },
    "banks": {
        "kind": "TEXT",
    },
}


def new_id() -> str:
    return uuid.uuid4().hex


def _connect() -> sqlite3.Connection:
    # 每个请求一条独立连接，但 async 端点跑在事件循环线程、同步依赖跑在线程池，
    # 同一条连接会跨线程用。既然不共享，关掉同线程检查是安全的。
    conn = sqlite3.connect(DB_PATH, timeout=15, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    tables = {
        row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    for table, columns in _MIGRATIONS.items():
        if table not in tables:
            continue  # 表还不存在，交给 schema.sql 建新的
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        for column, ddl in columns.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def init_db() -> None:
    for directory in (DATA_DIR, UPLOAD_DIR, NORMALIZED_DIR, SCRIPTS_DIR):
        directory.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    # 必须先补列再跑 schema：旧库的表缺列时，schema.sql 里的
    # CREATE INDEX ... ON t(缺的列) 会直接报 no such column。
    _migrate(conn)
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf8"))
    conn.commit()
    conn.close()


def get_db():
    """每个请求一条连接，避免跨线程共享游标"""
    conn = _connect()
    try:
        yield conn
    finally:
        conn.close()
