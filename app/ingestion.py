"""
Document ingestion pipeline for WeaveFlow AI.
Supports:
- Web crawling & HTML cleaning
- Sitemap.xml bulk URL extraction
- Direct PDF file parsing via pypdf
- Markdown, TXT, CSV file ingestion
- Semantic text chunking
"""

import re
import io
import json
import csv
import urllib.parse
from typing import List, Dict, Any, Set, Optional
import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

def extract_structured_metadata(soup: BeautifulSoup, base_url: str = "") -> str:
    """
    Extracts structured product, real estate, and offer metadata from JSON-LD,
    HTML Microdata, OpenGraph meta tags, and common catalog cards.
    """
    spec_lines = []
    
    # 1. Parse JSON-LD scripts
    for script in soup.find_all("script", type="application/ld+json"):
        if not script.string:
            continue
        try:
            raw_data = json.loads(script.string.strip())
            items_to_check = []
            if isinstance(raw_data, list):
                items_to_check.extend(raw_data)
            elif isinstance(raw_data, dict):
                if "@graph" in raw_data and isinstance(raw_data["@graph"], list):
                    items_to_check.extend(raw_data["@graph"])
                else:
                    items_to_check.append(raw_data)

            for item in items_to_check:
                if not isinstance(item, dict):
                    continue
                type_val = str(item.get("@type", "")).lower()
                is_prod = any(t in type_val for t in ["product", "individualproduct", "offer", "itempage"])
                is_re = any(t in type_val for t in ["realestatelisting", "singlefamilyresidence", "apartment", "house", "residence", "accommodation", "place"])
                
                if is_prod or is_re:
                    name = item.get("name") or item.get("headline") or ""
                    desc = item.get("description") or ""
                    
                    price = ""
                    curr = ""
                    freq = ""
                    offers = item.get("offers")
                    if isinstance(offers, dict):
                        price = str(offers.get("price", ""))
                        curr = str(offers.get("priceCurrency", ""))
                        ps = offers.get("priceSpecification", {})
                        if isinstance(ps, dict):
                            freq = str(ps.get("unitText") or ps.get("billingIncrement") or "")
                    elif isinstance(offers, list) and len(offers) > 0 and isinstance(offers[0], dict):
                        price = str(offers[0].get("price", ""))
                        curr = str(offers[0].get("priceCurrency", ""))
                        ps = offers[0].get("priceSpecification", {})
                        if isinstance(ps, dict):
                            freq = str(ps.get("unitText") or ps.get("billingIncrement") or "")
                    elif "price" in item:
                        price = str(item.get("price", ""))
                        curr = str(item.get("priceCurrency", ""))

                    # Detect rental frequency
                    is_rental = False
                    if is_re:
                        combined_text = (name + " " + desc + " " + str(offers)).lower()
                        if any(w in combined_text for w in ["rent", "rental", "per month", "/month", "/mo", "monthly", "leasing"]):
                            is_rental = True
                            if not freq or "mon" in freq.lower():
                                freq = "month"
                        elif any(w in combined_text for w in ["per year", "/year", "/yr", "annually", "annual"]):
                            is_rental = True
                            freq = "year"

                    beds = item.get("numberOfBedrooms") or item.get("numberOfRooms")
                    baths = item.get("numberOfBathroomsTotal") or item.get("numberOfBathrooms")
                    area = item.get("floorSize", {}).get("value") if isinstance(item.get("floorSize"), dict) else item.get("floorSize")

                    address_str = ""
                    addr = item.get("address")
                    if isinstance(addr, dict):
                        address_str = f"{addr.get('streetAddress', '')} {addr.get('addressLocality', '')} {addr.get('addressRegion', '')}".strip()
                    elif isinstance(addr, str):
                        address_str = addr

                    specs = []
                    item_type_label = ("PROPERTY LISTING (FOR RENT)" if is_rental else "PROPERTY LISTING (FOR SALE)") if is_re else "PRODUCT SPECIFICATION"
                    formatted_price = f"{curr + ' ' if curr else ''}{price}".strip()
                    if freq and is_rental:
                        formatted_price += f" / {freq}"

                    if name: specs.append(f"• Item Name: {name}")
                    if formatted_price: specs.append(f"• Price: {formatted_price}")
                    if is_re: specs.append(f"• Deal Type: {'Rental' if is_rental else 'For Sale'}")
                    if address_str: specs.append(f"• Location / Address: {address_str}")
                    if beds: specs.append(f"• Bedrooms: {beds}")
                    if baths: specs.append(f"• Bathrooms: {baths}")
                    if area: specs.append(f"• Size: {area}")
                    if desc: specs.append(f"• Description: {desc[:300]}")
                    if base_url: specs.append(f"• Direct URL: {base_url}")
                    
                    if specs:
                        spec_lines.append(f"🏷️ STRUCTURED {item_type_label}:\n" + "\n".join(specs))
        except Exception:
            continue

    # 2. Parse HTML Microdata (itemscope itemtype="...Product|RealEstate...")
    if not spec_lines:
        micro_items = soup.find_all(attrs={"itemscope": True})
        for m in micro_items[:8]:
            itype = str(m.get("itemtype", "")).lower()
            is_prod = "product" in itype or "offer" in itype
            is_re = any(t in itype for t in ["realestatelisting", "apartment", "house", "residence"])
            if is_prod or is_re:
                name_tag = m.find(attrs={"itemprop": "name"})
                price_tag = m.find(attrs={"itemprop": "price"}) or m.find(attrs={"itemprop": "lowPrice"})
                curr_tag = m.find(attrs={"itemprop": "priceCurrency"})
                desc_tag = m.find(attrs={"itemprop": "description"})
                addr_tag = m.find(attrs={"itemprop": "address"})
                bed_tag = m.find(attrs={"itemprop": re.compile(r"numberOfBedrooms|numberOfRooms", re.I)})

                name_val = name_tag.get_text().strip() if name_tag else ""
                price_val = price_tag.get("content") or (price_tag.get_text().strip() if price_tag else "")
                curr_val = curr_tag.get("content") or (curr_tag.get_text().strip() if curr_tag else "")
                desc_val = desc_tag.get_text().strip() if desc_tag else ""

                if name_val and price_val:
                    specs = [f"• Item Name: {name_val}", f"• Price: {curr_val + ' ' if curr_val else ''}{price_val}"]
                    if addr_tag: specs.append(f"• Location / Address: {addr_tag.get_text().strip()}")
                    if bed_tag: specs.append(f"• Bedrooms: {bed_tag.get_text().strip()}")
                    if desc_val: specs.append(f"• Description: {desc_val[:250]}")
                    if base_url: specs.append(f"• Direct URL: {base_url}")
                    label = "PROPERTY LISTING" if is_re else "PRODUCT SPECIFICATION"
                    spec_lines.append(f"🏷️ STRUCTURED {label}:\n" + "\n".join(specs))

    # 3. Parse OpenGraph meta tags if no JSON-LD or Microdata found
    if not spec_lines:
        og_title = soup.find("meta", property=re.compile(r"og:title|twitter:title", re.I))
        og_price = soup.find("meta", property=re.compile(r"product:price:amount|og:price:amount", re.I))
        og_curr = soup.find("meta", property=re.compile(r"product:price:currency|og:price:currency", re.I))
        og_desc = soup.find("meta", property=re.compile(r"og:description|twitter:description", re.I))
        
        if og_title and og_title.get("content"):
            title_text = og_title.get("content").strip()
            price_text = og_price.get("content", "").strip() if og_price else ""
            curr_text = og_curr.get("content", "").strip() if og_curr else ""
            desc_text = og_desc.get("content", "").strip() if og_desc else ""
            
            if price_text:
                spec_lines.append(
                    f"🏷️ STRUCTURED ITEM SPECIFICATION:\n"
                    f"• Item Name: {title_text}\n"
                    f"• Price: {curr_text + ' ' if curr_text else ''}{price_text}\n"
                    f"• Description: {desc_text[:300]}\n"
                    f"• Direct URL: {base_url}"
                )

    return "\n\n".join(spec_lines)

