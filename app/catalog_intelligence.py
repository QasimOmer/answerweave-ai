"""
Catalog and Property Intelligence Engine for AnswerWeave / WeaveFlow AI.
Specialized in:
- E-Commerce product discovery & budget filtering
- Real Estate property search (Rentals vs Sales, bedrooms, locations, budget)
- Multi-currency extraction & arithmetic comparison (AED, $, EUR, GBP, SAR)
- Structured catalog chunk extraction & reranking
"""

import re
from typing import List, Dict, Any, Optional, Tuple, Set

# Currency normalization helpers
CURRENCY_MAP = {
    "aed": "AED",
    "dirham": "AED",
    "dirhams": "AED",
    "dhs": "AED",
    "$": "USD",
    "usd": "USD",
    "dollar": "USD",
    "dollars": "USD",
    "€": "EUR",
    "eur": "EUR",
    "euro": "EUR",
    "euros": "EUR",
    "£": "GBP",
    "gbp": "GBP",
    "pound": "GBP",
    "pounds": "GBP",
    "sar": "SAR",
    "riyal": "SAR",
    "riyals": "SAR",
    "inr": "INR",
    "rupee": "INR",
    "rupees": "INR"
}

def parse_user_query_intent(query: str) -> Dict[str, Any]:
    """
    Parses a user query to detect:
    - is_catalog_query: Whether this is looking for products, properties, or inventory
    - entity_type: 'product' | 'property' | 'any'
    - deal_type: 'rent' | 'sale' | 'any' (for real estate)
    - max_price: float upper budget bound
    - min_price: float lower budget bound
    - currency: 'AED' | 'USD' | 'EUR' | 'GBP' | 'AED_OR_USD' | 'ANY'
    - bedrooms: int, 'studio', or None
    - keywords: extracted attribute/location/category tokens
    """
    q = query.strip().lower()
    
    # Check if query is asking for catalog, inventory, recommendations, or budget items
    catalog_keywords = [
        "product", "products", "item", "items", "goods", "shop", "buy", "purchase",
        "property", "properties", "apartment", "apartments", "flat", "flats",
        "villa", "villas", "house", "houses", "home", "homes", "studio", "studios",
        "condo", "condos", "penthouse", "penthouses", "townhouse", "townhouses",
        "rent", "rental", "rentals", "leasing", "lease", "to rent", "for rent",
        "under", "below", "less than", "within", "max", "maximum", "budget",
        "price", "cost", "cheap", "cheapest", "affordable", "available", "suggest", "recommend"
    ]
    
    is_catalog_query = any(k in q for k in catalog_keywords)
    
    # Entity Type: product vs property vs any
    property_indicators = [
        "property", "properties", "apartment", "apartments", "flat", "flats",
        "villa", "villas", "house", "houses", "home", "homes", "studio", "studios",
        "condo", "condos", "penthouse", "penthouses", "townhouse", "townhouses",
        "real estate", "realtor", "rent property", "rental property", "rent apartment",
        "bhk", "bedroom", "bedrooms", "bed", "beds"
    ]
    product_indicators = [
        "product", "products", "item", "items", "merchandise", "goods",
        "shoe", "shoes", "sneaker", "sneakers", "cloth", "clothes", "clothing",
        "shirt", "laptop", "phone", "electronics", "bag", "watch", "perfume"
    ]
    
    has_property = any(w in q for w in property_indicators)
    has_product = any(w in q for w in product_indicators)
    
    if has_property and not has_product:
        entity_type = "property"
    elif has_product and not has_property:
        entity_type = "product"
    elif has_property and has_product:
        entity_type = "any"
    else:
        # If deal_type is rent, default to property
        if any(w in q for w in ["rent", "rental", "rentals", "lease", "leasing"]):
            entity_type = "property"
        else:
            entity_type = "any"

    # Deal Type: rent vs sale vs any
    rent_indicators = ["rent", "rental", "rentals", "lease", "leasing", "to rent", "for rent", "per month", "monthly", "per year", "annual"]
    sale_indicators = ["sale", "for sale", "buy", "purchase", "invest", "investment", "to buy"]
    
    has_rent = any(w in q for w in rent_indicators)
    has_sale = any(w in q for w in sale_indicators)
    
    if has_rent and not has_sale:
        deal_type = "rent"
    elif has_sale and not has_rent:
        deal_type = "sale"
    else:
        deal_type = "rent" if entity_type == "property" and has_rent else "any"

    # Currency extraction
    found_currencies = set()
    if re.search(r'(?:[0-9]|\b)(aed|dirham|dirhams|dhs)(?:[0-9.,!?]|\b)', q):
        found_currencies.add("AED")
    if "$" in q or re.search(r'(?:[0-9]|\b)(usd|dollar|dollars)(?:[0-9.,!?]|\b)', q):
        found_currencies.add("USD")
    if "€" in q or re.search(r'(?:[0-9]|\b)(eur|euro|euros)(?:[0-9.,!?]|\b)', q):
        found_currencies.add("EUR")
    if "£" in q or re.search(r'(?:[0-9]|\b)(gbp|pound|pounds)(?:[0-9.,!?]|\b)', q):
        found_currencies.add("GBP")
    if re.search(r'(?:[0-9]|\b)(sar|riyal|riyals)(?:[0-9.,!?]|\b)', q):
        found_currencies.add("SAR")

    # Handle multi-currency queries like "under 1000 aed or $"
    if "AED" in found_currencies and "USD" in found_currencies:
        currency = "AED_OR_USD"
    elif found_currencies:
        currency = list(found_currencies)[0]
    else:
        currency = "ANY"

    # Budget / Price Extraction:
    # Patterns:
    # "under 500aed", "under 500 aed", "under $500", "below 1000", "under 1000 aed or $", "max 500"
    max_price = None
    min_price = None

    # Check for upper bound: "under X", "below X", "less than X", "within X", "max X", "up to X", "<= X"
    upper_patterns = [
        r'(?:under|below|less\s+than|within|max|maximum|up\s+to|cheaper\s+than|budget\s+of)\s*[\$€£]?\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)\s*(?:k|kilo|thousand)?\s*(?:aed|dhs|usd|\$|€|£|eur|gbp|sar)?',
        r'[\$€£]\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)\s*(?:k)?\s*(?:or\s+less|or\s+below|max)',
        r'([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)\s*(?:k)?\s*(?:aed|dhs|usd|\$|€|£)?\s*(?:or\s+less|or\s+below|max|budget)'
    ]
    
    for pat in upper_patterns:
        match = re.search(pat, q)
        if match:
            raw_val = match.group(1).replace(",", "")
            try:
                val = float(raw_val)
                # Check if "k" suffix was matched
                full_matched_text = match.group(0).lower()
                if "k" in full_matched_text and not full_matched_text.endswith("k"):
                    # Check if 'k' follows the number
                    if re.search(r'[0-9]\s*k\b', full_matched_text):
                        val *= 1000
                elif full_matched_text.endswith("k") or "thousand" in full_matched_text:
                    val *= 1000
                max_price = val
                is_catalog_query = True
                break
            except ValueError:
                pass

    # Range: "between X and Y"
    range_match = re.search(r'between\s*[\$€£]?\s*([0-9,]+)\s*(?:and|to|-)\s*[\$€£]?\s*([0-9,]+)', q)
    if range_match:
        try:
            min_p = float(range_match.group(1).replace(",", ""))
            max_p = float(range_match.group(2).replace(",", ""))
            min_price = min_p
            max_price = max_p
            is_catalog_query = True
        except ValueError:
            pass

    # Bedroom extraction (studio, 1 bed, 2 bedroom, 3 bhk, etc.)
    bedrooms = None
    if "studio" in q:
        bedrooms = "studio"
    else:
        bed_match = re.search(r'\b([1-9])\s*(?:bed|bedroom|bedrooms|bhk|br)\b', q)
        if bed_match:
            bedrooms = int(bed_match.group(1))

    # Location / Attribute keywords
    location_list = ["downtown", "marina", "jvc", "jlt", "business bay", "al barsha", "al furjan", "palm jumeirah", "hills", "ranches", "deira", "bur dubai"]
    found_locations = [loc for loc in location_list if loc in q]

    return {
        "is_catalog_query": is_catalog_query or (max_price is not None),
        "entity_type": entity_type,
        "deal_type": deal_type,
        "max_price": max_price,
        "min_price": min_price,
        "currency": currency,
        "bedrooms": bedrooms,
        "locations": found_locations,
        "raw_query": query
    }

