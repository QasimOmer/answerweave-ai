"""
WeaveFlow AI - Complete SaaS Platform API
Multi-Assistant Website Management, Grounded RAG, AI Call-Prep Briefs,
PDF & File Ingestion, Visitor Conversation Inbox, Knowledge Gaps resolution,
and Subscription Tier Management.
"""

import os
import io
import csv
import json
import time
import uuid
import secrets
import re
import urllib.parse
import requests
from typing import Optional, List, Dict, Any, Iterator
from fastapi import FastAPI, HTTPException, Request, Response, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from app.auth import (
    auth_middleware,
    accessible_assistant_ids,
    create_token,
    can_access_assistant,
    is_admin,
    public_assistant_view,
    create_purpose_token,
    read_purpose_token,
    RESET_TTL_SECONDS,
    VERIFY_TTL_SECONDS,
)
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
    delete_unanswered_question,
    dismiss_unanswered_question,
    add_unanswered_question,
    invalidate_chunks_cache,
    get_subscription_info,
    update_subscription_plan,
    get_assistant_analytics,
    create_user,
    authenticate_user,
    get_user_by_email,
    get_user_by_id,
    list_users,
    update_user,
    delete_user,
    list_assistants_for_user,
    get_conversation,
    set_conversation_status,
    add_operator_message,
    clear_unread_operator_messages,
    add_user_assistant,
    hash_password,
    verify_password,
    set_user_password_hash,
    mark_human_requested,
    clear_human_requested,
    touch_user_presence,
    count_operators_online,
    list_waiting_conversations,
    set_message_feedback,
    get_answer_quality,
    get_embedding_status,
    log_unanswered_question,
    is_trivial_or_conversational,
    create_workspace,
    get_workspace,
    update_workspace,
    delete_workspace,
    list_user_workspaces,
    list_all_workspaces,
    get_member_role,
    add_workspace_member,
    remove_workspace_member,
    count_workspace_owners,
    list_workspace_members,
    set_member_assistants,
    visible_assistant_ids,
    list_assistants_in_workspace,
    assistant_workspace_id,
    create_invite,
    list_pending_invites,
    revoke_invite,
    get_invite_by_token,
    accept_invite,
    set_email_verified,
    WORKSPACE_ROLES,
    get_crawl_job,
    list_crawl_jobs,
    active_crawl_job,
    cancel_crawl_job,
)
from app.notify import notify_human_requested, send_email, email_provider
from app.config import (
    get_bot_settings,
    update_bot_settings,
    get_api_key,
    DEFAULT_GEMINI_MODEL,
    FALLBACK_GEMINI_MODEL,
    EMBEDDING_MODEL
)
from app.ingestion import fetch_url, crawl_website, crawl_sitemap, parse_uploaded_file, chunk_text
from app.embeddings import generate_embeddings_batch, current_embedding_tag, reindex_assistant
from app.rag import (
    ASSISTANT_TONES,
    generate_grounded_response,
    stream_grounded_response,
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
from app import jobs as crawl_jobs  # noqa: E402  (after init_db so the jobs table exists)
crawl_jobs.start_background_worker()

app = FastAPI(
    title="WeaveFlow AI SaaS Engine",
    description="Multi-tenant grounded AI website assistant platform with lead capture, file uploads, conversation inbox, and Call-Prep intelligence",
    version="2.2.0"
)

# Every /api route is private unless listed as public in app/auth.py ROUTE_RULES.
app.middleware("http")(auth_middleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def revalidate_frontend_assets(request, call_next):
    """Force browsers to revalidate the widget and HTML pages (cheap 304 via ETag),
    so customer sites pick up widget updates immediately after a deploy."""
    response = await call_next(request)
    path = request.url.path
    if path.endswith("widget.js") or path.endswith(".html") or path in ("/", "/dashboard", "/demo"):
        response.headers["Cache-Control"] = "no-cache"
    return response

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# ----------------- Request Models -----------------
class AuthSignupRequest(BaseModel):
    email: str
    password: str
    name: str
    invite_token: Optional[str] = None   # signing up from a team invite joins that workspace
    workspace_name: Optional[str] = None

class ForgotPasswordRequest(BaseModel):
    email: str

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

class VerifyEmailRequest(BaseModel):
    token: str

class CreateWorkspaceRequest(BaseModel):
    name: str

class UpdateWorkspaceRequest(BaseModel):
    name: Optional[str] = None
    use_platform_keys: Optional[bool] = None

class InviteRequest(BaseModel):
    email: str
    role: str = "agent"

class UpdateMemberRequest(BaseModel):
    role: Optional[str] = None
    assistant_ids: Optional[List[str]] = None  # agents only; empty = all assistants in the workspace

class AuthLoginRequest(BaseModel):
    email: str
    password: str

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

class CreateUserRequest(BaseModel):
    name: str
    email: str
    password: str
    role: str = "client"
    assigned_assistant_ids: List[str] = []

class UpdateUserRequest(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    password: Optional[str] = None
    assigned_assistant_ids: Optional[List[str]] = None

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
    whatsapp_number: Optional[str] = None
    input_placeholder: Optional[str] = None
    launcher_pulse: Optional[bool] = None
    border_radius: Optional[str] = None
    font_family: Optional[str] = None
    widget_width: Optional[str] = None
    offset_x: Optional[int] = None
    offset_y: Optional[int] = None
    launcher_icon: Optional[str] = None
    teaser_delay: Optional[int] = None
    exit_intent: Optional[bool] = None
    hide_on_mobile: Optional[bool] = None
    custom_css: Optional[str] = None
    tone: Optional[str] = None
    reply_length: Optional[str] = None
    custom_instructions: Optional[str] = None
    avoid_topics: Optional[str] = None
    industry: Optional[str] = None  # auto | general | real_estate | ecommerce
    recrawl_frequency: Optional[str] = None  # off | daily | weekly
    crawl_max_pages: Optional[int] = None

class ReindexRequest(BaseModel):
    full: bool = False              # re-embed everything, not just chunks from older models
    after_id: Optional[int] = None  # continue a batch run from this chunk id

class CrawlJobRequest(BaseModel):
    kind: str = "crawl"          # crawl | sitemap | resync | page
    url: Optional[str] = None
    max_pages: int = 50

class FeedbackRequest(BaseModel):
    rating: int  # 1 = helpful, -1 = not helpful, 0 = clear

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
    official_answer: Optional[str] = None
    answer: Optional[str] = None

    @property
    def get_answer(self) -> str:
        return (self.official_answer or self.answer or "").strip()

class CreateCustomQARequest(BaseModel):
    question: str
    answer: str

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

class TakeoverRequest(BaseModel):
    operator_name: Optional[str] = "Support Operator"

class OperatorMessageRequest(BaseModel):
    message: str
    operator_name: Optional[str] = "Support Operator"
    assistant_id: Optional[str] = ""

class GlobalSettingsRequest(BaseModel):
    scope: Optional[str] = None  # "platform" (platform admin only) edits the shared fallback keys
    clear_keys: Optional[List[str]] = None
    use_platform_keys: Optional[bool] = None
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

@app.get("/account")
def get_account_page():
    """Password reset, email confirmation and team invite links land here."""
    return FileResponse(os.path.join(STATIC_DIR, "account.html"))

@app.get("/demo")
def get_demo_page():
    return FileResponse(os.path.join(STATIC_DIR, "demo.html"))

@app.get("/widget.js")
def get_widget_js():
    return FileResponse(os.path.join(STATIC_DIR, "widget.js"), media_type="application/javascript")

# ----------------- Admin Auth Endpoints -----------------
def app_base_url(request: Request) -> str:
    """Public URL for links in emails (APP_BASE_URL in production, else the request's host)."""
    return (os.environ.get("APP_BASE_URL") or str(request.base_url)).rstrip("/")


def send_account_email(to: str, subject: str, intro: str, link: str, button: str) -> bool:
    """Best-effort account email. Without an email provider the link is logged for local development."""
    text = f"{intro}\n\n{button}: {link}\n\nIf you didn't expect this email, you can ignore it."
    body = (f"<p>{intro}</p><p><a href=\"{link}\" style=\"display:inline-block;padding:10px 16px;background:#4f46e5;"
            f"color:#fff;border-radius:8px;text-decoration:none\">{button}</a></p>"
            f"<p style=\"color:#64748b;font-size:13px\">If you didn't expect this email, you can ignore it.</p>")
    if not email_provider():
        print(f"[AnswerWeave] No email provider configured. {subject} for {to}: {link}")
        return False
    ok, detail = send_email([to], subject, text, body)
    if not ok:
        print(f"[AnswerWeave] Could not send '{subject}' to {to}: {detail}")
    return ok


def send_verification_email(user: Dict[str, Any], request: Request) -> bool:
    token = create_purpose_token(user["id"], "verify", VERIFY_TTL_SECONDS)
    link = f"{app_base_url(request)}/account?verify={token}"
    return send_account_email(user["email"], "Confirm your email for AnswerWeave",
                              f"Hi {user.get('name') or 'there'}, please confirm your email address.", link, "Confirm email")


def workspaces_payload(user: Dict[str, Any], current_id: Optional[str]) -> Dict[str, Any]:
    if is_admin(user):
        mine = {w["id"]: w["role"] for w in list_user_workspaces(user["id"])}
        items = [{**w, "role": mine.get(w["id"], "owner")} for w in list_all_workspaces()]
    else:
        items = list_user_workspaces(user["id"])
    return {"workspaces": items, "current_workspace_id": current_id}


@app.post("/api/auth/signup")
def api_signup(req: AuthSignupRequest, request: Request):
    if len(req.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    if "@" not in (req.email or ""):
        raise HTTPException(status_code=400, detail="Please enter a valid email address.")
    invite = get_invite_by_token(req.invite_token) if req.invite_token else None
    if req.invite_token and not invite:
        raise HTTPException(status_code=400, detail="This invite link has expired or was already used.")
    if invite and invite["email"] != req.email.strip().lower():
        raise HTTPException(status_code=400, detail=f"This invite was sent to {invite['email']}. Sign up with that address.")
    user = create_user(req.email, req.password, req.name, role="member")
    if not user:
        raise HTTPException(status_code=400, detail="An account with this email already exists.")
    if invite:
        accept_invite(req.invite_token, user["id"], user["email"])
        set_email_verified(user["id"])  # the invite link already proved they own this inbox
        workspace_id = invite["workspace_id"]
    else:
        label = (req.workspace_name or "").strip() or f"{(req.name or req.email.split('@')[0]).strip()}'s workspace"
        workspace_id = create_workspace(label, user["id"])["id"]
        send_verification_email(user, request)
    return {"status": "success", "user": get_user_by_id(user["id"]), "token": create_token(user["id"]),
            "workspace_id": workspace_id}

@app.post("/api/auth/forgot-password")
def api_forgot_password(req: ForgotPasswordRequest, request: Request):
    check_rate_limit(request, limit=10, window=900)
    row = get_user_by_email(req.email or "")
    if row:
        token = create_purpose_token(row["id"], "reset", RESET_TTL_SECONDS)
        send_account_email(row["email"], "Reset your AnswerWeave password",
                           "Someone asked to reset the password for this account. The link works for one hour.",
                           f"{app_base_url(request)}/account?reset={token}", "Choose a new password")
    # Same answer either way, so the form can't be used to find out who has an account.
    return {"status": "success", "message": "If that email has an account, a reset link is on its way."}

@app.post("/api/auth/reset-password")
def api_reset_password(req: ResetPasswordRequest, request: Request):
    check_rate_limit(request, limit=20, window=900)
    user = read_purpose_token(req.token, "reset")
    if not user:
        raise HTTPException(status_code=400, detail="This reset link has expired or was already used. Request a new one.")
    if len(req.new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    set_user_password_hash(user["id"], hash_password(req.new_password))
    set_email_verified(user["id"])  # they proved they can read this inbox
    return {"status": "success", "user": get_user_by_id(user["id"]), "token": create_token(user["id"])}

@app.post("/api/auth/verify-email")
def api_verify_email(req: VerifyEmailRequest):
    user = read_purpose_token(req.token, "verify")
    if not user:
        raise HTTPException(status_code=400, detail="This confirmation link has expired. Sign in and request a new one.")
    set_email_verified(user["id"])
    return {"status": "success", "email": user["email"]}

@app.post("/api/auth/resend-verification")
def api_resend_verification(request: Request):
    check_rate_limit(request, limit=5, window=900)
    me = get_user_by_id(request.state.user["id"])
    if me.get("email_verified"):
        return {"status": "success", "already_verified": True}
    sent = send_verification_email(me, request)
    return {"status": "success", "sent": sent}

@app.post("/api/auth/login")
def api_login(req: AuthLoginRequest):
    user = authenticate_user(req.email, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    return {"status": "success", "user": user, "token": create_token(user["id"])}

@app.get("/api/auth/me")
def api_get_me(request: Request):
    user = get_user_by_id(request.state.user["id"])
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    return {**user, **workspaces_payload(user, request.state.workspace_id),
            "workspace_role": request.state.workspace_role, "is_platform_admin": is_admin(user)}

# ----------------- Workspaces & Team -----------------
@app.get("/api/workspaces")
def api_list_workspaces(request: Request):
    return workspaces_payload(request.state.user, request.state.workspace_id)

@app.post("/api/workspaces")
def api_create_workspace(req: CreateWorkspaceRequest, request: Request):
    if not (req.name or "").strip():
        raise HTTPException(status_code=400, detail="Give the workspace a name.")
    ws = create_workspace(req.name, request.state.user["id"])
    return {"status": "success", "workspace": ws}

@app.get("/api/workspace")
def api_get_current_workspace(request: Request):
    ws = get_workspace(request.state.workspace_id)
    return {**ws, "role": request.state.workspace_role,
            "subscription": get_subscription_info(request.state.workspace_id)}

@app.patch("/api/workspace")
def api_update_current_workspace(req: UpdateWorkspaceRequest, request: Request):
    update_workspace(request.state.workspace_id, name=req.name, use_platform_keys=req.use_platform_keys)
    return {"status": "success", "workspace": get_workspace(request.state.workspace_id)}

@app.delete("/api/workspace")
def api_delete_current_workspace(request: Request):
    me = request.state.user
    if not is_admin(me) and len(list_user_workspaces(me["id"])) <= 1:
        raise HTTPException(status_code=400, detail="This is your only workspace. Create another one before deleting it.")
    delete_workspace(request.state.workspace_id)
    return {"status": "success"}

@app.get("/api/workspace/members")
def api_list_members(request: Request):
    return {"members": list_workspace_members(request.state.workspace_id), "my_role": request.state.workspace_role}

@app.patch("/api/workspace/members/{user_id}")
def api_update_member(user_id: str, req: UpdateMemberRequest, request: Request):
    ws_id, my_role = request.state.workspace_id, request.state.workspace_role
    target_role = get_member_role(ws_id, user_id)
    if not target_role:
        raise HTTPException(status_code=404, detail="That person isn't in this workspace.")
    if my_role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Only owners and admins can change roles.")
    if req.role is not None:
        if req.role not in WORKSPACE_ROLES:
            raise HTTPException(status_code=400, detail="Role must be owner, admin or agent.")
        # Only owners can create owners or change an owner.
        if (req.role == "owner" or target_role == "owner") and my_role != "owner":
            raise HTTPException(status_code=403, detail="Only an owner can change owners.")
        if target_role == "owner" and req.role != "owner" and count_workspace_owners(ws_id) <= 1:
            raise HTTPException(status_code=400, detail="A workspace needs at least one owner.")
        add_workspace_member(ws_id, user_id, req.role)
    if req.assistant_ids is not None:
        set_member_assistants(ws_id, user_id, req.assistant_ids)
    return {"status": "success", "members": list_workspace_members(ws_id)}

@app.delete("/api/workspace/members/{user_id}")
def api_remove_member(user_id: str, request: Request):
    ws_id, my_role, me = request.state.workspace_id, request.state.workspace_role, request.state.user
    target_role = get_member_role(ws_id, user_id)
    if not target_role:
        raise HTTPException(status_code=404, detail="That person isn't in this workspace.")
    leaving = user_id == me["id"]
    if not leaving:
        if my_role not in ("owner", "admin"):
            raise HTTPException(status_code=403, detail="Only owners and admins can remove people.")
        if target_role == "owner" and my_role != "owner":
            raise HTTPException(status_code=403, detail="Only an owner can remove an owner.")
    if target_role == "owner" and count_workspace_owners(ws_id) <= 1:
        raise HTTPException(status_code=400, detail="A workspace needs at least one owner. Make someone else an owner first.")
    remove_workspace_member(ws_id, user_id)
    return {"status": "success"}

@app.get("/api/workspace/invites")
def api_list_invites(request: Request):
    return {"invites": list_pending_invites(request.state.workspace_id)}

@app.post("/api/workspace/invites")
def api_invite_member(req: InviteRequest, request: Request):
    check_rate_limit(request, limit=30, window=3600)
    email = (req.email or "").strip().lower()
    if "@" not in email:
        raise HTTPException(status_code=400, detail="Please enter a valid email address.")
    if req.role not in WORKSPACE_ROLES:
        raise HTTPException(status_code=400, detail="Role must be owner, admin or agent.")
    if req.role == "owner" and request.state.workspace_role != "owner":
        raise HTTPException(status_code=403, detail="Only an owner can invite another owner.")
    ws = get_workspace(request.state.workspace_id)
    existing = get_user_by_email(email)
    if existing and get_member_role(ws["id"], existing["id"]):
        raise HTTPException(status_code=400, detail=f"{email} is already in this workspace.")
    invite = create_invite(ws["id"], email, req.role, request.state.user["id"])
    link = f"{app_base_url(request)}/account?invite={invite['token']}"
    inviter = request.state.user.get("name") or request.state.user["email"]
    sent = send_account_email(email, f"{inviter} invited you to {ws['name']} on AnswerWeave",
                              f"{inviter} invited you to join the {ws['name']} workspace as {'an' if req.role[0] in 'aeiou' else 'a'} {req.role}. The invite expires in 7 days.",
                              link, "Accept invite")
    # The inviter can share the link themselves if email isn't set up (or lands in spam).
    return {"status": "success", "invite": {k: invite[k] for k in ("id", "email", "role")},
            "invite_link": link, "email_sent": sent}

@app.delete("/api/workspace/invites/{invite_id}")
def api_revoke_invite(invite_id: str, request: Request):
    if not revoke_invite(request.state.workspace_id, invite_id):
        raise HTTPException(status_code=404, detail="Invite not found.")
    return {"status": "success"}

@app.get("/api/invites/{token}")
def api_get_invite(token: str):
    invite = get_invite_by_token(token)
    if not invite:
        raise HTTPException(status_code=404, detail="This invite link has expired or was already used.")
    return {"workspace_name": invite["workspace_name"], "email": invite["email"], "role": invite["role"],
            "has_account": bool(get_user_by_email(invite["email"]))}

@app.post("/api/invites/{token}/accept")
def api_accept_invite(token: str, request: Request):
    me = request.state.user
    invite = get_invite_by_token(token)
    if not invite:
        raise HTTPException(status_code=404, detail="This invite link has expired or was already used.")
    if invite["email"] != me["email"]:
        raise HTTPException(status_code=403, detail=f"This invite was sent to {invite['email']}. Sign in with that account to accept it.")
    accept_invite(token, me["id"], me["email"])
    set_email_verified(me["id"])
    return {"status": "success", "workspace_id": invite["workspace_id"], "workspace_name": invite["workspace_name"]}

@app.post("/api/auth/change-password")
def api_change_password(req: ChangePasswordRequest, request: Request):
    me = request.state.user
    row = get_user_by_email(me["email"])
    if not row or not verify_password(req.current_password, row["password_hash"]):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")
    if len(req.new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters.")
    set_user_password_hash(me["id"], hash_password(req.new_password))
    # Changing the password invalidates every existing session; hand back a fresh token.
    return {"status": "success", "token": create_token(me["id"])}

@app.post("/api/presence")
def api_presence(request: Request):
    """Dashboard heartbeat: marks the signed-in user as available for live chats."""
    touch_user_presence(request.state.user["id"])
    return {"status": "ok"}

@app.get("/api/inbox/waiting")
def api_waiting_conversations(request: Request):
    """Visitors waiting for a person, across every assistant the user can access."""
    return list_waiting_conversations(accessible_assistant_ids(request.state.user, request.state.workspace_id))

@app.post("/api/assistants/{asst_id}/alerts/test")
def api_test_alert(asst_id: str):
    asst = get_assistant(asst_id)
    if not asst:
        raise HTTPException(status_code=404, detail="Assistant not found")
    recipients = [e.strip() for e in (asst.get("notification_email") or "").replace(";", ",").split(",") if "@" in e]
    ok, detail = send_email(
        recipients,
        f"Test alert from AnswerWeave — {asst.get('name') or asst_id}",
        "This is a test. You'll get an email like this when a visitor asks to talk to a person.",
    )
    return {"status": "success" if ok else "error", "detail": detail, "provider": email_provider() or None, "recipients": recipients}

# ----------------- User & Client Management Endpoints -----------------
@app.get("/api/users")
def api_list_users():
    return list_users()

@app.post("/api/users")
def api_create_user(req: CreateUserRequest):
    if len(req.password) < 4:
        raise HTTPException(status_code=400, detail="Password must be at least 4 characters.")
    user = create_user(
        email=req.email,
        password=req.password,
        name=req.name,
        role=req.role,
        assigned_assistant_ids=req.assigned_assistant_ids
    )
    if not user:
        raise HTTPException(status_code=400, detail="User with this email already exists.")
    # Platform-created users join the workspaces of the assistants they're given, as agents.
    for asst_id in req.assigned_assistant_ids or []:
        ws_id = assistant_workspace_id(asst_id)
        if ws_id and not get_member_role(ws_id, user["id"]):
            add_workspace_member(ws_id, user["id"], "agent")
    return {"status": "success", "user": user}

@app.put("/api/users/{user_id}")
def api_update_user(user_id: str, req: UpdateUserRequest):
    user = update_user(
        user_id=user_id,
        name=req.name,
        role=req.role,
        password=req.password,
        assigned_assistant_ids=req.assigned_assistant_ids
    )
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    return {"status": "success", "user": user}

@app.delete("/api/users/{user_id}")
def api_delete_user(user_id: str):
    success = delete_user(user_id)
    if not success:
        raise HTTPException(status_code=400, detail="Cannot delete default admin or user not found.")
    return {"status": "success"}

# ----------------- Multi-Assistant SaaS Endpoints -----------------
@app.get("/api/assistants")
def api_list_assistants(request: Request):
    ws_id, role, me = request.state.workspace_id, request.state.workspace_role, request.state.user
    return list_assistants_in_workspace(ws_id, only_ids=visible_assistant_ids(ws_id, me["id"], role))

@app.post("/api/assistants")
def api_create_assistant(req: CreateAssistantRequest, request: Request):
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
        widget_subtitle=req.widget_subtitle or "Online • AI Assistant",
        workspace_id=request.state.workspace_id
    )

    # The site crawl runs as a background job; the dashboard shows its progress.
    job = None
    if req.website_url and req.crawl_whole_site:
        try:
            job = crawl_jobs.start_crawl_job(asst_id, "crawl", req.website_url, max_pages=50,
                                             created_by=request.state.user["id"])
        except Exception as e:
            print(f"Could not queue the site crawl for {asst_id}: {e}")

    return {
        "status": "success",
        "assistant_id": asst_id,
        "assistant": get_assistant(asst_id),
        "crawl_job": job,
        "pages_indexed": 0,
        "total_chunks": 0
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

    # Never block requests originating from dashboard, demo, or internal API calls
    referer = request.headers.get("referer") or ""
    if "/dashboard" in referer or "/demo" in referer or "/api/assistants" in referer:
        return

    server_host = (request.headers.get("host") or "").split(":")[0].strip().lower()
    
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

    if host and server_host and host.lower() == server_host:
        return

    if not is_domain_allowed(allowed, host):
        raise HTTPException(
            status_code=403, 
            detail=f"Access denied: Website domain '{host or 'unknown'}' is not authorized to use assistant '{asst.get('name')}'. Allowed domain whitelist: '{allowed}'."
        )

# ----------------- Rate Limiting (Token Bucket / Sliding Window) -----------------
_RATE_LIMIT_BUCKETS: Dict[str, List[float]] = {}
RATE_LIMIT_MAX_REQUESTS = 60  # max 60 chat requests per minute per IP
RATE_LIMIT_WINDOW_SECONDS = 60.0

def check_rate_limit(request: Request, limit: int = RATE_LIMIT_MAX_REQUESTS, window: float = RATE_LIMIT_WINDOW_SECONDS):
    """
    Enforces sliding-window rate limiting per client IP.
    Returns HTTP 429 Too Many Requests if rate is exceeded.
    """
    client_ip = request.client.host if request.client else "unknown"
    # Whitelist localhost for dev and automated QA test runs
    if client_ip in ["127.0.0.1", "localhost", "testclient"]:
        limit = 400

    now = time.time()
    timestamps = _RATE_LIMIT_BUCKETS.get(client_ip, [])
    cutoff = now - window
    timestamps = [t for t in timestamps if t > cutoff]
    
    if len(timestamps) >= limit:
        retry_after = int(window - (now - timestamps[0])) + 1
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Please wait {retry_after}s before sending another message.",
            headers={"Retry-After": str(max(1, retry_after))}
        )
    
    timestamps.append(now)
    _RATE_LIMIT_BUCKETS[client_ip] = timestamps

@app.get("/api/assistants/{asst_id}")
def api_get_assistant(asst_id: str, request: Request):
    asst = get_assistant(asst_id)
    if not asst:
        raise HTTPException(status_code=404, detail="Assistant not found")
    if can_access_assistant(getattr(request.state, "user", None), asst_id):
        return asst
    # Anonymous callers (the embedded widget) only get display settings.
    verify_assistant_domain_access(asst, request)
    return public_assistant_view(asst)

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
    if "launcher_pulse" in data:
        data["launcher_pulse"] = 1 if data["launcher_pulse"] else 0
    for flag in ("exit_intent", "hide_on_mobile"):
        if flag in data:
            data[flag] = 1 if data[flag] else 0
    # Clamp layout values so a bad input can't push the widget off-screen.
    for key in ("offset_x", "offset_y"):
        if key in data and data[key] is not None:
            data[key] = max(0, min(200, int(data[key])))
    if "teaser_delay" in data and data["teaser_delay"] is not None:
        data["teaser_delay"] = max(0, min(600, int(data["teaser_delay"])))
    if "font_family" in data and data["font_family"] not in ("jakarta", "inter", "system", "serif", "inherit"):
        data["font_family"] = "jakarta"
    if "widget_width" in data and data["widget_width"] not in ("compact", "standard", "wide"):
        data["widget_width"] = "standard"
    if "launcher_icon" in data and data["launcher_icon"] not in ("chat", "sparkles", "help", "avatar"):
        data["launcher_icon"] = "chat"
    if "custom_css" in data and data["custom_css"] is not None:
        data["custom_css"] = data["custom_css"][:8000]
    if "tone" in data and data["tone"] not in ASSISTANT_TONES:
        data["tone"] = "friendly"
    if "reply_length" in data and data["reply_length"] not in ("short", "balanced", "detailed"):
        data["reply_length"] = "balanced"
    if "recrawl_frequency" in data and data["recrawl_frequency"] not in ("off", "daily", "weekly"):
        data["recrawl_frequency"] = "off"
    if "crawl_max_pages" in data and data["crawl_max_pages"] is not None:
        data["crawl_max_pages"] = max(1, min(crawl_jobs.MAX_PAGES_LIMIT, int(data["crawl_max_pages"])))
    if "industry" in data and data["industry"] not in ("auto", "general", "real_estate", "ecommerce"):
        data["industry"] = "auto"
    for key, limit in (("custom_instructions", 2000), ("avoid_topics", 1000)):
        if key in data:
            data[key] = (data[key] or "").strip()[:limit]
    success = update_assistant(asst_id, data)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to update assistant")
    return {"status": "success", "assistant": get_assistant(asst_id)}

@app.delete("/api/assistants/{asst_id}")
def api_delete_assistant(asst_id: str):
    ws_id = assistant_workspace_id(asst_id)
    delete_assistant(asst_id)
    remaining = list_assistants_in_workspace(ws_id) if ws_id else []
    active_id = remaining[0]["id"] if remaining else None
    if not remaining:
        active_id = create_assistant("New Website Project", "*", workspace_id=ws_id)
    return {"status": "success", "deleted_id": asst_id, "active_id": active_id}

@app.get("/api/assistants/{asst_id}/analytics")
def api_get_assistant_analytics(asst_id: str):
    return get_assistant_analytics(asst_id)

@app.get("/api/assistants/{asst_id}/answer-quality")
def api_get_answer_quality(asst_id: str, days: int = 30):
    """Reply speed, answer coverage, visitor ratings and provider usage."""
    return get_answer_quality(asst_id, days=max(1, min(365, days)))

@app.get("/api/assistants/{asst_id}/catalog")
def api_get_catalog(asst_id: str, limit: int = 24):
    """Listings and products the assistant found in its knowledge, as the widget would show them."""
    from app import verticals
    asst = get_assistant(asst_id)
    items = verticals.all_catalog_items(asst_id)
    properties = sum(1 for it in items if it.get("entity_type") == "property")
    return {
        "industry": (asst or {}).get("industry") or "auto",
        "detected_industry": verticals.resolve_industry({**(asst or {}), "industry": "auto"}, asst_id),
        "total": len(items),
        "properties": properties,
        "products": len(items) - properties,
        "with_images": sum(1 for it in items if it.get("image_url")),
        "with_prices": sum(1 for it in items if it.get("price_num") is not None),
        "items": [verticals.to_card(it) for it in items[:max(1, min(60, limit))]],
    }

@app.get("/api/assistants/{asst_id}/embeddings")
def api_get_embedding_status(asst_id: str):
    status = get_embedding_status(asst_id, current_embedding_tag())
    return {**status, "model": EMBEDDING_MODEL, "semantic_enabled": bool(get_api_key("gemini", assistant_workspace_id(asst_id)))}

@app.post("/api/assistants/{asst_id}/reindex")
def api_reindex_assistant(asst_id: str, req: Optional[ReindexRequest] = None):
    """Re-embeds knowledge with the current model in batches; call again with next_after_id until done."""
    req = req or ReindexRequest()
    after_id = req.after_id if req.after_id is not None else (0 if req.full else None)
    return reindex_assistant(asst_id, max_chunks=200, after_id=after_id)

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
            embs = generate_embeddings_batch(chunks, workspace_id=assistant_workspace_id(asst_id), titles=[parsed["title"]] * len(chunks))
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
def api_ingest_sitemap(asst_id: str, req: IngestSitemapRequest, request: Request):
    """Queues a background job that indexes every page listed in a sitemap.xml."""
    return queue_crawl(asst_id, "sitemap", req.sitemap_url, req.max_pages, request)

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
        return api_ingest_sitemap(asst_id, req, request)
    elif "url" in data:
        req = IngestUrlRequest(url=data["url"], crawl_depth=data.get("crawl_depth", 50))
        return api_ingest_url(asst_id, req, request)
    raise HTTPException(status_code=400, detail="Payload must include 'url' or 'title' & 'content'")

@app.post("/api/assistants/{asst_id}/sources/url")
def api_ingest_url(asst_id: str, req: IngestUrlRequest, request: Request):
    """One page is indexed right away; a multi-page crawl is queued as a background job."""
    url = req.url.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url
    if req.crawl_depth > 1:
        return queue_crawl(asst_id, "crawl", url, req.crawl_depth, request)

    single = fetch_url(url)
    page = {"url": url.split("#")[0].rstrip("/"), "title": single["title"], "content": single["content"]}
    if len(page["content"]) < 60:
        raise HTTPException(status_code=400, detail="No readable content found at URL.")
    result = crawl_jobs.upsert_page(asst_id, page)
    return {
        "status": "success",
        "assistant_id": asst_id,
        "pages_indexed": 1,
        "outcome": result["outcome"],
        "total_chunks": result["chunks"],
        "sources": [{"title": page["title"], "url": page["url"], "chunks": result["chunks"]}]
    }


def queue_crawl(asst_id: str, kind: str, url: Optional[str], max_pages: int, request: Request) -> Dict[str, Any]:
    try:
        job = crawl_jobs.start_crawl_job(asst_id, kind, url, max_pages=max_pages, created_by=request.state.user["id"])
    except crawl_jobs.JobConflict as e:
        raise HTTPException(status_code=409, detail={"message": "A crawl is already running for this assistant.",
                                                     "job": get_crawl_job(str(e))})
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "queued", "assistant_id": asst_id, "job": job,
            "message": "Crawl started. Progress updates live in the dashboard."}


# ----------------- Background crawl jobs -----------------
def _job_for(asst_id: str, job_id: str) -> Dict[str, Any]:
    job = get_crawl_job(job_id)
    if not job or job["assistant_id"] != asst_id:
        raise HTTPException(status_code=404, detail="Crawl job not found.")
    return job

@app.post("/api/assistants/{asst_id}/jobs")
def api_start_crawl_job(asst_id: str, req: CrawlJobRequest, request: Request):
    return queue_crawl(asst_id, req.kind, req.url, req.max_pages, request)

@app.get("/api/assistants/{asst_id}/jobs")
def api_list_crawl_jobs(asst_id: str):
    return {"active": active_crawl_job(asst_id), "recent": list_crawl_jobs(asst_id, limit=10)}

@app.get("/api/assistants/{asst_id}/jobs/{job_id}")
def api_get_crawl_job(asst_id: str, job_id: str):
    return _job_for(asst_id, job_id)

@app.post("/api/assistants/{asst_id}/jobs/{job_id}/step")
def api_step_crawl_job(asst_id: str, job_id: str):
    """Runs a few seconds of the crawl. The dashboard calls this while showing progress, so crawls
    move forward even on hosts without a background worker."""
    job = _job_for(asst_id, job_id)
    if job["status"] in ("queued", "running"):
        job = crawl_jobs.run_job_step(job_id, budget_seconds=8) or job
    return job

@app.post("/api/assistants/{asst_id}/jobs/{job_id}/cancel")
def api_cancel_crawl_job(asst_id: str, job_id: str):
    _job_for(asst_id, job_id)
    cancel_crawl_job(job_id)
    return get_crawl_job(job_id)

@app.api_route("/api/cron/tick", methods=["GET", "POST"])
def api_cron_tick(request: Request):
    """Scheduler hook: starts due re-crawls and advances queued crawl jobs.
    Call with `Authorization: Bearer $CRON_SECRET` (Vercel Cron sends this automatically)."""
    secret = os.environ.get("CRON_SECRET", "").strip()
    supplied = (request.headers.get("authorization") or "").removeprefix("Bearer ").strip()
    is_local = request.client and request.client.host in ("127.0.0.1", "localhost", "testclient")
    if not ((secret and secrets.compare_digest(supplied, secret)) or (not secret and is_local)):
        raise HTTPException(status_code=401, detail="Invalid cron secret.")
    return {"status": "ok", **crawl_jobs.tick()}

@app.post("/api/assistants/{asst_id}/sources/text")
def api_ingest_text(asst_id: str, req: IngestTextRequest):
    if not req.content.strip():
        raise HTTPException(status_code=400, detail="Content cannot be empty.")

    src_id = add_source(asst_id, "text", req.title, req.url or "Text Document", req.content)
    chunks = chunk_text(req.content)
    if chunks:
        embs = generate_embeddings_batch(chunks, workspace_id=assistant_workspace_id(asst_id), titles=[req.title] * len(chunks))
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

@app.post("/api/assistants/{asst_id}/sync")
def api_sync_assistant_knowledge(asst_id: str, request: Request):
    """'Re-crawl & sync': refreshes every indexed page in the background, re-embedding only pages that
    changed, adding new pages from the site and removing pages that no longer exist."""
    if not get_assistant(asst_id):
        raise HTTPException(status_code=404, detail="Assistant not found")
    result = queue_crawl(asst_id, "resync", None, 0, request)
    return {**result, "status": "success", "message": "Re-crawl started. Unchanged pages are skipped automatically."}

# ----------------- Visitor Conversations Inbox -----------------
@app.get("/api/assistants/{asst_id}/conversations")
def api_list_conversations(asst_id: str):
    """Returns conversation inbox sessions with first query and message counts."""
    return list_conversations_with_metadata(assistant_id=asst_id)

@app.get("/api/conversations/{conv_id}/transcript")
def api_get_conversation_transcript(conv_id: str, after_id: Optional[int] = None):
    """Fetches the transcript (latest 200 messages), or only messages after `after_id`."""
    history = get_conversation_history(conv_id, limit=200, after_id=after_id)
    conv = get_conversation(conv_id)
    return {
        "conversation_id": conv_id,
        "messages": history,
        "status": conv.get("status", "bot") if conv else "bot",
        "operator_name": conv.get("operator_name", "") if conv else "",
        "human_requested_epoch": int(conv.get("human_requested_epoch") or 0) if conv else 0,
        "unread_operator_msgs": conv.get("unread_operator_msgs", 0) if conv else 0
    }

@app.get("/api/conversations/{conv_id}/status")
def api_get_conversation_status(conv_id: str):
    """Returns conversation takeover status, operator name, and unread counts."""
    conv = get_conversation(conv_id)
    if not conv:
        return {"status": "bot", "operator_name": "", "unread_operator_msgs": 0}
    return {
        "conversation_id": conv_id,
        "status": conv.get("status", "bot"),
        "operator_name": conv.get("operator_name", ""),
        "unread_operator_msgs": conv.get("unread_operator_msgs", 0)
    }

@app.post("/api/conversations/{conv_id}/takeover")
def api_takeover_conversation(conv_id: str, req: TakeoverRequest):
    """Transfers a conversation from automated AI to a live human operator."""
    operator = req.operator_name or "Support Operator"
    conv = get_conversation(conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    if conv.get("status") != "human":
        asst = get_assistant(conv.get("assistant_id") or "") or {}
        org = (asst.get("name") or "").strip()
        from_org = f" from {org}" if org else ""
        add_message(
            conv_id, "system",
            f"You're now chatting with {operator}{from_org} — a real person, not the AI assistant.",
            assistant_id=conv.get("assistant_id") or "asst_default",
        )
    set_conversation_status(conv_id, status="human", operator_name=operator)
    clear_human_requested(conv_id)
    return {
        "status": "success",
        "conversation_id": conv_id,
        "conversation_status": "human",
        "operator_name": operator,
        "message": f"Operator '{operator}' has taken over the conversation."
    }

@app.post("/api/conversations/{conv_id}/release")
def api_release_conversation(conv_id: str):
    """Returns a conversation back to the automated AI assistant."""
    conv = get_conversation(conv_id)
    if conv and conv.get("status") == "human":
        name = conv.get("operator_name") or "The operator"
        add_message(conv_id, "system", f"{name} has left the chat. You're back with the AI assistant.", assistant_id=conv.get("assistant_id") or "asst_default")
    set_conversation_status(conv_id, status="bot", operator_name="")
    return {
        "status": "success",
        "conversation_id": conv_id,
        "conversation_status": "bot",
        "message": "Conversation returned to AI bot."
    }

@app.post("/api/conversations/{conv_id}/operator-message")
def api_send_operator_message(conv_id: str, req: OperatorMessageRequest):
    """Allows an operator to send a live message to the visitor."""
    msg = req.message.strip()
    if not msg:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")
    operator = req.operator_name or "Support Operator"
    add_operator_message(conv_id, msg, operator_name=operator, assistant_id=req.assistant_id or "")
    return {
        "status": "success",
        "conversation_id": conv_id,
        "operator_name": operator,
        "message": msg
    }

@app.post("/api/conversations/{conv_id}/clear-unread")
def api_clear_conversation_unread(conv_id: str):
    """Clears unread operator notifications for the visitor."""
    clear_unread_operator_messages(conv_id)
    return {"status": "success", "conversation_id": conv_id}

# ----------------- Knowledge Gaps & Unanswered Questions -----------------
@app.get("/api/assistants/{asst_id}/gaps")
def api_list_knowledge_gaps(asst_id: str, status: Optional[str] = None):
    return list_unanswered_questions(assistant_id=asst_id, status=status)

@app.post("/api/assistants/{asst_id}/gaps/{gap_id}/resolve")
def api_resolve_gap(asst_id: str, gap_id: int, req: ResolveGapRequest):
    """Resolves an unanswered question by indexing the official answer into the knowledge base."""
    answer_text = req.get_answer
    if not answer_text:
        raise HTTPException(status_code=400, detail="Answer text cannot be empty.")

    gaps = list_unanswered_questions(assistant_id=asst_id)
    target = next((g for g in gaps if g["id"] == gap_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Knowledge gap item not found")

    title = f"FAQ: {target['question'][:60]}"
    body = f"Question: {target['question']}\n\nOfficial Answer: {answer_text}"
    
    src_id = add_source(asst_id, "faq", title, "Knowledge Gap Resolution", body)
    chunks = chunk_text(body)
    if chunks:
        embs = generate_embeddings_batch(chunks, workspace_id=assistant_workspace_id(asst_id), titles=[title] * len(chunks))
        for idx, (c_text, emb) in enumerate(zip(chunks, embs)):
            add_chunk(asst_id, src_id, idx, c_text, title, "Knowledge Gap Resolution", emb)
        update_source_chunk_count(src_id, len(chunks))

    resolve_unanswered_question(gap_id, answer_text)
    invalidate_chunks_cache(asst_id)

    return {
        "status": "success",
        "gap_id": gap_id,
        "source_id": src_id,
        "message": "Answer added to knowledge base and question marked as resolved!"
    }

@app.post("/api/assistants/{asst_id}/gaps/custom")
def api_add_custom_qa(asst_id: str, req: CreateCustomQARequest):
    """Proactively adds a verified Q&A pair directly into knowledge vault."""
    q = req.question.strip()
    a = req.answer.strip()
    if not q or not a:
        raise HTTPException(status_code=400, detail="Both question and answer are required.")

    title = f"FAQ: {q[:60]}"
    body = f"Question: {q}\n\nOfficial Answer: {a}"
    src_id = add_source(asst_id, "faq", title, "Custom Knowledge FAQ", body)
    chunks = chunk_text(body)
    if chunks:
        embs = generate_embeddings_batch(chunks, workspace_id=assistant_workspace_id(asst_id), titles=[title] * len(chunks))
        for idx, (c_text, emb) in enumerate(zip(chunks, embs)):
            add_chunk(asst_id, src_id, idx, c_text, title, "Custom Knowledge FAQ", emb)
        update_source_chunk_count(src_id, len(chunks))

    gap_id = add_unanswered_question(asst_id, q, status="resolved", resolution_notes=a)
    invalidate_chunks_cache(asst_id)

    return {
        "status": "success",
        "gap_id": gap_id,
        "source_id": src_id,
        "message": "Custom Q&A added to knowledge vault and assistant trained!"
    }

@app.delete("/api/assistants/{asst_id}/gaps/{gap_id}")
def api_delete_gap(asst_id: str, gap_id: int):
    """Deletes an unanswered question item."""
    delete_unanswered_question(gap_id)
    return {"status": "success", "message": "Knowledge gap deleted."}

@app.post("/api/assistants/{asst_id}/gaps/{gap_id}/dismiss")
def api_dismiss_gap(asst_id: str, gap_id: int):
    """Dismisses an unanswered question item without indexing."""
    dismiss_unanswered_question(gap_id)
    return {"status": "success", "message": "Knowledge gap dismissed."}

# ----------------- Chat Endpoint -----------------
def build_operator_handoff_reply(conv_id: str, op_name: str, request: Request) -> str:
    """Reply for a visitor message while a person is handling the chat.

    Current widgets (which send `X-AW-Widget: 2`) receive operator messages live,
    so they get no auto-reply. Older widget builds that browsers may still have
    cached can't receive live messages, so we tell them who they're talking to and
    include the operator's replies since the visitor's previous message.
    """
    if request.headers.get("x-aw-widget") == "2":
        return ""
    history = get_conversation_history(conv_id, limit=60)
    user_idxs = [i for i, m in enumerate(history) if m.get("role") == "user"]
    since = user_idxs[-2] if len(user_idxs) >= 2 else -1
    recent_ops = [m.get("content", "") for m in history[since + 1:] if m.get("role") == "operator"]
    text = f"You're chatting with {op_name}, a real person from our team."
    if recent_ops:
        text += "\n\n" + "\n\n".join(f"**{op_name}:** {c}" for c in recent_ops[-3:])
    else:
        text += f" {op_name} will reply here in a moment."
    return text


# Visitor asks for a person ("can I talk to a human / real person / agent ...").
HUMAN_REQUEST_PATTERNS = [
    r"\b(?:talk|speak|chat|connect)\s+(?:me\s+)?(?:to|with)\s+(?:a|an|some|the|your|one\s+of\s+your)?\s*(?:real\s+)?(?:human|person|people|agent|representative|rep|someone|somebody|specialist|staff|team\s+member|sales|support|team|operator|consultant|advisor|adviser|support\s+agent|sales\s+person|salesperson)s?\b",
    r"\b(?:human|live)\s+(?:agent|support|person|operator|chat)\b",
    r"\breal\s+(?:person|human)\b",
    r"\b(?:need|want)\s+(?:a|to\s+talk\s+to\s+a)?\s*human\b",
    r"(?:موظف|شخص\s+حقيقي|التحدث\s+مع\s+(?:شخص|أحد|موظف)|خدمة\s+العملاء)",
]


def wants_human(message: str) -> bool:
    text = (message or "").lower()
    return any(re.search(p, text) for p in HUMAN_REQUEST_PATTERNS)


def handle_human_request(asst: Dict[str, Any], conv_id: str, message: str, request: Request) -> Dict[str, Any]:
    is_new = mark_human_requested(conv_id)
    online = count_operators_online(asst["id"]) > 0
    if is_new:
        try:
            notify_human_requested(asst, conv_id, message, str(request.base_url))
        except Exception as e:
            print(f"Human-request alert failed: {e}")
    # "EcomAlign Assistant" -> "EcomAlign" so the reply reads "the EcomAlign team".
    team = re.sub(r"\s+(?:ai\s+)?(?:assistant|chatbot|bot)$", "", (asst.get("name") or "").strip(), flags=re.IGNORECASE) or "our"
    if online:
        answer = (f"I've let the {team} team know you'd like to talk to a person — someone will join this chat shortly. "
                  "You can keep typing here in the meantime.")
    else:
        answer = (f"The {team} team isn't online right now, but I've passed your request on. "
                  "Leave your email below and they'll get back to you as soon as they can.")
    return {
        "answer": answer,
        "sources": [],
        "lead_prompted": (not online) and bool(asst.get("lead_capture_enabled", 1)),
        "human_requested": True,
        "operators_online": online,
    }


# Messages of memory the assistant gets for each reply (the current message is added separately).
CHAT_HISTORY_LIMIT = 12


def store_assistant_reply(asst_id: str, conv_id: str, result: Dict[str, Any], started: float) -> Optional[int]:
    """Saves the reply with its answer analytics and returns the message id (used for visitor feedback)."""
    message_id = add_message(
        conv_id,
        "assistant",
        result["answer"],
        assistant_id=asst_id,
        sources=result["sources"],
        lead_prompted=result["lead_prompted"],
        response_ms=int((time.time() - started) * 1000),
        provider=result.get("provider") or ("handoff" if result.get("human_requested") else ""),
        knowledge_gap=bool(result.get("knowledge_gap")),
        cards=result.get("cards") or None,
    )
    result["message_id"] = message_id
    return message_id


def answer_visitor_message(asst: Dict[str, Any], conv_id: str, message: str, request: Request) -> Dict[str, Any]:
    """Store the visitor's message, produce the reply (AI or human hand-off) and store it."""
    started = time.time()
    asst_id = asst["id"]
    history = get_conversation_history(conv_id, limit=CHAT_HISTORY_LIMIT)
    add_message(conv_id, "user", message, assistant_id=asst_id)

    if wants_human(message):
        result = handle_human_request(asst, conv_id, message, request)
    else:
        result = generate_grounded_response(query=message, assistant_id=asst_id, conversation_history=history)
        result.setdefault("human_requested", False)
        result.setdefault("operators_online", None)

    store_assistant_reply(asst_id, conv_id, result, started)
    return result


def stream_visitor_message(asst: Dict[str, Any], conv_id: str, message: str, request: Request) -> Iterator[Dict[str, Any]]:
    """Streaming version of answer_visitor_message: yields token events, then a final 'done' event."""
    started = time.time()
    asst_id = asst["id"]
    history = get_conversation_history(conv_id, limit=CHAT_HISTORY_LIMIT)
    add_message(conv_id, "user", message, assistant_id=asst_id)

    if wants_human(message):
        result = handle_human_request(asst, conv_id, message, request)
        yield {"type": "token", "token": result["answer"]}
    else:
        result = None
        for event in stream_grounded_response(query=message, assistant_id=asst_id, conversation_history=history):
            if event["type"] == "done":
                result = event
            else:
                yield event
        result = {k: v for k, v in result.items() if k != "type"}
        result.setdefault("human_requested", False)
        result.setdefault("operators_online", None)

    store_assistant_reply(asst_id, conv_id, result, started)
    yield {"type": "done", **result}


@app.post("/api/chat")
def api_chat(req: ChatRequest, request: Request):
    check_rate_limit(request)
    asst_id = req.assistant_id
    if not asst_id:
        raise HTTPException(status_code=400, detail="Field 'assistant_id' is required.")
    asst = get_assistant(asst_id)
    if not asst:
        raise HTTPException(status_code=404, detail=f"Assistant '{asst_id}' not found")
    verify_assistant_domain_access(asst, request)

    conv_id = req.conversation_id or str(uuid.uuid4())

    # Check if a human operator is currently assigned to this conversation
    conv = get_conversation(conv_id)
    if conv and conv.get("status") == "human":
        add_message(conv_id, "user", req.message, assistant_id=asst_id)
        op_name = conv.get("operator_name") or "Support Specialist"
        # A person is handling this chat: no AI reply (see build_operator_handoff_reply).
        return {
            "conversation_id": conv_id,
            "assistant_id": asst_id,
            "answer": build_operator_handoff_reply(conv_id, op_name, request),
            "sources": [],
            "lead_prompted": False,
            "operator_active": True,
            "operator_name": op_name
        }

    result = answer_visitor_message(asst, conv_id, req.message, request)

    return {
        "conversation_id": conv_id,
        "assistant_id": asst_id,
        "answer": result["answer"],
        "sources": result["sources"],
        "lead_prompted": result["lead_prompted"],
        "message_id": result.get("message_id"),
        "cards": result.get("cards") or [],
        "operator_active": False,
        "human_requested": result.get("human_requested", False),
        "operators_online": result.get("operators_online")
    }

@app.post("/api/chat/stream")
def api_chat_stream(req: ChatRequest, request: Request):
    """Real-time SSE token streaming for instantaneous, typing-effect chat responses."""
    check_rate_limit(request)
    asst_id = req.assistant_id
    if not asst_id:
        raise HTTPException(status_code=400, detail="Field 'assistant_id' is required.")
    asst = get_assistant(asst_id)
    if not asst:
        raise HTTPException(status_code=404, detail=f"Assistant '{asst_id}' not found")
    verify_assistant_domain_access(asst, request)

    conv_id = req.conversation_id or str(uuid.uuid4())

    # Check if a human operator is currently assigned to this conversation
    conv = get_conversation(conv_id)
    if conv and conv.get("status") == "human":
        add_message(conv_id, "user", req.message, assistant_id=asst_id)
        op_name = conv.get("operator_name") or "Support Specialist"
        # A person is handling this chat: no AI reply (see build_operator_handoff_reply).
        handoff_reply = build_operator_handoff_reply(conv_id, op_name, request)

        def operator_stream():
            yield f"data: {json.dumps({'type': 'start', 'conversation_id': conv_id, 'assistant_id': asst_id, 'operator_active': True})}\n\n"
            if handoff_reply:
                yield f"data: {json.dumps({'type': 'token', 'token': handoff_reply})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'answer': handoff_reply, 'sources': [], 'lead_prompted': False, 'conversation_id': conv_id, 'operator_active': True, 'operator_name': op_name})}\n\n"

        return StreamingResponse(
            operator_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"
            }
        )

    def event_stream():
        yield f"data: {json.dumps({'type': 'start', 'conversation_id': conv_id, 'assistant_id': asst_id})}\n\n"
        # Tokens are forwarded as the model writes them; 'done' carries the final, cleaned answer.
        for event in stream_visitor_message(asst, conv_id, req.message, request):
            if event["type"] == "token":
                yield f"data: {json.dumps({'type': 'token', 'token': event['token']})}\n\n"
            else:
                done = {
                    "type": "done",
                    "answer": event["answer"],
                    "sources": event["sources"],
                    "lead_prompted": event["lead_prompted"],
                    "message_id": event.get("message_id"),
                    "cards": event.get("cards") or [],
                    "conversation_id": conv_id,
                    "human_requested": event.get("human_requested", False),
                    "operators_online": event.get("operators_online"),
                }
                yield f"data: {json.dumps(done)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

@app.post("/api/conversations/{conv_id}/messages/{message_id}/feedback")
def api_message_feedback(conv_id: str, message_id: int, req: FeedbackRequest, request: Request):
    """Visitor rates a bot reply. Not-helpful replies send their question to the knowledge-gaps tab."""
    check_rate_limit(request)
    rating = 1 if req.rating > 0 else (-1 if req.rating < 0 else 0)
    rated = set_message_feedback(conv_id, message_id, rating)
    if not rated:
        raise HTTPException(status_code=404, detail="Message not found in this conversation")
    question = (rated.get("question") or "").strip()
    if rating == -1 and len(question) >= 4 and not is_trivial_or_conversational(question):
        try:
            log_unanswered_question(rated["assistant_id"], question)
        except Exception as e:
            print(f"Could not log disliked answer as a knowledge gap: {e}")
    return {"status": "success", "message_id": message_id, "rating": rating}

# ----------------- Leads & Call-Prep -----------------
@app.post("/api/leads")
@app.post("/api/lead")
def api_capture_lead(req: LeadRequest, request: Request):
    check_rate_limit(request)
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

    call_prep_brief = generate_call_prep_brief(history, assistant_id=asst_id)
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

@app.get("/api/assistants/{asst_id}/conversations/export")
def api_export_conversations_csv(asst_id: str):
    """Exports conversation inbox sessions as a CSV file."""
    asst = get_assistant(asst_id)
    name = asst.get("name", "Assistant") if asst else "Assistant"
    convs = list_conversations_with_metadata(assistant_id=asst_id)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Conversation ID",
        "Status",
        "Operator",
        "First User Query",
        "Last Message",
        "Message Count",
        "Lead Email",
        "Created At",
        "Updated At"
    ])

    for c in convs:
        writer.writerow([
            c.get("id"),
            c.get("status", "bot"),
            c.get("operator_name", ""),
            c.get("first_query", ""),
            c.get("last_message", ""),
            c.get("message_count", 0),
            c.get("lead_email", ""),
            c.get("created_at", ""),
            c.get("updated_at", "")
        ])

    output.seek(0)
    safe_name = "".join(ch for ch in name if ch.isalnum() or ch in (' ', '_', '-')).strip().replace(' ', '_')
    filename = f"{safe_name}_conversations_{int(time.time())}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@app.post("/api/assistants/{asst_id}/webhook/test")
def api_test_assistant_webhook(asst_id: str):
    """Dispatches a test payload to verify webhook URL connectivity."""
    asst = get_assistant(asst_id)
    if not asst:
        raise HTTPException(status_code=404, detail="Assistant not found")
    url = asst.get("webhook_url")
    if not url:
        raise HTTPException(status_code=400, detail="No webhook URL configured for this assistant. Enter a URL first.")

    payload = {
        "event": "webhook_test",
        "assistant_id": asst_id,
        "assistant_name": asst.get("name"),
        "timestamp": time.time(),
        "test_data": {
            "message": "WeaveFlow AI Webhook Test Successful!",
            "lead_sample": {
                "name": "Jane Doe",
                "email": "jane@example.com",
                "phone": "+1 555 123 4567"
            }
        }
    }
    try:
        resp = requests.post(url, json=payload, timeout=8)
        return {
            "status": "success",
            "status_code": resp.status_code,
            "message": f"Webhook ping succeeded with HTTP {resp.status_code}!",
            "response_preview": resp.text[:200]
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to reach webhook URL: {str(e)}")

# ----------------- Subscription & Tier Plans -----------------
@app.get("/api/subscription")
def api_get_subscription(request: Request):
    ws_id = getattr(request.state, "workspace_id", None)
    info = get_subscription_info(ws_id)
    if getattr(request.state, "user", None) and ws_id:
        return info
    return {"all_plans": info.get("all_plans", {})}

@app.post("/api/subscription/upgrade")
def api_upgrade_plan(req: UpgradePlanRequest, request: Request):
    # Platform admin only (see auth rules) until self-serve billing is connected.
    update_subscription_plan(req.plan_key, request.state.workspace_id)
    return {"status": "success", "subscription": get_subscription_info(request.state.workspace_id)}

# ----------------- Global Settings -----------------
@app.get("/api/config")
@app.get("/api/settings")
def api_get_config(request: Request, scope: Optional[str] = None):
    """AI engine settings for the current workspace (platform admins can pass scope=platform)."""
    if scope == "platform":
        if not is_admin(request.state.user):
            raise HTTPException(status_code=403, detail="Admin access required.")
        return {**get_bot_settings(), "scope": "platform"}
    return {**get_bot_settings(request.state.workspace_id), "scope": "workspace",
            "can_edit_platform": is_admin(request.state.user)}

@app.post("/api/config")
@app.post("/api/settings")
def api_update_config(req: GlobalSettingsRequest, request: Request):
    data = req.dict(exclude_unset=True)
    if data.pop("scope", None) == "platform":
        if not is_admin(request.state.user):
            raise HTTPException(status_code=403, detail="Admin access required.")
        update_bot_settings(data)
        return {"status": "success", "settings": get_bot_settings()}
    ws_id = request.state.workspace_id
    if "use_platform_keys" in data:
        update_workspace(ws_id, use_platform_keys=data.pop("use_platform_keys"))
    update_bot_settings(data, ws_id)
    return {"status": "success", "settings": get_bot_settings(ws_id)}

@app.post("/api/settings/test-llm")
def api_test_llm(req: TestLLMRequest, request: Request):
    """
    Test connectivity for the chosen provider using an explicit key or saved key.
    Useful for validating Chinese model API keys (SiliconFlow, DeepSeek, Qwen) or standard keys.
    """
    provider = req.provider.lower().strip()
    key = (req.api_key or "").strip() or get_api_key(provider, request.state.workspace_id)

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
