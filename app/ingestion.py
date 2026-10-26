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

from app.netsafe import check_public_url, is_public_url
from pypdf import PdfReader

def _offer_price(offer: Dict[str, Any]) -> tuple:
    """(price, currency, frequency) from a schema.org Offer, AggregateOffer or priceSpecification.

    WooCommerce puts simple-product prices in offers[].priceSpecification[] and variable
    products in an AggregateOffer with lowPrice/highPrice, so both are read here.
    """
    def _s(v) -> str:
        return "" if v is None else str(v).strip()

    specs = offer.get("priceSpecification")
    specs = [s for s in (specs if isinstance(specs, list) else [specs]) if isinstance(s, dict)]
    spec = specs[0] if specs else {}
    curr = _s(offer.get("priceCurrency")) or _s(spec.get("priceCurrency"))
    freq = _s(spec.get("unitText") or spec.get("billingIncrement"))
    low, high = _s(offer.get("lowPrice")), _s(offer.get("highPrice"))
    price = _s(offer.get("price")) or _s(spec.get("price"))
    if not price and low:
        price = f"{low} - {high}" if high and high != low else low
    return price, curr, freq


def extract_product_grid(soup: BeautifulSoup, base_url: str = "", limit: int = 60) -> str:
    """Product cards on shop/category pages (WooCommerce, Shopify and similar themes).

    Each card that has a link, a name and a price becomes a structured block, so
    listing pages turn into real catalog items instead of a wall of button labels.
    """
    cards = soup.select("li.product, div.product-grid-item, div.product-item, li.product-item, div.product-card, li.grid__item")
    blocks, seen = [], set()
    for card in cards:
        if len(blocks) >= limit:
            break
        title_el = card.select_one(".woocommerce-loop-product__title, .product-title, .product-name, .product-item-link, .card__heading, h2, h3")
        name = title_el.get_text(" ", strip=True) if title_el else ""
        link_el = (title_el.find_parent("a", href=True) if title_el else None) or (title_el.find("a", href=True) if title_el else None) or card.find("a", href=True)
        href = urllib.parse.urljoin(base_url, link_el["href"]).split("#")[0].rstrip("/") if link_el else ""
        price_el = card.select_one(".price, .product-price, .price-item, [class*=price]")
        price_text = re.sub(r"\s+", " ", price_el.get_text(" ", strip=True)) if price_el else ""
        # "$ 260.00 – $ 270.00 Price range: ..." -> "$260.00 - $270.00"
        price_text = re.sub(r"([$€£])\s+(?=\d)", r"\1", price_text.split("Price range")[0]).replace("–", "-").strip()
        if not (name and href.startswith("http") and re.search(r"\d", price_text)) or href in seen:
            continue
        seen.add(href)
        img_el = card.find("img")
        img = ""
        if img_el:
            img = img_el.get("data-src") or img_el.get("src") or ""
            if img.startswith("data:"):
                img = img_el.get("data-lazy-src") or ""
            img = urllib.parse.urljoin(base_url, img) if img else ""
        lines = [f"• Item Name: {name[:150]}", f"• Price: {price_text[:60]}"]
        if card.select_one(".out-of-stock, .outofstock, .sold-out") or "outofstock" in " ".join(card.get("class", [])):
            lines.append("• Availability: OutOfStock")
        if img.startswith("http"):
            lines.append(f"• Image URL: {img}")
        lines.append(f"• Direct URL: {href}")
        blocks.append("🏷️ STRUCTURED PRODUCT SPECIFICATION:\n" + "\n".join(lines))
    return "\n\n".join(blocks)


