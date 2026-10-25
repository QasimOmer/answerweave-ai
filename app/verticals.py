"""
Industry modes for real estate and e-commerce assistants.

- Catalog search over *every* listing/product the assistant has indexed (not just
  the few passages retrieved for a question), filtered by budget, rent/buy,
  bedrooms, location and keywords, then ranked.
- Matches go to the model as a compact "listings" block (so it recommends and
  explains instead of dumping specs) and to the widget as visual cards.
- Industry-specific guidance: a property consultant that qualifies buyers and
  books viewings, or a shopping assistant that recommends, compares and links
  products.
"""

import re
from typing import Any, Dict, List, Optional, Tuple

from app.catalog_intelligence import parse_user_query_intent, match_items_against_query
from app.embeddings import STOPWORDS, _get_index

INDUSTRIES = ("auto", "general", "real_estate", "ecommerce")
MAX_CARDS = 6

_RE_HINTS = ("real estate", "realty", "properties", "property", "homes", "estate", "realtor", "lettings", "brokerage")
_SHOP_HINTS = ("shop", "store", "boutique", "market", "mart", "outlet", "fashion", "apparel", "cosmetics")

# Words that describe the search itself, not what the visitor wants, so they don't count as keywords.
_GENERIC_WORDS = {
    "show", "looking", "need", "want", "any", "available", "options", "option", "recommend", "suggest",
    "something", "anything", "cheap", "cheaper", "cheapest", "affordable", "budget", "under", "below",
    "less", "than", "within", "max", "maximum", "price", "prices", "cost", "around", "between",
    "rent", "rental", "rentals", "sale", "buy", "purchase", "lease", "month", "monthly", "year", "yearly",
    "property", "properties", "apartment", "apartments", "flat", "flats", "home", "homes", "house", "houses",
    "product", "products", "item", "items", "bed", "beds", "bedroom", "bedrooms", "bhk", "aed", "usd", "dhs",
    "eur", "gbp", "sar", "dollars", "dirhams", "thousand", "million", "have", "got", "listings", "listing",
}
_SHOPPING_INTENT = re.compile(
    r"\b(?:show|looking\s+for|need|want|any|anything|available|options?|recommend|suggest|compare|similar|alternatives?|"
    r"cheaper|in\s+stock|best|which\s+one|for\s+sale|to\s+rent|for\s+rent|do\s+you\s+(?:have|sell|carry|stock))\b", re.I)


# ---------------------------------------------------------------- catalog

def all_catalog_items(assistant_id: str) -> List[Dict[str, Any]]:
    """Every listing/product parsed from the assistant's knowledge, de-duplicated (cached with the search index)."""
    index = _get_index(assistant_id)
    cached = getattr(index, "_all_items", None)
    if cached is not None:
        return cached
    seen, items = set(), []
    for i in range(len(index.chunks)):
        for it in index.catalog_items(i):
            key = ((it.get("url") or "").lower(), (it.get("name") or "").strip().lower())
            if key in seen or not it.get("name"):
                continue
            seen.add(key)
            items.append(it)
    # Pages that merely mention a price (shipping policy, pricing FAQ) aren't listings. Use the structured
    # listings when the site has them; fall back to everything for sites that only describe items in prose.
    structured = [it for it in items if it.get("structured")]
    if structured:
        items = structured
    index._all_items = items
    return items


def resolve_industry(asst: Optional[Dict[str, Any]], assistant_id: str) -> str:
    """The assistant's configured industry, or a best guess from its name, domain and catalog."""
    chosen = ((asst or {}).get("industry") or "auto").strip()
    if chosen in ("general", "real_estate", "ecommerce"):
        return chosen
    label = f"{(asst or {}).get('name') or ''} {(asst or {}).get('domain') or ''}".lower()
    if any(h in label for h in _RE_HINTS):
        return "real_estate"
    items = all_catalog_items(assistant_id)
    props = sum(1 for it in items if it.get("entity_type") == "property")
    prods = len(items) - props
    if props >= 3 and props >= prods:
        return "real_estate"
    if prods >= 3 or (prods and any(h in label for h in _SHOP_HINTS)):
        return "ecommerce"
    return "general"


