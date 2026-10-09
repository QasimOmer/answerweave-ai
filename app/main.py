"""
WeaveFlow AI - Complete SaaS Platform API
Multi-Assistant Website Management, Grounded RAG, AI Call-Prep Briefs,
PDF & File Ingestion, Visitor Conversation Inbox, Knowledge Gaps resolution,
and Subscription Tier Management.
"""

import os
import io
import csv
import uuid
import re
import urllib.parse
import requests
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, Request, Response, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from app.db import (
    init_db,
    create_assistant,
    list_assistants,
    get_assistant,
    update_assistant,
    delete_assistant,
    add_source,
    add_chunk,
    update_source_chunk_count,
    list_sources,
    delete_source,
    add_lead,
    list_leads,
    update_lead_status,
    add_message,
    get_conversation_history,
    list_conversations_with_metadata,
    list_unanswered_questions,
    resolve_unanswered_question,
    get_subscription_info,
    update_subscription_plan,
    get_assistant_analytics,
    create_user,
    authenticate_user,
    get_user_by_email
)
from app.config import (
    get_bot_settings,
    update_bot_settings,
    get_api_key,
    DEFAULT_GEMINI_MODEL,
    FALLBACK_GEMINI_MODEL
)
from app.ingestion import fetch_url, crawl_website, crawl_sitemap, parse_uploaded_file, chunk_text
from app.embeddings import generate_embeddings_batch
from app.rag import (
    generate_grounded_response,
    generate_call_prep_brief,
    call_siliconflow_llm,
    call_deepseek_llm,
    call_qwen_llm,
    call_groq_llm,
    call_openai_llm,
    call_openrouter_llm
)
from google import genai
from google.genai import types

init_db()

app = FastAPI(
    title="WeaveFlow AI SaaS Engine",
    description="Multi-tenant grounded AI website assistant platform with lead capture, file uploads, conversation inbox, and Call-Prep intelligence",
    version="2.2.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# ----------------- Request Models -----------------
class AuthSignupRequest(BaseModel):
    email: str
    password: str
    name: str

class AuthLoginRequest(BaseModel):
    email: str
    password: str

class CreateAssistantRequest(BaseModel):
    name: str
    domain: Optional[str] = "*"
    website_url: Optional[str] = None
    crawl_whole_site: Optional[bool] = True
    primary_color: Optional[str] = "#0f172a"
    welcome_message: Optional[str] = None
    suggested_questions: Optional[str] = None
    bot_avatar: Optional[str] = "⚡"
    widget_subtitle: Optional[str] = "Online • AI Assistant"

class UpdateAssistantRequest(BaseModel):
    name: Optional[str] = None
    domain: Optional[str] = None
    primary_color: Optional[str] = None
    welcome_message: Optional[str] = None
    bot_avatar: Optional[str] = None
    position: Optional[str] = None
    suggested_questions: Optional[str] = None
    lead_capture_enabled: Optional[bool] = None
    voice_enabled: Optional[bool] = None
    notification_email: Optional[str] = None
    webhook_url: Optional[str] = None
    theme_mode: Optional[str] = None
    widget_subtitle: Optional[str] = None
    launcher_text: Optional[str] = None
    launcher_style: Optional[str] = None
    teaser_message: Optional[str] = None
    lead_title: Optional[str] = None
    lead_fields: Optional[str] = None
    sound_enabled: Optional[bool] = None
    show_branding: Optional[bool] = None

class IngestUrlRequest(BaseModel):
    url: str
    crawl_depth: int = 50

class IngestSitemapRequest(BaseModel):
    sitemap_url: str
    max_pages: int = 100

class IngestTextRequest(BaseModel):
    title: str
    content: str
    url: Optional[str] = None

class ResolveGapRequest(BaseModel):
    official_answer: str

class UpgradePlanRequest(BaseModel):
    plan_key: str

class ChatRequest(BaseModel):
    assistant_id: Optional[str] = None
    conversation_id: Optional[str] = None
    message: str

class LeadRequest(BaseModel):
    assistant_id: Optional[str] = None
    conversation_id: Optional[str] = None
    email: str
    name: Optional[str] = ""
    phone: Optional[str] = ""
    note: Optional[str] = ""

class UpdateLeadStatusRequest(BaseModel):
    status: str

class GlobalSettingsRequest(BaseModel):
    llm_provider: Optional[str] = None
    gemini_api_key: Optional[str] = None
    groq_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    deepseek_api_key: Optional[str] = None
    siliconflow_api_key: Optional[str] = None
    qwen_api_key: Optional[str] = None
    openrouter_api_key: Optional[str] = None

class TestLLMRequest(BaseModel):
    provider: str
    api_key: Optional[str] = None

# ----------------- Dashboard & Landing Page Routes -----------------
@app.get("/")
def get_root():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))

