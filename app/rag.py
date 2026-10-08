"""
Grounded RAG generation engine for WeaveFlow AI SaaS.
Features:
- Multi-assistant partition search
- Strict factual anti-hallucination guardrails
- Automated Lead Triggering
- Signature AnswerWeave-style AI Call-Prep Briefs for sales teams
"""

import re
import requests
from typing import List, Dict, Any, Optional
from google import genai
from google.genai import types

from app.config import (
    get_api_key,
    get_provider,
    DEFAULT_GEMINI_MODEL,
    FALLBACK_GEMINI_MODEL,
    DEFAULT_GROQ_MODEL,
    DEFAULT_DEEPSEEK_MODEL,
    DEFAULT_SILICONFLOW_MODEL,
    DEFAULT_QWEN_MODEL,
    DEFAULT_OPENROUTER_MODEL
)
from app.embeddings import search_relevant_chunks
from app.db import log_unanswered_question

GROUNDED_SYSTEM_PROMPT = """You are a grounded AI assistant representing the organization on a customer chat widget.
Your primary directive is absolute factual accuracy based ONLY on the provided Context Sources.

STRICT CONCISENESS & BREVITY RULES (CRITICAL):
1. BE SHORT, CRISP, AND TO THE POINT: Visitors are chatting on a small website widget. Never write lengthy essays or walls of text.
2. MAXIMUM LENGTH: Keep answers strictly within 2 to 3 sentences (or 2 to 3 punchy bullet points).
3. ZERO FILLER OR PREAMBLE: Do NOT start with fluff like "Hello! I would be delighted to assist you...", "Certainly!", or "According to the context sources provided above...". Jump immediately straight into the answer.
4. ACCURACY: ONLY state facts explicitly written in the Context Sources. Do NOT extrapolate, speculate, or guess.
5. UNKNOWN INFORMATION: If the provided sources do NOT contain enough information, do NOT invent an answer. Say directly:
   "I apologize, but I do not have enough details on that in our current documentation. Please leave your contact email below and our team will be glad to follow up!"
   and append [LEAD_TRIGGER] at the end.
6. CITATIONS: Use bracketed numbers [1], [2] when referencing source facts.
"""

