"""
Database layer for WeaveFlow AI SaaS Platform.
Supports:
- Multi-assistant tenant isolation
- Knowledge sources, chunks, embeddings
- Leads with AI Call-Prep dossiers
- Full visitor chat transcripts & inbox
- Unanswered questions / Knowledge Gaps queue
- Subscription plans & usage tracking (AnswerWeave flat-fee tier model)
"""

import sqlite3
import json
import os
import re
import shutil
import time
import uuid
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

# Automatically load environment variables from .env.local or .env if present
def _load_env_files():
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for fname in [".env.local", ".env"]:
        fpath = os.path.join(root_dir, fname)
        if os.path.exists(fpath):
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            k = k.strip()
                            v = v.strip().strip('"').strip("'")
                            if k not in os.environ and v:
                                os.environ[k] = v
            except Exception:
                pass

_load_env_files()

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False

try:
    import pg8000.dbapi
    HAS_PG8000 = True
except ImportError:
    HAS_PG8000 = False

_pg_url = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
USE_POSTGRES = bool(_pg_url and (HAS_PSYCOPG2 or HAS_PG8000))

_is_serverless = bool(os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))
_repo_db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "weaveflow.db")

if not USE_POSTGRES:
    if _is_serverless:
        DB_PATH = os.environ.get("DB_PATH", "/tmp/weaveflow.db")
        if not os.path.exists(DB_PATH) and os.path.exists(_repo_db_path):
            try:
                shutil.copy2(_repo_db_path, DB_PATH)
            except Exception:
                pass
    else:
        DB_PATH = os.environ.get("DB_PATH", _repo_db_path)
else:
    DB_PATH = _repo_db_path

SUBSCRIPTION_PLANS = {
    "free": {
        "name": "Free Tier",
        "price": 0,
        "monthly_messages": 100,
        "page_limit": 1000,
        "assistants_limit": 1,
        "features": ["100 messages/mo", "1,000 pages", "1 assistant", "Standard grounding", "Community support"]
    },
    "starter": {
        "name": "Starter Plan",
        "price": 29,
        "monthly_messages": 2000,
        "page_limit": 5000,
        "assistants_limit": 1,
        "features": ["2,000 messages/mo", "5,000 pages", "1 assistant", "Voice question input", "Lead Call-Prep briefs", "Email alerts"]
    },
    "pro": {
        "name": "Pro Plan",
        "price": 49,
        "monthly_messages": 5000,
        "page_limit": 8000,
        "assistants_limit": 2,
        "features": ["5,000 messages/mo", "8,000 pages", "2 assistants", "Custom branding", "Lead webhooks", "Priority support"]
    },
    "growth": {
        "name": "Growth Plan",
        "price": 89,
        "monthly_messages": 10000,
        "page_limit": 10000,
        "assistants_limit": 3,
        "features": ["10,000 messages/mo", "10,000 pages", "3 assistants", "Unlimited domains", "Zapier integration"]
    },
    "agency": {
        "name": "Agency Plan",
        "price": 249,
        "monthly_messages": 100000,
        "page_limit": 100000,
        "assistants_limit": 50,
        "features": ["100,000 messages/mo", "100,000 pages", "50 assistants", "White-labeling", "Dedicated account manager"]
    }
}