def clean_html(html_content: str, base_url: str = "") -> Dict[str, str]:
    soup = BeautifulSoup(html_content, "html.parser")
    
    # Extract title
    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    elif soup.find("h1"):
        title = soup.find("h1").get_text().strip()
    else:
        title = base_url or "Untitled Document"

    # Pre-extract structured catalog & property schema before removing script tags
    structured_block = extract_structured_metadata(soup, base_url=base_url)

    # Remove irrelevant tags
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript", "iframe", "svg"]):
        tag.decompose()
        
    main = soup.find("main") or soup.find("article") or soup.find("div", {"id": re.compile(r"content|main|body", re.I)}) or soup.body
    text = main.get_text(separator="\n", strip=True) if main else soup.get_text(separator="\n", strip=True)

    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    
    full_content = (structured_block + "\n\n" + text).strip() if structured_block else text.strip()

    return {
        "title": title,
        "content": full_content
    }

DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"

def fetch_url(url: str, timeout: int = 15) -> Dict[str, str]:
    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }
    resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    resp.raise_for_status()
    return clean_html(resp.text, base_url=url)

def crawl_sitemap(sitemap_url: str, max_urls: int = 100) -> List[str]:
    """Extracts page URLs from a sitemap.xml, including nested sitemap indexes."""
    headers = {
        "User-Agent": DEFAULT_USER_AGENT
    }
    found_urls = []
    try:
        resp = requests.get(sitemap_url, headers=headers, timeout=10, allow_redirects=True)
        if resp.status_code != 200:
            return []
        
        # Regex loc extraction (avoids lxml dependency)
        locs = re.findall(r"<loc>\s*(https?://[^\s<]+)\s*</loc>", resp.text, re.I)
        
        # Check for nested sub-sitemaps
        sub_sitemaps = [u for u in locs if u.endswith(".xml") or "sitemap" in u]
        if sub_sitemaps:
            for sm_url in sub_sitemaps[:5]:
                try:
                    sub_resp = requests.get(sm_url, headers=headers, timeout=10, allow_redirects=True)
                    sub_locs = re.findall(r"<loc>\s*(https?://[^\s<]+)\s*</loc>", sub_resp.text, re.I)
                    for u in sub_locs:
                        clean_u = u.strip()
                        if clean_u and not clean_u.endswith(".xml") and clean_u not in found_urls:
                            found_urls.append(clean_u)
                            if len(found_urls) >= max_urls:
                                break
                except Exception:
                    pass
        else:
            for u in locs:
                clean_u = u.strip()
                if clean_u and not clean_u.endswith(".xml") and clean_u not in found_urls:
                    found_urls.append(clean_u)
                    if len(found_urls) >= max_urls:
                        break

        return found_urls[:max_urls]
    except Exception as e:
        print(f"Error parsing sitemap {sitemap_url}: {e}")
        return []