def extract_price_and_currency(text: str) -> Tuple[Optional[float], Optional[str], Optional[str]]:
    """
    Extracts (numeric_price, currency_code, frequency) from a text line or snippet.
    Examples:
    "• Price: 450 AED" -> (450.0, "AED", "")
    "• Price: 4,500 AED / month" -> (4500.0, "AED", "month")
    "$89.99" -> (89.99, "USD", "")
    """
    clean = text.strip()
    
    # 1. Check frequency
    frequency = ""
    if re.search(r'/\s*(?:month|mo)\b|per\s+month|monthly', clean, re.I):
        frequency = "month"
    elif re.search(r'/\s*(?:year|yr|annum)\b|per\s+year|annually|annual', clean, re.I):
        frequency = "year"
    elif re.search(r'/\s*(?:day|night)\b|per\s+day|daily|nightly', clean, re.I):
        frequency = "day"

    # 2. Match currency and number patterns
    patterns = [
        # "AED 450", "AED 4,500.00", "Dhs 450"
        r'(?:aed|dhs|dirhams?)\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)',
        # "450 AED", "4,500 AED"
        r'([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)\s*(?:aed|dhs|dirhams?)',
        # "$450", "$ 450.00"
        r'\$\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)',
        # "450 USD", "450 $"
        r'([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)\s*(?:usd|\$)',
        # "€ 450", "450 €", "450 EUR"
        r'(?:€|eur)\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)',
        r'([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)\s*(?:€|eur)',
        # "£ 450", "450 £", "450 GBP"
        r'(?:£|gbp)\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)',
        r'([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)\s*(?:£|gbp)',
        # Generic "Price: 450"
        r'(?:price|cost|rent):\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)'
    ]

    for pat in patterns:
        match = re.search(pat, clean, re.I)
        if match:
            num_str = match.group(1).replace(",", "")
            try:
                num = float(num_str)
                # Determine currency
                curr = "USD" if "$" in match.group(0) else ("AED" if re.search(r'aed|dhs', match.group(0), re.I) else ("EUR" if "€" in match.group(0) or "eur" in match.group(0).lower() else ("GBP" if "£" in match.group(0) or "gbp" in match.group(0).lower() else "AED")))
                return num, curr, frequency
            except ValueError:
                pass

    return None, None, None

