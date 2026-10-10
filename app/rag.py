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
from typing import List, Dict, Any, Optional, Set
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
from app.db import log_unanswered_question, get_assistant, is_trivial_or_conversational

GROUNDED_SYSTEM_PROMPT = """You are an intelligent, grounded AI assistant representing the organization on a customer chat widget.

PRIMARY DIRECTIVES:
1. GREETINGS & CASUAL INTERACTION: When a visitor greets you ("hello", "hi", "good morning"), introduces themselves, asks who you are, or engages in polite pleasantries, ALWAYS respond warmly, professionally, and politely. Welcome them to the organization, introduce your role as the AI assistant, and invite them to ask any questions. Never reply with "I do not have enough details" to a casual greeting!
2. FACTUAL GROUNDING: For factual questions regarding the organization, products, services, features, policies, or pricing, answer accurately based ONLY on the provided Context Sources.
3. CONCISENESS & CLARITY: Keep responses crisp and easy to read on a compact website chat widget (clean bullet points or short paragraphs). Avoid lengthy walls of text.
4. UNKNOWN FACTS: Only if a visitor asks a specific factual business question that is genuinely not covered in the Context Sources, say directly:
   "I apologize, but I do not have enough details on that in our current documentation. Please feel free to leave your contact email below and our team will be glad to follow up!"
   and append [LEAD_TRIGGER] at the end.
5. CITATIONS: Use bracketed numbers [1], [2] when referencing source facts.
6. E-COMMERCE & PRODUCT RECOMMENDATIONS:
   - When a visitor asks about products, suggestions, or items under a specific budget (e.g. "any product under 500aed", "shoes under $100"):
   - Accurately evaluate prices against their requested budget. Compare amounts mathematically (e.g. 450 AED is under 500 AED; 700 AED is over).
   - Match the currency requested (AED, $, USD, EUR, GBP, SAR, etc.).
   - Clearly present matching products from the Context Sources:
     • **Product Name** — **Price** (with currency)
       Key features, specifications, and availability
       Direct link / URL ONLY IF the exact full URL is explicitly written in the Context Sources for that item.
   - If no products in the Context Sources fall under the visitor's exact budget, clearly explain that items under that specific budget are currently unavailable, highlight the closest or lowest priced alternatives that ARE available in the sources, and invite them to leave contact info for updates.
7. REAL ESTATE & PROPERTY RECOMMENDATIONS:
   - Differentiate between **Rental Properties** (per month / per year) and **Properties for Sale**.
   - When a visitor asks for rentals under a budget (e.g. "any rental property under 1000 aed or $", "2 bedroom apartment for rent under 60k"):
     - Accurately check rental rates and frequency (e.g., 950 AED / month, $1,200 / month, 45,000 AED / year).
     - Present matching listings clearly:
       • **Property Title / Listing** — **Price / Rent** (with frequency, e.g. 950 AED / month)
         Location / Neighborhood • Bedrooms / Bathrooms • Size & Amenities
         Direct link / URL ONLY IF the exact full URL is explicitly written in the Context Sources for that item.
     - If the requested budget is lower than any rental properties in the documentation (e.g. asking for 1,000 AED rentals when typical rents in the documentation start higher):
       Politely inform the visitor of the typical starting rates from the documentation, offer to connect them with a leasing specialist, and append [LEAD_TRIGGER].
8. STRICT LINK & URL ACCURACY DIRECTIVE (ZERO 404 BROKEN LINKS):
   - CRITICAL: NEVER invent, fabricate, or guess web URLs or paths (e.g., never create links like '/properties/123', '/rent/...', or '/product/xyz').
   - You may ONLY link to a URL if that EXACT full URL is explicitly stated in the provided Context Sources.
   - If an item does not have an exact URL in the sources, present all available details (name, price, specs, location) WITHOUT generating a markdown link. Any broken link or 404 is strictly unacceptable.
9. REAL ESTATE OVERVIEWS & COMPREHENSIVE PROPERTY INQUIRIES:
   - When a visitor asks broad questions about properties (e.g., "tell me about properties", "can you share some rental properties", "do you have properties for sale"):
   - Clearly outline the organization's property solutions:
     • Residential rentals (studios, 1–4 bed apartments, villas across Dubai Marina, Downtown, Palm Jumeirah, JVC).
     • Off-plan investments & ready homes with developer payment plans.
     • Full tenancy support (RERA contracts, Ejari registration, property valuations).
   - Never output internal staff bios or privacy policy clauses as an answer to a property inquiry.
   - Invite the visitor to share their preferred community, bedroom count, or budget to connect directly with the team.
"""