def crawl_website(start_url: str, max_pages: int = 50) -> List[Dict[str, str]]:
    """Crawls an entire website, checking sitemaps and recursive internal links."""
    parsed_start = urllib.parse.urlparse(start_url)
    domain = parsed_start.netloc
    scheme = parsed_start.scheme or "https"
    base_domain_url = f"{scheme}://{domain}"

    visited: Set[str] = set()
    to_visit: List[str] = [start_url]
    results: List[Dict[str, str]] = []

    headers = {
        "User-Agent": DEFAULT_USER_AGENT
    }

    # 1. Probe standard sitemap locations to seed URLs across the whole site
    sitemap_candidates = [
        f"{base_domain_url}/sitemap.xml",
        f"{base_domain_url}/wp-sitemap.xml",
        f"{base_domain_url}/sitemap_index.xml"
    ]
    for sm_candidate in sitemap_candidates:
        sitemap_urls = crawl_sitemap(sm_candidate, max_urls=max_pages)
        if sitemap_urls:
            for u in sitemap_urls:
                clean_u = u.split("#")[0].rstrip("/")
                if clean_u not in to_visit and clean_u not in visited:
                    to_visit.append(clean_u)
            break

    # Excluded URL patterns (admin, feeds, logins, media)
    exclude_pattern = re.compile(
        r"(wp-admin|wp-includes|wp-json|xmlrpc|feed|comments|\?add-to-cart|cart|checkout|my-account|login|logout|register|\.(pdf|png|jpg|jpeg|gif|zip|exe|mp4|svg|webp|css|js|woff|woff2|ttf))$",
        re.I
    )

    while to_visit and len(visited) < max_pages:
        current_url = to_visit.pop(0)
        current_url = current_url.split("#")[0].rstrip("/")
        if not current_url or current_url in visited:
            continue

        if exclude_pattern.search(current_url):
            continue

        visited.add(current_url)

        try:
            resp = requests.get(current_url, headers=headers, timeout=10, allow_redirects=True)
            if resp.status_code != 200 or "text/html" not in resp.headers.get("Content-Type", ""):
                continue

            parsed_data = clean_html(resp.text, base_url=current_url)
            if len(parsed_data["content"]) > 60:
                results.append({
                    "url": current_url,
                    "title": parsed_data["title"],
                    "content": parsed_data["content"]
                })

            # Discover more internal links
            if len(visited) < max_pages:
                soup = BeautifulSoup(resp.text, "html.parser")
                for a_tag in soup.find_all("a", href=True):
                    href = a_tag["href"]
                    resolved = urllib.parse.urljoin(current_url, href).split("#")[0].rstrip("/")
                    parsed_link = urllib.parse.urlparse(resolved)
                    if parsed_link.netloc == domain and resolved not in visited and resolved not in to_visit:
                        if not exclude_pattern.search(resolved):
                            to_visit.append(resolved)
        except Exception:
            continue

    return results