class RowDict(dict):
    """Dictionary subclass supporting both key access ('col') and index access (row[0]) like sqlite3.Row."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._values = list(self.values())

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)

class PostgresCursorWrapper:
    def __init__(self, raw_cursor):
        self._cur = raw_cursor
        self._lastrowid = None

    def execute(self, sql, params=None):
        clean_sql = sql
        if "?" in clean_sql:
            clean_sql = clean_sql.replace("%", "%%").replace("?", "%s")

        if re.search(r"INSERT\s+OR\s+IGNORE\s+INTO", clean_sql, re.I):
            clean_sql = re.sub(r"INSERT\s+OR\s+IGNORE\s+INTO", "INSERT INTO", clean_sql, flags=re.I)
            clean_sql = clean_sql.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING;"
        
        if re.search(r"INSERT\s+OR\s+REPLACE\s+INTO\s+settings", clean_sql, re.I):
            clean_sql = re.sub(
                r"INSERT\s+OR\s+REPLACE\s+INTO\s+settings\s*\(([^)]+)\)\s*VALUES\s*\(([^)]+)\)", 
                r"INSERT INTO settings (\1) VALUES (\2) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", 
                clean_sql, 
                flags=re.I
            )

        is_insert = clean_sql.strip().upper().startswith("INSERT INTO")
        has_returning = "RETURNING" in clean_sql.upper()
        if is_insert and not has_returning and "ON CONFLICT DO NOTHING" not in clean_sql.upper():
            lower = clean_sql.lower()
            if any(t in lower for t in ["into leads", "into sources", "into chunks", "into unanswered_questions", "into messages"]):
                clean_sql = clean_sql.rstrip().rstrip(";") + " RETURNING id;"
                has_returning = True

        if params is not None:
            self._cur.execute(clean_sql, params)
        else:
            self._cur.execute(clean_sql)

        if is_insert and has_returning:
            try:
                row = self._cur.fetchone()
                if row:
                    self._lastrowid = row["id"] if isinstance(row, dict) else row[0]
            except Exception:
                pass
        return self

    @property
    def lastrowid(self):
        return self._lastrowid

    def fetchone(self):
        row = self._cur.fetchone()
        if row is None:
            return None
        if isinstance(row, dict):
            return RowDict(row)
        if hasattr(self._cur, "description") and self._cur.description:
            col_names = [d[0] for d in self._cur.description]
            return RowDict(zip(col_names, row))
        return RowDict(row)

    def fetchall(self):
        rows = self._cur.fetchall()
        if not rows:
            return []
        if isinstance(rows[0], dict):
            return [RowDict(r) for r in rows]
        if hasattr(self._cur, "description") and self._cur.description:
            col_names = [d[0] for d in self._cur.description]
            return [RowDict(zip(col_names, r)) for r in rows]
        return [RowDict(r) for r in rows]

    def __iter__(self):
        return iter(self.fetchall())

class PostgresConnWrapper:
    def __init__(self, raw_conn):
        self._conn = raw_conn

    def cursor(self):
        return PostgresCursorWrapper(self._conn.cursor())

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()

def get_db():
    if USE_POSTGRES:
        if HAS_PSYCOPG2:
            raw_conn = psycopg2.connect(_pg_url, cursor_factory=RealDictCursor)
            return PostgresConnWrapper(raw_conn)
        elif HAS_PG8000:
            import urllib.parse
            p = urllib.parse.urlparse(_pg_url)
            raw_conn = pg8000.dbapi.connect(
                user=p.username,
                password=p.password,
                host=p.hostname,
                port=p.port or 5432,
                database=p.path.lstrip("/"),
                ssl_context=True
            )
            return PostgresConnWrapper(raw_conn)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def _default_admin_password() -> str:
    """Password for the first-run admin account.

    Uses AW_ADMIN_PASSWORD when set. Local SQLite dev keeps the old demo password
    for convenience; hosted databases get a random one (printed once to the logs).
    """
    env = os.environ.get("AW_ADMIN_PASSWORD", "").strip()
    if env:
        return env
    if not USE_POSTGRES:
        return "admin123"
    generated = secrets.token_urlsafe(12)
    print(f"[AnswerWeave] Created admin@answerweave.ai with a random password: {generated} (set AW_ADMIN_PASSWORD to choose one)")
    return generated


# Columns added after the original schema: embedding versioning, answer analytics,
# per-assistant personality, and workspace tenancy.
SCHEMA_COLUMNS = [
    ("assistants", "workspace_id", "TEXT DEFAULT ''"),
    ("assistants", "industry", "TEXT DEFAULT 'auto'"),
    ("assistants", "recrawl_frequency", "TEXT DEFAULT 'off'"),
    ("assistants", "installed_epoch", "INTEGER DEFAULT 0"),
    ("assistants", "installed_url", "TEXT DEFAULT ''"),
    ("assistants", "crawl_root_url", "TEXT DEFAULT ''"),
    ("assistants", "crawl_max_pages", "INTEGER DEFAULT 50"),
    ("assistants", "last_recrawl_epoch", "INTEGER DEFAULT 0"),
    ("sources", "content_hash", "TEXT DEFAULT ''"),
    ("messages", "cards_json", "TEXT"),
    ("users", "email_verified", "INTEGER DEFAULT 0"),
    ("chunks", "embedding_model", "TEXT DEFAULT ''"),
    ("messages", "feedback", "INTEGER DEFAULT 0"),
    ("messages", "response_ms", "INTEGER DEFAULT 0"),
    ("messages", "provider", "TEXT DEFAULT ''"),
    ("messages", "knowledge_gap", "INTEGER DEFAULT 0"),
    ("assistants", "tone", "TEXT DEFAULT 'friendly'"),
    ("assistants", "reply_length", "TEXT DEFAULT 'balanced'"),
    ("assistants", "custom_instructions", "TEXT DEFAULT ''"),
    ("assistants", "avoid_topics", "TEXT DEFAULT ''"),
]


def init_db():
    if USE_POSTGRES:
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS assistants (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            domain TEXT DEFAULT '*',
            primary_color TEXT DEFAULT '#4F46E5',
            welcome_message TEXT DEFAULT 'Hi there! 👋 How can I help you today?',
            bot_avatar TEXT DEFAULT '⚡',
            position TEXT DEFAULT 'bottom-right',
            suggested_questions TEXT DEFAULT 'What are your products?\nHow much does it cost?\nHow do I contact support?',
            lead_capture_enabled INTEGER DEFAULT 1,
            voice_enabled INTEGER DEFAULT 1,
            notification_email TEXT DEFAULT '',
            webhook_url TEXT DEFAULT '',
            monthly_message_limit INTEGER DEFAULT 2000,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            theme_mode TEXT DEFAULT 'light',
            widget_subtitle TEXT DEFAULT 'Online • AI Assistant',
            launcher_text TEXT DEFAULT '',
            launcher_style TEXT DEFAULT 'circle',
            teaser_message TEXT DEFAULT '👋 Hi! Need quick answers?',
            lead_title TEXT DEFAULT 'Get in touch with our team',
            lead_fields TEXT DEFAULT 'name_email',
            sound_enabled INTEGER DEFAULT 1,
            show_branding INTEGER DEFAULT 1,
            whatsapp_number TEXT DEFAULT '',
            input_placeholder TEXT DEFAULT 'Ask a question...',
            launcher_pulse INTEGER DEFAULT 1,
            border_radius TEXT DEFAULT '22px',
            font_family TEXT DEFAULT 'jakarta',
            widget_width TEXT DEFAULT 'standard',
            offset_x INTEGER DEFAULT 24,
            offset_y INTEGER DEFAULT 24,
            launcher_icon TEXT DEFAULT 'chat',
            teaser_delay INTEGER DEFAULT 12,
            exit_intent INTEGER DEFAULT 1,
            hide_on_mobile INTEGER DEFAULT 0,
            custom_css TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS sources (
            id SERIAL PRIMARY KEY,
            assistant_id TEXT NOT NULL DEFAULT 'asst_default',
            source_type TEXT NOT NULL,
            title TEXT,
            url TEXT,
            content TEXT,
            chunk_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS chunks (
            id SERIAL PRIMARY KEY,
            assistant_id TEXT NOT NULL DEFAULT 'asst_default',
            source_id INTEGER,
            chunk_index INTEGER,
            content TEXT NOT NULL,
            title TEXT,
            url TEXT,
            embedding TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS leads (
            id SERIAL PRIMARY KEY,
            assistant_id TEXT NOT NULL DEFAULT 'asst_default',
            email TEXT NOT NULL,
            name TEXT,
            phone TEXT,
            note TEXT,
            status TEXT DEFAULT 'new',
            conversation_summary TEXT,
            ai_call_prep_brief TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            assistant_id TEXT NOT NULL DEFAULT 'asst_default',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS messages (
            id SERIAL PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            assistant_id TEXT NOT NULL DEFAULT 'asst_default',
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            sources_json TEXT,
            lead_prompted INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS unanswered_questions (
            id SERIAL PRIMARY KEY,
            assistant_id TEXT NOT NULL DEFAULT 'asst_default',
            question TEXT NOT NULL,
            frequency INTEGER DEFAULT 1,
            resolution_notes TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            name TEXT NOT NULL,
            role TEXT DEFAULT 'admin',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS user_assistants (
            user_id TEXT NOT NULL,
            assistant_id TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, assistant_id)
        );
        """)
        try:
            cursor.execute("ALTER TABLE assistants ADD COLUMN IF NOT EXISTS whatsapp_number TEXT DEFAULT '';")
            cursor.execute("ALTER TABLE assistants ADD COLUMN IF NOT EXISTS input_placeholder TEXT DEFAULT 'Ask a question...';")
            cursor.execute("ALTER TABLE assistants ADD COLUMN IF NOT EXISTS launcher_pulse INTEGER DEFAULT 1;")
            cursor.execute("ALTER TABLE assistants ADD COLUMN IF NOT EXISTS border_radius TEXT DEFAULT '22px';")
            cursor.execute("ALTER TABLE assistants ADD COLUMN IF NOT EXISTS font_family TEXT DEFAULT 'jakarta';")
            cursor.execute("ALTER TABLE assistants ADD COLUMN IF NOT EXISTS widget_width TEXT DEFAULT 'standard';")
            cursor.execute("ALTER TABLE assistants ADD COLUMN IF NOT EXISTS offset_x INTEGER DEFAULT 24;")
            cursor.execute("ALTER TABLE assistants ADD COLUMN IF NOT EXISTS offset_y INTEGER DEFAULT 24;")
            cursor.execute("ALTER TABLE assistants ADD COLUMN IF NOT EXISTS launcher_icon TEXT DEFAULT 'chat';")
            cursor.execute("ALTER TABLE assistants ADD COLUMN IF NOT EXISTS teaser_delay INTEGER DEFAULT 12;")
            cursor.execute("ALTER TABLE assistants ADD COLUMN IF NOT EXISTS exit_intent INTEGER DEFAULT 1;")
            cursor.execute("ALTER TABLE assistants ADD COLUMN IF NOT EXISTS hide_on_mobile INTEGER DEFAULT 0;")
            cursor.execute("ALTER TABLE assistants ADD COLUMN IF NOT EXISTS custom_css TEXT DEFAULT '';")
            cursor.execute("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'bot';")
            cursor.execute("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS human_requested_epoch INTEGER DEFAULT 0;")
            cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_seen_epoch INTEGER DEFAULT 0;")
            cursor.execute("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS operator_name TEXT DEFAULT '';")
            cursor.execute("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS unread_operator_msgs INTEGER DEFAULT 0;")
        except Exception:
            pass
        conn.commit();
        # One statement per transaction, so a failure can't skip the rest.
        for table, col, col_def in SCHEMA_COLUMNS:
            try:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {col_def};")
                conn.commit()
            except Exception:
                conn.rollback()

        # Check if assistants table in Postgres has data
        cursor.execute("SELECT count(*) as cnt FROM assistants;")
        cnt_row = cursor.fetchone()
        asst_count = cnt_row["cnt"] if cnt_row else 0
        if asst_count == 0 and os.path.exists(_repo_db_path):
            try:
                sq_conn = sqlite3.connect(_repo_db_path)
                sq_conn.row_factory = sqlite3.Row
                sq_cur = sq_conn.cursor()

                sq_cur.execute("SELECT * FROM assistants;")
                for r in sq_cur.fetchall():
                    d = dict(r)
                    cols = list(d.keys())
                    placeholders = ", ".join(["%s"] * len(cols))
                    col_names = ", ".join(cols)
                    cursor.execute(f"INSERT INTO assistants ({col_names}) VALUES ({placeholders}) ON CONFLICT (id) DO NOTHING;", list(d.values()))

                sq_cur.execute("SELECT * FROM sources;")
                for r in sq_cur.fetchall():
                    d = dict(r)
                    cols = list(d.keys())
                    placeholders = ", ".join(["%s"] * len(cols))
                    col_names = ", ".join(cols)
                    cursor.execute(f"INSERT INTO sources ({col_names}) VALUES ({placeholders}) ON CONFLICT DO NOTHING;", list(d.values()))

                sq_cur.execute("SELECT * FROM chunks;")
                for r in sq_cur.fetchall():
                    d = dict(r)
                    cols = list(d.keys())
                    placeholders = ", ".join(["%s"] * len(cols))
                    col_names = ", ".join(cols)
                    cursor.execute(f"INSERT INTO chunks ({col_names}) VALUES ({placeholders}) ON CONFLICT DO NOTHING;", list(d.values()))

                sq_cur.execute("SELECT * FROM settings;")
                for r in sq_cur.fetchall():
                    d = dict(r)
                    cursor.execute("INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING;", (d["key"], d["value"]))

                sq_cur.execute("SELECT * FROM users;")
                for r in sq_cur.fetchall():
                    d = dict(r)
                    cursor.execute("INSERT INTO users (id, email, password_hash, name, role) VALUES (%s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING;", (d["id"], d["email"], d["password_hash"], d["name"], d.get("role", "admin")))

                conn.commit()
                sq_conn.close()
            except Exception as e:
                print(f"Error migrating SQLite to Postgres: {e}")

        cursor.execute("SELECT id FROM users WHERE email = 'admin@answerweave.ai'")
        if not cursor.fetchone():
            admin_id = f"user_{uuid.uuid4().hex[:8]}"
            pwd_hash = hash_password(_default_admin_password())
            cursor.execute("INSERT INTO users (id, email, password_hash, name, role) VALUES (?, 'admin@answerweave.ai', ?, 'Admin', 'admin')", (admin_id, pwd_hash))
            conn.commit()

        conn.close()
        init_workspaces()
        return

    conn = get_db()
    cursor = conn.cursor()
    
    # 1. Assistants Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS assistants (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        domain TEXT DEFAULT '*',
        primary_color TEXT DEFAULT '#4F46E5',
        welcome_message TEXT DEFAULT 'Hi there! 👋 How can I help you today?',
        bot_avatar TEXT DEFAULT '⚡',
        position TEXT DEFAULT 'bottom-right',
        suggested_questions TEXT DEFAULT 'What are your products?\nHow much does it cost?\nHow do I contact support?',
        lead_capture_enabled INTEGER DEFAULT 1,
        voice_enabled INTEGER DEFAULT 1,
        notification_email TEXT DEFAULT '',
        webhook_url TEXT DEFAULT '',
        monthly_message_limit INTEGER DEFAULT 2000,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 2. Sources Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sources (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        assistant_id TEXT NOT NULL DEFAULT 'asst_default',
        source_type TEXT NOT NULL,
        title TEXT,
        url TEXT,
        content TEXT,
        chunk_count INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (assistant_id) REFERENCES assistants(id) ON DELETE CASCADE
    );
    """)

    # 3. Knowledge Chunks Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS chunks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        assistant_id TEXT NOT NULL DEFAULT 'asst_default',
        source_id INTEGER,
        chunk_index INTEGER,
        content TEXT NOT NULL,
        title TEXT,
        url TEXT,
        embedding TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE CASCADE,
        FOREIGN KEY (assistant_id) REFERENCES assistants(id) ON DELETE CASCADE
    );
    """)

    # 4. Leads Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS leads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        assistant_id TEXT NOT NULL DEFAULT 'asst_default',
        email TEXT NOT NULL,
        name TEXT,
        phone TEXT,
        note TEXT,
        status TEXT DEFAULT 'new',
        conversation_summary TEXT,
        ai_call_prep_brief TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (assistant_id) REFERENCES assistants(id) ON DELETE CASCADE
    );
    """)

    # 5. Conversations Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS conversations (
        id TEXT PRIMARY KEY,
        assistant_id TEXT NOT NULL DEFAULT 'asst_default',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (assistant_id) REFERENCES assistants(id) ON DELETE CASCADE
    );
    """)

    # 6. Messages Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_id TEXT NOT NULL,
        assistant_id TEXT NOT NULL DEFAULT 'asst_default',
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        sources_json TEXT,
        lead_prompted INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
    );
    """)

    # 7. Knowledge Gaps / Unanswered Questions Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS unanswered_questions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        assistant_id TEXT NOT NULL DEFAULT 'asst_default',
        question TEXT NOT NULL,
        frequency INTEGER DEFAULT 1,
        resolution_notes TEXT DEFAULT '',
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (assistant_id) REFERENCES assistants(id) ON DELETE CASCADE
    );
    """)

    # 8. Global Settings Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    );
    """)

    # 9. Admin Users Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        name TEXT NOT NULL,
        role TEXT DEFAULT 'admin',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 10. User <-> Assistant access mapping
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_assistants (
        user_id TEXT NOT NULL,
        assistant_id TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (user_id, assistant_id)
    );
    """)

    # Migrations
    tables_to_migrate = [
        ("sources", "assistant_id", "TEXT NOT NULL DEFAULT 'asst_default'"),
        ("chunks", "assistant_id", "TEXT NOT NULL DEFAULT 'asst_default'"),
        ("leads", "assistant_id", "TEXT NOT NULL DEFAULT 'asst_default'"),
        ("leads", "status", "TEXT DEFAULT 'new'"),
        ("leads", "ai_call_prep_brief", "TEXT DEFAULT ''"),
        ("conversations", "assistant_id", "TEXT NOT NULL DEFAULT 'asst_default'"),
        ("messages", "assistant_id", "TEXT NOT NULL DEFAULT 'asst_default'"),
        ("assistants", "theme_mode", "TEXT DEFAULT 'light'"),
        ("assistants", "widget_subtitle", "TEXT DEFAULT 'Instant Grounded Answers'"),
        ("assistants", "launcher_text", "TEXT DEFAULT ''"),
        ("assistants", "launcher_style", "TEXT DEFAULT 'circle'"),
        ("assistants", "teaser_message", "TEXT DEFAULT '👋 Need help? Ask anything!'"),
        ("assistants", "lead_title", "TEXT DEFAULT 'Get in touch with our team'"),
        ("assistants", "lead_fields", "TEXT DEFAULT 'name_email'"),
        ("assistants", "sound_enabled", "INTEGER DEFAULT 1"),
        ("assistants", "show_branding", "INTEGER DEFAULT 1"),
        ("assistants", "whatsapp_number", "TEXT DEFAULT ''"),
        ("assistants", "input_placeholder", "TEXT DEFAULT 'Ask a question...'"),
        ("assistants", "launcher_pulse", "INTEGER DEFAULT 1"),
        ("assistants", "border_radius", "TEXT DEFAULT '22px'"),
        ("assistants", "font_family", "TEXT DEFAULT 'jakarta'"),
        ("assistants", "widget_width", "TEXT DEFAULT 'standard'"),
        ("assistants", "offset_x", "INTEGER DEFAULT 24"),
        ("assistants", "offset_y", "INTEGER DEFAULT 24"),
        ("assistants", "launcher_icon", "TEXT DEFAULT 'chat'"),
        ("assistants", "teaser_delay", "INTEGER DEFAULT 12"),
        ("assistants", "exit_intent", "INTEGER DEFAULT 1"),
        ("assistants", "hide_on_mobile", "INTEGER DEFAULT 0"),
        ("assistants", "custom_css", "TEXT DEFAULT ''"),
        ("conversations", "status", "TEXT DEFAULT 'bot'"),
        ("conversations", "human_requested_epoch", "INTEGER DEFAULT 0"),
        ("users", "last_seen_epoch", "INTEGER DEFAULT 0"),
        ("conversations", "operator_name", "TEXT DEFAULT ''"),
        ("conversations", "unread_operator_msgs", "INTEGER DEFAULT 0")
    ] + SCHEMA_COLUMNS
    for tbl, col, col_def in tables_to_migrate:
        try:
            cursor.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} {col_def};")
        except sqlite3.OperationalError:
            pass

    # Ensure default assistant exists
    cursor.execute("SELECT id FROM assistants WHERE id = 'asst_default'")
    if not cursor.fetchone():
        cursor.execute("""
        INSERT INTO assistants (
            id, name, domain, primary_color, welcome_message, bot_avatar,
            position, widget_subtitle, suggested_questions, lead_capture_enabled, voice_enabled,
            teaser_message, lead_title, lead_fields, show_branding
        ) VALUES (
            'asst_default', 'EcomAlign Assistant', 'ecomalign.com', '#0f172a',
            'Hi there! 👋 Welcome to EcomAlign. How can we help grow your e-commerce brand across Amazon, eBay, TikTok Shop, or other marketplaces today?', '⚡',
            'bottom-right', 'Online • Marketplace Growth AI', 'How does EcomAlign help scale sales across Amazon, eBay & TikTok Shop?\nWhat full-service store management & listing optimization do you provide?\nHow can I book a call or start a project with your growth team?', 1, 1,
            '👋 Need help growing on marketplaces?', 'Start Your Project with EcomAlign', 'name_email', 1
        );
        """)

    # Ensure default admin user exists
    cursor.execute("SELECT id FROM users WHERE email = 'admin@answerweave.ai'")
    if not cursor.fetchone():
        admin_id = f"user_{uuid.uuid4().hex[:8]}"
        pwd_hash = hash_password(_default_admin_password())
        cursor.execute("""
            INSERT INTO users (id, email, password_hash, name, role)
            VALUES (?, 'admin@answerweave.ai', ?, 'Admin', 'admin')
        """, (admin_id, pwd_hash))

    conn.commit()
    conn.close()
    init_workspaces()