def _keywords(query: str) -> List[str]:
    words = re.findall(r"[a-z0-9][a-z0-9-]*", query.lower())
    return list(dict.fromkeys(
        w for w in words
        if len(w) >= 3 and w not in STOPWORDS and w not in _GENERIC_WORDS and not re.fullmatch(r"\d+(?:k|m)?", w)
    ))


def wants_catalog(query: str, industry: str) -> bool:
    intent = parse_user_query_intent(query)
    if intent.get("is_catalog_query"):
        return True
    return industry in ("real_estate", "ecommerce") and bool(_SHOPPING_INTENT.search(query))


def find_matches(assistant_id: str, query: str, industry: str = "general",
                 limit: int = MAX_CARDS) -> Tuple[Dict[str, Any], List[Dict[str, Any]], bool]:
    """(intent, best items, exact) — exact is False when nothing fits and these are the closest options."""
    intent = parse_user_query_intent(query)
    if industry == "real_estate" and intent.get("entity_type") == "any":
        intent["entity_type"] = "property"
    elif industry == "ecommerce" and intent.get("entity_type") == "any":
        intent["entity_type"] = "product"

    items = [dict(it) for it in all_catalog_items(assistant_id)]  # copies: matching marks them
    if not items:
        return intent, [], False
    ranked = match_items_against_query(items, intent)
    if not ranked and intent.get("entity_type") != "any":
        ranked = match_items_against_query(items, {**intent, "entity_type": "any"})

    words = _keywords(query)

    def relevance(it: Dict[str, Any]) -> float:
        text = " ".join(str(it.get(k) or "") for k in ("name", "specs", "category", "brand", "location", "description")).lower()
        hits = sum(1 for w in words if w in text)
        loc_hit = any(w in (it.get("location") or "").lower() for w in words)
        return hits + (1.5 if loc_hit else 0.0) + (0.5 if it.get("image_url") else 0.0)

    if words:
        scored = [(relevance(it), pos, it) for pos, it in enumerate(ranked)]
        with_hits = [s for s in scored if s[0] >= 1]
        # If the visitor named something specific ("red sneakers", "marina"), only show items that mention it.
        pool = with_hits if with_hits else scored
        pool.sort(key=lambda s: (-s[0], s[1]))
        ranked = [s[2] for s in pool]
    exact = any(it.get("within_budget") for it in ranked[:limit]) and (
        not words or any(relevance(it) >= 1 for it in ranked[:limit]))
    return intent, ranked[:limit], exact


def _http(url: str) -> str:
    url = (url or "").strip()
    return url if re.match(r"^https?://", url, re.I) else ""


def to_card(it: Dict[str, Any]) -> Dict[str, Any]:
    """What the widget needs to draw one card (only safe http(s) links)."""
    beds = it.get("bedrooms")
    price = (it.get("price_str") or "").strip()
    num = it.get("price_num")
    if isinstance(num, (int, float)):
        # "AED 115000 / year" -> "AED 115,000"; the frequency is shown separately on the card.
        amount = f"{num:,.2f}" if num < 100 and num != int(num) else f"{num:,.0f}"
        symbol = {"USD": "$", "EUR": "€", "GBP": "£"}.get((it.get("currency") or "").upper())
        price = f"{symbol}{amount}" if symbol else f"{(it.get('currency') or '').upper()} {amount}".strip()
    return {
        "name": (it.get("name") or "")[:120],
        "kind": "property" if it.get("entity_type") == "property" else "product",
        "deal": it.get("deal_type") if it.get("entity_type") == "property" else "",
        "price": price[:60],
        "price_num": it.get("price_num"),
        "currency": it.get("currency") or "",
        "frequency": it.get("frequency") or "",
        "image": _http(it.get("image_url")),
        "url": _http(it.get("url")),
        "location": (it.get("location") or "")[:80],
        "bedrooms": "Studio" if beds == "studio" else (beds or ""),
        "bathrooms": (str(it.get("bathrooms") or "")[:10]),
        "size": (str(it.get("size") or "")[:30]),
        "availability": (it.get("availability") or "")[:30],
        "brand": (it.get("brand") or "")[:40],
        "category": (it.get("category") or "")[:40],
        "within_budget": bool(it.get("within_budget", True)),
    }