def parse_csv_catalog(file_bytes: bytes, filename: str) -> Dict[str, str]:
    """
    Intelligently parses e-commerce product catalogs or real estate listing CSVs/TSVs
    into structured atomic knowledge blocks for accurate search, budget filtering, and recommendation.
    """
    try:
        text = file_bytes.decode("utf-8")
    except UnicodeDecodeError:
        text = file_bytes.decode("latin-1")

    # Detect delimiter
    sample = text[:2048]
    delimiter = "\t" if "\t" in sample and sample.count("\t") > sample.count(",") else (";" if sample.count(";") > sample.count(",") else ",")
    
    try:
        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
        if not reader.fieldnames:
            title = filename.rsplit(".", 1)[0].replace("_", " ").title()
            return {"title": f"{title} (Catalog)", "content": text.strip()}

        field_map = {f.strip().lower(): f for f in reader.fieldnames if f}
        
        def get_val(row: Dict[str, str], aliases: List[str]) -> str:
            for a in aliases:
                for k_lower, orig_k in field_map.items():
                    if a == k_lower or a in k_lower:
                        val = row.get(orig_k, "")
                        if val is not None and str(val).strip():
                            return str(val).strip()
            return ""

        item_blocks = []
        row_count = 0

        for idx, row in enumerate(reader, 1):
            name = get_val(row, ["name", "title", "product", "property", "listing", "item", "heading"])
            if not name:
                continue
            
            row_count += 1
            price = get_val(row, ["price", "cost", "rent", "rate", "sale_price", "listing_price", "budget", "amount"])
            curr = get_val(row, ["currency", "curr"])
            if not curr and price:
                if "$" in price: curr = "$"
                elif "aed" in price.lower(): curr = "AED"
                elif "€" in price: curr = "€"
                elif "£" in price: curr = "£"

            cat = get_val(row, ["category", "type", "property_type", "listing_type", "department", "genre"])
            loc = get_val(row, ["location", "city", "neighborhood", "area", "address", "state"])
            beds = get_val(row, ["bedrooms", "beds", "bhk"])
            baths = get_val(row, ["bathrooms", "baths"])
            sqft = get_val(row, ["sqft", "size", "area_sqft", "sqm"])
            features = get_val(row, ["features", "amenities", "specs", "specifications", "tags", "color", "sizes"])
            stock = get_val(row, ["stock", "availability", "in_stock", "status"])
            desc = get_val(row, ["description", "details", "summary", "overview", "notes", "about"])
            url = get_val(row, ["url", "link", "product_url", "listing_url", "page_url"])

            specs_list = []
            if beds: specs_list.append(f"{beds} Beds")
            if baths: specs_list.append(f"{baths} Baths")
            if sqft: specs_list.append(f"{sqft} sqft")
            if features: specs_list.append(features)
            if stock: specs_list.append(f"Status: {stock}")
            specs_str = " • ".join(specs_list) if specs_list else "Standard Specifications"

            is_real_estate = bool(beds or baths or sqft or any(w in (cat + name + desc).lower() for w in ["villa", "apartment", "condo", "penthouse", "real estate", "rent", "buy property", "bedroom", "studio"]))
            
            # Detect rental frequency and deal type
            rent_freq = get_val(row, ["rent_period", "period", "frequency", "billing", "term", "payment_term", "duration"])
            deal_type_val = get_val(row, ["deal_type", "listing_type", "offer_type", "transaction", "purpose"])
            is_rental = False
            if is_real_estate:
                combined_re = (deal_type_val + " " + price + " " + cat + " " + name + " " + rent_freq).lower()
                if any(w in combined_re for w in ["rent", "rental", "lease", "leasing", "/mo", "/month", "monthly"]):
                    is_rental = True
                    if not rent_freq or "mo" in rent_freq.lower():
                        rent_freq = "month"
                elif any(w in combined_re for w in ["/yr", "/year", "annually", "annual"]):
                    is_rental = True
                    rent_freq = "year"

            icon = "🏠" if is_real_estate else "🏷️"
            label = ("PROPERTY LISTING (FOR RENT)" if is_rental else "PROPERTY LISTING (FOR SALE)") if is_real_estate else "PRODUCT SPECIFICATION"

            formatted_price = f"{curr + ' ' if curr and not price.startswith(curr) else ''}{price}".strip() if price else "Inquire for Pricing"
            if rent_freq and is_rental and not any(f in formatted_price.lower() for f in ["/month", "/mo", "/year", "/yr"]):
                formatted_price += f" / {rent_freq}"

            block = (
                f"==================================================\n"
                f"{icon} {label}: {name}\n"
                f"• Price: {formatted_price}\n"
                + (f"• Deal Type: {'Rental' if is_rental else 'For Sale'}\n" if is_real_estate else "")
                + f"• Category / Type: {cat or ('Real Estate' if is_real_estate else 'Retail Product')}\n"
                + (f"• Location / Neighborhood: {loc}\n" if loc else "")
                + f"• Key Specs & Features: {specs_str}\n"
                + (f"• Description: {desc}\n" if desc else "")
                + (f"• Direct URL: {url}\n" if url else "")
                + f"=================================================="
            )
            item_blocks.append(block)

        if item_blocks:
            formatted_content = f"# Catalog Inventory ({row_count} Items)\n\n" + "\n\n".join(item_blocks)
            title = filename.rsplit(".", 1)[0].replace("_", " ").title()
            return {
                "title": f"{title} ({row_count} Catalog Items)",
                "content": formatted_content
            }
    except Exception:
        pass

    title = filename.rsplit(".", 1)[0].replace("_", " ").title()
    return {"title": f"{title} (File Upload)", "content": text.strip()}

