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
import shutil
from datetime import datetime
from typing import List, Dict, Any, Optional

_is_serverless = bool(os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))
_repo_db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "weaveflow.db")

if _is_serverless:
    DB_PATH = os.environ.get("DB_PATH", "/tmp/weaveflow.db")
    if not os.path.exists(DB_PATH) and os.path.exists(_repo_db_path):
        try:
            shutil.copy2(_repo_db_path, DB_PATH)
        except Exception:
            pass
else:
    DB_PATH = os.environ.get("DB_PATH", _repo_db_path)

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

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
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
        ("assistants", "show_branding", "INTEGER DEFAULT 1")
    ]
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
            position, suggested_questions, lead_capture_enabled, voice_enabled
        ) VALUES (
            'asst_default', 'AcmeCloud AI Assistant', 'acmecloud.io', '#4F46E5',
            'Hi there! 👋 How can I help you today?', '⚡',
            'bottom-right', 'What are your products?\nHow much does it cost?\nHow do I contact support?', 1, 1
        );
        """)

    conn.commit()
    conn.close()

# ----------------- Assistant CRUD -----------------
def create_assistant(name: str, domain: str = "*", primary_color: str = "#4F46E5", welcome_message: str = "", suggested_questions: str = "") -> str:
    asst_id = f"asst_{uuid.uuid4().hex[:8]}"
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO assistants (
            id, name, domain, primary_color, welcome_message, suggested_questions
        ) VALUES (?, ?, ?, ?, ?, ?)
    """, (
        asst_id,
        name,
        domain or "*",
        primary_color or "#4F46E5",
        welcome_message or "Hello! 👋 How can I help you today?",
        suggested_questions or "What do you offer?\nHow does pricing work?\nCan I talk to sales?"
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

def get_assistant(assistant_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM assistants WHERE id = ?", (assistant_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def update_assistant(assistant_id: str, data: Dict[str, Any]) -> bool:
    allowed_keys = [
        "name", "domain", "primary_color", "welcome_message", "bot_avatar",
        "position", "suggested_questions", "lead_capture_enabled", "voice_enabled",
        "notification_email", "webhook_url",
        "theme_mode", "widget_subtitle", "launcher_text", "launcher_style",
        "teaser_message", "lead_title", "lead_fields", "sound_enabled", "show_branding"
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
    cursor.execute("DELETE FROM assistants WHERE id = ?", (assistant_id,))
    conn.commit()
    conn.close()

# ----------------- Settings Helpers -----------------
def get_setting(key: str, default: str = "") -> str:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row["value"] if row else default

def set_setting(key: str, value: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

# ----------------- Source & Chunk Helpers -----------------
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
    return source_id

def add_chunk(assistant_id: str, source_id: int, chunk_index: int, content: str, title: str, url: str, embedding: List[float]):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO chunks (assistant_id, source_id, chunk_index, content, title, url, embedding)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (assistant_id, source_id, chunk_index, content, title, url, json.dumps(embedding)))
    conn.commit()
    conn.close()

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
    cursor.execute("DELETE FROM chunks WHERE source_id = ?", (source_id,))
    cursor.execute("DELETE FROM sources WHERE id = ?", (source_id,))
    conn.commit()
    conn.close()

def get_chunks_for_assistant(assistant_id: str) -> List[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, assistant_id, source_id, chunk_index, content, title, url, embedding
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
            "embedding": emb
        })
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
    return [dict(r) for r in rows]

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
    lead_prompted: bool = False
):
    ensure_conversation(conversation_id, assistant_id)
    conn = get_db()
    cursor = conn.cursor()
    sources_json = json.dumps(sources) if sources else None
    cursor.execute("""
        INSERT INTO messages (conversation_id, assistant_id, role, content, sources_json, lead_prompted)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (conversation_id, assistant_id, role, content, sources_json, 1 if lead_prompted else 0))
    cursor.execute("UPDATE conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (conversation_id,))
    conn.commit()
    conn.close()

def get_conversation_history(conversation_id: str, limit: int = 10) -> List[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT role, content, sources_json, lead_prompted, created_at
        FROM messages
        WHERE conversation_id = ?
        ORDER BY id ASC
        LIMIT ?
    """, (conversation_id, limit))
    rows = cursor.fetchall()
    conn.close()
    
    msgs = []
    for r in rows:
        item = {
            "role": r["role"],
            "content": r["content"],
            "lead_prompted": bool(r["lead_prompted"]),
            "created_at": r["created_at"],
            "sources": json.loads(r["sources_json"]) if r["sources_json"] else []
        }
        msgs.append(item)
    return msgs

def list_conversations_with_metadata(assistant_id: str) -> List[Dict[str, Any]]:
    """Lists visitor conversations for the admin inbox."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT c.id, c.assistant_id, c.created_at, c.updated_at,
            (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) as message_count,
            (SELECT content FROM messages m WHERE m.conversation_id = c.id AND m.role = 'user' ORDER BY id ASC LIMIT 1) as first_query,
            (SELECT content FROM messages m WHERE m.conversation_id = c.id ORDER BY id DESC LIMIT 1) as last_message,
            (SELECT email FROM leads l WHERE l.assistant_id = c.assistant_id AND l.note LIKE '%' || c.id || '%' OR l.created_at >= c.created_at LIMIT 1) as lead_email
        FROM conversations c
        WHERE c.assistant_id = ?
        ORDER BY c.updated_at DESC
        LIMIT 50
    """, (assistant_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ----------------- Knowledge Gaps / Unanswered Questions -----------------
def log_unanswered_question(assistant_id: str, question: str):
    """Logs questions where the bot lacked documentation or had low confidence."""
    conn = get_db()
    cursor = conn.cursor()
    cleaned = question.strip()
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

def list_unanswered_questions(assistant_id: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    if status:
        cursor.execute("SELECT * FROM unanswered_questions WHERE assistant_id = ? AND status = ? ORDER BY frequency DESC, updated_at DESC", (assistant_id, status))
    else:
        cursor.execute("SELECT * FROM unanswered_questions WHERE assistant_id = ? ORDER BY status ASC, frequency DESC", (assistant_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

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

# ----------------- Subscription Tiers -----------------
def get_subscription_info() -> Dict[str, Any]:
    plan_key = get_setting("subscription_plan", "starter")
    plan = SUBSCRIPTION_PLANS.get(plan_key, SUBSCRIPTION_PLANS["starter"])

    # Aggregate message usage across all assistants
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM messages WHERE role = 'user'")
    total_messages = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*), COALESCE(SUM(chunk_count), 0) FROM sources")
    row = cursor.fetchone()
    total_sources = row[0]
    total_chunks = row[1]

    cursor.execute("SELECT COUNT(*) FROM assistants")
    total_assistants = cursor.fetchone()[0]
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

def update_subscription_plan(plan_key: str):
    if plan_key in SUBSCRIPTION_PLANS:
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
