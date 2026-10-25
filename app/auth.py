"""
Authentication and authorization for the AnswerWeave admin API.

- Stateless signed bearer tokens (HMAC-SHA256), 7-day expiry. Each token embeds a
  fingerprint of the user's password hash, so changing a password signs out
  every existing session.
- A single middleware (`auth_middleware`) guards every /api route according to
  ROUTE_RULES, so new endpoints are private unless explicitly listed as public.
- Tenancy: data belongs to workspaces. Members act as owner, admin or agent in
  the workspace the dashboard selects (X-Workspace-Id). users.role = "admin" is
  the platform operator and can open every workspace.
"""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from typing import Any, Dict, List, Optional, Tuple

from fastapi import Request
from fastapi.responses import JSONResponse

from app.db import (
    get_db,
    get_setting,
    set_setting,
    get_workspace,
    get_member_role,
    list_user_workspaces,
    assistant_workspace_id,
    visible_assistant_ids,
    MANAGER_ROLES,
)

TOKEN_TTL_SECONDS = 7 * 24 * 3600


# ----------------------------------------------------------------------------
# Signing secret
# ----------------------------------------------------------------------------
_SECRET_CACHE: Optional[bytes] = None


def _auth_secret() -> bytes:
    """AW_AUTH_SECRET from the environment, else a random secret persisted in the
    settings table (so every serverless instance shares it)."""
    global _SECRET_CACHE
    if _SECRET_CACHE:
        return _SECRET_CACHE
    env = os.environ.get("AW_AUTH_SECRET", "").strip()
    if env:
        _SECRET_CACHE = env.encode("utf-8")
        return _SECRET_CACHE
    stored = get_setting("auth_secret", "")
    if not stored:
        candidate = secrets.token_hex(32)
        set_setting("auth_secret", candidate)
        # Re-read in case another instance won the race to create it.
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = ?", ("auth_secret",))
        row = cursor.fetchone()
        conn.close()
        stored = (row["value"] if row else None) or candidate
    _SECRET_CACHE = stored.encode("utf-8")
    return _SECRET_CACHE


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _password_fingerprint(password_hash: str) -> str:
    return hashlib.sha256((password_hash or "").encode("utf-8")).hexdigest()[:16]