def clean_extracted_noise(text: str) -> str:
    """Cleans boilerplate navigation, form fields, and junk text from crawled snippets."""
    text = re.sub(r'^(FAQs|Answers to your questions|See more|Our services|Services We Provide|Complete solutions|Industries We Serve)\s*[:\-•–]?\s*', '', text, flags=re.I)
    text = re.sub(r'(First Name|Last Name|Send it to Experts|Privacy Policy|All rights reserved|Terms of Service|Tell us about your goals).*', '', text, flags=re.I)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def generate_local_extractive_answer(query: str, chunks: List[Dict[str, Any]], assistant_id: str = "asst_default") -> Dict[str, Any]:
    """Zero-key local extractive grounding optimized for concise, to-the-point answers."""
    if not chunks:
        try:
            log_unanswered_question(assistant_id, query)
        except Exception:
            pass
        return {
            "answer": "I apologize, but I do not have enough details on that in our current documentation. Please feel free to leave your contact email below and our team will be glad to follow up with you!",
            "sources": [],
            "lead_prompted": True
        }

    from app.embeddings import STOPWORDS
    stop_words = STOPWORDS | {'what', 'when', 'where', 'which', 'who', 'how', 'why', 'are', 'the', 'you', 'for', 'and', 'with', 'does', 'can', 'about', 'your', 'our', 'tell', 'help'}
    meaningful_query_words = set(w for w in re.findall(r"[a-z0-9]{3,}", query.lower()) if w not in stop_words)
    
    sources_list = []
    candidates = []

    for idx, c in enumerate(chunks, 1):
        content = c.get("content", "")
        title = c.get("title", "Documentation")
        url = c.get("url", "#")
        
        sources_list.append({
            "index": idx,
            "title": title,
            "url": url,
            "snippet": content[:200] + ("..." if len(content) > 200 else ""),
            "similarity": c.get("similarity", 0.0)
        })

        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+|\n+', content) if s.strip()]
        for i, s in enumerate(sentences):
            s_clean = clean_extracted_noise(s)
            s_low = s_clean.lower()
            if any(junk in s_low for junk in ['last name', 'first name', 'contact message', 'send it to', 'tell us about your goals']):
                continue

            # 1. Check if sentence is an FAQ heading / question that matches the query
            if s.endswith('?') and i + 1 < len(sentences):
                q_matches = sum(1 for w in meaningful_query_words if w in s_low) if meaningful_query_words else 0
                if q_matches >= 1:
                    ans_text = clean_extracted_noise(sentences[i+1])
                    if len(ans_text) >= 15 and not ans_text.endswith('?'):
                        if i + 2 < len(sentences) and len(ans_text) < 50 and not sentences[i+2].endswith('?'):
                            ans_text += ' ' + clean_extracted_noise(sentences[i+2])
                        candidates.append((q_matches * 4 + 3, ans_text, idx))

            # 2. Regular informative sentence match (must NOT end with a question mark)
            if not s_clean.endswith('?'):
                matches = sum(1 for w in meaningful_query_words if w in s_low) if meaningful_query_words else 0
                if matches >= 1 and 20 <= len(s_clean) <= 260:
                    candidates.append((matches, s_clean, idx))

    candidates.sort(key=lambda x: (x[0], -len(x[1])), reverse=True)

    chosen_points = []
    seen_texts = set()
    for score, text, idx in candidates:
        text_clean = text.strip()
        norm = re.sub(r'[^a-z0-9]', '', text_clean.lower())
        if not norm or len(norm) < 10:
            continue
        # Deduplicate exact or substring matches
        if any(norm in s or s in norm for s in seen_texts):
            continue
        seen_texts.add(norm)
        if len(text_clean) > 220:
            text_clean = text_clean[:217] + "..."
        chosen_points.append(f"{text_clean} [{idx}]")
        if len(chosen_points) >= 2:
            break

    if chosen_points:
        if len(chosen_points) == 1:
            formatted_answer = chosen_points[0]
        else:
            formatted_answer = "\n".join([f"• {pt}" for pt in chosen_points])
    else:
        try:
            log_unanswered_question(assistant_id, query)
        except Exception:
            pass
        return {
            "answer": "I apologize, but I do not have enough details on that in our current documentation. Please feel free to leave your contact email below and our team will be glad to follow up with you!",
            "sources": [],
            "lead_prompted": True
        }

    lower_q = query.lower()
    lead_trigger = any(w in lower_q for w in ["contact", "speak to human", "sales", "call me", "reach out", "email me", "support ticket", "pricing", "quote", "demo"])

    return {
        "answer": formatted_answer,
        "sources": sources_list,
        "lead_prompted": lead_trigger
    }

def get_groq_active_model(api_key: str) -> str:
    """Dynamically queries Groq /models to find the best available active chat model."""
    try:
        resp = requests.get(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=5
        )
        if resp.ok:
            models_data = resp.json().get("data", [])
            model_ids = [m["id"] for m in models_data if "id" in m]
            preferences = [
                "llama-3.3-70b-versatile",
                "llama-3.1-70b-versatile",
                "llama-3.1-8b-instant",
                "llama3-70b-8192",
                "llama3-8b-8192",
                "mixtral-8x7b-32768",
                "gemma2-9b-it"
            ]
            for pref in preferences:
                if pref in model_ids:
                    return pref
            chat_models = [m for m in model_ids if "whisper" not in m]
            if chat_models:
                return chat_models[0]
    except Exception:
        pass
    return "llama-3.3-70b-versatile"

