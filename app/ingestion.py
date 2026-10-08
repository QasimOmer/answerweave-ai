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
import urllib.parse
from typing import List, Dict, Any, Set, Optional
import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

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

    # Remove irrelevant tags
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript", "iframe", "svg"]):
        tag.decompose()
        
    main = soup.find("main") or soup.find("article") or soup.find("div", {"id": re.compile(r"content|main|body", re.I)}) or soup.body
    text = main.get_text(separator="\n", strip=True) if main else soup.get_text(separator="\n", strip=True)

    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    
    return {
        "title": title,
        "content": text.strip()
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

def parse_uploaded_file(file_bytes: bytes, filename: str) -> Dict[str, str]:
    """
    Extracts text from uploaded PDF, TXT, Markdown, or CSV files.
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

    elif ext in ["txt", "md", "csv", "json"]:
        try:
            text = file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            text = file_bytes.decode("latin-1")
        return {"title": f"{title} (File Upload)", "content": text.strip()}

    else:
        raise ValueError(f"Unsupported file format: .{ext}. Supported formats: .pdf, .txt, .md, .csv")

def chunk_text(text: str, chunk_size: int = 700, overlap: int = 100) -> List[str]:
    """Splits text into chunks preserving semantic paragraph boundaries."""
    if not text:
        return []
        
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