# ----------------------------------------------------------------------------
# Tokens
# ----------------------------------------------------------------------------
def create_token(user_id: str) -> str:
    row = _load_user_row(user_id)
    if not row:
        raise ValueError("Unknown user")
    payload = {
        "uid": user_id,
        "exp": int(time.time()) + TOKEN_TTL_SECONDS,
        "pv": _password_fingerprint(row["password_hash"]),
    }
    body = _b64e(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = _b64e(hmac.new(_auth_secret(), body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{sig}"


def _load_user_row(user_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, email, name, role, password_hash FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def user_from_token(token: str) -> Optional[Dict[str, Any]]:
    try:
        body, sig = token.split(".", 1)
        expected = _b64e(hmac.new(_auth_secret(), body.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(_b64d(body))
        if int(payload.get("exp", 0)) < time.time():
            return None
        row = _load_user_row(payload.get("uid", ""))
        if not row or payload.get("pv") != _password_fingerprint(row["password_hash"]):
            return None
        row.pop("password_hash", None)
        return row
    except Exception:
        return None


# ----------------------------------------------------------------------------
# One-purpose links (password reset, email verification)
# ----------------------------------------------------------------------------
RESET_TTL_SECONDS = 3600
VERIFY_TTL_SECONDS = 7 * 24 * 3600


def create_purpose_token(user_id: str, purpose: str, ttl_seconds: int) -> str:
    """Signed link token bound to one purpose. Reset tokens also embed the password
    fingerprint, so a link stops working as soon as it has been used."""
    row = _load_user_row(user_id)
    if not row:
        raise ValueError("Unknown user")
    payload = {"uid": user_id, "use": purpose, "exp": int(time.time()) + ttl_seconds, "em": row["email"]}
    if purpose == "reset":
        payload["pv"] = _password_fingerprint(row["password_hash"])
    body = _b64e(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = _b64e(hmac.new(_auth_secret(), f"{purpose}.{body}".encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{sig}"


def read_purpose_token(token: str, purpose: str) -> Optional[Dict[str, Any]]:
    """The user row for a valid, unexpired token of this purpose, else None."""
    try:
        body, sig = (token or "").split(".", 1)
        expected = _b64e(hmac.new(_auth_secret(), f"{purpose}.{body}".encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(_b64d(body))
        if payload.get("use") != purpose or int(payload.get("exp", 0)) < time.time():
            return None
        row = _load_user_row(payload.get("uid", ""))
        if not row or row["email"] != payload.get("em"):
            return None
        if purpose == "reset" and payload.get("pv") != _password_fingerprint(row["password_hash"]):
            return None
        row.pop("password_hash", None)
        return row
    except Exception:
        return None


def is_admin(user: Optional[Dict[str, Any]]) -> bool:
    """Platform operator (users.role = 'admin'): can open every workspace."""
    return bool(user) and (user.get("role") or "").lower() == "admin"


def resolve_workspace(user: Optional[Dict[str, Any]], requested: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """The workspace a request acts in, and the user's role there.

    The dashboard sends X-Workspace-Id; without it (or if the user isn't a member)
    the user's first workspace is used. Platform admins act as owner anywhere.
    """
    if not user:
        return None, None
    requested = (requested or "").strip()
    if requested:
        if is_admin(user) and get_workspace(requested):
            return requested, "owner"
        role = get_member_role(requested, user["id"])
        if role:
            return requested, role
    memberships = list_user_workspaces(user["id"])
    if memberships:
        return memberships[0]["id"], memberships[0]["role"]
    if is_admin(user):
        default_ws = get_setting("default_workspace_id", "")
        if default_ws and get_workspace(default_ws):
            return default_ws, "owner"
    return None, None


def workspace_role_for(user: Optional[Dict[str, Any]], workspace_id: Optional[str]) -> Optional[str]:
    if not user or not workspace_id:
        return None
    if is_admin(user):
        return "owner"
    return get_member_role(workspace_id, user["id"])


def can_access_assistant(user: Optional[Dict[str, Any]], assistant_id: Optional[str], need: str = "view") -> bool:
    """need='view' for reading and inbox work, 'manage' for changing the assistant or its knowledge."""
    if not user or not assistant_id:
        return False
    if is_admin(user):
        return True
    workspace_id = assistant_workspace_id(assistant_id)
    role = workspace_role_for(user, workspace_id)
    if not role:
        return False
    if need == "manage" and role not in MANAGER_ROLES:
        return False
    if role == "agent":
        return assistant_id in visible_assistant_ids(workspace_id, user["id"], role)
    return True


def accessible_assistant_ids(user: Dict[str, Any], workspace_id: Optional[str] = None) -> Optional[List[str]]:
    """Assistants the user can see in a workspace; None means 'all' (platform admin, no workspace)."""
    if workspace_id:
        role = workspace_role_for(user, workspace_id)
        return visible_assistant_ids(workspace_id, user["id"], role) if role else []
    return None if is_admin(user) else []


# ----------------------------------------------------------------------------
# Ownership lookups for child resources
# ----------------------------------------------------------------------------
def _owner(table: str, key_col: str, key_val: Any) -> Optional[str]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(f"SELECT assistant_id FROM {table} WHERE {key_col} = ?", (key_val,))
    row = cursor.fetchone()
    conn.close()
    return row["assistant_id"] if row else None


# ----------------------------------------------------------------------------
# Route rules
# ----------------------------------------------------------------------------
PUBLIC = "public"            # no login needed
OPTIONAL = "optional"        # works without login; endpoint may return more when logged in
USER = "user"                # any signed-in user
ADMIN = "admin"              # platform admin only
WS_MEMBER = "ws_member"      # any role in the current workspace
WS_MANAGE = "ws_manage"      # owner or admin of the current workspace
WS_OWNER = "ws_owner"        # owner of the current workspace

_WS_LEVEL_ROLES = {WS_MEMBER: ("owner", "admin", "agent"), WS_MANAGE: MANAGER_ROLES, WS_OWNER: ("owner",)}

# (methods, path regex, level, ownership resolver)
# Ownership resolvers return the assistant_id the request touches (checked for
# tenant access), or None when there is nothing to check. Rules are checked in order.
ROUTE_RULES: List[Tuple[Tuple[str, ...], "re.Pattern", str, Optional[str]]] = [
    # --- Public: auth and the embeddable widget ---
    (("POST",), re.compile(r"^/api/auth/(login|signup|forgot-password|reset-password|verify-email)$"), PUBLIC, None),
    (("GET",), re.compile(r"^/api/invites/[^/]+$"), PUBLIC, None),
    (("POST",), re.compile(r"^/api/chat(/stream)?$"), PUBLIC, None),
    (("POST",), re.compile(r"^/api/leads?$"), PUBLIC, None),
    # Visitor's own conversation: the unguessable conversation id is the capability.
    (("GET",), re.compile(r"^/api/conversations/[^/]+/(transcript|status)$"), PUBLIC, None),
    (("POST",), re.compile(r"^/api/conversations/[^/]+/clear-unread$"), PUBLIC, None),
    (("POST",), re.compile(r"^/api/conversations/[^/]+/messages/\d+/feedback$"), PUBLIC, None),
    # Widget config (public fields only unless the caller can manage the assistant).
    (("GET",), re.compile(r"^/api/assistants/[^/]+$"), OPTIONAL, None),
    # Plan catalogue for the pricing page (usage only when signed in).
    (("GET",), re.compile(r"^/api/subscription$"), OPTIONAL, None),

    # --- Platform admin only ---
    (("GET", "POST", "PUT", "PATCH", "DELETE"), re.compile(r"^/api/users(/[^/]+)?$"), ADMIN, None),
    # Plan changes stay with the platform until self-serve billing exists.
    (("POST",), re.compile(r"^/api/subscription/upgrade$"), ADMIN, None),

    # --- Account ---
    (("GET",), re.compile(r"^/api/auth/me$"), USER, None),
    (("POST",), re.compile(r"^/api/auth/(change-password|resend-verification)$"), USER, None),
    (("POST",), re.compile(r"^/api/invites/[^/]+/accept$"), USER, None),
    (("GET", "POST"), re.compile(r"^/api/workspaces$"), USER, None),

    # --- Current workspace (X-Workspace-Id) ---
    (("GET",), re.compile(r"^/api/workspace$"), WS_MEMBER, None),
    (("PATCH",), re.compile(r"^/api/workspace$"), WS_MANAGE, None),
    (("DELETE",), re.compile(r"^/api/workspace$"), WS_OWNER, None),
    (("GET",), re.compile(r"^/api/workspace/members$"), WS_MEMBER, None),
    # Members may remove themselves; changing anyone else is checked in the endpoint.
    (("PATCH", "DELETE"), re.compile(r"^/api/workspace/members/[^/]+$"), WS_MEMBER, None),
    (("GET", "POST", "DELETE"), re.compile(r"^/api/workspace/invites(/[^/]+)?$"), WS_MANAGE, None),
    (("GET", "POST"), re.compile(r"^/api/(config|settings)$"), WS_MANAGE, None),
    (("POST",), re.compile(r"^/api/settings/test-llm$"), WS_MANAGE, None),
    (("GET",), re.compile(r"^/api/assistants$"), WS_MEMBER, None),
    (("POST",), re.compile(r"^/api/assistants$"), WS_MANAGE, None),
    (("GET",), re.compile(r"^/api/inbox/waiting$"), WS_MEMBER, None),
    (("POST",), re.compile(r"^/api/presence$"), USER, None),

    # --- Per-assistant resources (role checked against the assistant's workspace) ---
    (("POST",), re.compile(r"^/api/assistants/[^/]+/gaps/(?P<gap>\d+)/(resolve|dismiss)$"), USER, "gap"),
    (("DELETE",), re.compile(r"^/api/assistants/[^/]+/gaps/(?P<gap>\d+)$"), USER, "gap"),
    (("GET", "POST", "PUT", "PATCH", "DELETE"), re.compile(r"^/api/assistants/(?P<asst>[^/]+)(/.*)?$"), USER, "asst"),
    (("POST",), re.compile(r"^/api/conversations/(?P<conv>[^/]+)/(takeover|release|operator-message)$"), USER, "conv"),
    (("PATCH", "POST"), re.compile(r"^/api/leads/(?P<lead>\d+)/status$"), USER, "lead"),
    (("DELETE",), re.compile(r"^/api/sources/(?P<source>\d+)$"), USER, "source"),
]

# Writes agents may make on an assistant (knowledge-gap work); every other write needs owner/admin.
_AGENT_WRITE_PATHS = re.compile(r"^/api/assistants/[^/]+/gaps(/.*)?$")


def _match_rule(method: str, path: str):
    for methods, pattern, level, resolver in ROUTE_RULES:
        if method in methods:
            m = pattern.match(path)
            if m:
                return level, resolver, m
    return USER, None, None  # anything unlisted requires sign-in


def _deny(status: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail})


async def auth_middleware(request: Request, call_next):
    path = request.url.path
    if request.method == "OPTIONS" or not path.startswith("/api/"):
        return await call_next(request)

    user = None
    auth_header = request.headers.get("authorization") or ""
    if auth_header.lower().startswith("bearer "):
        user = user_from_token(auth_header[7:].strip())
    request.state.user = user
    ws_id, ws_role = resolve_workspace(user, request.headers.get("x-workspace-id"))
    request.state.workspace_id = ws_id
    request.state.workspace_role = ws_role

    level, resolver, match = _match_rule(request.method, path)
    if level in (PUBLIC, OPTIONAL):
        return await call_next(request)
    if not user:
        return _deny(401, "Please sign in.")
    if level == ADMIN and not is_admin(user):
        return _deny(403, "Admin access required.")
    if level in _WS_LEVEL_ROLES:
        if not ws_id:
            return _deny(403, "You're not a member of any workspace yet.")
        if ws_role not in _WS_LEVEL_ROLES[level]:
            return _deny(403, "Your role in this workspace doesn't allow that.")

    if resolver and match:
        need = "view"
        if resolver == "asst":
            asst_id = match.group("asst")
            if request.method != "GET" and not _AGENT_WRITE_PATHS.match(path):
                need = "manage"
        elif resolver == "gap":
            # A gap must belong to the assistant named in the URL.
            gap_owner = _owner("unanswered_questions", "id", int(match.group("gap")))
            url_asst = path.split("/")[3]
            if gap_owner and gap_owner != url_asst:
                return _deny(404, "Not found.")
            asst_id = gap_owner or url_asst
        elif resolver == "conv":
            asst_id = _owner("conversations", "id", match.group("conv"))
        elif resolver == "lead":
            asst_id = _owner("leads", "id", int(match.group("lead")))
        elif resolver == "source":
            asst_id = _owner("sources", "id", int(match.group("source")))
            need = "manage"
        else:
            asst_id = None
        if asst_id is None and resolver != "asst":
            return _deny(404, "Not found.")
        if not can_access_assistant(user, asst_id, need):
            if need == "manage" and can_access_assistant(user, asst_id, "view"):
                return _deny(403, "Your role in this workspace doesn't allow that.")
            return _deny(404, "Not found.")

    return await call_next(request)


# ----------------------------------------------------------------------------
# Public widget config
# ----------------------------------------------------------------------------
PUBLIC_ASSISTANT_FIELDS = {
    "id", "name", "domain", "primary_color", "welcome_message", "bot_avatar", "position",
    "suggested_questions", "lead_capture_enabled", "voice_enabled", "theme_mode",
    "widget_subtitle", "launcher_text", "launcher_style", "teaser_message", "lead_title",
    "lead_fields", "sound_enabled", "show_branding", "whatsapp_number", "input_placeholder",
    "launcher_pulse", "border_radius", "font_family", "widget_width", "offset_x", "offset_y",
    "launcher_icon", "teaser_delay", "exit_intent", "hide_on_mobile", "custom_css",
}


def public_assistant_view(asst: Dict[str, Any]) -> Dict[str, Any]:
    """What an anonymous visitor's widget is allowed to see (no webhooks, emails, usage)."""
    return {k: v for k, v in asst.items() if k in PUBLIC_ASSISTANT_FIELDS}