def listings_block(items: List[Dict[str, Any]], exact: bool, intent: Dict[str, Any]) -> str:
    """Compact summary of the matches for the model; the visitor sees them as cards under the reply."""
    if not items:
        return ""
    criteria = []
    if intent.get("max_price") is not None:
        criteria.append(f"budget up to {intent['max_price']:,.0f}")
    if intent.get("deal_type") in ("rent", "sale"):
        criteria.append("to rent" if intent["deal_type"] == "rent" else "to buy")
    if intent.get("bedrooms"):
        criteria.append(f"{intent['bedrooms']} bedroom(s)" if intent["bedrooms"] != "studio" else "studio")
    lines = []
    for n, it in enumerate(items, 1):
        bits = [it.get("name") or "Item", it.get("price_str") or "price on request"]
        for key, label in (("location", ""), ("bedrooms", "beds"), ("bathrooms", "baths"), ("size", ""),
                           ("brand", ""), ("availability", ""), ("specs", "")):
            v = it.get(key)
            if v:
                bits.append(f"{v} {label}".strip() if label else str(v)[:120])
        if it.get("url"):
            bits.append(it["url"])
        lines.append(f"L{n}. " + " | ".join(str(b) for b in bits))
    head = ("Matching listings" if exact else
            "Closest listings (nothing matches every criterion exactly — say so honestly)")
    if criteria:
        head += f" for: {', '.join(criteria)}"
    return (f"<listings>\n{head}. These are shown to the visitor as cards with photos, prices and links "
            "right under your reply.\n" + "\n".join(lines) + "\n</listings>")


# ---------------------------------------------------------------- prompts

INDUSTRY_PROMPTS = {
    "real_estate": """REAL ESTATE MODE
- You're {org}'s property consultant: knowledgeable, warm and efficient, like a top agent.
- When someone is searching, qualify them naturally, one short question at a time and only for what's missing: buying or renting, budget, preferred areas, bedrooms, and when they want to move. Don't interrogate; if they've given enough, show options.
- When <listings> are attached, the visitor already sees them as cards. Don't repeat every detail. Recommend the 2-3 best fits by name and say briefly why (price vs budget, area, size, a standout feature). Mention any trade-offs honestly.
- If nothing fits exactly, say so and point out the closest options and what's different (e.g. slightly over budget, one bedroom fewer).
- Offer the next step: booking a viewing, getting more photos or floor plans, or having an agent call. When they want a viewing or a call, end with {lead_tag}.
- Never invent prices, fees, service charges, availability, ROI or mortgage rates. You may do mortgage or rent-to-income arithmetic only with numbers the visitor gives you, and call it a rough estimate.""",
    "ecommerce": """E-COMMERCE MODE
- You're {org}'s shopping assistant: friendly, knowledgeable and honest, like a great in-store expert.
- Help people choose: ask at most one quick question if it really changes the recommendation (budget, size, use, style), otherwise recommend straight away.
- When <listings> are attached, the visitor already sees them as product cards with photos, prices and links. Don't repeat every spec. Recommend the best 1-3 by name and why they fit; compare options side by side when asked.
- Only state price, stock, sizes, colours, materials, shipping and returns if they appear in the listings or excerpts. If stock says out of stock, say so and suggest an alternative.
- Nudge toward the product page or checkout naturally, and suggest a genuinely useful add-on only when it fits. Never invent discounts or promo codes.""",
}


def industry_prompt(industry: str, org: str, lead_tag: str) -> str:
    template = INDUSTRY_PROMPTS.get(industry)
    return ("\n" + template.format(org=org, lead_tag=lead_tag) + "\n") if template else ""