# ----------------- User Auth Helpers -----------------
import hashlib
import secrets

PBKDF2_ITERATIONS = 200_000


def _legacy_sha256_hash(password: str, salt: str) -> str:
    return f"{salt}:" + hashlib.sha256(f"{salt}:{password}".encode("utf-8")).hexdigest()


def hash_password(password: str) -> str:
    """PBKDF2-SHA256 with a random salt: pbkdf2_sha256$<iterations>$<salt>$<hex>."""
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ITERATIONS).hex()
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        if stored_hash.startswith("pbkdf2_sha256$"):
            _, iterations, salt, digest = stored_hash.split("$")
            candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), int(iterations)).hex()
            return secrets.compare_digest(candidate, digest)
        # Legacy format "<salt>:<sha256>" from earlier versions.
        parts = stored_hash.split(":")
        if len(parts) != 2:
            return False
        return secrets.compare_digest(_legacy_sha256_hash(password, parts[0]), stored_hash)
    except Exception:
        return False


def password_needs_upgrade(stored_hash: str) -> bool:
    return not (stored_hash or "").startswith("pbkdf2_sha256$")


def set_user_password_hash(user_id: str, new_hash: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, user_id))
    conn.commit()
    conn.close()


def add_user_assistant(user_id: str, assistant_id: str):
    """Grant a user access to one assistant without touching their other grants."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO user_assistants (user_id, assistant_id)
        VALUES (?, ?)
        ON CONFLICT DO NOTHING;
    """, (user_id, assistant_id))
    conn.commit()
    conn.close()


def set_user_assistants(user_id: str, assistant_ids: List[str]):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM user_assistants WHERE user_id = ?", (user_id,))
    for asst_id in assistant_ids:
        if asst_id and str(asst_id).strip():
            cursor.execute("""
                INSERT INTO user_assistants (user_id, assistant_id)
                VALUES (?, ?)
                ON CONFLICT DO NOTHING;
            """, (user_id, str(asst_id).strip()))
    conn.commit()
    conn.close()

def get_user_assigned_assistants(user_id: str) -> List[str]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT assistant_id FROM user_assistants WHERE user_id = ?", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return [r["assistant_id"] for r in rows]