# Page furniture that adds noise (and other products' prices) to a page's text.
NOISE_SELECTORS = (
    "section.related, .related.products, .upsells, .cross-sells, #reviews, .woocommerce-Reviews, #respond, .comment-respond, "
    ".yith-wcwl-add-to-wishlist, .yith-wcwl-wishlistexistsbrowse, [class*=wishlist], .compare, .woocommerce-breadcrumb, "
    "[class*=quick-view], [class*=quickview], .quick-view, "
    ".screen-reader-text, .sr-only, .visually-hidden, .woocommerce-result-count, .woocommerce-ordering, .share, .social-share, "
    "form.cart, form.variations_form, form.comment-form, form.search-form, form[role=search], select, button"
)


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
                    
                    offers = item.get("offers")
                    if isinstance(offers, list) and offers and isinstance(offers[0], dict):
                        price, curr, freq = _offer_price(offers[0])
                    elif isinstance(offers, dict):
                        price, curr, freq = _offer_price(offers)
                    else:
                        price, curr, freq = _offer_price(item)

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

                    # Extract primary image URL
                    image_url = ""
                    img_val = item.get("image")
                    if isinstance(img_val, str) and img_val.startswith("http"):
                        image_url = img_val
                    elif isinstance(img_val, list) and len(img_val) > 0:
                        first_img = img_val[0]
                        if isinstance(first_img, str) and first_img.startswith("http"):
                            image_url = first_img
                        elif isinstance(first_img, dict) and first_img.get("url"):
                            image_url = str(first_img.get("url", ""))
                    elif isinstance(img_val, dict) and img_val.get("url"):
                        image_url = str(img_val.get("url", ""))

                    if not image_url:
                        og_img = soup.find("meta", property=re.compile(r"og:image|twitter:image", re.I))
                        if og_img and str(og_img.get("content", "")).startswith("http"):
                            image_url = og_img.get("content").strip()

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
                    if is_prod:
                        offer0 = offers[0] if isinstance(offers, list) and offers and isinstance(offers[0], dict) else (offers if isinstance(offers, dict) else {})
                        availability = str(offer0.get("availability") or "").rsplit("/", 1)[-1]
                        if availability: specs.append(f"• Availability: {availability}")
                        brand = item.get("brand")
                        brand = brand.get("name") if isinstance(brand, dict) else brand
                        if isinstance(brand, str) and brand.strip(): specs.append(f"• Brand: {brand.strip()}")
                        category = item.get("category")
                        if isinstance(category, str) and category.strip(): specs.append(f"• Category: {category.strip()[:80]}")
                    if desc: specs.append(f"• Description: {desc[:300]}")
                    if image_url: specs.append(f"• Image URL: {image_url}")
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
                img_tag = m.find(attrs={"itemprop": "image"})

                name_val = name_tag.get_text().strip() if name_tag else ""
                price_val = price_tag.get("content") or (price_tag.get_text().strip() if price_tag else "")
                curr_val = curr_tag.get("content") or (curr_tag.get_text().strip() if curr_tag else "")
                desc_val = desc_tag.get_text().strip() if desc_tag else ""
                
                img_val = ""
                if img_tag:
                    img_val = img_tag.get("src") or img_tag.get("content") or img_tag.get("href") or ""
                    if img_val and not img_val.startswith("http") and base_url:
                        img_val = urllib.parse.urljoin(base_url, img_val)
                if not img_val:
                    og_img = soup.find("meta", property=re.compile(r"og:image|twitter:image", re.I))
                    if og_img and str(og_img.get("content", "")).startswith("http"):
                        img_val = og_img.get("content").strip()

                if name_val and price_val:
                    specs = [f"• Item Name: {name_val}", f"• Price: {curr_val + ' ' if curr_val else ''}{price_val}"]
                    if addr_tag: specs.append(f"• Location / Address: {addr_tag.get_text().strip()}")
                    if bed_tag: specs.append(f"• Bedrooms: {bed_tag.get_text().strip()}")
                    if desc_val: specs.append(f"• Description: {desc_val[:250]}")
                    if img_val: specs.append(f"• Image URL: {img_val}")
                    if base_url: specs.append(f"• Direct URL: {base_url}")
                    label = "PROPERTY LISTING" if is_re else "PRODUCT SPECIFICATION"
                    spec_lines.append(f"🏷️ STRUCTURED {label}:\n" + "\n".join(specs))

    # 3. Parse OpenGraph meta tags if no JSON-LD or Microdata found
    if not spec_lines:
        og_title = soup.find("meta", property=re.compile(r"og:title|twitter:title", re.I))
        og_price = soup.find("meta", property=re.compile(r"product:price:amount|og:price:amount", re.I))
        og_curr = soup.find("meta", property=re.compile(r"product:price:currency|og:price:currency", re.I))
        og_desc = soup.find("meta", property=re.compile(r"og:description|twitter:description", re.I))
        og_img = soup.find("meta", property=re.compile(r"og:image|twitter:image", re.I))
        
        if og_title and og_title.get("content"):
            title_text = og_title.get("content").strip()
            price_text = og_price.get("content", "").strip() if og_price else ""
            curr_text = og_curr.get("content", "").strip() if og_curr else ""
            desc_text = og_desc.get("content", "").strip() if og_desc else ""
            img_text = og_img.get("content", "").strip() if og_img else ""
            
            if price_text:
                specs = [
                    f"• Item Name: {title_text}",
                    f"• Price: {curr_text + ' ' if curr_text else ''}{price_text}",
                    f"• Description: {desc_text[:300]}"
                ]
                if img_text and img_text.startswith("http"):
                    specs.append(f"• Image URL: {img_text}")
                if base_url:
                    specs.append(f"• Direct URL: {base_url}")
                spec_lines.append(f"🏷️ STRUCTURED ITEM SPECIFICATION:\n" + "\n".join(specs))

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
    # Shop and category pages: one block per product card (a product page already has its own schema).
    if "PRODUCT SPECIFICATION" not in structured_block:
        grid_block = extract_product_grid(soup, base_url=base_url)
        if grid_block:
            structured_block = (structured_block + "\n\n" + grid_block).strip()

    # Remove irrelevant tags
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript", "iframe", "svg"]):
        tag.decompose()
    for tag in soup.select(NOISE_SELECTORS):
        tag.decompose()

    main = soup.find("main") or soup.find("article") or soup.find("div", {"id": re.compile(r"content|main|body", re.I)}) or soup.body
    text = main.get_text(separator="\n", strip=True) if main else soup.get_text(separator="\n", strip=True)

    # Prices split over lines by inline markup: "$\n260.00\n–\n$\n270.00" -> "$260.00 – $270.00"
    text = re.sub(r"([$€£])\n(?=\d)", r"\1", text)
    text = re.sub(r"(\d)\n([–-])\n(?=[$€£\d])", r"\1 \2 ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    
    full_content = (structured_block + "\n\n" + text).strip() if structured_block else text.strip()

    return {
        "title": title,
        "content": full_content
    }

DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"

def fetch_url(url: str, timeout: int = 15) -> Dict[str, str]:
    ok, reason = check_public_url(url)
    if not ok:
        raise ValueError(reason)
    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }
    resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    resp.raise_for_status()
    return clean_html(resp.text, base_url=url)