def extract_catalog_items_from_chunk(
    content: str,
    chunk_index: int = 1,
    url: str = "",
    title: str = ""
) -> List[Dict[str, Any]]:
    """
    Parses individual products and property listings from a chunk.
    Works on structured catalog chunks (with headers, bullet points) as well as semi-structured text.
    """
    items = []
    
    # 1. Delimited item blocks (e.g. from parse_csv_catalog or clean_html)
    if "==================================================" in content:
        raw_blocks = re.split(r"={30,}", content)
    elif "🏷️ PRODUCT SPECIFICATION:" in content or "🏠 PROPERTY LISTING:" in content or "🏷️ STRUCTURED" in content:
        raw_blocks = re.split(r"(?=(?:🏷️|🏠)\s*(?:PRODUCT SPECIFICATION|PROPERTY LISTING|STRUCTURED))", content)
    else:
        # Check if entire chunk is an individual item
        raw_blocks = [content]

    for block in raw_blocks:
        b = block.strip()
        if not b or len(b) < 25:
            continue

        # Check for item name
        name = ""
        name_match = re.search(
            r'(?:(?:🏷️|🏠)?\s*(?:PRODUCT SPECIFICATION|PROPERTY LISTING|STRUCTURED ITEM SPECIFICATION)(?:\s*\([^)]*\))?:\s*([^\n]+))|(?:Item Name:\s*([^\n]+))|(?:Product:\s*([^\n]+))|(?:Property:\s*([^\n]+))',
            b, re.I
        )
        if name_match:
            name = (name_match.group(1) or name_match.group(2) or name_match.group(3) or name_match.group(4) or "").strip()
        
        # If no explicit name tag, check first line if it looks like a product/property title
        if not name:
            first_line = b.split("\n")[0].strip()
            if len(first_line) > 5 and len(first_line) < 100 and not first_line.startswith("http") and not first_line.startswith("#"):
                if any(w in b.lower() for w in ["price:", "• price", "rent:", "aed", "$"]):
                    name = first_line

        # Clean name of any remaining prefixes or emoji markers
        name = re.sub(r'^(?:🏷️|🏠)?\s*(?:PRODUCT SPECIFICATION|PROPERTY LISTING|STRUCTURED ITEM SPECIFICATION)(?:\s*\([^)]*\))?:\s*', '', name, flags=re.I).strip()
        name = re.sub(r'^(?:Item Name|Product|Property):\s*', '', name, flags=re.I).strip()

        # Price extraction
        price_num = None
        curr = None
        freq = ""
        
        price_line_match = re.search(r'(?:•\s*)?(?:Price|Cost|Rent|Rate):\s*([^\n]+)', b, re.I)
        if price_line_match:
            raw_price_str = price_line_match.group(1).strip()
            price_num, curr, freq = extract_price_and_currency(raw_price_str)
            price_display = raw_price_str
        else:
            price_num, curr, freq = extract_price_and_currency(b)
            if price_num is not None:
                price_display = f"{curr or ''} {price_num:,.2f}" if curr else f"{price_num:,.2f}"
            else:
                price_display = "Inquire for Pricing"

        # If no price could be extracted and it's not a clear item block, skip
        if price_num is None and not ("PRODUCT SPECIFICATION" in b or "PROPERTY LISTING" in b):
            continue

        # Entity type & deal type
        is_prop = any(w in b.lower() for w in ["property listing", "apartment", "villa", "penthouse", "studio", "bedroom", "bhk", "landlord", "rent", "tenant", "real estate"])
        entity_type = "property" if is_prop else "product"
        
        deal_type = "product"
        if is_prop:
            if freq in ["month", "year", "day"] or any(w in b.lower() for w in ["rental", "for rent", "to rent", "rent:", "per month", "monthly", "leasing", "rent"]):
                deal_type = "rent"
            else:
                deal_type = "sale"

        # Bedrooms
        bedrooms = None
        if "studio" in b.lower():
            bedrooms = "studio"
        else:
            bed_m = re.search(r'\b([1-9])\s*(?:bed|bedroom|bhk|br)\b', b, re.I)
            if bed_m:
                bedrooms = int(bed_m.group(1))

        # Location
        location = ""
        loc_match = re.search(r'(?:•\s*)?(?:Location|Neighborhood|Address):\s*([^\n]+)', b, re.I)
        if loc_match:
            location = loc_match.group(1).strip()

        # Specs & Features
        specs = ""
        specs_match = re.search(r'(?:•\s*)?(?:Key Specs & Features|Features|Specs|Details):\s*([^\n]+)', b, re.I)
        if specs_match:
            specs = specs_match.group(1).strip()

        # Direct URL
        direct_url = url
        url_match = re.search(r'(?:•\s*)?(?:Direct URL|URL|Link):\s*(https?://[^\s\n]+)', b, re.I)
        if url_match:
            direct_url = url_match.group(1).strip()

        # Description snippet
        desc = ""
        desc_match = re.search(r'(?:•\s*)?Description:\s*([^\n]+)', b, re.I)
        if desc_match:
            desc = desc_match.group(1).strip()

        items.append({
            "name": name or title or "Featured Item",
            "entity_type": entity_type,
            "deal_type": deal_type,
            "price_num": price_num,
            "price_str": price_display,
            "currency": curr or "AED",
            "frequency": freq,
            "bedrooms": bedrooms,
            "location": location,
            "specs": specs,
            "description": desc,
            "url": direct_url,
            "chunk_index": chunk_index,
            "title": title
        })

    return items