def call_groq_llm(api_key: str, prompt: str, system_prompt: str, model: str = None) -> str:
    active_model = model or get_groq_active_model(api_key)
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": active_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.2,
        "max_tokens": 300
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=20)
    if not resp.ok:
        try:
            err_json = resp.json()
            err_msg = err_json.get("error", {}).get("message", resp.text)
        except Exception:
            err_msg = resp.text

        # If primary model failed with 404/not found, try fallback models
        if resp.status_code == 404 or "not found" in str(err_msg).lower():
            for fb in ["llama-3.1-8b-instant", "llama3-8b-8192", "mixtral-8x7b-32768"]:
                if fb != active_model:
                    payload["model"] = fb
                    retry = requests.post(url, headers=headers, json=payload, timeout=20)
                    if retry.ok:
                        return retry.json()["choices"][0]["message"]["content"]

        raise Exception(f"Groq API error ({resp.status_code}): {err_msg}")

    data = resp.json()
    return data["choices"][0]["message"]["content"]

def call_openai_llm(api_key: str, prompt: str, system_prompt: str) -> str:
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.2,
        "max_tokens": 300
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]

def call_siliconflow_llm(api_key: str, prompt: str, system_prompt: str, model: str = DEFAULT_SILICONFLOW_MODEL) -> str:
    """
    SiliconFlow (硅基流动) OpenAI-compatible API endpoint.
    Offers free-tier access and free tokens for models like DeepSeek-V3,
    DeepSeek-R1-Distill-Qwen-7B, and Qwen/Qwen2.5-7B-Instruct.
    """
    url = "https://api.siliconflow.cn/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model or DEFAULT_SILICONFLOW_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.2,
        "max_tokens": 300
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=25)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]

def call_deepseek_llm(api_key: str, prompt: str, system_prompt: str, model: str = DEFAULT_DEEPSEEK_MODEL) -> str:
    """
    DeepSeek Official OpenAI-compatible API endpoint.
    Supports deepseek-chat (V3) and deepseek-reasoner (R1).
    """
    url = "https://api.deepseek.com/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model or DEFAULT_DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.2,
        "max_tokens": 300
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=25)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]

def call_qwen_llm(api_key: str, prompt: str, system_prompt: str, model: str = DEFAULT_QWEN_MODEL) -> str:
    """
    Alibaba DashScope (Qwen) OpenAI-compatible API endpoint.
    Supports qwen-plus, qwen-turbo, qwen-max.
    """
    url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model or DEFAULT_QWEN_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.2,
        "max_tokens": 300
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=25)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]

def call_openrouter_llm(api_key: str, prompt: str, system_prompt: str, model: str = DEFAULT_OPENROUTER_MODEL) -> str:
    """
    OpenRouter unified API endpoint.
    Offers completely free access to models like deepseek/deepseek-r1:free,
    deepseek/deepseek-chat:free, and qwen/qwen-2.5-72b-instruct:free.
    """
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://answerweave-ai.vercel.app",
        "X-Title": "WeaveFlow AI"
    }
    payload = {
        "model": model or DEFAULT_OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.2,
        "max_tokens": 300
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=25)
    if not resp.ok:
        try:
            err_json = resp.json()
            err_msg = err_json.get("error", {}).get("message", resp.text)
        except Exception:
            err_msg = resp.text
        raise Exception(f"OpenRouter error ({resp.status_code}): {err_msg}")
    data = resp.json()
    return data["choices"][0]["message"]["content"]

