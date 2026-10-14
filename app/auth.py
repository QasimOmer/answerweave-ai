"""
Authentication and authorization for the AnswerWeave admin API.

- Stateless signed bearer tokens (HMAC-SHA256), 7-day expiry. Each token embeds a
  fingerprint of the user's password hash, so changing a password signs out
  every existing session.
- A single middleware (`auth_middleware`) guards every /api route according to
  ROUTE_RULES, so new endpoints are private unless explicitly listed as public.
- Tenancy: users with role "admin" can access everything; other users only the
  assistants assigned to them in `user_assistants`.
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
    get_user_assigned_assistants,
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


def is_admin(user: Optional[Dict[str, Any]]) -> bool:
    return bool(user) and (user.get("role") or "").lower() == "admin"


def can_access_assistant(user: Optional[Dict[str, Any]], assistant_id: Optional[str]) -> bool:
    if not user or not assistant_id:
        return False
    if is_admin(user):
        return True
    return assistant_id in set(get_user_assigned_assistants(user["id"]))


def accessible_assistant_ids(user: Dict[str, Any]) -> Optional[List[str]]:
    """None means 'all' (admin)."""
    return None if is_admin(user) else get_user_assigned_assistants(user["id"])


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
ADMIN = "admin"              # admin role only

# (methods, path regex, level, ownership resolver)
# Ownership resolvers return the assistant_id the request touches (checked for
# tenant access), or None when there is nothing to check.
ROUTE_RULES: List[Tuple[Tuple[str, ...], "re.Pattern", str, Optional[str]]] = [
    # --- Public: auth and the embeddable widget ---
    (("POST",), re.compile(r"^/api/auth/(login|signup)$"), PUBLIC, None),
    (("POST",), re.compile(r"^/api/chat(/stream)?$"), PUBLIC, None),
    (("POST",), re.compile(r"^/api/leads?$"), PUBLIC, None),
    # Visitor's own conversation: the unguessable conversation id is the capability.
    (("GET",), re.compile(r"^/api/conversations/[^/]+/(transcript|status)$"), PUBLIC, None),
    (("POST",), re.compile(r"^/api/conversations/[^/]+/clear-unread$"), PUBLIC, None),
    # Widget config (public fields only unless the caller can manage the assistant).
    (("GET",), re.compile(r"^/api/assistants/[^/]+$"), OPTIONAL, None),
    # Plan catalogue for the pricing page (usage only when signed in).
    (("GET",), re.compile(r"^/api/subscription$"), OPTIONAL, None),

    # --- Admin only ---
    (("GET", "POST", "PUT", "PATCH", "DELETE"), re.compile(r"^/api/users(/[^/]+)?$"), ADMIN, None),
    (("GET", "POST"), re.compile(r"^/api/(config|settings)$"), ADMIN, None),
    (("POST",), re.compile(r"^/api/settings/test-llm$"), ADMIN, None),
    (("POST",), re.compile(r"^/api/subscription/upgrade$"), ADMIN, None),

    # --- Signed-in users, scoped to their assistants ---
    (("GET",), re.compile(r"^/api/auth/me$"), USER, None),
    (("POST",), re.compile(r"^/api/auth/change-password$"), USER, None),
    (("GET", "POST"), re.compile(r"^/api/assistants$"), USER, None),
    (("POST",), re.compile(r"^/api/assistants/[^/]+/gaps/(?P<gap>\d+)/(resolve|dismiss)$"), USER, "gap"),
    (("DELETE",), re.compile(r"^/api/assistants/[^/]+/gaps/(?P<gap>\d+)$"), USER, "gap"),
    (("GET", "POST", "PUT", "PATCH", "DELETE"), re.compile(r"^/api/assistants/(?P<asst>[^/]+)(/.*)?$"), USER, "asst"),
    (("POST",), re.compile(r"^/api/conversations/(?P<conv>[^/]+)/(takeover|release|operator-message)$"), USER, "conv"),
    (("PATCH", "POST"), re.compile(r"^/api/leads/(?P<lead>\d+)/status$"), USER, "lead"),
    (("DELETE",), re.compile(r"^/api/sources/(?P<source>\d+)$"), USER, "source"),
]


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

    level, resolver, match = _match_rule(request.method, path)
    if level in (PUBLIC, OPTIONAL):
        return await call_next(request)
    if not user:
        return _deny(401, "Please sign in.")
    if level == ADMIN and not is_admin(user):
        return _deny(403, "Admin access required.")

    if resolver and match:
        if resolver == "asst":
            asst_id = match.group("asst")
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
        else:
            asst_id = None
        if asst_id is None and resolver != "asst":
            return _deny(404, "Not found.")
        if not can_access_assistant(user, asst_id):
            return _deny(404 if not is_admin(user) else 403, "Not found.")

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
