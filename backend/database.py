"""
database.py — SQLite 初始化、迁移、get_db
"""
import sqlite3
import os
import logging
from contextlib import contextmanager
from datetime import datetime

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./data/yyanji.db")
# 解析路径
DB_PATH = DATABASE_URL.replace("sqlite:////", "/").replace("sqlite:///", "")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def get_db():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


DDL = """
-- 用户
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phone TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    nickname TEXT NOT NULL,
    birth_year INTEGER NOT NULL,
    birth_month INTEGER NOT NULL,
    birth_day INTEGER,
    birth_hour TEXT,
    gender TEXT,
    self_desc TEXT,
    personality_tags TEXT DEFAULT '[]',
    is_disabled INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    last_active_at TEXT
);

-- 对话（每天一条）
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    title TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id),
    UNIQUE(user_id, date)
);

-- 消息
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    audio_path TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(conversation_id) REFERENCES conversations(id),
    FOREIGN KEY(user_id) REFERENCES users(id)
);

-- 日摘要
CREATE TABLE IF NOT EXISTS daily_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    content TEXT NOT NULL,
    emotion_tags TEXT DEFAULT '[]',
    topic_tags TEXT DEFAULT '[]',
    emotion_score REAL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id),
    UNIQUE(user_id, date)
);

-- 周摘要
CREATE TABLE IF NOT EXISTS weekly_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    year INTEGER NOT NULL,
    week INTEGER NOT NULL,
    content TEXT NOT NULL,
    theme_tags TEXT DEFAULT '[]',
    created_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id),
    UNIQUE(user_id, year, week)
);

-- 月摘要
CREATE TABLE IF NOT EXISTS monthly_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    year INTEGER NOT NULL,
    month INTEGER NOT NULL,
    content TEXT NOT NULL,
    milestone_tags TEXT DEFAULT '[]',
    created_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id),
    UNIQUE(user_id, year, month)
);

-- 年度回顾
CREATE TABLE IF NOT EXISTS yearly_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    year INTEGER NOT NULL,
    content TEXT NOT NULL,
    theme_words TEXT DEFAULT '[]',
    created_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id),
    UNIQUE(user_id, year)
);

-- 用户画像（滚动更新）
CREATE TABLE IF NOT EXISTS user_portraits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    content TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id)
);

-- 订阅
CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL UNIQUE,
    plan TEXT NOT NULL DEFAULT 'free',
    expire_at TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id)
);

-- 用量配额
CREATE TABLE IF NOT EXISTS usage_quotas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    year_month TEXT NOT NULL,
    chat_count INTEGER DEFAULT 0,
    reset_at TEXT,
    FOREIGN KEY(user_id) REFERENCES users(id),
    UNIQUE(user_id, year_month)
);

-- 使用码
CREATE TABLE IF NOT EXISTS invite_codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    duration_days INTEGER NOT NULL DEFAULT 30,
    batch_tag TEXT,
    used_by INTEGER,
    used_at TEXT,
    created_at TEXT NOT NULL,
    expires_at TEXT,
    FOREIGN KEY(used_by) REFERENCES users(id)
);

-- LLM 配置
CREATE TABLE IF NOT EXISTS llm_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    use_for TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT 'openai_compat',
    model_name TEXT NOT NULL,
    api_key TEXT NOT NULL,
    base_url TEXT,
    is_active INTEGER DEFAULT 1,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- STT 配置
CREATE TABLE IF NOT EXISTS stt_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL DEFAULT 'faster-whisper',
    model_name TEXT NOT NULL DEFAULT 'small',
    api_key TEXT,
    base_url TEXT,
    is_active INTEGER DEFAULT 1,
    notes TEXT,
    created_at TEXT NOT NULL
);

-- 管理员
CREATE TABLE IF NOT EXISTS admin_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- LLM 调用日志
CREATE TABLE IF NOT EXISTS llm_call_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    use_for TEXT,
    model_name TEXT,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);

-- STT 调用日志
CREATE TABLE IF NOT EXISTS stt_call_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    duration_seconds REAL DEFAULT 0,
    provider TEXT,
    created_at TEXT NOT NULL
);

-- FTS 虚拟表（日/周摘要全文检索）
CREATE VIRTUAL TABLE IF NOT EXISTS summaries_fts USING fts5(
    user_id UNINDEXED,
    summary_type,
    ref_id UNINDEXED,
    date_label,
    content,
    tags
);
"""


def init_db():
    """初始化所有表，幂等执行"""
    os.makedirs(os.path.dirname(DB_PATH) if os.path.dirname(DB_PATH) else ".", exist_ok=True)
    conn = get_connection()
    try:
        cursor = conn.cursor()
        for stmt in DDL.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                cursor.execute(stmt)
        # 迁移：新增列
        _migrate(cursor)
        conn.commit()
        _seed_data(conn)
        logger.info(f"Database initialized: {DB_PATH}")
    finally:
        conn.close()

def _migrate(cursor):
    """幂等迁移，给已有表补列"""
    migrations = [
        ("users", "birth_day", "ALTER TABLE users ADD COLUMN birth_day INTEGER"),
    ]
    for table, col, sql in migrations:
        try:
            cursor.execute(sql)
            logger.info(f"Migration: added {table}.{col}")
        except Exception:
            pass  # 列已存在，忽略


def _seed_data(conn: sqlite3.Connection):
    """插入初始数据（幂等）"""
    from passlib.context import CryptContext
    import json

    pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
    now = datetime.utcnow().isoformat()

    # Admin 账号
    cur = conn.cursor()
    cur.execute("SELECT id FROM admin_users WHERE username='admin'")
    if not cur.fetchone():
        cur.execute(
            "INSERT INTO admin_users (username, password_hash, created_at) VALUES (?,?,?)",
            ("admin", pwd_ctx.hash("admin2026"), now),
        )
        logger.info("Admin user created: admin / admin2026")

    # LLM 配置
    api_key = "e0ecd249-6fde-4663-bb00-480d8e813628"
    base_url = "https://ark.cn-beijing.volces.com/api/v3"
    model = "doubao-seed-2-0-pro-260215"
    for use_for in ("chat", "summary", "portrait"):
        cur.execute("SELECT id FROM llm_configs WHERE use_for=? AND is_active=1", (use_for,))
        if not cur.fetchone():
            cur.execute(
                """INSERT INTO llm_configs
                   (use_for, provider, model_name, api_key, base_url, is_active, notes, created_at, updated_at)
                   VALUES (?,?,?,?,?,1,?,?,?)""",
                (use_for, "openai_compat", model, api_key, base_url, f"默认{use_for}配置", now, now),
            )
    logger.info("LLM configs seeded")

    # STT 配置
    cur.execute("SELECT id FROM stt_configs WHERE provider='faster-whisper' AND is_active=1")
    if not cur.fetchone():
        cur.execute(
            """INSERT INTO stt_configs (provider, model_name, is_active, notes, created_at)
               VALUES (?,?,1,?,?)""",
            ("faster-whisper", "small", "本地 CPU STT", now),
        )
    conn.commit()