def detect_conversational_intent(query: str, asst_name: str = "Our Team", welcome_msg: str = "") -> Optional[str]:
    """
    Detects purely conversational messages (greetings, pleasantries, identity queries, thanks, farewells)
    and returns a warm, helpful, brand-aligned response immediately.
    Returns None if the query contains a factual or business-specific question.
    """
    raw = query.strip()
    q = raw.lower()
    cleaned = re.sub(r'[\s\.,!?:;~]+', ' ', q).strip()
    words = cleaned.split()
    
    if not words:
        return None

    # Check for business-specific keywords - if present, this is a real factual question, not small talk
    business_question_indicators = {
        "price", "pricing", "cost", "plan", "plans", "feature", "features", "service", "services",
        "return", "refund", "shipping", "ship", "delivery", "policy", "contact", "support",
        "human", "demo", "buy", "purchase", "order", "hours", "address", "location", "quote",
        "discount", "coupon", "integrate", "integration", "api", "doc", "docs", "documentation",
        "login", "sign", "signup", "register", "cancel", "downgrade", "upgrade", "refunds"
    }
    if any(w in words for w in business_question_indicators):
        return None

    # 1. Greetings: "hello", "hi", "hey", "good morning", "howdy", "sup", etc.
    greeting_words = {"hi", "hello", "hey", "heyy", "heyyy", "howdy", "hola", "yo", "sup", "hiya", "greetings"}
    if len(words) <= 4:
        if any(w in greeting_words for w in words):
            if welcome_msg and len(welcome_msg.strip()) > 5:
                clean_welcome = welcome_msg.strip()
                if not any(clean_welcome.lower().startswith(g) for g in ["hi", "hello", "hey", "welcome"]):
                    return f"Hello! 👋 {clean_welcome}"
                return clean_welcome
            return f"Hello! 👋 Welcome to {asst_name}. How can I assist you today? Feel free to ask about our services, pricing, or features!"

        if cleaned in {"good morning", "good afternoon", "good evening", "good day", "morning", "afternoon", "evening"}:
            time_greeting = "Good day"
            if "morning" in cleaned:
                time_greeting = "Good morning"
            elif "afternoon" in cleaned:
                time_greeting = "Good afternoon"
            elif "evening" in cleaned:
                time_greeting = "Good evening"
            return f"{time_greeting}! 👋 Welcome to {asst_name}. How can I help you today?"

    # 2. Pleasantries / "How are you?":
    if cleaned in {
        "how are you", "how are you doing", "how are u", "how is it going", "hows it going",
        "how do you do", "hope you are well", "hope all is well", "whats up", "what is up"
    }:
        return f"I'm doing great, thank you for asking! 😊 How can I help you with {asst_name} today?"

    # 3. Identity & Capabilities: "Who are you?", "What can you do?", "What is your name?"
    identity_patterns = [
        r'^(who\s+are\s+you|what\s+are\s+you|what\s+is\s+your\s+name|who\s+made\s+you|tell\s+me\s+about\s+yourself)$',
        r'^(what\s+can\s+you\s+do|what\s+do\s+you\s+do|how\s+can\s+you\s+help(\s+me)?|what\s+is\s+this(\s+bot)?)$'
    ]
    if any(re.match(pat, cleaned) for pat in identity_patterns):
        return f"I'm the official AI assistant for {asst_name}! 🚀 I'm here to answer your questions about our products, services, features, and pricing based on our verified knowledge base. What would you like to know?"

    # 4. Gratitude: "thank you", "thanks", "thanks a lot", "appreciate it"
    thanks_words = {"thanks", "thank you", "thx", "thank u", "thanks a lot", "thank you so much", "much appreciated", "appreciate it"}
    if cleaned in thanks_words or (len(words) <= 3 and any(w in {"thanks", "thx"} for w in words)):
        return "You're very welcome! 😊 Let me know if there's anything else I can help you with."

    # 5. Farewells: "bye", "goodbye", "see you", "see ya"
    farewell_words = {"bye", "goodbye", "bye bye", "see you", "see ya", "have a good day", "have a great day", "cya", "talk to you later"}
    if cleaned in farewell_words or (len(words) <= 2 and any(w in {"bye", "goodbye", "cya"} for w in words)):
        return "Goodbye! Have a wonderful day, and feel free to return anytime if you have questions! 👋"

    # 6. Acknowledgments: "ok", "okay", "cool", "great", "awesome", "perfect", "sounds good"
    ack_words = {"ok", "okay", "cool", "great", "awesome", "perfect", "got it", "understood", "sounds good", "alright", "nice"}
    if cleaned in ack_words:
        return "Glad to hear that! Feel free to ask if there is anything else you would like to know."

    # 7. General Help: "help", "can you help me", "i need help"
    if cleaned in {"help", "can you help me", "i need help", "assist me", "support"}:
        return f"I'm here to help! What would you like to know about {asst_name}? You can ask me about our offerings, pricing, specifications, or contact details."

    return None