def _sitemap_priority(url: str) -> int:
    """Order sub-sitemaps so a page budget goes to what visitors ask about.

    Site pages (shipping, returns, contact) are few and answer the most questions, then
    products/listings, then categories, then blog posts. Tag and author archives are skipped.
    """
    name = url.lower().rsplit("/", 1)[-1].replace("sitemap", "")  # "sitemap" itself contains "item"
    if re.search(r"tag|author|attachment|media|image|video", name):
        return 9
    if re.search(r"page", name) and "product" not in name:
        return 0
    if re.search(r"product|listing|propert|item|inventory", name) and not re.search(r"_cat|categor", name):
        return 1
    if re.search(r"categor|_cat|collection", name):
        return 2
    if re.search(r"post|blog|news|article", name):
        return 3
    return 2


def crawl_sitemap(sitemap_url: str, max_urls: int = 100) -> List[str]:
    """Extracts page URLs from a sitemap.xml, including nested sitemap indexes."""
    headers = {
        "User-Agent": DEFAULT_USER_AGENT
    }
    found_urls = []
    if not is_public_url(sitemap_url):
        return []
    try:
        resp = requests.get(sitemap_url, headers=headers, timeout=10, allow_redirects=True)
        if resp.status_code != 200:
            return []
        
        # Regex loc extraction (avoids lxml dependency)
        locs = re.findall(r"<loc>\s*(https?://[^\s<]+)\s*</loc>", resp.text, re.I)
        
        # Check for nested sub-sitemaps
        sub_sitemaps = sorted((u for u in locs if u.endswith(".xml") or "sitemap" in u), key=_sitemap_priority)
        sub_sitemaps = [u for u in sub_sitemaps if _sitemap_priority(u) < 9]
        if sub_sitemaps:
            for sm_url in sub_sitemaps[:10]:
                try:
                    if not is_public_url(sm_url):
                        continue
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

# Excluded URL patterns (admin, feeds, logins, carts, media files)
EXCLUDE_URL_PATTERN = re.compile(
    r"(wp-admin|wp-includes|wp-json|xmlrpc|feed|comments|\?add-to-cart|cart|checkout|my-account|login|logout|register|\.(pdf|png|jpg|jpeg|gif|zip|exe|mp4|svg|webp|css|js|woff|woff2|ttf))(\?|$)",
    re.I
)
# Button and filter links (compare, wishlist, add to cart, sorting, filters, search, reply).
# They don't lead to new content, and stores often answer them with 404 or 429.
ACTION_LINK_PATTERN = re.compile(
    r"[?&](add-to-cart|add_to_cart|add-to-compare|add_to_compare|add_to_wishlist|add-to-wishlist|remove_item|"
    r"wishlist|compare|orderby|order|sort|sort_by|filter_[a-z_]*|min_price|max_price|stock_status|on_sale|"
    r"shop_view|per_page|product_view|s|replytocom|share|_wpnonce)=",
    re.I,
)
# Catalog pagination: /page/2, ?page=2, ?p=2, ?paged=2, ?pg=2, offset=10 (at the end of the URL, so
# "/shop/page/5/?add-to-compare=1" or "/shop/page/5/6209" are not treated as listing pages)
PAGINATION_PATTERN = re.compile(r"(/page/\d{1,3}/?$|[?&](page|p|paged|pg|offset)=\d{1,4}$)", re.I)


