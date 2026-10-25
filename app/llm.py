"""
Unified chat-model layer for every supported provider.

- One message format (OpenAI-style role/content dicts) for all providers.
- Provider failover: if the preferred provider errors or is rate-limited, the
  next configured provider answers instead of the visitor seeing a canned reply.
- True token streaming (SSE for OpenAI-compatible APIs, native for Gemini).
- Reasoning output (<think> blocks, model-specific citation glyphs) is removed.
"""

import json
import re
import time
from typing import Any, Dict, Iterator, List, Optional

import requests
from google import genai
from google.genai import types

from app.config import (
    get_api_key,
    get_provider,
    DEFAULT_GEMINI_MODEL,
    FALLBACK_GEMINI_MODEL,
    DEFAULT_DEEPSEEK_MODEL,
    DEFAULT_SILICONFLOW_MODEL,
    DEFAULT_QWEN_MODEL,
    DEFAULT_OPENROUTER_MODEL,
)

Message = Dict[str, str]

# Same order the dashboard reports as the active provider in "auto" mode.
AUTO_PROVIDER_ORDER = ["openrouter", "siliconflow", "deepseek", "gemini", "groq", "qwen", "openai"]

OPENAI_COMPATIBLE = {
    "openai": {"url": "https://api.openai.com/v1/chat/completions", "model": "gpt-4o-mini"},
    "siliconflow": {"url": "https://api.siliconflow.cn/v1/chat/completions", "model": DEFAULT_SILICONFLOW_MODEL},
    "deepseek": {"url": "https://api.deepseek.com/chat/completions", "model": DEFAULT_DEEPSEEK_MODEL},
    "qwen": {"url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions", "model": DEFAULT_QWEN_MODEL},
    "openrouter": {
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "model": DEFAULT_OPENROUTER_MODEL,
        "headers": {"HTTP-Referer": "https://answerweave-ai.vercel.app", "X-Title": "WeaveFlow AI"},
    },
    "groq": {"url": "https://api.groq.com/openai/v1/chat/completions", "model": None},  # discovered per key
}

REQUEST_TIMEOUT = 30


class LLMError(Exception):
    pass


class LLMUnavailable(LLMError):
    """No provider is configured (or the admin chose the local engine)."""


# ---------------------------------------------------------------- providers

def available_providers(workspace_id: Optional[str] = None) -> List[str]:
    """Providers to try, in order: the workspace's choice first, then any other usable key as backup."""
    choice = get_provider(workspace_id)
    if choice == "local":
        return []
    keyed = [p for p in AUTO_PROVIDER_ORDER if get_api_key(p, workspace_id)]
    if choice in keyed:
        return [choice] + [p for p in keyed if p != choice]
    return keyed


def is_configured(workspace_id: Optional[str] = None) -> bool:
    return bool(available_providers(workspace_id))


# ---------------------------------------------------------------- Groq model discovery
# Groq retires models regularly, so we discover what the account offers and
# only ever pick general chat models (never guard/safety classifiers, speech or TTS).
GROQ_PREFERRED_MODELS = [
    "openai/gpt-oss-120b",
    "llama-3.3-70b-versatile",
    "qwen/qwen3.8-27b",
    "openai/gpt-oss-20b",
    "llama-3.1-8b-instant",
]
_GROQ_NON_CHAT_MARKERS = ("guard", "safeguard", "whisper", "orpheus", "tts", "playai", "distil")
_GROQ_MODEL_CACHE: Dict[str, Any] = {"models": None, "ts": 0.0}
_GROQ_MODEL_TTL_SECONDS = 3600


def _is_groq_chat_model(model_id: str) -> bool:
    mid = model_id.lower()
    return not any(marker in mid for marker in _GROQ_NON_CHAT_MARKERS)


def get_groq_candidate_models(api_key: str) -> List[str]:
    """Ordered list of usable Groq chat models for this key (cached for an hour)."""
    now = time.time()
    if _GROQ_MODEL_CACHE["models"] and now - _GROQ_MODEL_CACHE["ts"] < _GROQ_MODEL_TTL_SECONDS:
        return _GROQ_MODEL_CACHE["models"]

    available: List[str] = []
    try:
        resp = requests.get(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=5
        )
        if resp.ok:
            available = [m["id"] for m in resp.json().get("data", []) if "id" in m and m.get("active", True)]
    except Exception:
        pass

    if not available:
        # Discovery failed; try the preferences blind rather than caching nothing.
        return list(GROQ_PREFERRED_MODELS)

    chat_models = [m for m in available if _is_groq_chat_model(m)]
    ordered = [m for m in GROQ_PREFERRED_MODELS if m in chat_models]
    ordered += [m for m in chat_models if m not in ordered]
    _GROQ_MODEL_CACHE.update(models=ordered, ts=now)
    return ordered