def normalize_url(u: str) -> str:
    """Canonical normalization for URLs."""
    return u.strip().rstrip("/").lower()

def get_verified_assistant_urls(assistant_id: str, chunks: Optional[List[Dict[str, Any]]] = None) -> Set[str]:
    """
    Returns the set of all verified, crawled, and indexed URLs for this assistant.
    Aggregates chunk URLs, assistant sources, and URLs mentioned inside chunk text.
    Used to strictly prevent hallucinated 404 links.
    """
    valid_urls = set()

    # 1. From chunks passed in
    if chunks:
        for c in chunks:
            u = c.get("url")
            if u and isinstance(u, str) and u.startswith("http"):
                valid_urls.add(u.strip())
            # Also extract explicit URLs found in chunk text
            content = c.get("content", "")
            if content and "http" in content:
                for match in re.findall(r'https?://[^\s\)"\'\]><]+', content):
                    clean_u = match.strip().rstrip(".,;:)!")
                    if clean_u:
                        valid_urls.add(clean_u)

    # 2. From all registered sources for this assistant
    if assistant_id:
        try:
            from app.db import list_sources
            sources = list_sources(assistant_id)
            for s in sources:
                u = s.get("url")
                if u and isinstance(u, str) and u.startswith("http"):
                    valid_urls.add(u.strip())
        except Exception:
            pass

    return valid_urls

def sanitize_hallucinated_urls(answer: str, verified_urls: Set[str]) -> str:
    """
    Scans the answer for any markdown links [anchor](url) or raw URLs.
    If a URL is not present in verified_urls, it strips or sanitizes the link to prevent 404 errors.
    - If anchor is generic ('View Listing', 'Click here', etc.), removes the link element cleanly.
    - If anchor is descriptive ('Downtown Studio', 'Sneaker XYZ'), keeps the text without the broken link.
    """
    if not answer:
        return ""
    if not verified_urls:
        verified_urls = set()

    norm_verified = {normalize_url(u) for u in verified_urls if u}

    generic_anchors = {
        "view listing", "view product", "view details", "view property",
        "click here", "link", "details", "website", "here", "direct url",
        "product page", "listing page", "view more", "learn more", "visit here",
        "listing", "view"
    }

    def replace_markdown_link(match):
        prefix = match.group(1) or ""
        anchor = match.group(2).strip()
        url = match.group(3).strip()
        norm_u = normalize_url(url)

        if norm_u in norm_verified:
            return match.group(0)

        # Unverified URL!
        clean_anchor = anchor.strip().lower()
        if clean_anchor in generic_anchors:
            return ""
        return f"{prefix}**{anchor}**" if not anchor.startswith("**") else f"{prefix}{anchor}"

    # Match optional bullet/emoji prefix + markdown link
    link_pattern = re.compile(r'((?:\n\s*)?(?:🔗\s*|•\s*)?)\[([^\]]+)\]\((https?://[^\s\)]+)\)')
    cleaned = link_pattern.sub(replace_markdown_link, answer)

    # Clean leftover empty lines or dangling emojis
    cleaned = re.sub(r'🔗\s*(?:\n|$)', '', cleaned)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned.strip()