@app.get("/dashboard")
def get_dashboard_page():
    return FileResponse(os.path.join(STATIC_DIR, "dashboard.html"))

@app.get("/demo")
def get_demo_page():
    return FileResponse(os.path.join(STATIC_DIR, "demo.html"))

@app.get("/widget.js")
def get_widget_js():
    return FileResponse(os.path.join(STATIC_DIR, "widget.js"), media_type="application/javascript")

# ----------------- Admin Auth Endpoints -----------------
@app.post("/api/auth/signup")
def api_signup(req: AuthSignupRequest):
    if len(req.password) < 4:
        raise HTTPException(status_code=400, detail="Password must be at least 4 characters.")
    user = create_user(req.email, req.password, req.name)
    if not user:
        raise HTTPException(status_code=400, detail="User with this email already exists.")
    return {"status": "success", "user": user}

@app.post("/api/auth/login")
def api_login(req: AuthLoginRequest):
    user = authenticate_user(req.email, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    return {"status": "success", "user": user}

@app.get("/api/auth/me")
def api_get_me(email: Optional[str] = None):
    target_email = email.strip().lower() if email else "admin@answerweave.ai"
    user = get_user_by_email(target_email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    u_dict = dict(user)
    u_dict.pop("password_hash", None)
    return u_dict

# ----------------- Multi-Assistant SaaS Endpoints -----------------
@app.get("/api/assistants")
def api_list_assistants():
    return list_assistants()

@app.post("/api/assistants")
def api_create_assistant(req: CreateAssistantRequest):
    target_domain = req.domain or "*"
    if req.website_url and target_domain == "*":
        try:
            parsed = urllib.parse.urlparse(req.website_url if "://" in req.website_url else "https://" + req.website_url)
            target_domain = parsed.netloc or req.website_url
        except Exception:
            target_domain = req.website_url

    asst_id = create_assistant(
        name=req.name,
        domain=target_domain,
        primary_color=req.primary_color or "#0f172a",
        welcome_message=req.welcome_message or f"Hello! 👋 Welcome to {req.name}. How can I assist you today?",
        suggested_questions=req.suggested_questions or "What services do you provide?\nHow does pricing work?\nHow can I speak to someone?",
        bot_avatar=req.bot_avatar or "⚡",
        widget_subtitle=req.widget_subtitle or "Online • AI Assistant"
    )

    pages_indexed = 0
    total_chunks = 0
    # Auto-crawl whole website if provided
    if req.website_url and req.crawl_whole_site:
        url = req.website_url.strip()
        if not url.startswith("http://") and not url.startswith("https://"):
            url = "https://" + url
        try:
            pages = crawl_website(url, max_pages=50)
            for p in pages:
                src_id = add_source(asst_id, "url", p["title"], p["url"], p["content"])
                chunks = chunk_text(p["content"])
                if chunks:
                    embs = generate_embeddings_batch(chunks)
                    for idx, (c_text, emb) in enumerate(zip(chunks, embs)):
                        add_chunk(asst_id, src_id, idx, c_text, p["title"], p["url"], emb)
                    update_source_chunk_count(src_id, len(chunks))
                    total_chunks += len(chunks)
                pages_indexed += 1
        except Exception as e:
            print(f"Auto-crawl warning during assistant creation: {e}")

    return {
        "status": "success",
        "assistant_id": asst_id,
        "assistant": get_assistant(asst_id),
        "pages_indexed": pages_indexed,
        "total_chunks": total_chunks
    }

def is_domain_allowed(allowed_domain_pattern: Optional[str], host: Optional[str]) -> bool:
    if not allowed_domain_pattern or allowed_domain_pattern.strip() == "*":
        return True
    if not host:
        return False
    
    host = host.lower().split(":")[0].strip()
    if host in ["localhost", "127.0.0.1", "testserver"] or host.endswith(".vercel.app") or host == "vercel.app":
        return True

    patterns = [p.strip().lower() for p in allowed_domain_pattern.split(",") if p.strip()]
    for pat in patterns:
        if pat == "*":
            return True
        pat = re.sub(r"^https?://", "", pat).split("/")[0].split(":")[0].strip()
        if not pat:
            continue
        if pat.startswith("*."):
            base = pat[2:]
            if host == base or host.endswith("." + base):
                return True
        else:
            if host == pat or host == f"www.{pat}" or pat == f"www.{host}":
                return True
            if host.endswith("." + pat):
                return True
    return False

def verify_assistant_domain_access(asst: Dict[str, Any], request: Request):
    allowed = asst.get("domain")
    if not allowed or allowed.strip() == "*":
        return
    
    # 1. Check Origin / Referer headers
    origin = request.headers.get("origin") or request.headers.get("referer")
    host = None
    if origin:
        try:
            parsed = urllib.parse.urlparse(origin if "://" in origin else f"https://{origin}")
            host = parsed.netloc.split(":")[0].strip()
        except Exception:
            pass
            
    # 2. Check X-Host-Domain header or host query param
    if not host:
        header_host = request.headers.get("x-host-domain") or request.headers.get("x-weaveflow-host") or request.query_params.get("host")
        if header_host:
            host = header_host.split(":")[0].strip()

    # 3. Check client host for local test clients
    if not host and request.client and request.client.host in ["127.0.0.1", "localhost", "testclient"]:
        host = "localhost"

    if not is_domain_allowed(allowed, host):
        raise HTTPException(
            status_code=403, 
            detail=f"Access denied: Website domain '{host or 'unknown'}' is not authorized to use assistant '{asst.get('name')}'. Allowed domain whitelist: '{allowed}'."
        )

@app.get("/api/assistants/{asst_id}")
def api_get_assistant(asst_id: str, request: Request):
    asst = get_assistant(asst_id)
    if not asst:
        raise HTTPException(status_code=404, detail="Assistant not found")
    verify_assistant_domain_access(asst, request)
    return asst

@app.put("/api/assistants/{asst_id}")
@app.patch("/api/assistants/{asst_id}")
def api_update_assistant(asst_id: str, req: UpdateAssistantRequest):
    data = req.dict(exclude_unset=True)
    if "lead_capture_enabled" in data:
        data["lead_capture_enabled"] = 1 if data["lead_capture_enabled"] else 0
    if "voice_enabled" in data:
        data["voice_enabled"] = 1 if data["voice_enabled"] else 0
    if "sound_enabled" in data:
        data["sound_enabled"] = 1 if data["sound_enabled"] else 0
    if "show_branding" in data:
        data["show_branding"] = 1 if data["show_branding"] else 0
    success = update_assistant(asst_id, data)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to update assistant")
    return {"status": "success", "assistant": get_assistant(asst_id)}

@app.delete("/api/assistants/{asst_id}")
def api_delete_assistant(asst_id: str):
    delete_assistant(asst_id)
    remaining = list_assistants()
    active_id = remaining[0]["id"] if remaining else None
    if not remaining:
        active_id = create_assistant("New Website Project", "*")
    return {"status": "success", "deleted_id": asst_id, "active_id": active_id}

@app.get("/api/assistants/{asst_id}/analytics")
def api_get_assistant_analytics(asst_id: str):
    return get_assistant_analytics(asst_id)

# ----------------- Knowledge Ingestion (URLs, Files, Sitemaps) -----------------
@app.post("/api/assistants/{asst_id}/sources/upload")
async def api_upload_file(asst_id: str, file: UploadFile = File(...)):
    """Uploads and parses a PDF, TXT, Markdown, or CSV file."""
    try:
        content_bytes = await file.read()
        parsed = parse_uploaded_file(content_bytes, file.filename)
        
        src_id = add_source(asst_id, "file", parsed["title"], f"File: {file.filename}", parsed["content"])
        chunks = chunk_text(parsed["content"])
        if chunks:
            embs = generate_embeddings_batch(chunks)
            for idx, (c_text, emb) in enumerate(zip(chunks, embs)):
                add_chunk(asst_id, src_id, idx, c_text, parsed["title"], f"File: {file.filename}", emb)
            update_source_chunk_count(src_id, len(chunks))
            
        return {
            "status": "success",
            "assistant_id": asst_id,
            "filename": file.filename,
            "title": parsed["title"],
            "chunks_count": len(chunks)
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/assistants/{asst_id}/sources/sitemap")
def api_ingest_sitemap(asst_id: str, req: IngestSitemapRequest):
    """Parses a sitemap.xml and ingests discovered URLs."""
    urls = crawl_sitemap(req.sitemap_url, max_urls=req.max_pages)
    if not urls:
        raise HTTPException(status_code=400, detail="No URLs extracted from sitemap.")

    indexed = []
    total_chunks = 0
    for u in urls:
        try:
            page = fetch_url(u)
            src_id = add_source(asst_id, "url", page["title"], u, page["content"])
            chunks = chunk_text(page["content"])
            if chunks:
                embs = generate_embeddings_batch(chunks)
                for idx, (c_text, emb) in enumerate(zip(chunks, embs)):
                    add_chunk(asst_id, src_id, idx, c_text, page["title"], u, emb)
                update_source_chunk_count(src_id, len(chunks))
                total_chunks += len(chunks)
            indexed.append({"id": src_id, "title": page["title"], "url": u, "chunks": len(chunks)})
        except Exception:
            continue

    return {
        "status": "success",
        "assistant_id": asst_id,
        "sitemap_url": req.sitemap_url,
        "pages_indexed": len(indexed),
        "total_chunks": total_chunks,
        "sources": indexed
    }

@app.post("/api/assistants/{asst_id}/sources")
async def api_ingest_source_generic(asst_id: str, request: Request):
    """Universal dispatcher for POST /api/assistants/{asst_id}/sources."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    if "content" in data and "title" in data:
        req = IngestTextRequest(title=data["title"], content=data["content"], url=data.get("url"))
        return api_ingest_text(asst_id, req)
    elif "sitemap_url" in data or (str(data.get("url", "")).endswith(".xml")):
        s_url = data.get("sitemap_url") or data.get("url")
        req = IngestSitemapRequest(sitemap_url=s_url, max_pages=data.get("crawl_depth", 10))
        return api_ingest_sitemap(asst_id, req)
    elif "url" in data:
        req = IngestUrlRequest(url=data["url"], crawl_depth=data.get("crawl_depth", 50))
        return api_ingest_url(asst_id, req)
    raise HTTPException(status_code=400, detail="Payload must include 'url' or 'title' & 'content'")

@app.post("/api/assistants/{asst_id}/sources/url")
def api_ingest_url(asst_id: str, req: IngestUrlRequest):
    url = req.url.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url

    pages_to_index = []
    if req.crawl_depth > 1:
        pages_to_index = crawl_website(url, max_pages=req.crawl_depth)
    else:
        single = fetch_url(url)
        pages_to_index = [{
            "url": url,
            "title": single["title"],
            "content": single["content"]
        }]

    if not pages_to_index:
        raise HTTPException(status_code=400, detail="No readable content found at URL.")

    indexed = []
    total_chunks = 0
    for p in pages_to_index:
        src_id = add_source(asst_id, "url", p["title"], p["url"], p["content"])
        chunks = chunk_text(p["content"])
        if chunks:
            embs = generate_embeddings_batch(chunks)
            for idx, (c_text, emb) in enumerate(zip(chunks, embs)):
                add_chunk(asst_id, src_id, idx, c_text, p["title"], p["url"], emb)
            update_source_chunk_count(src_id, len(chunks))
            total_chunks += len(chunks)
        indexed.append({"id": src_id, "title": p["title"], "url": p["url"], "chunks": len(chunks)})

    return {
        "status": "success",
        "assistant_id": asst_id,
        "pages_indexed": len(indexed),
        "total_chunks": total_chunks,
        "sources": indexed
    }

@app.post("/api/assistants/{asst_id}/sources/text")
def api_ingest_text(asst_id: str, req: IngestTextRequest):
    if not req.content.strip():
        raise HTTPException(status_code=400, detail="Content cannot be empty.")

    src_id = add_source(asst_id, "text", req.title, req.url or "Text Document", req.content)
    chunks = chunk_text(req.content)
    if chunks:
        embs = generate_embeddings_batch(chunks)
        for idx, (c_text, emb) in enumerate(zip(chunks, embs)):
            add_chunk(asst_id, src_id, idx, c_text, req.title, req.url or "Text Document", emb)
        update_source_chunk_count(src_id, len(chunks))

    return {
        "status": "success",
        "assistant_id": asst_id,
        "source_id": src_id,
        "chunks_count": len(chunks)
    }

@app.get("/api/assistants/{asst_id}/sources")
def api_list_sources(asst_id: str):
    return list_sources(assistant_id=asst_id)

@app.delete("/api/sources/{source_id}")
def api_delete_source(source_id: int):
    delete_source(source_id)
    return {"status": "success", "deleted_id": source_id}

# ----------------- Visitor Conversations Inbox -----------------
@app.get("/api/assistants/{asst_id}/conversations")
def api_list_conversations(asst_id: str):
    """Returns conversation inbox sessions with first query and message counts."""
    return list_conversations_with_metadata(assistant_id=asst_id)

@app.get("/api/conversations/{conv_id}/transcript")
def api_get_conversation_transcript(conv_id: str):
    """Fetches full back-and-forth transcript for a specific conversation."""
    history = get_conversation_history(conv_id, limit=50)
    return {"conversation_id": conv_id, "messages": history}

# ----------------- Knowledge Gaps & Unanswered Questions -----------------
@app.get("/api/assistants/{asst_id}/gaps")
def api_list_knowledge_gaps(asst_id: str, status: Optional[str] = None):
    return list_unanswered_questions(assistant_id=asst_id, status=status)

@app.post("/api/assistants/{asst_id}/gaps/{gap_id}/resolve")
def api_resolve_gap(asst_id: str, gap_id: int, req: ResolveGapRequest):
    """Resolves an unanswered question by indexing the official answer into the knowledge base."""
    gaps = list_unanswered_questions(assistant_id=asst_id)
    target = next((g for g in gaps if g["id"] == gap_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Knowledge gap item not found")

    title = f"FAQ: {target['question'][:60]}"
    body = f"Question: {target['question']}\n\nOfficial Answer: {req.official_answer}"
    
    src_id = add_source(asst_id, "faq", title, "Knowledge Gap Resolution", body)
    chunks = chunk_text(body)
    if chunks:
        embs = generate_embeddings_batch(chunks)
        for idx, (c_text, emb) in enumerate(zip(chunks, embs)):
            add_chunk(asst_id, src_id, idx, c_text, title, "Knowledge Gap Resolution", emb)
        update_source_chunk_count(src_id, len(chunks))

    resolve_unanswered_question(gap_id, req.official_answer)

    return {
        "status": "success",
        "gap_id": gap_id,
        "source_id": src_id,
        "message": "Answer added to knowledge base and question marked as resolved!"
    }

# ----------------- Chat Endpoint -----------------
@app.post("/api/chat")
def api_chat(req: ChatRequest, request: Request):
    asst_id = req.assistant_id
    if not asst_id:
        raise HTTPException(status_code=400, detail="Field 'assistant_id' is required.")
    asst = get_assistant(asst_id)
    if not asst:
        raise HTTPException(status_code=404, detail=f"Assistant '{asst_id}' not found")
    verify_assistant_domain_access(asst, request)

    conv_id = req.conversation_id or str(uuid.uuid4())

    history = get_conversation_history(conv_id, limit=6)
    add_message(conv_id, "user", req.message, assistant_id=asst_id)

    result = generate_grounded_response(
        query=req.message,
        assistant_id=asst_id,
        conversation_history=history
    )

    add_message(
        conv_id,
        "assistant",
        result["answer"],
        assistant_id=asst_id,
        sources=result["sources"],
        lead_prompted=result["lead_prompted"]
    )

    return {
        "conversation_id": conv_id,
        "assistant_id": asst_id,
        "answer": result["answer"],
        "sources": result["sources"],
        "lead_prompted": result["lead_prompted"]
    }

# ----------------- Leads & Call-Prep -----------------
@app.post("/api/leads")
@app.post("/api/lead")
def api_capture_lead(req: LeadRequest, request: Request):
    if not req.email:
        raise HTTPException(status_code=400, detail="Email is required.")

    asst_id = req.assistant_id
    if not asst_id:
        raise HTTPException(status_code=400, detail="Field 'assistant_id' is required.")
    asst = get_assistant(asst_id)
    if not asst:
        raise HTTPException(status_code=404, detail=f"Assistant '{asst_id}' not found")
    verify_assistant_domain_access(asst, request)

    history = get_conversation_history(req.conversation_id, limit=10) if req.conversation_id else []

    call_prep_brief = generate_call_prep_brief(history)
    summary = f"Inquired about: {history[-1]['content'] if history else 'General contact'}"

    lead_id = add_lead(
        assistant_id=asst_id,
        email=req.email,
        name=req.name or "",
        phone=req.phone or "",
        note=f"Conversation ID: {req.conversation_id or 'direct'}",
        conversation_summary=summary,
        ai_call_prep_brief=call_prep_brief
    )

    asst = get_assistant(asst_id)
    if asst and asst.get("webhook_url"):
        try:
            webhook_payload = {
                "event": "new_lead_captured",
                "assistant_id": asst_id,
                "assistant_name": asst.get("name"),
                "lead": {
                    "id": lead_id,
                    "email": req.email,
                    "name": req.name,
                    "phone": req.phone,
                    "call_prep_brief": call_prep_brief
                }
            }
            requests.post(asst["webhook_url"], json=webhook_payload, timeout=5)
        except Exception:
            pass

    return {
        "status": "success",
        "lead_id": lead_id,
        "ai_call_prep_brief": call_prep_brief,
        "message": "Thank you! Our team has received your information and will follow up shortly."
    }

@app.get("/api/assistants/{asst_id}/leads")
def api_list_leads_for_assistant(asst_id: str):
    return list_leads(assistant_id=asst_id)

@app.patch("/api/leads/{lead_id}/status")
def api_update_lead_status(lead_id: int, req: UpdateLeadStatusRequest):
    update_lead_status(lead_id, req.status)
    return {"status": "success", "lead_id": lead_id, "new_status": req.status}

@app.get("/api/assistants/{asst_id}/leads/export")
def api_export_leads_csv(asst_id: str):
    leads = list_leads(assistant_id=asst_id)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Lead ID", "Name", "Email", "Phone", "Status", "Note", "AI Call-Prep Brief", "Created At"])
    for l in leads:
        writer.writerow([
            l["id"],
            l["name"],
            l["email"],
            l["phone"],
            l["status"],
            l["note"],
            l["ai_call_prep_brief"],
            l["created_at"]
        ])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=leads_{asst_id}.csv"}
    )

# ----------------- Subscription & Tier Plans -----------------
@app.get("/api/subscription")
def api_get_subscription():
    return get_subscription_info()

@app.post("/api/subscription/upgrade")
def api_upgrade_plan(req: UpgradePlanRequest):
    update_subscription_plan(req.plan_key)
    return {"status": "success", "subscription": get_subscription_info()}

# ----------------- Global Settings -----------------
@app.get("/api/config")
@app.get("/api/settings")
def api_get_config():
    return get_bot_settings()

@app.post("/api/config")
@app.post("/api/settings")
def api_update_config(req: GlobalSettingsRequest):
    update_bot_settings(req.dict(exclude_unset=True))
    return {"status": "success", "settings": get_bot_settings()}

@app.post("/api/settings/test-llm")
def api_test_llm(req: TestLLMRequest):
    """
    Test connectivity for the chosen provider using an explicit key or saved key.
    Useful for validating Chinese model API keys (SiliconFlow, DeepSeek, Qwen) or standard keys.
    """
    provider = req.provider.lower().strip()
    key = (req.api_key or "").strip() or get_api_key(provider)

    if provider == "local":
        return {
            "status": "success",
            "provider": "local",
            "message": "Zero-Key Local Extractive Engine is active and running 100% offline!"
        }

    if not key:
        raise HTTPException(
            status_code=400,
            detail=f"No API key provided or found in system for '{provider}'."
        )

    test_prompt = "Hello! Please reply with 'WeaveFlow AI is connected!' to confirm our API integration."
    test_system = "You are a connectivity tester. Respond concisely."

    try:
        reply = ""
        if provider == "siliconflow":
            reply = call_siliconflow_llm(key, test_prompt, test_system)
        elif provider == "deepseek":
            reply = call_deepseek_llm(key, test_prompt, test_system)
        elif provider == "qwen":
            reply = call_qwen_llm(key, test_prompt, test_system)
        elif provider == "groq":
            reply = call_groq_llm(key, test_prompt, test_system)
        elif provider == "openrouter":
            reply = call_openrouter_llm(key, test_prompt, test_system)
        elif provider == "openai":
            reply = call_openai_llm(key, test_prompt, test_system)
        elif provider == "gemini":
            client = genai.Client(api_key=key)
            resp = client.models.generate_content(
                model=DEFAULT_GEMINI_MODEL,
                contents=test_prompt,
                config=types.GenerateContentConfig(system_instruction=test_system)
            )
            reply = resp.text.strip()
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported test provider '{provider}'")

        return {
            "status": "success",
            "provider": provider,
            "message": "API Key verified and responding successfully!",
            "response": reply[:200]
        }
    except Exception as e:
        error_msg = str(e)
        # Simplify common error messages for user convenience
        if "401" in error_msg or "Unauthorized" in error_msg or "Authentication" in error_msg:
            detail = "Authentication failed: Invalid API Key. Please verify your token."
        elif "429" in error_msg or "quota" in error_msg.lower():
            detail = "Rate limit or quota exceeded for this API key."
        else:
            detail = f"Provider error: {error_msg}"
        raise HTTPException(status_code=400, detail=detail)