def generate_grounded_response(
    query: str,
    assistant_id: str = "asst_default",
    conversation_history: List[Dict[str, Any]] = None,
    top_k: int = 4
) -> Dict[str, Any]:
    """Executes grounded RAG workflow partitioned by assistant."""
    chunks = search_relevant_chunks(query, assistant_id=assistant_id, top_k=top_k)
    if not chunks and assistant_id != "asst_default":
        chunks = search_relevant_chunks(query, assistant_id="asst_default", top_k=top_k)
    has_relevant_docs = len(chunks) > 0

    context_text = ""
    sources_list = []
    for idx, c in enumerate(chunks, 1):
        context_text += f"\n--- Context Source [{idx}] ---\n"
        context_text += f"Title: {c.get('title', 'Document')}\n"
        context_text += f"URL / Source: {c.get('url', 'N/A')}\n"
        context_text += f"Content:\n{c.get('content', '')}\n"
        
        sources_list.append({
            "index": idx,
            "title": c.get("title") or "Documentation",
            "url": c.get("url") or "#",
            "snippet": c.get("content", "")[:200] + ("..." if len(c.get("content", "")) > 200 else ""),
            "similarity": c.get("similarity", 0.0)
        })

    gemini_key = get_api_key("gemini")
    groq_key = get_api_key("groq")
    openai_key = get_api_key("openai")
    siliconflow_key = get_api_key("siliconflow")
    deepseek_key = get_api_key("deepseek")
    qwen_key = get_api_key("qwen")
    openrouter_key = get_api_key("openrouter")
    provider = get_provider()

    has_any_key = bool(gemini_key or groq_key or openai_key or siliconflow_key or deepseek_key or qwen_key or openrouter_key)
    if not has_any_key or provider == "local":
        return generate_local_extractive_answer(query, chunks, assistant_id=assistant_id)

    history_str = ""
    if conversation_history:
        recent = conversation_history[-4:]
        for msg in recent:
            role = "User" if msg.get("role") == "user" else "Assistant"
            history_str += f"{role}: {msg.get('content', '')}\n"

    user_prompt = f"""Conversation History:
{history_str}

Context Sources:
{context_text if has_relevant_docs else "[No matching knowledge base documents found]"}

User Question: {query}
"""

    lead_trigger = False
    raw_answer = ""

    try:
        if (provider == "openrouter" or (provider == "auto" and openrouter_key)) and openrouter_key:
            raw_answer = call_openrouter_llm(openrouter_key, user_prompt, GROUNDED_SYSTEM_PROMPT)

        elif (provider == "siliconflow" or (provider == "auto" and siliconflow_key)) and siliconflow_key:
            raw_answer = call_siliconflow_llm(siliconflow_key, user_prompt, GROUNDED_SYSTEM_PROMPT)

        elif (provider == "deepseek" or (provider == "auto" and deepseek_key)) and deepseek_key:
            raw_answer = call_deepseek_llm(deepseek_key, user_prompt, GROUNDED_SYSTEM_PROMPT)

        elif (provider == "qwen" or (provider == "auto" and qwen_key)) and qwen_key:
            raw_answer = call_qwen_llm(qwen_key, user_prompt, GROUNDED_SYSTEM_PROMPT)

        elif (provider == "gemini" or provider == "auto") and gemini_key:
            client = genai.Client(api_key=gemini_key)
            try:
                resp = client.models.generate_content(
                    model=DEFAULT_GEMINI_MODEL,
                    contents=user_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=GROUNDED_SYSTEM_PROMPT,
                        temperature=0.2,
                        max_output_tokens=300,
                    )
                )
                raw_answer = resp.text or ""
            except Exception:
                resp = client.models.generate_content(
                    model=FALLBACK_GEMINI_MODEL,
                    contents=user_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=GROUNDED_SYSTEM_PROMPT,
                        temperature=0.2,
                        max_output_tokens=300,
                    )
                )
                raw_answer = resp.text or ""

        elif (provider == "groq" or (provider == "auto" and groq_key)) and groq_key:
            raw_answer = call_groq_llm(groq_key, user_prompt, GROUNDED_SYSTEM_PROMPT)

        elif (provider == "openai" or (provider == "auto" and openai_key)) and openai_key:
            raw_answer = call_openai_llm(openai_key, user_prompt, GROUNDED_SYSTEM_PROMPT)

        else:
            return generate_local_extractive_answer(query, chunks, assistant_id=assistant_id)

        if "[LEAD_TRIGGER]" in raw_answer:
            lead_trigger = True
            raw_answer = raw_answer.replace("[LEAD_TRIGGER]", "").strip()

        lower_q = query.lower()
        if any(w in lower_q for w in ["contact", "speak to human", "sales", "call me", "reach out", "email me", "support ticket", "quote", "demo"]):
            lead_trigger = True

        return {
            "answer": raw_answer,
            "sources": sources_list if has_relevant_docs else [],
            "lead_prompted": lead_trigger
        }

    except Exception as e:
        print(f"Error calling LLM provider {provider}: {e}. Falling back to local extractor.")
        return generate_local_extractive_answer(query, chunks, assistant_id=assistant_id)