def clean_extracted_noise(text: str) -> str:
    """Cleans boilerplate navigation, form fields, and junk text from crawled snippets."""
    text = re.sub(r'^(Question|Official Answer|Answer|FAQ|Q|A)\s*[:\-•–]\s*', '', text, flags=re.I)
    text = re.sub(r'^(FAQs|Answers to your questions|See more|Our services|Services We Provide|Complete solutions|Industries We Serve)\s*[:\-•–]?\s*', '', text, flags=re.I)
    text = re.sub(r'(First Name|Last Name|Send it to Experts|Privacy Policy|All rights reserved|Terms of Service|Tell us about your goals).*', '', text, flags=re.I)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def generate_local_extractive_answer(query: str, chunks: List[Dict[str, Any]], assistant_id: str = "asst_default") -> Dict[str, Any]:
    """Zero-key local extractive grounding optimized for concise, to-the-point answers and catalog discovery."""
    from app.embeddings import normalize_query_terms
    norm_query = normalize_query_terms(query)

    # 1. Check conversational intent first
    asst = get_assistant(assistant_id) if assistant_id else None
    asst_name = asst.get("name") if asst else "Our Team"
    welcome_msg = asst.get("welcome_message") if asst else ""
    conv_reply = detect_conversational_intent(norm_query, asst_name=asst_name, welcome_msg=welcome_msg)
    if conv_reply:
        return {
            "answer": conv_reply,
            "sources": [],
            "lead_prompted": False
        }

    sources_list = []
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

    # 2. Check catalog, e-commerce product, and real estate property intent
    from app.catalog_intelligence import (
        parse_user_query_intent,
        extract_catalog_items_from_chunk,
        match_items_against_query,
        format_catalog_recommendation_answer,
        build_real_estate_overview_answer
    )
    intent = parse_user_query_intent(norm_query)

    # Determine if query or assistant context relates to Real Estate
    is_real_estate = (
        intent.get("entity_type") == "property"
        or intent.get("deal_type") in ["rent", "sale"]
        or any(w in norm_query.lower() for w in [
            "property", "properties", "apartment", "apartments", "flat", "flats",
            "villa", "villas", "studio", "studios", "penthouse", "penthouses",
            "townhouse", "townhouses", "rent", "rental", "rentals", "leasing", "lease",
            "to rent", "for rent", "for sale", "to buy", "off-plan", "ejari", "landlord", "tenant"
        ])
        or any("real estate" in (c.get("title", "") + " " + c.get("content", "")[:300]).lower() for c in chunks[:5])
        or any(w in asst_name.lower() for w in ["homes", "real estate", "property", "realty"])
    )

    if intent.get("is_catalog_query") or is_real_estate:
        all_chunk_items = []
        for idx, c in enumerate(chunks, 1):
            items = extract_catalog_items_from_chunk(
                c.get("content", ""),
                chunk_index=idx,
                url=c.get("url", "#"),
                title=c.get("title", "Listing")
            )
            all_chunk_items.extend(items)

        if all_chunk_items:
            matched_items = match_items_against_query(all_chunk_items, intent)
            if matched_items:
                verified_urls = get_verified_assistant_urls(assistant_id, chunks)
                cat_res = format_catalog_recommendation_answer(matched_items, intent, assistant_name=asst_name, allowed_urls=verified_urls)
                if cat_res.get("answer"):
                    clean_cat_ans = sanitize_hallucinated_urls(cat_res["answer"], verified_urls)
                    return {
                        "answer": clean_cat_ans,
                        "sources": sources_list,
                        "lead_prompted": cat_res.get("lead_prompted", False)
                    }

        # If real estate domain or property inquiry, synthesize the comprehensive real estate overview
        if is_real_estate:
            verified_urls = get_verified_assistant_urls(assistant_id, chunks)
            overview_res = build_real_estate_overview_answer(intent, chunks, assistant_name=asst_name, allowed_urls=verified_urls)
            if overview_res.get("answer"):
                clean_overview = sanitize_hallucinated_urls(overview_res["answer"], verified_urls)
                return {
                    "answer": clean_overview,
                    "sources": sources_list,
                    "lead_prompted": overview_res.get("lead_prompted", True)
                }

        # If e-commerce product query under a specific budget, but no matching catalog items were found
        if intent.get("max_price") is not None:
            max_p = intent["max_price"]
            curr = intent.get("currency")
            curr_str = f"**{max_p:,.0f} AED or $**" if curr == "AED_OR_USD" else f"**{curr + ' ' if curr not in ['ANY', ''] else ''}{max_p:,.0f}**"
            item_type = "products"
            
            return {
                "answer": f"I apologize, but we do not currently have {item_type} listed under {curr_str} in our current documentation.\n\nPlease feel free to leave your contact email below and our team will be glad to follow up with custom options matching your exact budget!",
                "sources": sources_list,
                "lead_prompted": True
            }

    if not chunks:
        if len(norm_query.strip()) >= 4 and not is_trivial_or_conversational(norm_query):
            try:
                log_unanswered_question(assistant_id, norm_query)
            except Exception:
                pass
        return {
            "answer": "I apologize, but I do not have enough details on that in our current documentation. Please feel free to leave your contact email below and our team will be glad to follow up with you!",
            "sources": [],
            "lead_prompted": True
        }

    from app.embeddings import STOPWORDS
    stop_words = STOPWORDS | {'what', 'when', 'where', 'which', 'who', 'how', 'why', 'are', 'the', 'you', 'for', 'and', 'with', 'does', 'can', 'about', 'your', 'our', 'tell', 'help', 'share', 'give', 'show', 'send', 'list', 'provide', 'some'}
    meaningful_query_words = set(w for w in re.findall(r"[a-z0-9]{3,}", norm_query.lower()) if w not in stop_words)
    candidates = []

    for idx, c in enumerate(chunks, 1):
        content = c.get("content", "")
        # Priority 0: Check for explicit FAQ / Q&A chunk patterns (e.g., from resolved Knowledge Gaps or FAQs)
        faq_match = re.search(r'(?:Question|Q):\s*(.+?)\s*\n+\s*(?:Official Answer|Answer|A):\s*(.+?)(?=\n+(?:Question|Q):|\Z)', content, re.IGNORECASE | re.DOTALL)
        if faq_match:
            faq_q = faq_match.group(1).strip()
            faq_a = faq_match.group(2).strip()
            faq_q_words = set(w for w in re.findall(r"[a-z0-9]{3,}", faq_q.lower()) if w not in stop_words)
            overlap = len(meaningful_query_words & faq_q_words) if meaningful_query_words else 0
            if overlap >= 1 or (not meaningful_query_words and norm_query.lower() in faq_q.lower()):
                clean_ans = clean_extracted_noise(faq_a)
                if len(clean_ans) >= 10:
                    candidates.append((overlap * 12 + 40, clean_ans, idx))

        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+|\n+', content) if s.strip()]
        for i, s in enumerate(sentences):
            s_clean = clean_extracted_noise(s)
            s_low = s_clean.lower()
            if any(junk in s_low for junk in ['last name', 'first name', 'contact message', 'send it to', 'tell us about your goals', 'captcha', 'submit form']):
                continue

            # Skip legal/privacy policy sentences unless explicitly queried
            legal_phrases = ['share your information', 'personal data', 'privacy policy', 'cookie policy', 'third-party service', 'log data', 'ip address', 'terms of use', 'terms & conditions']
            if any(lp in s_low for lp in legal_phrases) and not any(w in norm_query.lower() for w in ['privacy', 'policy', 'terms', 'cookie', 'legal', 'data']):
                continue

            # Skip staff bios unless explicitly queried
            bio_phrases = ['manages residential', 'supports investors', 'property administrator', 'under his leadership', 'meet our leadership', 'read profile →']
            if any(bp in s_low for bp in bio_phrases) and not any(w in norm_query.lower() for w in ['team', 'staff', 'who is', 'founder', 'leadership', 'sana', 'himanshi', 'lootah', 'ceo']):
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
        # If top candidate is a high-confidence FAQ / Knowledge Gap answer, return it cleanly
        if candidates and candidates[0][0] >= 40:
            formatted_answer = f"{candidates[0][1]} [{candidates[0][2]}]"
        elif len(chosen_points) == 1:
            formatted_answer = chosen_points[0]
        else:
            formatted_answer = "\n".join([f"• {pt}" for pt in chosen_points])
    else:
        if len(query.strip()) >= 4 and not is_trivial_or_conversational(query):
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

    verified_urls = get_verified_assistant_urls(assistant_id, chunks)
    clean_formatted_answer = sanitize_hallucinated_urls(formatted_answer, verified_urls)

    return {
        "answer": clean_formatted_answer,
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
        "max_tokens": 750
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
        "max_tokens": 750
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
        "max_tokens": 750
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
        "max_tokens": 750
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
        "max_tokens": 750
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
        "max_tokens": 750
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
    from app.embeddings import normalize_query_terms
    norm_query = normalize_query_terms(query)

    # 1. First, check if this is a conversational greeting, pleasantry, identity query, or farewell
    asst = get_assistant(assistant_id) if assistant_id else None
    asst_name = asst.get("name") if asst else "Our Team"
    welcome_msg = asst.get("welcome_message") if asst else ""
    
    conversational_reply = detect_conversational_intent(norm_query, asst_name=asst_name, welcome_msg=welcome_msg)
    if conversational_reply:
        return {
            "answer": conversational_reply,
            "sources": [],
            "lead_prompted": False
        }

    chunks = search_relevant_chunks(norm_query, assistant_id=assistant_id, top_k=top_k)
    if not chunks and assistant_id != "asst_default":
        chunks = search_relevant_chunks(norm_query, assistant_id="asst_default", top_k=top_k)
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
        return generate_local_extractive_answer(norm_query, chunks, assistant_id=assistant_id)

    history_str = ""
    if conversation_history:
        recent = conversation_history[-4:]
        for msg in recent:
            role = "User" if msg.get("role") == "user" else "Assistant"
            history_str += f"{role}: {msg.get('content', '')}\n"

    from app.catalog_intelligence import parse_user_query_intent
    catalog_intent = parse_user_query_intent(norm_query)
    catalog_hint = ""
    if catalog_intent.get("is_catalog_query"):
        if catalog_intent.get("max_price") is not None:
            curr_hint = catalog_intent.get("currency")
            curr_text = "AED or $" if curr_hint == "AED_OR_USD" else (curr_hint if curr_hint not in ["ANY", ""] else "")
            catalog_hint = f"\n[Special Directives for this Query: The visitor is inquiring about {catalog_intent.get('entity_type')}s with a maximum budget of {catalog_intent.get('max_price')} {curr_text}. In Dubai real estate, typical residential rental rates generally start from 3,000–4,500 AED / month (so budgets like 500,000 AED cover a wide selection of prime properties). Carefully present matching options or describe the comprehensive portfolio and invite them to leave contact info. Do NOT fabricate URLs.]\n"
        elif catalog_intent.get("deal_type") == "rent":
            catalog_hint = f"\n[Special Directives: The visitor is inquiring about rental properties. Present available residential rental options (studios, apartments, waterfront homes, villas across Dubai Marina, Downtown, Palm Jumeirah, JVC), full tenancy support (Ejari, tenancy contracts), and invite them to share their preferred community or contact info.]\n"
        elif catalog_intent.get("deal_type") == "sale":
            catalog_hint = f"\n[Special Directives: The visitor is inquiring about properties for sale/purchase. Present ready homes, off-plan projects with developer payment plans, seller brokerage, and invite them to connect with sales.]\n"
        elif catalog_intent.get("entity_type") == "property":
            catalog_hint = f"\n[Special Directives: The visitor is inquiring about real estate properties. Outline buying, renting, off-plan investments, and property management solutions, and invite them to share their preferred criteria.]\n"

    user_prompt = f"""Conversation History:
{history_str}

Context Sources:
{context_text if has_relevant_docs else "[No matching knowledge base documents found]"}
{catalog_hint}
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
                        max_output_tokens=750,
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
                        max_output_tokens=750,
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

        verified_urls = get_verified_assistant_urls(assistant_id, chunks)
        cleaned_answer = sanitize_hallucinated_urls(raw_answer, verified_urls)

        return {
            "answer": cleaned_answer,
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