def is_crawlable_link(url: str) -> bool:
    return not EXCLUDE_URL_PATTERN.search(url) and not ACTION_LINK_PATTERN.search(url)


def normalize_crawl_url(url: str) -> str:
    return (url or "").split("#")[0].rstrip("/")


def discover_sitemap_urls(start_url: str, max_urls: int = 50) -> List[str]:
    """Page URLs from the site's sitemap (robots.txt Sitemap: lines first, then the usual locations)."""
    parsed = urllib.parse.urlparse(start_url)
    base = f"{parsed.scheme or 'https'}://{parsed.netloc}"
    candidates = [f"{base}/sitemap.xml", f"{base}/wp-sitemap.xml", f"{base}/sitemap_index.xml"]
    if not is_public_url(base):
        return []
    try:
        robots = requests.get(f"{base}/robots.txt", headers={"User-Agent": DEFAULT_USER_AGENT}, timeout=6)
        if robots.status_code == 200:
            for line in robots.text.splitlines():
                if line.strip().lower().startswith("sitemap:"):
                    sm = line.split(":", 1)[1].strip()
                    if sm.startswith("http") and sm not in candidates:
                        candidates.insert(0, sm)
    except Exception:
        pass
    for candidate in candidates:
        urls = crawl_sitemap(candidate, max_urls=max_urls)
        if urls:
            return [normalize_crawl_url(u) for u in urls]
    return []


def fetch_page_with_links(url: str, timeout: int = 10) -> Dict[str, Any]:
    """Fetches one page. Returns {"status": http status or 0, "page": {...} or None, "links": [same-site URLs]}."""
    ok, reason = check_public_url(url)
    if not ok:
        return {"status": 0, "page": None, "links": [], "error": reason}
    try:
        resp = requests.get(url, headers={"User-Agent": DEFAULT_USER_AGENT}, timeout=timeout, allow_redirects=True)
    except Exception as e:
        return {"status": 0, "page": None, "links": [], "error": str(e)[:200]}
    if resp.status_code != 200 or "text/html" not in resp.headers.get("Content-Type", ""):
        return {"status": resp.status_code, "page": None, "links": []}
    parsed = clean_html(resp.text, base_url=url)
    page = {"url": url, "title": parsed["title"], "content": parsed["content"]} if len(parsed["content"]) > 60 else None
    domain = urllib.parse.urlparse(url).netloc
    links: List[str] = []
    seen: Set[str] = set()
    link_soup = BeautifulSoup(resp.text, "html.parser")
    for tag in link_soup.select(NOISE_SELECTORS):  # wishlist/compare/share buttons, reviews, related items
        tag.decompose()
    for a_tag in link_soup.find_all("a", href=True):
        resolved = normalize_crawl_url(urllib.parse.urljoin(url, a_tag["href"]))
        if (resolved and resolved not in seen and urllib.parse.urlparse(resolved).netloc == domain
                and resolved.startswith("http") and is_crawlable_link(resolved)):
            seen.add(resolved)
            links.append(resolved)
    # Catalog pagination first, so every page of products/listings gets indexed.
    links.sort(key=lambda u: 0 if PAGINATION_PATTERN.search(u) else 1)
    return {"status": 200, "page": page, "links": links}


def crawl_website(start_url: str, max_pages: int = 50) -> List[Dict[str, str]]:
    """Crawls a whole website in one go (sitemap first, then internal links).

    Request handlers should prefer a background crawl job (app.jobs), which does the
    same work in resumable steps so large sites don't hit request time limits.
    """
    start = normalize_crawl_url(start_url)
    to_visit: List[str] = [start] + [u for u in discover_sitemap_urls(start_url, max_pages) if u != start]
    visited: Set[str] = set()
    results: List[Dict[str, str]] = []
    while to_visit and len(visited) < max_pages:
        current = normalize_crawl_url(to_visit.pop(0))
        if not current or current in visited or not is_crawlable_link(current):
            continue
        visited.add(current)
        fetched = fetch_page_with_links(current)
        if fetched["page"]:
            results.append(fetched["page"])
        for link in fetched["links"]:
            if link not in visited and link not in to_visit:
                if PAGINATION_PATTERN.search(link):
                    to_visit.insert(0, link)
                else:
                    to_visit.append(link)
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
            image = get_val(row, ["image", "image_url", "img", "photo", "thumbnail", "picture", "featured_image"])

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
                + (f"• Image URL: {image}\n" if image else "")
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