def parse_uploaded_file(file_bytes: bytes, filename: str) -> Dict[str, str]:
    """
    Extracts text from uploaded PDF, TXT, Markdown, or CSV/TSV files.
    """
    ext = filename.lower().split(".")[-1]
    title = filename.rsplit(".", 1)[0].replace("_", " ").title()

    if ext == "pdf":
        try:
            reader = PdfReader(io.BytesIO(file_bytes))
            pages_text = []
            for idx, page in enumerate(reader.pages, 1):
                p_text = page.extract_text() or ""
                if p_text.strip():
                    pages_text.append(f"--- Page {idx} ---\n{p_text.strip()}")
            content = "\n\n".join(pages_text)
            return {"title": f"{title} (PDF Document)", "content": content}
        except Exception as e:
            raise ValueError(f"Failed to parse PDF document: {str(e)}")

    elif ext in ["csv", "tsv"]:
        return parse_csv_catalog(file_bytes, filename)

    elif ext in ["txt", "md", "json"]:
        try:
            text = file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            text = file_bytes.decode("latin-1")
        return {"title": f"{title} (File Upload)", "content": text.strip()}

    else:
        raise ValueError(f"Unsupported file format: .{ext}. Supported formats: .pdf, .txt, .md, .csv, .tsv")

def chunk_text(text: str, chunk_size: int = 700, overlap: int = 100) -> List[str]:
    """Splits text into chunks preserving semantic boundaries and catalog item blocks."""
    if not text:
        return []

    # If text is a structured catalog with item delimiters, preserve each item block intact
    if "==================================================" in text:
        raw_items = re.split(r"={40,}", text)
        chunks = []
        for it in raw_items:
            clean_it = it.strip()
            if len(clean_it) > 30 and ("PRODUCT SPECIFICATION" in clean_it or "PROPERTY LISTING" in clean_it or "• Price:" in clean_it):
                chunks.append(clean_it)
        if chunks:
            return chunks

    paragraphs = text.split("\n\n")
    chunks: List[str] = []
    current_chunk: List[str] = []
    current_len = 0
    
    for p in paragraphs:
        p_clean = p.strip()
        if not p_clean:
            continue
            
        p_len = len(p_clean)
        
        if p_len > chunk_size:
            sentences = re.split(r"(?<=[.!?])\s+", p_clean)
            for s in sentences:
                s_len = len(s)
                if current_len + s_len > chunk_size and current_chunk:
                    chunks.append("\n".join(current_chunk).strip())
                    current_chunk = []
                    current_len = 0
                current_chunk.append(s)
                current_len += s_len
            continue

        if current_len + p_len > chunk_size and current_chunk:
            chunks.append("\n".join(current_chunk).strip())
            if overlap > 0 and len(current_chunk[-1]) <= overlap:
                current_chunk = [current_chunk[-1], p_clean]
                current_len = len(current_chunk[0]) + p_len
            else:
                current_chunk = [p_clean]
                current_len = p_len
        else:
            current_chunk.append(p_clean)
            current_len += p_len
            
    if current_chunk:
        chunks.append("\n".join(current_chunk).strip())
        
    return [c for c in chunks if len(c.strip()) > 20]