def _drop_groq_model(model: str):
    if _GROQ_MODEL_CACHE["models"] and model in _GROQ_MODEL_CACHE["models"]:
        _GROQ_MODEL_CACHE["models"] = [m for m in _GROQ_MODEL_CACHE["models"] if m != model]


# ---------------------------------------------------------------- output cleanup

def clean_model_text(text: str) -> str:
    """Strip reasoning blocks and provider-specific citation glyphs from a full reply."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL)
    text = re.sub(r"^.*?</think>", "", text, flags=re.DOTALL)  # opening tag lost upstream
    # gpt-oss emits citations like 【5†L1-L4】; normalise to [5].
    text = re.sub(r"【(\d+)†[^】]*】", r"[\1]", text)
    text = re.sub(r"【[^】]*】", "", text)
    return text.strip()


class _ThinkFilter:
    """Drops <think>...</think> spans from a token stream without splitting tags across chunks."""

    def __init__(self):
        self.buf = ""
        self.in_think = False

    def feed(self, chunk: str) -> str:
        self.buf += chunk
        out = []
        while self.buf:
            tag = "</think>" if self.in_think else "<think>"
            i = self.buf.find(tag)
            if i >= 0:
                if not self.in_think:
                    out.append(self.buf[:i])
                self.buf = self.buf[i + len(tag):]
                self.in_think = not self.in_think
                continue
            # Hold back a possible partial tag at the end.
            keep = max((k for k in range(1, len(tag)) if self.buf.endswith(tag[:k])), default=0)
            if not self.in_think:
                out.append(self.buf[:len(self.buf) - keep])
            self.buf = self.buf[len(self.buf) - keep:]
            break
        return "".join(out)

    def flush(self) -> str:
        rest, self.buf = ("" if self.in_think else self.buf), ""
        return rest


# ---------------------------------------------------------------- OpenAI-compatible

def _openai_payload(provider: str, model: str, messages: List[Message], temperature: float, max_tokens: int, stream: bool) -> Dict[str, Any]:
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": stream,
    }
    if provider == "groq" and "gpt-oss" in model:
        # Reasoning models: keep thinking short so replies stay fast.
        payload["reasoning_effort"] = "low"
    return payload


def _error_text(resp: requests.Response) -> str:
    try:
        err = resp.json().get("error", {})
        return err.get("message", resp.text) if isinstance(err, dict) else str(err)
    except Exception:
        return resp.text[:300]


def _openai_models(provider: str, api_key: str, model: Optional[str]) -> List[str]:
    if model:
        return [model]
    if provider == "groq":
        return get_groq_candidate_models(api_key)[:3]
    return [OPENAI_COMPATIBLE[provider]["model"]]


def _openai_stream(provider: str, api_key: str, messages: List[Message], temperature: float,
                   max_tokens: int, model: Optional[str]) -> Iterator[str]:
    spec = OPENAI_COMPATIBLE[provider]
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", **spec.get("headers", {})}
    last_error = f"no {provider} model available"
    for active_model in _openai_models(provider, api_key, model):
        payload = _openai_payload(provider, active_model, messages, temperature, max_tokens, stream=True)
        try:
            resp = requests.post(spec["url"], headers=headers, json=payload, timeout=REQUEST_TIMEOUT, stream=True)
        except requests.RequestException as e:
            last_error = str(e)
            continue
        if not resp.ok:
            last_error = f"{resp.status_code}: {_error_text(resp)}"
            if resp.status_code in (401, 403):
                break  # auth problems won't be fixed by another model
            if provider == "groq" and resp.status_code != 429:
                _drop_groq_model(active_model)  # retired / rejected model
            continue  # Groq rate limits are per model, so the next one has its own budget

        resp.encoding = "utf-8"
        produced = False
        for line in resp.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                choice = (json.loads(data).get("choices") or [{}])[0]
            except ValueError:
                continue
            piece = (choice.get("delta") or {}).get("content") or ""
            if piece:
                produced = True
                yield piece
        if produced:
            return
        last_error = f"empty response from {active_model}"
    raise LLMError(f"{provider} error: {last_error}")


# ---------------------------------------------------------------- Gemini

def _gemini_request(messages: List[Message]):
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    contents = []
    for m in messages:
        if m["role"] == "system":
            continue
        role = "model" if m["role"] == "assistant" else "user"
        contents.append(types.Content(role=role, parts=[types.Part(text=m["content"])]))
    return system, contents


def _gemini_stream(api_key: str, messages: List[Message], temperature: float, max_tokens: int,
                   model: Optional[str]) -> Iterator[str]:
    client = genai.Client(api_key=api_key)
    system, contents = _gemini_request(messages)
    last_error = "unknown Gemini error"
    for active_model in ([model] if model else [DEFAULT_GEMINI_MODEL, FALLBACK_GEMINI_MODEL]):
        config = types.GenerateContentConfig(
            system_instruction=system or None,
            temperature=temperature,
            max_output_tokens=max_tokens,
        )
        if "2.5" in active_model:
            # Chat replies don't need extended thinking; it only adds latency.
            config.thinking_config = types.ThinkingConfig(thinking_budget=0)
        produced = False
        try:
            for chunk in client.models.generate_content_stream(model=active_model, contents=contents, config=config):
                piece = getattr(chunk, "text", None) or ""
                if piece:
                    produced = True
                    yield piece
        except Exception as e:
            if produced:
                raise LLMError(f"Gemini stream interrupted: {e}")
            last_error = str(e)
            continue
        if produced:
            return
        last_error = f"empty response from {active_model}"
    raise LLMError(f"Gemini error: {last_error}")


# ---------------------------------------------------------------- public API

def _provider_stream(provider: str, messages: List[Message], temperature: float, max_tokens: int,
                     model: Optional[str] = None, api_key: Optional[str] = None,
                     workspace_id: Optional[str] = None) -> Iterator[str]:
    key = api_key or get_api_key(provider, workspace_id)
    if not key:
        raise LLMError(f"no API key for {provider}")
    if provider == "gemini":
        return _gemini_stream(key, messages, temperature, max_tokens, model)
    if provider in OPENAI_COMPATIBLE:
        return _openai_stream(provider, key, messages, temperature, max_tokens, model)
    raise LLMError(f"unsupported provider '{provider}'")


def stream_chat(messages: List[Message], temperature: float = 0.5, max_tokens: int = 900,
                providers: Optional[List[str]] = None, meta: Optional[Dict[str, Any]] = None,
                workspace_id: Optional[str] = None) -> Iterator[str]:
    """Yield reply text as it is generated, failing over between providers.

    Failover only happens before the first token; once text has reached the
    visitor, an error mid-stream is raised rather than restarting elsewhere.
    If `meta` is given, meta["provider"] is set to the provider that answered.
    Keys come from `workspace_id` (its own keys, then platform keys if it may use them).
    """
    order = providers if providers is not None else available_providers(workspace_id)
    if not order:
        raise LLMUnavailable("no LLM provider configured")
    errors = []
    for provider in order:
        think = _ThinkFilter()
        produced = False
        try:
            for piece in _provider_stream(provider, messages, temperature, max_tokens, workspace_id=workspace_id):
                visible = think.feed(piece)
                if visible:
                    if not produced and meta is not None:
                        meta["provider"] = provider
                    produced = True
                    yield visible
            tail = think.flush()
            if tail:
                if not produced and meta is not None:
                    meta["provider"] = provider
                produced = True
                yield tail
            if produced:
                return
            errors.append(f"{provider}: empty reply")
        except Exception as e:
            if produced:
                raise
            errors.append(f"{provider}: {e}")
            print(f"LLM provider {provider} failed, trying next: {e}")
    raise LLMError("; ".join(errors) or "all providers failed")


def chat(messages: List[Message], temperature: float = 0.5, max_tokens: int = 900,
         providers: Optional[List[str]] = None, meta: Optional[Dict[str, Any]] = None,
         workspace_id: Optional[str] = None) -> str:
    """Return the full reply, with the same provider failover as stream_chat."""
    return clean_model_text("".join(stream_chat(messages, temperature, max_tokens, providers, meta, workspace_id)))


def complete_with_provider(provider: str, api_key: str, prompt: str, system_prompt: str,
                           model: Optional[str] = None, temperature: float = 0, max_tokens: int = 750) -> str:
    """Single call to one specific provider (used by the dashboard's key test and legacy helpers)."""
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}]
    return clean_model_text("".join(_provider_stream(provider, messages, temperature, max_tokens, model, api_key)))