def generate_call_prep_brief(conversation_history: List[Dict[str, Any]]) -> str:
    """
    Signature AnswerWeave feature: Generates an AI Call-Prep Brief for the sales team.
    Includes Intent, Pain Points, and Recommended Talking Points for follow-up.
    """
    if not conversation_history:
        return "Visitor submitted direct contact request from website widget."

    user_queries = [m.get("content", "") for m in conversation_history if m.get("role") == "user"]
    transcript = "\n".join([f"{m.get('role', 'user')}: {m.get('content', '')}" for m in conversation_history[-8:]])

    # Check if we can use an LLM
    gemini_key = get_api_key("gemini")
    groq_key = get_api_key("groq")
    openai_key = get_api_key("openai")
    siliconflow_key = get_api_key("siliconflow")
    deepseek_key = get_api_key("deepseek")
    qwen_key = get_api_key("qwen")
    openrouter_key = get_api_key("openrouter")
    provider = get_provider()

    system_brief_prompt = """You are an executive sales intelligence assistant.
Analyze this chatbot conversation between a website prospect and our bot.
Generate a structured, high-value 'AI Call-Prep Brief' for our sales rep before they call or email this lead.
Format:
• Primary Inquiries: (What were they looking for?)
• Detected Intent & Urgency: (High/Medium/Low - why?)
• Potential Objections or Concerns: (Pricing, features, SLA, etc.)
• Recommended Next Steps for Sales Rep: (Exact talking points to close them)
Keep it concise, actionable, and formatted with clean bullet points."""

    try:
        if (provider == "openrouter" or (provider == "auto" and openrouter_key)) and openrouter_key:
            return call_openrouter_llm(openrouter_key, transcript, system_brief_prompt)
        elif (provider == "siliconflow" or (provider == "auto" and siliconflow_key)) and siliconflow_key:
            return call_siliconflow_llm(siliconflow_key, transcript, system_brief_prompt)
        elif (provider == "deepseek" or (provider == "auto" and deepseek_key)) and deepseek_key:
            return call_deepseek_llm(deepseek_key, transcript, system_brief_prompt)
        elif (provider == "qwen" or (provider == "auto" and qwen_key)) and qwen_key:
            return call_qwen_llm(qwen_key, transcript, system_brief_prompt)
        elif (provider == "gemini" or provider == "auto") and gemini_key:
            client = genai.Client(api_key=gemini_key)
            resp = client.models.generate_content(
                model=DEFAULT_GEMINI_MODEL,
                contents=f"Transcript:\n{transcript}",
                config=types.GenerateContentConfig(system_instruction=system_brief_prompt)
            )
            return resp.text.strip()
        elif (provider == "groq" or (provider == "auto" and groq_key)) and groq_key:
            return call_groq_llm(groq_key, transcript, system_brief_prompt)
        elif (provider == "openai" or (provider == "auto" and openai_key)) and openai_key:
            return call_openai_llm(openai_key, transcript, system_brief_prompt)
    except Exception as e:
        print(f"Error generating LLM call-prep brief: {e}")

    # High-quality deterministic local Call-Prep Brief
    questions_summary = "; ".join(user_queries[:3]) if user_queries else "General product inquiry"
    has_pricing = any("price" in q.lower() or "cost" in q.lower() for q in user_queries)
    has_contact = any("support" in q.lower() or "human" in q.lower() or "sales" in q.lower() for q in user_queries)

    intent_level = "High" if (has_pricing or has_contact) else "Moderate"

    return f"""• Primary Inquiries: {questions_summary}
• Detected Intent & Urgency: {intent_level} (Prospect actively investigated specifications and contacted team)
• Key Inquiries: {'Pricing and commercial plans were explicitly raised.' if has_pricing else 'General feature exploration.'}
• Recommended Next Steps for Sales Rep:
  1. Acknowledge their questions regarding {user_queries[0] if user_queries else 'our platform'}.
  2. Offer a quick 10-minute tailored walkthrough.
  3. Share relevant case studies matching their use case."""
