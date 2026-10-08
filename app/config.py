"""
Configuration and settings manager for AnswerWeave clone.
Supports: Gemini (free tier), Groq (free Llama 3), OpenAI, and 100% Free Local Offline Mode.
"""

import os
from app.db import get_setting, set_setting

DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
FALLBACK_GEMINI_MODEL = "gemini-1.5-flash"
EMBEDDING_MODEL = "text-embedding-004"
DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"
DEFAULT_DEEPSEEK_MODEL = "deepseek-chat"
DEFAULT_SILICONFLOW_MODEL = "deepseek-ai/DeepSeek-V3"
DEFAULT_QWEN_MODEL = "qwen-plus"
DEFAULT_OPENROUTER_MODEL = "deepseek/deepseek-r1:free"

def get_provider() -> str:
    return get_setting("llm_provider", "auto")

def set_provider(provider: str):
    set_setting("llm_provider", provider)

def get_api_key(provider: str = "gemini") -> str:
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

def set_api_key(key: str, provider: str = "gemini"):
    set_setting(f"{provider}_api_key", key.strip())

def get_bot_settings() -> dict:
    gemini_key = get_api_key("gemini")
    groq_key = get_api_key("groq")
    openai_key = get_api_key("openai")
    deepseek_key = get_api_key("deepseek")
    siliconflow_key = get_api_key("siliconflow")
    qwen_key = get_api_key("qwen")
    openrouter_key = get_api_key("openrouter")
    
    current_provider = get_provider()
    if current_provider == "auto":
        if openrouter_key:
            current_provider = "openrouter"
        elif siliconflow_key:
            current_provider = "siliconflow"
        elif deepseek_key:
            current_provider = "deepseek"
        elif gemini_key:
            current_provider = "gemini"
        elif groq_key:
            current_provider = "groq"
        elif qwen_key:
            current_provider = "qwen"
        elif openai_key:
            current_provider = "openai"
        else:
            current_provider = "local" # Zero-key local engine!

    return {
        "bot_name": get_setting("bot_name", "WeaveFlow Bot"),
        "primary_color": get_setting("primary_color", "#081726"),
        "welcome_message": get_setting("welcome_message", "Hi there! 👋 How can I help you today?"),
        "suggested_questions": get_setting("suggested_questions", "What services do you provide?\nHow does pricing work?\nHow do I contact support?"),
        "lead_capture_enabled": get_setting("lead_capture_enabled", "true") == "true",
        "llm_provider": current_provider,
        "has_api_key": bool(gemini_key or groq_key or openai_key or deepseek_key or siliconflow_key or qwen_key or openrouter_key),
        "has_gemini_key": bool(gemini_key),
        "has_groq_key": bool(groq_key),
        "has_openai_key": bool(openai_key),
        "has_deepseek_key": bool(deepseek_key),
        "has_siliconflow_key": bool(siliconflow_key),
        "has_qwen_key": bool(qwen_key),
        "has_openrouter_key": bool(openrouter_key)
    }

def update_bot_settings(data: dict):
    if "bot_name" in data:
        set_setting("bot_name", data["bot_name"])
    if "primary_color" in data:
        set_setting("primary_color", data["primary_color"])
    if "welcome_message" in data:
        set_setting("welcome_message", data["welcome_message"])
    if "suggested_questions" in data:
        set_setting("suggested_questions", data["suggested_questions"])
    if "lead_capture_enabled" in data:
        set_setting("lead_capture_enabled", "true" if data["lead_capture_enabled"] else "false")
    if "llm_provider" in data:
        set_provider(data["llm_provider"])
    if "gemini_api_key" in data and data["gemini_api_key"].strip():
        set_api_key(data["gemini_api_key"].strip(), "gemini")
    if "groq_api_key" in data and data["groq_api_key"].strip():
        set_api_key(data["groq_api_key"].strip(), "groq")
    if "openai_api_key" in data and data["openai_api_key"].strip():
        set_api_key(data["openai_api_key"].strip(), "openai")
    if "deepseek_api_key" in data and data["deepseek_api_key"].strip():
        set_api_key(data["deepseek_api_key"].strip(), "deepseek")
    if "siliconflow_api_key" in data and data["siliconflow_api_key"].strip():
        set_api_key(data["siliconflow_api_key"].strip(), "siliconflow")
    if "qwen_api_key" in data and data["qwen_api_key"].strip():
        set_api_key(data["qwen_api_key"].strip(), "qwen")
    if "openrouter_api_key" in data and data["openrouter_api_key"].strip():
        set_api_key(data["openrouter_api_key"].strip(), "openrouter")
