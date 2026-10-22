CREATE TABLE IF NOT EXISTS users (
  id            TEXT PRIMARY KEY,
  username      TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  display_name  TEXT NOT NULL,
  is_admin      INTEGER NOT NULL DEFAULT 0,
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
  id         TEXT PRIMARY KEY,
  user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash TEXT NOT NULL UNIQUE,
  expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS banks (
  id          TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  platform    TEXT,
  description TEXT,
  owner_id    TEXT REFERENCES users(id) ON DELETE SET NULL,
  is_shared   INTEGER NOT NULL DEFAULT 1,
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_banks_owner ON banks(owner_id);

CREATE TABLE IF NOT EXISTS questions (
  id                 TEXT PRIMARY KEY,
  bank_id            TEXT NOT NULL REFERENCES banks(id) ON DELETE CASCADE,
  type               TEXT NOT NULL,
  content            TEXT NOT NULL,
  options            TEXT,
  answer             TEXT NOT NULL,
  acceptable_answers TEXT,
  explanation        TEXT,
  tags               TEXT,
  difficulty         INTEGER NOT NULL DEFAULT 3,
  source             TEXT,
  confidence         REAL,
  fingerprint        TEXT,
  created_at         TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_questions_bank ON questions(bank_id);
CREATE INDEX IF NOT EXISTS idx_questions_type ON questions(type);
CREATE INDEX IF NOT EXISTS idx_questions_fingerprint ON questions(fingerprint);

CREATE TABLE IF NOT EXISTS sources (
  id              TEXT PRIMARY KEY,
  owner_id        TEXT REFERENCES users(id) ON DELETE CASCADE,
  type            TEXT NOT NULL,
  name            TEXT NOT NULL,
  storage_path    TEXT,
  normalized_path TEXT,
  status          TEXT NOT NULL DEFAULT 'pending',
  error           TEXT,
  char_count      INTEGER NOT NULL DEFAULT 0,
  meta            TEXT,
  created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_sources_owner ON sources(owner_id);

CREATE TABLE IF NOT EXISTS extraction_jobs (
  id         TEXT PRIMARY KEY,
  owner_id   TEXT REFERENCES users(id) ON DELETE CASCADE,
  source_ids TEXT NOT NULL,
  mode       TEXT NOT NULL,
  status     TEXT NOT NULL DEFAULT 'pending',
  script_id  TEXT,
  stats      TEXT,
  result     TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS extraction_scripts (
  id         TEXT PRIMARY KEY,
  name       TEXT NOT NULL,
  platform   TEXT,
  code       TEXT NOT NULL,
  version    INTEGER NOT NULL DEFAULT 1,
  io_spec    TEXT,
  owner_id   TEXT REFERENCES users(id) ON DELETE SET NULL,
  is_shared  INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- agent 自己创建的工具：对话里 create_tool 落库，run_tool 复用。
-- 与 extraction_scripts 分工不同：那边是阶段四给同源页面反复用的确定性情
-- 工具（无网络沙盒），这边是 agent 的即时动手能力（本机执行、可用网络）。
CREATE TABLE IF NOT EXISTS agent_tools (
  id          TEXT PRIMARY KEY,
  owner_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name        TEXT NOT NULL,
  description TEXT,
  code        TEXT NOT NULL,
  created_at  TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(owner_id, name)
);
CREATE INDEX IF NOT EXISTS idx_agent_tools_owner ON agent_tools(owner_id);

-- 导入助手的会话记录：一轮对话一条，消息逐条落库（含工具轨迹与耗时），
-- 刷新页面、换设备都能接着聊。agent_messages 的 kind：text（对话）/
-- step（工具轨迹）/ system（系统提示，如提取结果摘要）。
CREATE TABLE IF NOT EXISTS agent_conversations (
  id         TEXT PRIMARY KEY,
  owner_id   TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title      TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_agent_conversations_owner ON agent_conversations(owner_id, updated_at);

CREATE TABLE IF NOT EXISTS agent_messages (
  id              TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL REFERENCES agent_conversations(id) ON DELETE CASCADE,
  role            TEXT NOT NULL,
  kind            TEXT NOT NULL DEFAULT 'text',
  text            TEXT NOT NULL,
  thought         TEXT,
  tool            TEXT,
  ok              INTEGER,
  ms              INTEGER,
  created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_agent_messages_conv ON agent_messages(conversation_id, id);

CREATE TABLE IF NOT EXISTS script_runs (
  id          TEXT PRIMARY KEY,
  script_id   TEXT REFERENCES extraction_scripts(id) ON DELETE CASCADE,
  job_id      TEXT,
  status      TEXT NOT NULL,
  log         TEXT,
  duration_ms INTEGER,
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS practice_sessions (
  id           TEXT PRIMARY KEY,
  user_id      TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  mode         TEXT NOT NULL,
  bank_id      TEXT,
  filters      TEXT,
  config       TEXT,
  question_ids TEXT,
  cursor       INTEGER NOT NULL DEFAULT 0,
  started_at   TEXT NOT NULL DEFAULT (datetime('now')),
  finished_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_practice_sessions_user ON practice_sessions(user_id);

CREATE TABLE IF NOT EXISTS practice_records (
  id          TEXT PRIMARY KEY,
  session_id  TEXT,
  exam_id     TEXT,
  user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  question_id TEXT NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
  user_answer TEXT,
  correct     INTEGER,
  score       REAL,
  max_score   REAL,
  comment     TEXT,
  judged_by   TEXT,
  judged_at   TEXT,
  time_spent  INTEGER,
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_records_user ON practice_records(user_id);
CREATE INDEX IF NOT EXISTS idx_records_session ON practice_records(session_id);

CREATE TABLE IF NOT EXISTS wrong_questions (
  id             TEXT PRIMARY KEY,
  user_id        TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  question_id    TEXT NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
  wrong_count    INTEGER NOT NULL DEFAULT 1,
  correct_streak INTEGER NOT NULL DEFAULT 0,
  mastered       INTEGER NOT NULL DEFAULT 0,
  last_wrong_at  TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(user_id, question_id)
);
CREATE INDEX IF NOT EXISTS idx_wrong_user ON wrong_questions(user_id);

CREATE TABLE IF NOT EXISTS exam_templates (
  id                TEXT PRIMARY KEY,
  name              TEXT NOT NULL,
  owner_id          TEXT REFERENCES users(id) ON DELETE SET NULL,
  is_shared         INTEGER NOT NULL DEFAULT 1,
  scope_bank_id     TEXT,
  scope_tags        TEXT,
  type_distribution TEXT NOT NULL,
  total_count       INTEGER NOT NULL,
  duration_minutes  INTEGER NOT NULL DEFAULT 60,
  shuffle           INTEGER NOT NULL DEFAULT 1,
  created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS exams (
  id               TEXT PRIMARY KEY,
  template_id      TEXT REFERENCES exam_templates(id) ON DELETE SET NULL,
  user_id          TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  question_ids     TEXT NOT NULL,
  started_at       TEXT NOT NULL DEFAULT (datetime('now')),
  submitted_at     TEXT,
  objective_score  REAL,
  subjective_score REAL,
  total_score      REAL,
  status           TEXT NOT NULL DEFAULT 'ongoing'
);
CREATE INDEX IF NOT EXISTS idx_exams_user ON exams(user_id);

CREATE TABLE IF NOT EXISTS settings (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