def create_user(email: str, password: str, name: str, role: str = "member", assigned_assistant_ids: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    user_id = f"user_{uuid.uuid4().hex[:8]}"
    pwd_hash = hash_password(password)
    try:
        cursor.execute("""
            INSERT INTO users (id, email, password_hash, name, role)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, email.strip().lower(), pwd_hash, name.strip(), role.strip().lower()))
        conn.commit()
        conn.close()
        if assigned_assistant_ids:
            set_user_assistants(user_id, assigned_assistant_ids)
        return get_user_by_id(user_id)
    except Exception:
        conn.close()
        return None

def update_user(user_id: str, name: Optional[str] = None, role: Optional[str] = None, password: Optional[str] = None, assigned_assistant_ids: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    updates = []
    params = []
    if name is not None and name.strip():
        updates.append("name = ?")
        params.append(name.strip())
    if role is not None and role.strip():
        updates.append("role = ?")
        params.append(role.strip().lower())
    if password and password.strip():
        updates.append("password_hash = ?")
        params.append(hash_password(password.strip()))
    if updates:
        params.append(user_id)
        cursor.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = ?;", params)
        conn.commit()
    conn.close()

    if assigned_assistant_ids is not None:
        set_user_assistants(user_id, assigned_assistant_ids)

    return get_user_by_id(user_id)

def delete_user(user_id: str) -> bool:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT email, role FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    if not row or row["email"] == "admin@answerweave.ai":
        conn.close()
        return False
    cursor.execute("DELETE FROM user_assistants WHERE user_id = ?", (user_id,))
    cursor.execute("DELETE FROM workspace_members WHERE user_id = ?", (user_id,))
    cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    return True

def list_users() -> List[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, email, name, role, created_at FROM users ORDER BY created_at ASC;")
    rows = cursor.fetchall()
    users = []
    for r in rows:
        u = dict(r)
        u_id = u["id"]
        cursor.execute("""
            SELECT a.id, a.name, a.domain
            FROM assistants a
            JOIN user_assistants ua ON ua.assistant_id = a.id
            WHERE ua.user_id = ?
            ORDER BY a.name ASC
        """, (u_id,))
        assts = cursor.fetchall()
        u["assigned_assistants"] = [dict(a) for a in assts]
        u["assigned_assistant_ids"] = [a["id"] for a in assts]
        users.append(u)
    conn.close()
    return users

def authenticate_user(email: str, password: str) -> Optional[Dict[str, Any]]:
    user = get_user_by_email(email)
    if not user:
        return None
    if verify_password(password, user["password_hash"]):
        if password_needs_upgrade(user["password_hash"]):
            try:
                set_user_password_hash(user["id"], hash_password(password))
            except Exception:
                pass
        u_dict = dict(user)
        u_dict.pop("password_hash", None)
        return u_dict
    return None

def get_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, email, name, role, created_at, COALESCE(email_verified, 0) AS email_verified FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return None
    u = dict(row)
    cursor.execute("""
        SELECT a.id, a.name, a.domain
        FROM assistants a
        JOIN user_assistants ua ON ua.assistant_id = a.id
        WHERE ua.user_id = ?
        ORDER BY a.name ASC
    """, (user_id,))
    assts = cursor.fetchall()
    conn.close()
    u["assigned_assistants"] = [dict(a) for a in assts]
    u["assigned_assistant_ids"] = [a["id"] for a in assts]
    return u

def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE email = ?", (email.strip().lower(),))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return None
    u = dict(row)
    user_id = u["id"]
    cursor.execute("""
        SELECT a.id, a.name, a.domain
        FROM assistants a
        JOIN user_assistants ua ON ua.assistant_id = a.id
        WHERE ua.user_id = ?
        ORDER BY a.name ASC
    """, (user_id,))
    assts = cursor.fetchall()
    conn.close()
    u["assigned_assistants"] = [dict(a) for a in assts]
    u["assigned_assistant_ids"] = [a["id"] for a in assts]
    return u

def list_assistants_for_user(user_id: Optional[str] = None) -> List[Dict[str, Any]]:
    if not user_id:
        return list_assistants()
    user = get_user_by_id(user_id)
    if not user or user.get("role") == "admin":
        return list_assistants()

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT a.*,
            (SELECT COUNT(*) FROM sources s WHERE s.assistant_id = a.id) as total_sources,
            (SELECT COUNT(*) FROM chunks c WHERE c.assistant_id = a.id) as total_chunks,
            (SELECT COUNT(*) FROM leads l WHERE l.assistant_id = a.id) as total_leads,
            (SELECT COUNT(*) FROM messages m WHERE m.assistant_id = a.id AND m.role = 'user') as total_messages
        FROM assistants a
        JOIN user_assistants ua ON ua.assistant_id = a.id
        WHERE ua.user_id = ?
        ORDER BY a.created_at ASC
    """, (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ----------------- Assistant CRUD -----------------
def create_assistant(name: str, domain: str = "*", primary_color: str = "#0f172a", welcome_message: str = "", suggested_questions: str = "", bot_avatar: str = "⚡", widget_subtitle: str = "Online • AI Assistant", teaser_message: str = "👋 Hi! Need quick answers?", workspace_id: str = "") -> str:
    asst_id = f"asst_{uuid.uuid4().hex[:8]}"
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO assistants (
            id, name, domain, primary_color, welcome_message, suggested_questions,
            bot_avatar, widget_subtitle, teaser_message, lead_capture_enabled, voice_enabled, show_branding, workspace_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, 1, ?)
    """, (
        asst_id,
        name.strip(),
        domain.strip() if domain else "*",
        primary_color or "#0f172a",
        welcome_message or f"Hello! 👋 Welcome to {name}. How can I assist you today?",
        suggested_questions or "What services do you offer?\nHow does pricing work?\nHow do I get started?",
        bot_avatar or "⚡",
        widget_subtitle or "Online • AI Assistant",
        teaser_message or "👋 Hi! Need quick answers?",
        workspace_id or ""
    ))
    conn.commit()
    conn.close()
    return asst_id

def list_assistants() -> List[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT a.*,
            (SELECT COUNT(*) FROM sources s WHERE s.assistant_id = a.id) as total_sources,
            (SELECT COUNT(*) FROM chunks c WHERE c.assistant_id = a.id) as total_chunks,
            (SELECT COUNT(*) FROM leads l WHERE l.assistant_id = a.id) as total_leads,
            (SELECT COUNT(*) FROM messages m WHERE m.assistant_id = a.id AND m.role = 'user') as total_messages
        FROM assistants a
        ORDER BY a.created_at ASC
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

_ASSISTANTS_CACHE: Dict[str, Dict[str, Any]] = {}
_ASSISTANTS_CACHE_TIMESTAMP: float = 0.0
_ASSISTANTS_CACHE_TTL: float = 30.0

def get_assistant(assistant_id: str) -> Optional[Dict[str, Any]]:
    global _ASSISTANTS_CACHE, _ASSISTANTS_CACHE_TIMESTAMP
    now = time.time()
    if (now - _ASSISTANTS_CACHE_TIMESTAMP) < _ASSISTANTS_CACHE_TTL and assistant_id in _ASSISTANTS_CACHE:
        return _ASSISTANTS_CACHE[assistant_id]

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM assistants WHERE id = ?", (assistant_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        res = dict(row)
        _ASSISTANTS_CACHE[assistant_id] = res
        _ASSISTANTS_CACHE_TIMESTAMP = now
        return res
    return None

def update_assistant(assistant_id: str, data: Dict[str, Any]) -> bool:
    global _ASSISTANTS_CACHE
    allowed_keys = [
        "name", "domain", "primary_color", "welcome_message", "bot_avatar",
        "position", "suggested_questions", "lead_capture_enabled", "voice_enabled",
        "notification_email", "webhook_url",
        "theme_mode", "widget_subtitle", "launcher_text", "launcher_style",
        "teaser_message", "lead_title", "lead_fields", "sound_enabled", "show_branding", "whatsapp_number",
        "input_placeholder", "launcher_pulse", "border_radius",
        "font_family", "widget_width", "offset_x", "offset_y", "launcher_icon", "teaser_delay", "exit_intent", "hide_on_mobile", "custom_css",
        "tone", "reply_length", "custom_instructions", "avoid_topics", "industry",
        "recrawl_frequency", "crawl_root_url", "crawl_max_pages", "installed_epoch", "installed_url"
    ]
    updates = []
    values = []
    for k in allowed_keys:
        if k in data:
            updates.append(f"{k} = ?")
            values.append(data[k])
    if not updates:
        return False
    values.append(assistant_id)
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(f"UPDATE assistants SET {', '.join(updates)} WHERE id = ?", values)
    conn.commit()
    conn.close()
    _ASSISTANTS_CACHE.pop(assistant_id, None)
    return True

def delete_assistant(assistant_id: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM chunks WHERE assistant_id = ?", (assistant_id,))
    cursor.execute("DELETE FROM sources WHERE assistant_id = ?", (assistant_id,))
    cursor.execute("DELETE FROM leads WHERE assistant_id = ?", (assistant_id,))
    cursor.execute("DELETE FROM messages WHERE assistant_id = ?", (assistant_id,))
    cursor.execute("DELETE FROM conversations WHERE assistant_id = ?", (assistant_id,))
    cursor.execute("DELETE FROM unanswered_questions WHERE assistant_id = ?", (assistant_id,))
    cursor.execute("DELETE FROM user_assistants WHERE assistant_id = ?", (assistant_id,))
    cursor.execute("DELETE FROM assistants WHERE id = ?", (assistant_id,))
    conn.commit()
    conn.close()
    # Without this a deleted assistant keeps answering from the cache for up to 30s.
    _ASSISTANTS_CACHE.pop(assistant_id, None)
    invalidate_chunks_cache(assistant_id)

# ----------------- Settings Helpers -----------------
_SETTINGS_CACHE: Dict[str, str] = {}
_SETTINGS_CACHE_TIMESTAMP: float = 0.0
_SETTINGS_CACHE_TTL: float = 30.0

def _refresh_settings_cache():
    global _SETTINGS_CACHE, _SETTINGS_CACHE_TIMESTAMP
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT key, value FROM settings")
        rows = cursor.fetchall()
        conn.close()
        _SETTINGS_CACHE = {r["key"]: r["value"] for r in rows}
        _SETTINGS_CACHE_TIMESTAMP = time.time()
    except Exception:
        pass

def get_setting(key: str, default: str = "") -> str:
    global _SETTINGS_CACHE, _SETTINGS_CACHE_TIMESTAMP
    now = time.time()
    if not _SETTINGS_CACHE or (now - _SETTINGS_CACHE_TIMESTAMP) > _SETTINGS_CACHE_TTL:
        _refresh_settings_cache()
    return _SETTINGS_CACHE.get(key, default)

def set_setting(key: str, value: str):
    global _SETTINGS_CACHE
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()
    _SETTINGS_CACHE[key] = value

# ----------------- Source & Chunk Helpers -----------------
_CHUNKS_CACHE: Dict[str, Dict[str, Any]] = {}
_CHUNKS_CACHE_TTL: float = 60.0

def invalidate_chunks_cache(assistant_id: Optional[str] = None):
    global _CHUNKS_CACHE
    if assistant_id:
        _CHUNKS_CACHE.pop(assistant_id, None)
    else:
        _CHUNKS_CACHE.clear()

def add_source(assistant_id: str, source_type: str, title: str, url: str, content: str) -> int:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO sources (assistant_id, source_type, title, url, content)
        VALUES (?, ?, ?, ?, ?)
    """, (assistant_id, source_type, title, url, content))
    source_id = cursor.lastrowid
    conn.commit()
    conn.close()
    invalidate_chunks_cache(assistant_id)
    return source_id

def add_chunk(assistant_id: str, source_id: int, chunk_index: int, content: str, title: str, url: str, embedding: List[float]):
    from app.embeddings import embedding_tag
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO chunks (assistant_id, source_id, chunk_index, content, title, url, embedding, embedding_model)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (assistant_id, source_id, chunk_index, content, title, url, json.dumps(embedding), embedding_tag(embedding)))
    conn.commit()
    conn.close()
    invalidate_chunks_cache(assistant_id)

def list_chunks_to_reindex(assistant_id: str, current_tag: str, limit: int, after_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """Chunks whose vectors weren't made by the current embedding model (oldest first).

    With `after_id` (a full rebuild), every chunk with a larger id is returned regardless of tag.
    """
    conn = get_db()
    cursor = conn.cursor()
    if after_id is not None:
        cursor.execute("""
            SELECT id, content, title FROM chunks
            WHERE assistant_id = ? AND id > ?
            ORDER BY id ASC LIMIT ?
        """, (assistant_id, after_id, limit))
    else:
        cursor.execute("""
            SELECT id, content, title FROM chunks
            WHERE assistant_id = ? AND (embedding_model IS NULL OR embedding_model != ?)
            ORDER BY id ASC LIMIT ?
        """, (assistant_id, current_tag, limit))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

def update_chunk_embeddings(assistant_id: str, updates: List[tuple]):
    """updates: [(chunk_id, embedding, tag), ...]"""
    if not updates:
        return
    conn = get_db()
    cursor = conn.cursor()
    for chunk_id, emb, tag in updates:
        cursor.execute("UPDATE chunks SET embedding = ?, embedding_model = ? WHERE id = ? AND assistant_id = ?",
                       (json.dumps(emb), tag, chunk_id, assistant_id))
    conn.commit()
    conn.close()
    invalidate_chunks_cache(assistant_id)

def get_embedding_status(assistant_id: str, current_tag: str) -> Dict[str, int]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(*) AS total,
               COALESCE(SUM(CASE WHEN embedding_model = ? THEN 1 ELSE 0 END), 0) AS current_count
        FROM chunks WHERE assistant_id = ?
    """, (current_tag, assistant_id))
    row = cursor.fetchone()
    conn.close()
    total, current = int(row["total"] or 0), int(row["current_count"] or 0)
    return {"total_chunks": total, "current_chunks": current, "stale_chunks": total - current}

def update_source_chunk_count(source_id: int, count: int):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE sources SET chunk_count = ? WHERE id = ?", (count, source_id))
    conn.commit()
    conn.close()

def list_sources(assistant_id: str = "asst_default") -> List[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, assistant_id, source_type, title, url, chunk_count, created_at
        FROM sources
        WHERE assistant_id = ?
        ORDER BY created_at DESC
    """, (assistant_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def delete_source(source_id: int):
    conn = get_db()
    cursor = conn.cursor()
    # Find assistant_id before deleting so we can invalidate chunk cache
    cursor.execute("SELECT assistant_id FROM sources WHERE id = ?", (source_id,))
    row = cursor.fetchone()
    asst_id = row["assistant_id"] if row else None
    
    cursor.execute("DELETE FROM chunks WHERE source_id = ?", (source_id,))
    cursor.execute("DELETE FROM sources WHERE id = ?", (source_id,))
    conn.commit()
    conn.close()
    if asst_id:
        invalidate_chunks_cache(asst_id)
    else:
        invalidate_chunks_cache()

def get_chunks_for_assistant(assistant_id: str) -> List[Dict[str, Any]]:
    global _CHUNKS_CACHE
    now = time.time()
    cached = _CHUNKS_CACHE.get(assistant_id)
    if cached and (now - cached["timestamp"]) < _CHUNKS_CACHE_TTL:
        return cached["chunks"]

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, assistant_id, source_id, chunk_index, content, title, url, embedding, embedding_model
        FROM chunks
        WHERE assistant_id = ?
    """, (assistant_id,))
    rows = cursor.fetchall()
    conn.close()
    
    results = []
    for r in rows:
        emb_str = r["embedding"]
        emb = json.loads(emb_str) if emb_str else []
        results.append({
            "id": r["id"],
            "assistant_id": r["assistant_id"],
            "source_id": r["source_id"],
            "chunk_index": r["chunk_index"],
            "content": r["content"],
            "title": r["title"],
            "url": r["url"],
            "embedding": emb,
            "embedding_model": r["embedding_model"] or ""
        })
    _CHUNKS_CACHE[assistant_id] = {"timestamp": now, "chunks": results}
    return results

# ----------------- Leads Helpers -----------------
def add_lead(
    assistant_id: str,
    email: str,
    name: str = "",
    phone: str = "",
    note: str = "",
    conversation_summary: str = "",
    ai_call_prep_brief: str = ""
) -> int:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO leads (assistant_id, email, name, phone, note, status, conversation_summary, ai_call_prep_brief)
        VALUES (?, ?, ?, ?, ?, 'new', ?, ?)
    """, (assistant_id, email, name, phone, note, conversation_summary, ai_call_prep_brief))
    lead_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return lead_id

def list_leads(assistant_id: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    if assistant_id:
        cursor.execute("SELECT * FROM leads WHERE assistant_id = ? ORDER BY created_at DESC", (assistant_id,))
    else:
        cursor.execute("SELECT * FROM leads ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        if hasattr(d.get("created_at"), "isoformat"):
            d["created_at"] = d["created_at"].isoformat()
        result.append(d)
    return result

def update_lead_status(lead_id: int, status: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE leads SET status = ? WHERE id = ?", (status, lead_id))
    conn.commit()
    conn.close()

# ----------------- Conversation & Messages -----------------
def ensure_conversation(conversation_id: str, assistant_id: str = "asst_default"):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO conversations (id, assistant_id) VALUES (?, ?)", (conversation_id, assistant_id))
    conn.commit()
    conn.close()

def add_message(
    conversation_id: str,
    role: str,
    content: str,
    assistant_id: str = "asst_default",
    sources: Optional[List[Dict[str, Any]]] = None,
    lead_prompted: bool = False,
    response_ms: int = 0,
    provider: str = "",
    knowledge_gap: bool = False,
    cards: Optional[List[Dict[str, Any]]] = None
) -> Optional[int]:
    """Stores a message and returns its id. The last three fields are answer analytics for bot replies."""
    ensure_conversation(conversation_id, assistant_id)
    conn = get_db()
    cursor = conn.cursor()
    sources_json = json.dumps(sources) if sources else None
    cursor.execute("""
        INSERT INTO messages (conversation_id, assistant_id, role, content, sources_json, lead_prompted,
                              response_ms, provider, knowledge_gap, cards_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (conversation_id, assistant_id, role, content, sources_json, 1 if lead_prompted else 0,
          int(response_ms or 0), provider or "", 1 if knowledge_gap else 0, json.dumps(cards) if cards else None))
    message_id = cursor.lastrowid
    cursor.execute("UPDATE conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (conversation_id,))
    conn.commit()
    conn.close()
    return message_id

def set_message_feedback(conversation_id: str, message_id: int, rating: int) -> Optional[Dict[str, Any]]:
    """Records a visitor's thumbs up (1) / down (-1) / cleared (0) on a bot reply in their own conversation.

    Returns the rated reply plus the visitor question it answered, or None if the message isn't a bot reply here.
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, assistant_id, content FROM messages
        WHERE id = ? AND conversation_id = ? AND role = 'assistant'
    """, (message_id, conversation_id))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return None
    cursor.execute("UPDATE messages SET feedback = ? WHERE id = ?", (rating, message_id))
    cursor.execute("""
        SELECT content FROM messages
        WHERE conversation_id = ? AND id < ? AND role = 'user'
        ORDER BY id DESC LIMIT 1
    """, (conversation_id, message_id))
    q = cursor.fetchone()
    conn.commit()
    conn.close()
    return {"id": row["id"], "assistant_id": row["assistant_id"], "answer": row["content"],
            "question": q["content"] if q else ""}

def get_answer_quality(assistant_id: str, days: int = 30) -> Dict[str, Any]:
    """Answer analytics for the dashboard: speed, coverage, visitor ratings and providers."""
    since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(*) AS replies,
               COALESCE(AVG(CASE WHEN response_ms > 0 THEN response_ms END), 0) AS avg_ms,
               COALESCE(SUM(CASE WHEN knowledge_gap = 1 THEN 1 ELSE 0 END), 0) AS gaps,
               COALESCE(SUM(CASE WHEN feedback = 1 THEN 1 ELSE 0 END), 0) AS up,
               COALESCE(SUM(CASE WHEN feedback = -1 THEN 1 ELSE 0 END), 0) AS down
        FROM messages
        WHERE assistant_id = ? AND role = 'assistant' AND created_at >= ?
    """, (assistant_id, since))
    s = cursor.fetchone()
    replies, gaps, up, down = int(s["replies"] or 0), int(s["gaps"] or 0), int(s["up"] or 0), int(s["down"] or 0)

    cursor.execute("""
        SELECT provider, COUNT(*) AS n
        FROM messages
        WHERE assistant_id = ? AND role = 'assistant' AND created_at >= ? AND provider IS NOT NULL AND provider != ''
        GROUP BY provider
        ORDER BY n DESC
    """, (assistant_id, since))
    providers = [{"provider": r["provider"], "replies": int(r["n"])} for r in cursor.fetchall()]

    cursor.execute("""
        SELECT m.id, m.conversation_id, m.content, m.created_at,
               (SELECT u.content FROM messages u
                 WHERE u.conversation_id = m.conversation_id AND u.id < m.id AND u.role = 'user'
                 ORDER BY u.id DESC LIMIT 1) AS question
        FROM messages m
        WHERE m.assistant_id = ? AND m.role = 'assistant' AND m.feedback = -1
        ORDER BY m.id DESC LIMIT 10
    """, (assistant_id,))
    disliked = []
    for r in cursor.fetchall():
        created = r["created_at"]
        disliked.append({
            "id": r["id"], "conversation_id": r["conversation_id"], "question": r["question"] or "",
            "answer": r["content"], "created_at": created.isoformat() if hasattr(created, "isoformat") else created,
        })
    conn.close()

    rated = up + down
    return {
        "days": days,
        "replies": replies,
        "avg_response_ms": int(round(float(s["avg_ms"] or 0))),
        "answered_rate": round((replies - gaps) / replies * 100, 1) if replies else None,
        "knowledge_gaps": gaps,
        "thumbs_up": up,
        "thumbs_down": down,
        "satisfaction": round(up / rated * 100, 1) if rated else None,
        "providers": providers,
        "recent_disliked": disliked,
    }

def get_conversation_history(conversation_id: str, limit: int = 10, after_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """Returns the most recent `limit` messages in chronological order.

    With `after_id`, returns only messages newer than that id (oldest first), which
    lets the widget and inbox poll for just the new messages.
    """
    conn = get_db()
    cursor = conn.cursor()
    if after_id is not None:
        cursor.execute("""
            SELECT id, role, content, sources_json, lead_prompted, feedback, cards_json, created_at
            FROM messages
            WHERE conversation_id = ? AND id > ?
            ORDER BY id ASC
            LIMIT ?
        """, (conversation_id, int(after_id), limit))
    else:
        cursor.execute("""
            SELECT id, role, content, sources_json, lead_prompted, feedback, cards_json, created_at FROM (
                SELECT id, role, content, sources_json, lead_prompted, feedback, cards_json, created_at
                FROM messages
                WHERE conversation_id = ?
                ORDER BY id DESC
                LIMIT ?
            ) AS recent
            ORDER BY id ASC
        """, (conversation_id, limit))
    rows = cursor.fetchall()
    conn.close()
    
    msgs = []
    for r in rows:
        created_at = r["created_at"]
        if hasattr(created_at, "isoformat"):
            created_at = created_at.isoformat()
        item = {
            "id": r["id"],
            "role": r["role"],
            "content": r["content"],
            "lead_prompted": bool(r["lead_prompted"]),
            "feedback": int(r["feedback"] or 0),
            "cards": json.loads(r["cards_json"]) if r["cards_json"] else [],
            "created_at": created_at,
            "sources": json.loads(r["sources_json"]) if r["sources_json"] else []
        }
        msgs.append(item)
    return msgs

def get_conversation(conversation_id: str) -> Optional[Dict[str, Any]]:
    """Fetches a conversation by ID with status and metadata."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    if hasattr(d.get("created_at"), "isoformat"):
        d["created_at"] = d["created_at"].isoformat()
    if hasattr(d.get("updated_at"), "isoformat"):
        d["updated_at"] = d["updated_at"].isoformat()
    if "status" not in d or not d["status"]:
        d["status"] = "bot"
    return d

def set_conversation_status(conversation_id: str, status: str = "bot", operator_name: str = "", assistant_id: str = "asst_default"):
    """Updates the takeover state of a conversation, creating row if needed."""
    ensure_conversation(conversation_id, assistant_id)
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE conversations 
        SET status = ?, operator_name = ?, updated_at = CURRENT_TIMESTAMP 
        WHERE id = ?
    """, (status, operator_name, conversation_id))
    conn.commit()
    conn.close()

def add_operator_message(conversation_id: str, content: str, operator_name: str = "Operator", assistant_id: str = "") -> Dict[str, Any]:
    """Adds a human operator message to the conversation and increments unread count."""
    if not assistant_id:
        conv = get_conversation(conversation_id)
        assistant_id = (conv or {}).get("assistant_id") or "asst_default"
    add_message(conversation_id, "operator", content, assistant_id=assistant_id)
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE conversations 
        SET unread_operator_msgs = COALESCE(unread_operator_msgs, 0) + 1,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (conversation_id,))
    conn.commit()
    conn.close()
    return {"status": "success", "content": content, "operator_name": operator_name}

def mark_human_requested(conversation_id: str, cooldown_seconds: int = 600) -> bool:
    """Flag that the visitor asked for a person. Returns True if this is a new
    request (none in the last `cooldown_seconds`), so callers alert the team once."""
    now = int(time.time())
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COALESCE(human_requested_epoch, 0) AS t FROM conversations WHERE id = ?", (conversation_id,))
    row = cursor.fetchone()
    previous = int(row["t"] or 0) if row else 0
    cursor.execute("UPDATE conversations SET human_requested_epoch = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (now, conversation_id))
    conn.commit()
    conn.close()
    return now - previous > cooldown_seconds


def list_waiting_conversations(assistant_ids: Optional[List[str]] = None, max_age_seconds: int = 86400) -> List[Dict[str, Any]]:
    """Chats where a visitor asked for a person and nobody has taken over yet.
    `assistant_ids=None` means all assistants (admins)."""
    cutoff = int(time.time()) - max_age_seconds
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT c.id, c.assistant_id, a.name AS assistant_name, c.human_requested_epoch,
            (SELECT content FROM messages m WHERE m.conversation_id = c.id AND m.role = 'user' ORDER BY m.id DESC LIMIT 1) AS last_message
        FROM conversations c
        JOIN assistants a ON a.id = c.assistant_id
        WHERE COALESCE(c.human_requested_epoch, 0) >= ?
          AND COALESCE(c.status, 'bot') != 'human'
        ORDER BY c.human_requested_epoch DESC
        LIMIT 50
    """, (cutoff,))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    if assistant_ids is not None:
        allowed = set(assistant_ids)
        rows = [r for r in rows if r["assistant_id"] in allowed]
    return rows


def clear_human_requested(conversation_id: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE conversations SET human_requested_epoch = 0 WHERE id = ?", (conversation_id,))
    conn.commit()
    conn.close()


def touch_user_presence(user_id: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET last_seen_epoch = ? WHERE id = ?", (int(time.time()), user_id))
    conn.commit()
    conn.close()


def count_operators_online(assistant_id: str, window_seconds: int = 90) -> int:
    """Signed-in dashboard users who can handle this assistant and were active recently."""
    cutoff = int(time.time()) - window_seconds
    conn = get_db()
    cursor = conn.cursor()
    # The assistant's workspace team, minus agents who are limited to other assistants.
    cursor.execute("""
        SELECT COUNT(*) AS n FROM users u
        JOIN workspace_members m ON m.user_id = u.id
        JOIN assistants a ON a.workspace_id = m.workspace_id AND a.id = ?
        WHERE COALESCE(u.last_seen_epoch, 0) >= ?
          AND (m.role != 'agent'
               OR NOT EXISTS (SELECT 1 FROM user_assistants ua JOIN assistants a2 ON a2.id = ua.assistant_id
                              WHERE ua.user_id = u.id AND a2.workspace_id = m.workspace_id)
               OR EXISTS (SELECT 1 FROM user_assistants ua WHERE ua.user_id = u.id AND ua.assistant_id = a.id))
    """, (assistant_id, cutoff))
    row = cursor.fetchone()
    conn.close()
    return int(row["n"] or 0) if row else 0


def clear_unread_operator_messages(conversation_id: str):
    """Resets the unread operator message counter."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE conversations 
        SET unread_operator_msgs = 0 
        WHERE id = ?
    """, (conversation_id,))
    conn.commit()
    conn.close()

def list_conversations_with_metadata(assistant_id: str) -> List[Dict[str, Any]]:
    """Lists visitor conversations for the admin inbox."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT c.id, c.assistant_id, c.created_at, c.updated_at,
            COALESCE(c.status, 'bot') as status,
            COALESCE(c.operator_name, '') as operator_name,
            COALESCE(c.human_requested_epoch, 0) as human_requested_epoch,
            (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) as message_count,
            (SELECT content FROM messages m WHERE m.conversation_id = c.id AND m.role = 'user' ORDER BY id ASC LIMIT 1) as first_query,
            (SELECT content FROM messages m WHERE m.conversation_id = c.id ORDER BY id DESC LIMIT 1) as last_message,
            (SELECT email FROM leads l WHERE l.assistant_id = c.assistant_id AND (l.note LIKE '%' || c.id || '%' OR l.note = c.id) ORDER BY l.id DESC LIMIT 1) as lead_email
        FROM conversations c
        WHERE c.assistant_id = ?
        ORDER BY c.updated_at DESC
        LIMIT 50
    """, (assistant_id,))
    rows = cursor.fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        if hasattr(d.get("created_at"), "isoformat"):
            d["created_at"] = d["created_at"].isoformat()
        if hasattr(d.get("updated_at"), "isoformat"):
            d["updated_at"] = d["updated_at"].isoformat()
        result.append(d)
    return result

# ----------------- Knowledge Gaps / Unanswered Questions -----------------
def is_trivial_or_conversational(text: str) -> bool:
    """Returns True if the text is a greeting, single-word filler, or conversational pleasantry."""
    cleaned = text.strip().lower()
    if len(cleaned) < 3:
        return True
    cleaned = re.sub(r'[!?.,:;~]+$', '', cleaned).strip()
    trivial_words = {
        "hi", "hello", "hey", "hola", "howdy", "sup", "yo", "good morning", "good afternoon", "good evening",
        "thanks", "thank you", "thx", "bye", "goodbye", "cya", "ok", "okay", "test", "testing", "asdf",
        "who are you", "what can you do", "help", "yes", "no", "cool", "great", "nice", "awesome"
    }
    return cleaned in trivial_words

def log_unanswered_question(assistant_id: str, question: str):
    """Logs questions where the bot lacked documentation or had low confidence, skipping greetings and filler."""
    cleaned = question.strip()
    if not cleaned or is_trivial_or_conversational(cleaned):
        return

    conn = get_db()
    cursor = conn.cursor()
    # Check if exists pending
    cursor.execute("""
        SELECT id, frequency FROM unanswered_questions
        WHERE assistant_id = ? AND lower(question) = lower(?) AND status = 'pending'
    """, (assistant_id, cleaned))
    row = cursor.fetchone()
    if row:
        cursor.execute("UPDATE unanswered_questions SET frequency = frequency + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (row["id"],))
    else:
        cursor.execute("""
            INSERT INTO unanswered_questions (assistant_id, question, frequency, status)
            VALUES (?, ?, 1, 'pending')
        """, (assistant_id, cleaned))
    conn.commit()
    conn.close()

def add_unanswered_question(assistant_id: str, question: str, status: str = "pending", resolution_notes: str = "") -> int:
    """Manually adds a knowledge gap item or custom Q&A."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO unanswered_questions (assistant_id, question, frequency, status, resolution_notes)
        VALUES (?, ?, 1, ?, ?)
    """, (assistant_id, question.strip(), status, resolution_notes.strip()))
    gap_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return gap_id

def list_unanswered_questions(assistant_id: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    if status:
        cursor.execute("""
            SELECT * FROM unanswered_questions 
            WHERE assistant_id = ? AND status = ? 
            ORDER BY frequency DESC, updated_at DESC
        """, (assistant_id, status))
    else:
        cursor.execute("""
            SELECT * FROM unanswered_questions 
            WHERE assistant_id = ? 
            ORDER BY CASE WHEN status = 'pending' THEN 0 ELSE 1 END, frequency DESC, updated_at DESC
        """, (assistant_id,))
    rows = cursor.fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        if hasattr(d.get("created_at"), "isoformat"):
            d["created_at"] = d["created_at"].isoformat()
        elif d.get("created_at") is not None:
            d["created_at"] = str(d["created_at"])
        if hasattr(d.get("updated_at"), "isoformat"):
            d["updated_at"] = d["updated_at"].isoformat()
        elif d.get("updated_at") is not None:
            d["updated_at"] = str(d["updated_at"])
        # Add boolean helper for frontend convenience
        d["resolved"] = d.get("status") == "resolved"
        result.append(d)
    return result

def resolve_unanswered_question(gap_id: int, resolution_notes: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE unanswered_questions
        SET status = 'resolved', resolution_notes = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (resolution_notes, gap_id))
    conn.commit()
    conn.close()

def delete_unanswered_question(gap_id: int):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM unanswered_questions WHERE id = ?", (gap_id,))
    conn.commit()
    conn.close()

def dismiss_unanswered_question(gap_id: int):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE unanswered_questions SET status = 'dismissed', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (gap_id,))
    conn.commit()
    conn.close()

# ----------------- Subscription Tiers -----------------
def get_subscription_info(workspace_id: Optional[str] = None) -> Dict[str, Any]:
    """Plan and usage for one workspace (or the whole platform when no workspace is given)."""
    ws = get_workspace(workspace_id) if workspace_id else None
    plan_key = (ws or {}).get("plan") or get_setting("subscription_plan", "starter")
    plan = SUBSCRIPTION_PLANS.get(plan_key, SUBSCRIPTION_PLANS["starter"])

    conn = get_db()
    cursor = conn.cursor()
    if ws:
        scope, params = " AND assistant_id IN (SELECT id FROM assistants WHERE workspace_id = ?)", (workspace_id,)
        cursor.execute("SELECT COUNT(*) FROM messages WHERE role = 'user'" + scope, params)
        total_messages = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*), COALESCE(SUM(chunk_count), 0) FROM sources WHERE 1 = 1" + scope, params)
        row = cursor.fetchone()
        cursor.execute("SELECT COUNT(*) FROM assistants WHERE workspace_id = ?", params)
    else:
        cursor.execute("SELECT COUNT(*) FROM messages WHERE role = 'user'")
        total_messages = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*), COALESCE(SUM(chunk_count), 0) FROM sources")
        row = cursor.fetchone()
        cursor.execute("SELECT COUNT(*) FROM assistants")
    total_assistants = cursor.fetchone()[0]
    total_sources = row[0]
    total_chunks = row[1]
    conn.close()

    return {
        "current_plan_key": plan_key,
        "plan_name": plan["name"],
        "price_monthly": plan["price"],
        "messages_used": total_messages,
        "messages_limit": plan["monthly_messages"],
        "pages_indexed": total_sources,
        "pages_limit": plan["page_limit"],
        "assistants_count": total_assistants,
        "assistants_limit": plan["assistants_limit"],
        "all_plans": SUBSCRIPTION_PLANS
    }

def update_subscription_plan(plan_key: str, workspace_id: Optional[str] = None):
    if plan_key not in SUBSCRIPTION_PLANS:
        return
    if workspace_id:
        update_workspace(workspace_id, plan=plan_key)
    else:
        set_setting("subscription_plan", plan_key)

# ----------------- Analytics -----------------
def get_assistant_analytics(assistant_id: str) -> Dict[str, Any]:
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM messages WHERE assistant_id = ? AND role = 'user'", (assistant_id,))
    total_queries = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM leads WHERE assistant_id = ?", (assistant_id,))
    total_leads = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*), COALESCE(SUM(chunk_count), 0) FROM sources WHERE assistant_id = ?", (assistant_id,))
    s_row = cursor.fetchone()
    total_sources = s_row[0]
    total_chunks = s_row[1]

    cursor.execute("SELECT COUNT(*) FROM unanswered_questions WHERE assistant_id = ? AND status = 'pending'", (assistant_id,))
    pending_gaps = cursor.fetchone()[0]

    conversion_rate = round((total_leads / total_queries * 100), 1) if total_queries > 0 else 0.0

    conn.close()
    return {
        "assistant_id": assistant_id,
        "total_queries": total_queries,
        "total_leads": total_leads,
        "conversion_rate": conversion_rate,
        "total_sources": total_sources,
        "total_chunks": total_chunks,
        "pending_gaps": pending_gaps,
        "monthly_limit": 2000
    }


# ----------------- Workspaces (tenancy) -----------------
# A workspace owns assistants, team members, AI keys and settings, and a plan.
# Roles inside a workspace:
#   owner  - everything, including deleting the workspace and managing owners
#   admin  - assistants, knowledge, settings, AI keys and inviting people
#   agent  - inbox, conversations, leads and knowledge gaps (read-only elsewhere);
#            if an agent has assistant assignments, they only see those assistants
# users.role = 'admin' remains the platform operator, who can see every workspace.

WORKSPACE_ROLES = ("owner", "admin", "agent")
MANAGER_ROLES = ("owner", "admin")
INVITE_TTL_SECONDS = 7 * 24 * 3600


def init_workspaces():
    conn = get_db()
    cursor = conn.cursor()
    for ddl in [
        """CREATE TABLE IF NOT EXISTS workspaces (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            plan TEXT DEFAULT 'starter',
            use_platform_keys INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS workspace_members (
            workspace_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'agent',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (workspace_id, user_id)
        )""",
        """CREATE TABLE IF NOT EXISTS workspace_settings (
            workspace_id TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT,
            PRIMARY KEY (workspace_id, key)
        )""",
        """CREATE TABLE IF NOT EXISTS workspace_invites (
            id TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL,
            email TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'agent',
            token_hash TEXT NOT NULL,
            invited_by TEXT,
            expires_epoch INTEGER NOT NULL,
            accepted_epoch INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        CRAWL_JOBS_DDL,
    ]:
        cursor.execute(ddl)
    conn.commit()
    conn.close()
    _migrate_to_workspaces()


def _migrate_to_workspaces():
    """One-time move of the single-tenant data into workspaces.

    - A member who is the only person assigned to an assistant gets their own
      workspace (as owner) containing those assistants: they created them at signup.
    - Everything else goes to a "Default workspace" owned by the platform admins.
      Members who shared assistants join it as agents restricted to those assistants.
    - The old global plan and AI provider choice move to the default workspace.
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM assistants WHERE workspace_id IS NULL OR workspace_id = ''")
    orphan_ids = [r["id"] for r in cursor.fetchall()]
    cursor.execute("SELECT COUNT(*) AS n FROM workspaces")
    has_workspaces = int(cursor.fetchone()["n"] or 0) > 0
    if has_workspaces and not orphan_ids:
        conn.close()
        return

    cursor.execute("SELECT id, name, email, role FROM users")
    users = {r["id"]: dict(r) for r in cursor.fetchall()}
    cursor.execute("SELECT user_id, assistant_id FROM user_assistants")
    grants = [(r["user_id"], r["assistant_id"]) for r in cursor.fetchall()]
    conn.close()

    members_by_asst: Dict[str, List[str]] = {}
    for uid, aid in grants:
        if uid in users and users[uid]["role"] != "admin":
            members_by_asst.setdefault(aid, []).append(uid)

    default_ws = get_setting("default_workspace_id", "")
    if not default_ws or not get_workspace(default_ws):
        default_ws = _insert_workspace("Default workspace", plan=get_setting("subscription_plan", "starter") or "starter")
        set_setting("default_workspace_id", default_ws)
        provider = get_setting("llm_provider", "")
        if provider:
            set_workspace_setting(default_ws, "llm_provider", provider)
        for u in users.values():
            if u["role"] == "admin":
                add_workspace_member(default_ws, u["id"], "owner")

    own_ws: Dict[str, str] = {}
    for aid in orphan_ids:
        owners = members_by_asst.get(aid, [])
        if len(owners) == 1:
            uid = owners[0]
            if uid not in own_ws:
                label = (users[uid].get("name") or users[uid]["email"].split("@")[0]).strip()
                own_ws[uid] = _insert_workspace(f"{label}'s workspace")
                add_workspace_member(own_ws[uid], uid, "owner")
            target = own_ws[uid]
        else:
            target = default_ws
            for uid in owners:
                if not get_member_role(default_ws, uid):
                    add_workspace_member(default_ws, uid, "agent")
        _set_assistant_workspace(aid, target)

    # Signed-up members with no assistants yet still need a workspace of their own.
    for u in users.values():
        if u["role"] != "admin" and not list_user_workspaces(u["id"]):
            label = (u.get("name") or u["email"].split("@")[0]).strip()
            ws = _insert_workspace(f"{label}'s workspace")
            add_workspace_member(ws, u["id"], "owner")


def _insert_workspace(name: str, plan: str = "starter") -> str:
    ws_id = f"ws_{uuid.uuid4().hex[:10]}"
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO workspaces (id, name, plan, use_platform_keys) VALUES (?, ?, ?, 1)",
                   (ws_id, (name or "My workspace").strip()[:80], plan if plan in SUBSCRIPTION_PLANS else "starter"))
    conn.commit()
    conn.close()
    return ws_id


def _set_assistant_workspace(assistant_id: str, workspace_id: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE assistants SET workspace_id = ? WHERE id = ?", (workspace_id, assistant_id))
    conn.commit()
    conn.close()
    _ASSISTANTS_CACHE.pop(assistant_id, None)


def create_workspace(name: str, owner_user_id: str, plan: str = "starter") -> Dict[str, Any]:
    ws_id = _insert_workspace(name, plan)
    add_workspace_member(ws_id, owner_user_id, "owner")
    return get_workspace(ws_id)


def get_workspace(workspace_id: str) -> Optional[Dict[str, Any]]:
    if not workspace_id:
        return None
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, plan, use_platform_keys, created_at FROM workspaces WHERE id = ?", (workspace_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    ws = dict(row)
    ws["use_platform_keys"] = bool(ws.get("use_platform_keys", 1))
    if hasattr(ws.get("created_at"), "isoformat"):
        ws["created_at"] = ws["created_at"].isoformat()
    return ws


def update_workspace(workspace_id: str, name: Optional[str] = None, use_platform_keys: Optional[bool] = None,
                     plan: Optional[str] = None):
    updates, values = [], []
    if name is not None and name.strip():
        updates.append("name = ?"); values.append(name.strip()[:80])
    if use_platform_keys is not None:
        updates.append("use_platform_keys = ?"); values.append(1 if use_platform_keys else 0)
    if plan is not None and plan in SUBSCRIPTION_PLANS:
        updates.append("plan = ?"); values.append(plan)
    if not updates:
        return
    values.append(workspace_id)
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(f"UPDATE workspaces SET {', '.join(updates)} WHERE id = ?", values)
    conn.commit()
    conn.close()
    _WS_SETTINGS_CACHE.pop(workspace_id, None)


def delete_workspace(workspace_id: str):
    """Deletes a workspace and everything it owns."""
    for a in list_workspace_assistant_ids(workspace_id):
        delete_assistant(a)
    conn = get_db()
    cursor = conn.cursor()
    for table in ("workspace_members", "workspace_settings", "workspace_invites"):
        cursor.execute(f"DELETE FROM {table} WHERE workspace_id = ?", (workspace_id,))
    cursor.execute("DELETE FROM workspaces WHERE id = ?", (workspace_id,))
    conn.commit()
    conn.close()
    _WS_SETTINGS_CACHE.pop(workspace_id, None)


def list_user_workspaces(user_id: str) -> List[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT w.id, w.name, w.plan, m.role
        FROM workspaces w JOIN workspace_members m ON m.workspace_id = w.id
        WHERE m.user_id = ?
        ORDER BY w.created_at ASC, w.id ASC
    """, (user_id,))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


def list_all_workspaces() -> List[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, plan FROM workspaces ORDER BY created_at ASC, id ASC")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


def get_member_role(workspace_id: str, user_id: str) -> Optional[str]:
    if not workspace_id or not user_id:
        return None
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT role FROM workspace_members WHERE workspace_id = ? AND user_id = ?", (workspace_id, user_id))
    row = cursor.fetchone()
    conn.close()
    return row["role"] if row else None


def add_workspace_member(workspace_id: str, user_id: str, role: str = "agent"):
    role = role if role in WORKSPACE_ROLES else "agent"
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT role FROM workspace_members WHERE workspace_id = ? AND user_id = ?", (workspace_id, user_id))
    if cursor.fetchone():
        cursor.execute("UPDATE workspace_members SET role = ? WHERE workspace_id = ? AND user_id = ?", (role, workspace_id, user_id))
    else:
        cursor.execute("INSERT INTO workspace_members (workspace_id, user_id, role) VALUES (?, ?, ?)", (workspace_id, user_id, role))
    conn.commit()
    conn.close()


def remove_workspace_member(workspace_id: str, user_id: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM workspace_members WHERE workspace_id = ? AND user_id = ?", (workspace_id, user_id))
    # Drop assistant assignments inside this workspace too.
    cursor.execute("""
        DELETE FROM user_assistants WHERE user_id = ? AND assistant_id IN
            (SELECT id FROM assistants WHERE workspace_id = ?)
    """, (user_id, workspace_id))
    conn.commit()
    conn.close()


def count_workspace_owners(workspace_id: str) -> int:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) AS n FROM workspace_members WHERE workspace_id = ? AND role = 'owner'", (workspace_id,))
    n = int(cursor.fetchone()["n"] or 0)
    conn.close()
    return n


def list_workspace_members(workspace_id: str) -> List[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT u.id, u.email, u.name, m.role, m.created_at, COALESCE(u.last_seen_epoch, 0) AS last_seen_epoch
        FROM workspace_members m JOIN users u ON u.id = m.user_id
        WHERE m.workspace_id = ?
        ORDER BY CASE m.role WHEN 'owner' THEN 0 WHEN 'admin' THEN 1 ELSE 2 END, u.email
    """, (workspace_id,))
    members = []
    for r in cursor.fetchall():
        m = dict(r)
        if hasattr(m.get("created_at"), "isoformat"):
            m["created_at"] = m["created_at"].isoformat()
        cursor.execute("""
            SELECT ua.assistant_id FROM user_assistants ua JOIN assistants a ON a.id = ua.assistant_id
            WHERE ua.user_id = ? AND a.workspace_id = ?
        """, (m["id"], workspace_id))
        m["assistant_ids"] = [x["assistant_id"] for x in cursor.fetchall()]
        members.append(m)
    conn.close()
    return members


def set_member_assistants(workspace_id: str, user_id: str, assistant_ids: List[str]):
    """Restrict an agent to some assistants of this workspace (empty list = all of them)."""
    allowed = set(list_workspace_assistant_ids(workspace_id))
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        DELETE FROM user_assistants WHERE user_id = ? AND assistant_id IN
            (SELECT id FROM assistants WHERE workspace_id = ?)
    """, (user_id, workspace_id))
    for aid in assistant_ids or []:
        if aid in allowed:
            cursor.execute("INSERT INTO user_assistants (user_id, assistant_id) VALUES (?, ?) ON CONFLICT DO NOTHING;", (user_id, aid))
    conn.commit()
    conn.close()


def list_workspace_assistant_ids(workspace_id: str) -> List[str]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM assistants WHERE workspace_id = ? ORDER BY created_at ASC", (workspace_id,))
    ids = [r["id"] for r in cursor.fetchall()]
    conn.close()
    return ids


def visible_assistant_ids(workspace_id: str, user_id: str, role: Optional[str]) -> List[str]:
    """Assistants in the workspace this member may see (agents can be limited to assigned ones)."""
    ids = list_workspace_assistant_ids(workspace_id)
    if role == "agent":
        assigned = set(get_user_assigned_assistants(user_id))
        mine = [a for a in ids if a in assigned]
        if mine:
            return mine
    return ids


def list_assistants_in_workspace(workspace_id: str, only_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT a.*,
            (SELECT COUNT(*) FROM sources s WHERE s.assistant_id = a.id) as total_sources,
            (SELECT COUNT(*) FROM chunks c WHERE c.assistant_id = a.id) as total_chunks,
            (SELECT COUNT(*) FROM leads l WHERE l.assistant_id = a.id) as total_leads,
            (SELECT COUNT(*) FROM messages m WHERE m.assistant_id = a.id AND m.role = 'user') as total_messages
        FROM assistants a
        WHERE a.workspace_id = ?
        ORDER BY a.created_at ASC
    """, (workspace_id,))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    if only_ids is not None:
        keep = set(only_ids)
        rows = [r for r in rows if r["id"] in keep]
    return rows


def assistant_workspace_id(assistant_id: str) -> str:
    asst = get_assistant(assistant_id) if assistant_id else None
    return (asst or {}).get("workspace_id") or ""


# ---- Workspace settings (AI provider, API keys, ...) ----
_WS_SETTINGS_CACHE: Dict[str, Dict[str, Any]] = {}
_WS_SETTINGS_TTL = 30.0


def get_workspace_settings(workspace_id: str) -> Dict[str, str]:
    if not workspace_id:
        return {}
    cached = _WS_SETTINGS_CACHE.get(workspace_id)
    if cached and time.time() - cached["ts"] < _WS_SETTINGS_TTL:
        return cached["values"]
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT key, value FROM workspace_settings WHERE workspace_id = ?", (workspace_id,))
    values = {r["key"]: r["value"] for r in cursor.fetchall()}
    conn.close()
    _WS_SETTINGS_CACHE[workspace_id] = {"ts": time.time(), "values": values}
    return values


def get_workspace_setting(workspace_id: str, key: str, default: str = "") -> str:
    return get_workspace_settings(workspace_id).get(key, default) or default


def set_workspace_setting(workspace_id: str, key: str, value: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM workspace_settings WHERE workspace_id = ? AND key = ?", (workspace_id, key))
    if value is not None and value != "":
        cursor.execute("INSERT INTO workspace_settings (workspace_id, key, value) VALUES (?, ?, ?)", (workspace_id, key, value))
    conn.commit()
    conn.close()
    _WS_SETTINGS_CACHE.pop(workspace_id, None)


# ---- Invites ----
def _token_hash(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def create_invite(workspace_id: str, email: str, role: str, invited_by: str) -> Dict[str, Any]:
    """Creates (or refreshes) an invite and returns it with the one-time token."""
    email = email.strip().lower()
    role = role if role in WORKSPACE_ROLES else "agent"
    token = secrets.token_urlsafe(32)
    invite_id = f"inv_{uuid.uuid4().hex[:10]}"
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM workspace_invites WHERE workspace_id = ? AND email = ? AND COALESCE(accepted_epoch, 0) = 0",
                   (workspace_id, email))
    cursor.execute("""
        INSERT INTO workspace_invites (id, workspace_id, email, role, token_hash, invited_by, expires_epoch)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (invite_id, workspace_id, email, role, _token_hash(token), invited_by, int(time.time()) + INVITE_TTL_SECONDS))
    conn.commit()
    conn.close()
    return {"id": invite_id, "workspace_id": workspace_id, "email": email, "role": role, "token": token}


def list_pending_invites(workspace_id: str) -> List[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, email, role, expires_epoch, created_at FROM workspace_invites
        WHERE workspace_id = ? AND COALESCE(accepted_epoch, 0) = 0 AND expires_epoch > ?
        ORDER BY created_at DESC
    """, (workspace_id, int(time.time())))
    rows = []
    for r in cursor.fetchall():
        d = dict(r)
        if hasattr(d.get("created_at"), "isoformat"):
            d["created_at"] = d["created_at"].isoformat()
        rows.append(d)
    conn.close()
    return rows


def revoke_invite(workspace_id: str, invite_id: str) -> bool:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM workspace_invites WHERE id = ? AND workspace_id = ? AND COALESCE(accepted_epoch, 0) = 0",
                   (invite_id, workspace_id))
    changed = cursor.rowcount if hasattr(cursor, "rowcount") else 1
    conn.commit()
    conn.close()
    return bool(changed)


def get_invite_by_token(token: str) -> Optional[Dict[str, Any]]:
    """A pending, unexpired invite for this token, with the workspace name."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT i.id, i.workspace_id, i.email, i.role, i.expires_epoch, w.name AS workspace_name
        FROM workspace_invites i JOIN workspaces w ON w.id = i.workspace_id
        WHERE i.token_hash = ? AND COALESCE(i.accepted_epoch, 0) = 0 AND i.expires_epoch > ?
    """, (_token_hash(token), int(time.time())))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def accept_invite(token: str, user_id: str, user_email: str) -> Optional[Dict[str, Any]]:
    """Adds the user to the invite's workspace. The signed-in email must match the invited one."""
    invite = get_invite_by_token(token)
    if not invite or invite["email"] != (user_email or "").strip().lower():
        return None
    existing = get_member_role(invite["workspace_id"], user_id)
    # Accepting never downgrades someone who is already a member.
    rank = {"owner": 0, "admin": 1, "agent": 2}
    if not existing or rank[invite["role"]] < rank.get(existing, 3):
        add_workspace_member(invite["workspace_id"], user_id, invite["role"])
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE workspace_invites SET accepted_epoch = ? WHERE id = ?", (int(time.time()), invite["id"]))
    conn.commit()
    conn.close()
    return invite


def count_workspace_visitor_messages_since(workspace_id: str, since: str) -> int:
    """Visitor messages to this workspace's assistants since a 'YYYY-MM-DD HH:MM:SS' UTC timestamp."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(*) AS n FROM messages
        WHERE role = 'user' AND created_at >= ?
          AND assistant_id IN (SELECT id FROM assistants WHERE workspace_id = ?)
    """, (since, workspace_id))
    n = int(cursor.fetchone()["n"] or 0)
    conn.close()
    return n


def set_email_verified(user_id: str, verified: bool = True):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET email_verified = ? WHERE id = ?", (1 if verified else 0, user_id))
    conn.commit()
    conn.close()


# ----------------- Background crawl jobs -----------------
# Crawls run as resumable jobs: each step processes a few pages within a time budget
# and saves its frontier, so large sites work on serverless hosts (see app/jobs.py).

JOB_ACTIVE_STATUSES = ("queued", "running")

CRAWL_JOBS_DDL = """CREATE TABLE IF NOT EXISTS crawl_jobs (
    id TEXT PRIMARY KEY,
    assistant_id TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'crawl',
    trigger_type TEXT DEFAULT 'manual',
    start_url TEXT,
    max_pages INTEGER DEFAULT 50,
    status TEXT NOT NULL DEFAULT 'queued',
    pages_done INTEGER DEFAULT 0,
    pages_added INTEGER DEFAULT 0,
    pages_updated INTEGER DEFAULT 0,
    pages_unchanged INTEGER DEFAULT 0,
    pages_removed INTEGER DEFAULT 0,
    pages_failed INTEGER DEFAULT 0,
    chunks_added INTEGER DEFAULT 0,
    queue_size INTEGER DEFAULT 0,
    current_url TEXT DEFAULT '',
    error TEXT DEFAULT '',
    state_json TEXT,
    lock_token TEXT DEFAULT '',
    locked_until INTEGER DEFAULT 0,
    created_by TEXT DEFAULT '',
    created_epoch INTEGER DEFAULT 0,
    updated_epoch INTEGER DEFAULT 0,
    finished_epoch INTEGER DEFAULT 0
)"""

_JOB_PUBLIC_FIELDS = (
    "id", "assistant_id", "kind", "trigger_type", "start_url", "max_pages", "status", "pages_done", "pages_added",
    "pages_updated", "pages_unchanged", "pages_removed", "pages_failed", "chunks_added", "queue_size",
    "current_url", "error", "created_epoch", "updated_epoch", "finished_epoch",
)


def create_crawl_job(assistant_id: str, kind: str, start_url: str, max_pages: int, state: Dict[str, Any],
                     trigger: str = "manual", created_by: str = "") -> Dict[str, Any]:
    job_id = f"job_{uuid.uuid4().hex[:12]}"
    now = int(time.time())
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO crawl_jobs (id, assistant_id, kind, trigger_type, start_url, max_pages, status, queue_size,
                                state_json, created_by, created_epoch, updated_epoch)
        VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?)
    """, (job_id, assistant_id, kind, trigger, start_url, int(max_pages), len(state.get("frontier", [])),
          json.dumps(state), created_by, now, now))
    conn.commit()
    conn.close()
    return get_crawl_job(job_id)


def get_crawl_job(job_id: str, with_state: bool = False) -> Optional[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM crawl_jobs WHERE id = ?", (job_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    job = {k: row[k] for k in _JOB_PUBLIC_FIELDS}
    if with_state:
        job["state"] = json.loads(row["state_json"]) if row["state_json"] else {}
        job["lock_token"] = row["lock_token"]
    return job


def list_crawl_jobs(assistant_id: str, limit: int = 10) -> List[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(f"SELECT {', '.join(_JOB_PUBLIC_FIELDS)} FROM crawl_jobs WHERE assistant_id = ? ORDER BY created_epoch DESC LIMIT ?",
                   (assistant_id, limit))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


def active_crawl_job(assistant_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM crawl_jobs WHERE assistant_id = ? AND status IN ('queued', 'running') ORDER BY created_epoch ASC LIMIT 1",
                   (assistant_id,))
    row = cursor.fetchone()
    conn.close()
    return get_crawl_job(row["id"]) if row else None


def runnable_crawl_job_ids(limit: int = 5) -> List[str]:
    """Active jobs nobody is working on right now, oldest first."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id FROM crawl_jobs
        WHERE status IN ('queued', 'running') AND COALESCE(locked_until, 0) < ?
        ORDER BY updated_epoch ASC LIMIT ?
    """, (int(time.time()), limit))
    ids = [r["id"] for r in cursor.fetchall()]
    conn.close()
    return ids


def claim_crawl_job(job_id: str, lease_seconds: int) -> Optional[str]:
    """Takes the job's lease so only one worker runs it at a time; returns the lock token or None."""
    token = secrets.token_hex(8)
    now = int(time.time())
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE crawl_jobs SET lock_token = ?, locked_until = ?
        WHERE id = ? AND status IN ('queued', 'running') AND COALESCE(locked_until, 0) < ?
    """, (token, now + lease_seconds, job_id, now))
    conn.commit()
    cursor.execute("SELECT lock_token FROM crawl_jobs WHERE id = ?", (job_id,))
    row = cursor.fetchone()
    conn.close()
    return token if row and row["lock_token"] == token else None


def save_crawl_job(job_id: str, token: str, fields: Dict[str, Any], state: Optional[Dict[str, Any]] = None,
                   release: bool = False) -> bool:
    """Writes progress if this worker still holds the lease (a cancel clears it)."""
    allowed = set(_JOB_PUBLIC_FIELDS) - {"id", "assistant_id", "created_epoch"}
    sets, values = [], []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k} = ?"); values.append(v)
    if state is not None:
        sets.append("state_json = ?"); values.append(json.dumps(state))
    sets.append("updated_epoch = ?"); values.append(int(time.time()))
    if release:
        sets.append("locked_until = 0")
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT lock_token, status FROM crawl_jobs WHERE id = ?", (job_id,))
    row = cursor.fetchone()
    if not row or row["lock_token"] != token or row["status"] not in JOB_ACTIVE_STATUSES:
        conn.close()
        return False
    cursor.execute(f"UPDATE crawl_jobs SET {', '.join(sets)} WHERE id = ?", values + [job_id])
    conn.commit()
    conn.close()
    return True


def cancel_crawl_job(job_id: str) -> bool:
    now = int(time.time())
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT status FROM crawl_jobs WHERE id = ?", (job_id,))
    row = cursor.fetchone()
    if not row or row["status"] not in JOB_ACTIVE_STATUSES:
        conn.close()
        return False
    cursor.execute("""
        UPDATE crawl_jobs SET status = 'cancelled', lock_token = '', locked_until = 0,
               finished_epoch = ?, updated_epoch = ? WHERE id = ?
    """, (now, now, job_id))
    conn.commit()
    conn.close()
    return True


def get_url_source(assistant_id: str, url: str) -> Optional[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, url, title, content_hash FROM sources
        WHERE assistant_id = ? AND source_type = 'url' AND url = ?
        ORDER BY id DESC LIMIT 1
    """, (assistant_id, url))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def list_url_source_urls(assistant_id: str) -> List[str]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT url FROM sources WHERE assistant_id = ? AND source_type = 'url' AND url LIKE 'http%'",
                   (assistant_id,))
    urls = [r["url"] for r in cursor.fetchall()]
    conn.close()
    return urls


def set_source_content_hash(source_id: int, content_hash: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE sources SET content_hash = ? WHERE id = ?", (content_hash, source_id))
    conn.commit()
    conn.close()


def assistants_due_for_recrawl(now: Optional[int] = None) -> List[Dict[str, Any]]:
    """Assistants whose re-crawl schedule says they're due and that have no crawl running."""
    now = now or int(time.time())
    intervals = {"daily": 86400, "weekly": 7 * 86400}
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, recrawl_frequency, COALESCE(last_recrawl_epoch, 0) AS last_recrawl_epoch FROM assistants
        WHERE recrawl_frequency IN ('daily', 'weekly')
          AND NOT EXISTS (SELECT 1 FROM crawl_jobs j WHERE j.assistant_id = assistants.id AND j.status IN ('queued', 'running'))
    """)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return [r for r in rows if now - int(r["last_recrawl_epoch"] or 0) >= intervals[r["recrawl_frequency"]]]


def mark_assistant_recrawled(assistant_id: str, when: Optional[int] = None):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE assistants SET last_recrawl_epoch = ? WHERE id = ?", (when or int(time.time()), assistant_id))
    conn.commit()
    conn.close()
    _ASSISTANTS_CACHE.pop(assistant_id, None)
