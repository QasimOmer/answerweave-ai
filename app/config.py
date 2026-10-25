"""
Configuration and settings manager for AnswerWeave clone.
Supports: Gemini (free tier), Groq (free Llama 3), OpenAI, and 100% Free Local Offline Mode.
"""

import os
from typing import Optional

from app.db import get_setting, set_setting, get_workspace, get_workspace_setting, set_workspace_setting

DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
FALLBACK_GEMINI_MODEL = "gemini-2.5-flash-lite"
EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIM = 768  # gemini-embedding-001 supports 768 / 1536 / 3072; 768 keeps storage and search light
DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"
DEFAULT_DEEPSEEK_MODEL = "deepseek-chat"
DEFAULT_SILICONFLOW_MODEL = "deepseek-ai/DeepSeek-V3"
DEFAULT_QWEN_MODEL = "qwen-plus"
DEFAULT_OPENROUTER_MODEL = "deepseek/deepseek-r1:free"

PROVIDERS = ("gemini", "groq", "openai", "deepseek", "siliconflow", "qwen", "openrouter")


def get_provider(workspace_id: Optional[str] = None) -> str:
    """The workspace's provider choice, else the platform default."""
    if workspace_id:
        choice = get_workspace_setting(workspace_id, "llm_provider", "")
        if choice:
            return choice
    return get_setting("llm_provider", "auto")

def set_provider(provider: str, workspace_id: Optional[str] = None):
    if workspace_id:
        set_workspace_setting(workspace_id, "llm_provider", provider)
    else:
        set_setting("llm_provider", provider)

def workspace_uses_platform_keys(workspace_id: Optional[str]) -> bool:
    ws = get_workspace(workspace_id) if workspace_id else None
    return True if ws is None else bool(ws.get("use_platform_keys", True))

def get_workspace_api_key(provider: str, workspace_id: str) -> str:
    """Only the key the workspace saved itself (never the platform's)."""
    return (get_workspace_setting(workspace_id, f"{provider}_api_key", "") or "").strip()

def get_api_key(provider: str = "gemini", workspace_id: Optional[str] = None) -> str:
    """Key used for a request: the workspace's own key first, then the platform key
    if the workspace is allowed to use it."""
    if workspace_id:
        own = get_workspace_api_key(provider, workspace_id)
        if own:
            return own
        if not workspace_uses_platform_keys(workspace_id):
            return ""
    return get_platform_api_key(provider)

def get_platform_api_key(provider: str) -> str:
    # 1. Check database setting
    db_key = get_setting(f"{provider}_api_key", "").strip()
    if db_key:
        return db_key
    # 2. Check environment variable
    env_var_map = {
        "gemini": "GEMINI_API_KEY",
        "groq": "GROQ_API_KEY",
        "openai": "OPENAI_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "siliconflow": "SILICONFLOW_API_KEY",
        "qwen": "DASHSCOPE_API_KEY",
        "openrouter": "OPENROUTER_API_KEY"
    }
    return os.environ.get(env_var_map.get(provider, ""), "").strip()

def set_api_key(key: str, provider: str = "gemini", workspace_id: Optional[str] = None):
    if workspace_id:
        set_workspace_setting(workspace_id, f"{provider}_api_key", key.strip())
    else:
        set_setting(f"{provider}_api_key", key.strip())

AUTO_ORDER = ["openrouter", "siliconflow", "deepseek", "gemini", "groq", "qwen", "openai"]


def get_bot_settings(workspace_id: Optional[str] = None) -> dict:
    """AI engine settings as the dashboard shows them. With a workspace, `has_<provider>_key`
    means the workspace saved its own key; `platform_keys` says which the platform provides."""
    effective = {p: get_api_key(p, workspace_id) for p in PROVIDERS}
    own = {p: (get_workspace_api_key(p, workspace_id) if workspace_id else effective[p]) for p in PROVIDERS}

    current_provider = get_provider(workspace_id)
    if current_provider == "auto":
        current_provider = next((p for p in AUTO_ORDER if effective[p]), "local")  # local = zero-key engine

    settings = {
        "bot_name": get_setting("bot_name", "WeaveFlow Bot"),
        "primary_color": get_setting("primary_color", "#081726"),
        "welcome_message": get_setting("welcome_message", "Hi there! 👋 How can I help you today?"),
        "suggested_questions": get_setting("suggested_questions", "What services do you provide?\nHow does pricing work?\nHow do I contact support?"),
        "lead_capture_enabled": get_setting("lead_capture_enabled", "true") == "true",
        "llm_provider": current_provider,
        "llm_provider_choice": get_provider(workspace_id),
        "has_api_key": any(effective.values()),
        **{f"has_{p}_key": bool(own[p]) for p in PROVIDERS},
    }
    if workspace_id:
        settings["workspace_id"] = workspace_id
        settings["uses_platform_keys"] = workspace_uses_platform_keys(workspace_id)
        settings["platform_keys"] = {p: bool(get_platform_api_key(p)) for p in PROVIDERS}
    return settings

def update_bot_settings(data: dict, workspace_id: Optional[str] = None):
    """Saves AI engine settings for a workspace (or the platform defaults when none is given)."""
    if workspace_id is None:
        for key in ("bot_name", "primary_color", "welcome_message", "suggested_questions"):
            if key in data:
                set_setting(key, data[key])
        if "lead_capture_enabled" in data:
            set_setting("lead_capture_enabled", "true" if data["lead_capture_enabled"] else "false")
    if data.get("llm_provider"):
        set_provider(data["llm_provider"], workspace_id)
    for p in PROVIDERS:
        value = data.get(f"{p}_api_key")
        if isinstance(value, str) and value.strip():
            set_api_key(value.strip(), p, workspace_id)
    for p in data.get("clear_keys") or []:
        if p in PROVIDERS:
            set_api_key("", p, workspace_id)