def match_items_against_query(
    items: List[Dict[str, Any]],
    intent: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """
    Filters and ranks extracted catalog items against the user query intent.
    Matches budget constraints, deal type (rent vs buy), entity type (product vs property).
    """
    if not items:
        return []

    matched = []
    over_budget = []
    
    req_entity = intent.get("entity_type", "any")
    req_deal = intent.get("deal_type", "any")
    req_curr = intent.get("currency", "ANY")
    max_price = intent.get("max_price")
    min_price = intent.get("min_price")
    req_beds = intent.get("bedrooms")
    req_locs = intent.get("locations", [])

    for item in items:
        score = 1.0
        
        # 1. Entity type check
        if req_entity != "any" and item["entity_type"] != req_entity:
            # If user explicitly asked for property, do not show shoes/products
            continue

        # 2. Deal type check for properties (rent vs sale)
        if req_deal == "rent" and item["deal_type"] == "sale":
            # If user explicitly asked for rental property, deprioritize or skip sale listings
            score -= 0.5
        elif req_deal == "sale" and item["deal_type"] == "rent":
            score -= 0.5

        # 3. Currency compatibility
        item_curr = item.get("currency", "").upper()
        curr_match = True
        if req_curr == "AED_OR_USD":
            curr_match = item_curr in ["AED", "USD", "$"]
        elif req_curr not in ["ANY", ""]:
            # If user specified AED, match AED
            if req_curr == "AED" and item_curr != "AED":
                curr_match = False
            elif req_curr == "USD" and item_curr not in ["USD", "$"]:
                curr_match = False

        # 4. Bedroom check
        if req_beds is not None:
            if item.get("bedrooms") == req_beds:
                score += 0.5
            elif item.get("bedrooms") is not None and item.get("bedrooms") != req_beds:
                score -= 0.3

        # 5. Location check
        if req_locs:
            item_text = (item.get("location", "") + " " + item.get("name", "")).lower()
            if any(loc in item_text for loc in req_locs):
                score += 0.6

        # 6. Budget check
        p_num = item.get("price_num")
        if max_price is not None:
            if p_num is not None:
                # Check if within budget
                if p_num <= max_price:
                    # Within budget!
                    score += 1.5
                    item["within_budget"] = True
                    matched.append((score, item))
                else:
                    # Over budget
                    item["within_budget"] = False
                    over_budget.append((p_num - max_price, item))
            else:
                # Price unknown/unspecified - cannot confirm under requested budget
                item["within_budget"] = False
                over_budget.append((999999, item))
        else:
            # No budget constraint specified
            item["within_budget"] = True
            matched.append((score, item))

    # Sort matching items by score descending, then price ascending
    matched.sort(key=lambda x: (-x[0], x[1].get("price_num") or 999999999))
    result = [m[1] for m in matched]

    # If no items met the exact budget, sort over_budget items by closest price
    if not result and over_budget:
        over_budget.sort(key=lambda x: x[0])
        result = [o[1] for o in over_budget]

    return result

def format_catalog_recommendation_answer(
    matched_items: List[Dict[str, Any]],
    query_intent: Dict[str, Any],
    assistant_name: str = "Our Team",
    allowed_urls: Optional[Set[str]] = None
) -> Dict[str, Any]:
    """
    Generates a clear, professional, structured answer for product/property queries.
    Used for local extractive mode as well as zero-key offline generation.
    Strictly prevents 404 links by verifying URLs against allowed_urls.
    """
    if not matched_items:
        return {
            "answer": None,
            "lead_prompted": True
        }

    norm_allowed = {u.strip().rstrip("/").lower() for u in allowed_urls if u} if allowed_urls is not None else None

    max_p = query_intent.get("max_price")
    curr = query_intent.get("currency")
    curr_label = "AED" if curr == "AED" else ("$" if curr == "USD" else (curr if curr not in ["ANY", "AED_OR_USD"] else ""))
    is_prop = query_intent.get("entity_type") == "property" or any(it.get("entity_type") == "property" for it in matched_items)
    is_rental = query_intent.get("deal_type") == "rent"

    # Check if we have items that fit the budget
    fitting_items = [it for it in matched_items if it.get("within_budget", True)]

    lines = []
    lead_prompted = False

    if fitting_items:
        if max_p:
            item_label = "rental properties" if (is_prop and is_rental) else ("properties" if is_prop else "products")
            budget_str = f"**{max_p:,.0f} AED or $**" if curr == "AED_OR_USD" else f"**{curr_label + ' ' if curr_label else ''}{max_p:,.0f}**"
            lines.append(f"Here are our available {item_label} under {budget_str}:")
        else:
            item_label = "rental properties" if (is_prop and is_rental) else ("properties" if is_prop else "options")
            lines.append(f"Here are our top recommended {item_label}:")

        for it in fitting_items[:4]:
            name = it.get("name", "Item")
            price = it.get("price_str", "Inquire for price")
            specs = it.get("specs") or ""
            loc = it.get("location") or ""
            url = it.get("url") or ""
            idx = it.get("chunk_index", 1)

            entry = f"• **{name}** — **{price}**"
            details = []
            if loc:
                details.append(f"📍 {loc}")
            if specs:
                details.append(specs)
            if details:
                entry += f"\n  {' • '.join(details)}"
            if url and url != "#" and url.startswith("http"):
                norm_u = url.strip().rstrip("/").lower()
                is_valid_url = True
                if norm_allowed is not None:
                    is_valid_url = norm_u in norm_allowed
                if is_valid_url:
                    entry += f"\n  🔗 [View Listing]({url})"
            entry += f" [{idx}]"
            lines.append(entry)

        lines.append("\nWould you like more details on any of these options or to speak with our team?")
    else:
        # We had items, but NONE were under the requested budget!
        # Provide transparent and helpful guidance with closest alternatives.
        lowest_item = matched_items[0]
        lowest_price = lowest_item.get("price_str", "")
        item_label = "rental properties" if (is_prop and is_rental) else ("properties" if is_prop else "products")
        budget_str = f"**{max_p:,.0f} AED or $**" if curr == "AED_OR_USD" else f"**{curr_label + ' ' if curr_label else ''}{max_p:,.0f}**"
        
        lines.append(
            f"We currently do not have {item_label} available under {budget_str}."
        )
        lines.append(
            f"Our closest available options start from **{lowest_price}**:\n"
            f"• **{lowest_item.get('name')}** — **{lowest_price}**"
            + (f" ({lowest_item.get('location')})" if lowest_item.get("location") else "")
            + f" [{lowest_item.get('chunk_index', 1)}]"
        )
        lines.append(
            "Please feel free to leave your contact email below and our team will be glad to assist you with tailored options that fit your requirements!"
        )
        lead_prompted = True

    return {
        "answer": "\n\n".join(lines),
        "lead_prompted": lead_prompted
    }

def build_real_estate_overview_answer(
    query_intent: Dict[str, Any],
    chunks: List[Dict[str, Any]],
    assistant_name: str = "Our Team",
    allowed_urls: Optional[Set[str]] = None
) -> Dict[str, Any]:
    """
    Synthesizes a domain-aware, professional real-estate overview answer when
    individual item catalog cards are not present or when answering high-level property inquiries.
    Covers Rentals, Sales, Off-Plan, Selling, and Budget Guidance.
    """
    deal_type = query_intent.get("deal_type", "any")
    max_p = query_intent.get("max_price")
    curr = query_intent.get("currency")
    curr_label = "AED" if curr in ["AED", "ANY"] else ("$" if curr == "USD" else (curr if curr not in ["ANY", "AED_OR_USD"] else "AED or $"))
    
    # Locate verified action URLs if present
    norm_allowed = {u.strip().rstrip("/").lower(): u for u in allowed_urls} if allowed_urls else {}
    
    def find_best_link(keyword: str, fallback: str) -> Optional[str]:
        for k, original_url in norm_allowed.items():
            if k.endswith("/" + keyword) or k == fallback.rstrip("/").lower():
                return original_url
        for k, original_url in norm_allowed.items():
            if keyword in k:
                return original_url
        if any("idealhomes" in u for u in norm_allowed.values()) or "ideal homes" in assistant_name.lower():
            return fallback
        return None

    off_plan_link = find_best_link("off-plan", "https://idealhomes.ae/off-plan")
    sell_link = find_best_link("sell", "https://idealhomes.ae/sell")
    contact_link = find_best_link("contact", "https://idealhomes.ae/contact")
    list_link = find_best_link("list-your-property", "https://idealhomes.ae/list-your-property")

    lines = []
    
    # 1. Budget Rental Query (e.g., "rental properties under 500000" or "under 1000 aed or $")
    if max_p is not None and deal_type == "rent":
        is_below_market = (
            (curr in ["AED", "ANY", "AED_OR_USD"] and max_p < 2500)
            or (curr == "USD" and max_p < 700)
            or (curr in ["EUR", "GBP"] and max_p < 600)
        )
        budget_disp = f"**{max_p:,.0f} AED or $**" if curr == "AED_OR_USD" else f"**{curr_label + ' ' if curr_label else ''}{max_p:,.0f}**"
        
        if is_below_market:
            lines.append(
                f"In Dubai, typical residential rental rates generally start higher than {budget_disp} "
                f"(studios in residential communities typically start from approximately 3,000–4,500 AED / month depending on location, furnishings, and payment terms)."
            )
            lines.append(
                f"{assistant_name} offers a wide selection of competitive rental options across Dubai. "
                f"Our RERA-certified leasing consultants can help identify the best value options matching your preferred criteria."
            )
        else:
            lines.append(
                f"{assistant_name} offers a comprehensive portfolio of residential rental properties across Dubai within your budget of {budget_disp}:"
            )
            lines.append(
                "• **Available Options**: From modern studios and 1–3 bedroom apartments in prime city hubs to luxury waterfront penthouses and private family villas.\n"
                "• **Top Communities**: Dubai Marina, Downtown Dubai, Palm Jumeirah, JVC (Jumeirah Village Circle), Business Bay, and Dubai Hills Estate.\n"
                "• **Full Tenancy Support**: Our RERA-certified leasing consultants handle private viewings, RERA-compliant tenancy contracts, Ejari registration, and move-in inspection reports."
            )
        lines.append(
            "Would you like to explore apartments, villas, or townhouses? Feel free to share your preferred community and bedroom count, or leave your contact details below to speak directly with our leasing team!"
        )

    # 2. General Rental Query (e.g., "can u share seome renatl properties")
    elif deal_type == "rent":
        lines.append(
            f"{assistant_name} provides an extensive selection of residential and commercial rental properties across Dubai's most desirable communities:"
        )
        lines.append(
            "• **Property Options**: Fully furnished and unfurnished studios, 1–4 bedroom apartments, waterfront residences, and private family villas.\n"
            "• **Prime Locations**: Dubai Marina, Downtown Dubai, Palm Jumeirah, JVC (Jumeirah Village Circle), Business Bay, and Arabian Ranches.\n"
            "• **End-to-End Tenancy Support**: RERA-compliant tenancy contracts, Ejari registration, DEWA connection assistance, and move-in coordination."
        )
        if contact_link:
            lines.append(f"🔗 [Contact Our Leasing Specialists]({contact_link})")
        lines.append(
            "Please feel free to share your preferred location, bedroom count, or budget below, and our leasing team will be glad to share tailored options!"
        )

    # 3. Sales / Buying / Selling (e.g., "properties for sell", "properties for sale", "buy property")
    elif deal_type == "sale":
        lines.append(
            f"{assistant_name} provides full-service real estate brokerage across Dubai for buyers, investors, and property sellers:"
        )
        sales_points = [
            "• **Properties for Sale & Off-Plan Investments**:\n"
            "  - Ready apartments, luxury penthouses, and villas across Dubai Marina, Downtown Dubai, Palm Jumeirah, and Dubai Hills Estate.\n"
            "  - Exclusive off-plan project launches directly from top developers (Emaar, Nakheel, Sobha, Damac) with flexible developer payment plans.",
            "• **Selling Your Property**:\n"
            "  - Complete seller brokerage including free market valuations, professional photography, RERA Form A marketing, and qualified buyer matching.",
            "• **Advisory & Conveyancing**:\n"
            "  - Complete guidance through Dubai Land Department (DLD) transfer procedures, NOC issuance, and mortgage financing."
        ]
        lines.append("\n\n".join(sales_points))
        action_links = []
        if off_plan_link:
            action_links.append(f"🔗 [Explore Off-Plan Projects]({off_plan_link})")
        if sell_link:
            action_links.append(f"🔗 [Sell Your Property & Free Valuation]({sell_link})")
        if contact_link:
            action_links.append(f"🔗 [Contact Our Sales Team]({contact_link})")
        if action_links:
            lines.append(" • ".join(action_links))
        lines.append(
            "Are you looking to buy a property, explore off-plan investments, or list your property for sale? Let us know or leave your contact details below to speak with a specialist!"
        )

    # 4. General Property Overview (e.g., "tell me about properties")
    else:
        lines.append(
            f"{assistant_name} is a RERA-certified Dubai real estate brokerage offering end-to-end property solutions across Dubai's top communities:"
        )
        lines.append(
            "• **Buying & Off-Plan Investments**: Ready residential homes, waterfront penthouses, and new off-plan launches with developer payment plans.\n"
            "• **Renting & Leasing**: Apartments, studios, and villas across prime communities with complete Ejari registration and tenancy contract support.\n"
            "• **Property Management & Selling**: 25 specialized landlord management services, tenant screening, maintenance, and free property valuations."
        )
        action_links = []
        if off_plan_link:
            action_links.append(f"🔗 [Off-Plan Projects]({off_plan_link})")
        if sell_link:
            action_links.append(f"🔗 [Sell Your Property]({sell_link})")
        if contact_link:
            action_links.append(f"🔗 [Contact Team]({contact_link})")
        if action_links:
            lines.append(" • ".join(action_links))
        lines.append(
            "How can we assist your property search today? Feel free to share your preferred community or budget, or leave your contact details below!"
        )

    return {
        "answer": "\n\n".join(lines),
        "lead_prompted": True
    }

