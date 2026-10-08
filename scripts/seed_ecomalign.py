import sqlite3
import re
import urllib.request
import os
import json
from bs4 import BeautifulSoup

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "weaveflow.db")
print(f"Target DB: {DB_PATH}")

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# 1. Update/insert asst_default, asst_dd54f019, asst_ecomalign
assistants_to_seed = [
    {
        "id": "asst_default",
        "name": "EcomAlign Assistant",
        "domain": "ecomalign.com",
        "primary_color": "#0f172a",
        "welcome_message": "Hi there! 👋 Welcome to EcomAlign. How can we help grow your e-commerce brand across Amazon, eBay, TikTok Shop, or other marketplaces today?",
        "bot_avatar": "⚡",
        "position": "bottom-right",
        "widget_subtitle": "Online • Marketplace Growth AI",
        "suggested_questions": "How does EcomAlign help scale sales across Amazon, eBay & TikTok Shop?\nWhat full-service store management & listing optimization do you provide?\nHow can I book a call or start a project with your growth team?",
        "lead_capture_enabled": 1,
        "voice_enabled": 1,
        "teaser_message": "👋 Need help growing on marketplaces?",
        "lead_title": "Start Your Project with EcomAlign",
        "lead_fields": "name_email",
        "show_branding": 1
    },
    {
        "id": "asst_dd54f019",
        "name": "EcomAlign Assistant",
        "domain": "ecomalign.com",
        "primary_color": "#0f172a",
        "welcome_message": "Hi there! 👋 Welcome to EcomAlign. How can we help grow your e-commerce brand across Amazon, eBay, TikTok Shop, or other marketplaces today?",
        "bot_avatar": "⚡",
        "position": "bottom-right",
        "widget_subtitle": "Online • Marketplace Growth AI",
        "suggested_questions": "How does EcomAlign help scale sales across Amazon, eBay & TikTok Shop?\nWhat full-service store management & listing optimization do you provide?\nHow can I book a call or start a project with your growth team?",
        "lead_capture_enabled": 1,
        "voice_enabled": 1,
        "teaser_message": "👋 Need help growing on marketplaces?",
        "lead_title": "Start Your Project with EcomAlign",
        "lead_fields": "name_email",
        "show_branding": 1
    },
    {
        "id": "asst_ecomalign",
        "name": "EcomAlign Assistant",
        "domain": "ecomalign.com",
        "primary_color": "#0f172a",
        "welcome_message": "Hi there! 👋 Welcome to EcomAlign. How can we help grow your e-commerce brand across Amazon, eBay, TikTok Shop, or other marketplaces today?",
        "bot_avatar": "⚡",
        "position": "bottom-right",
        "widget_subtitle": "Online • Marketplace Growth AI",
        "suggested_questions": "How does EcomAlign help scale sales across Amazon, eBay & TikTok Shop?\nWhat full-service store management & listing optimization do you provide?\nHow can I book a call or start a project with your growth team?",
        "lead_capture_enabled": 1,
        "voice_enabled": 1,
        "teaser_message": "👋 Need help growing on marketplaces?",
        "lead_title": "Start Your Project with EcomAlign",
        "lead_fields": "name_email",
        "show_branding": 1
    }
]

for asst in assistants_to_seed:
    cursor.execute("SELECT id FROM assistants WHERE id = ?", (asst["id"],))
    exists = cursor.fetchone()
    if exists:
        cursor.execute("""
            UPDATE assistants SET
                name = ?, domain = ?, primary_color = ?, welcome_message = ?,
                bot_avatar = ?, position = ?, widget_subtitle = ?, suggested_questions = ?,
                lead_capture_enabled = ?, voice_enabled = ?, teaser_message = ?,
                lead_title = ?, lead_fields = ?, show_branding = ?
            WHERE id = ?
        """, (
            asst["name"], asst["domain"], asst["primary_color"], asst["welcome_message"],
            asst["bot_avatar"], asst["position"], asst["widget_subtitle"], asst["suggested_questions"],
            asst["lead_capture_enabled"], asst["voice_enabled"], asst["teaser_message"],
            asst["lead_title"], asst["lead_fields"], asst["show_branding"],
            asst["id"]
        ))
    else:
        cursor.execute("""
            INSERT INTO assistants (
                id, name, domain, primary_color, welcome_message, bot_avatar,
                position, widget_subtitle, suggested_questions, lead_capture_enabled,
                voice_enabled, teaser_message, lead_title, lead_fields, show_branding
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            asst["id"], asst["name"], asst["domain"], asst["primary_color"], asst["welcome_message"],
            asst["bot_avatar"], asst["position"], asst["widget_subtitle"], asst["suggested_questions"],
            asst["lead_capture_enabled"], asst["voice_enabled"], asst["teaser_message"],
            asst["lead_title"], asst["lead_fields"], asst["show_branding"]
        ))

conn.commit()
print("Assistants seeded/updated successfully.")

# 2. Scrape ecomalign.com pages
urls_to_crawl = [
    "https://ecomalign.com/",
    "https://ecomalign.com/services/",
    "https://ecomalign.com/about-us/",
    "https://ecomalign.com/portfolio/",
    "https://ecomalign.com/ecommerce-seo-checklist/",
    "https://ecomalign.com/amazon-fba-prep-center-guide/"
]

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
}

def clean_html(html, url):
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.string.strip() if soup.title and soup.title.string else url
    for t in soup(["script", "style", "nav", "footer", "header", "noscript", "svg", "iframe"]):
        t.decompose()
    main = soup.find("main") or soup.find("article") or soup.body
    text = main.get_text(separator="\n", strip=True) if main else soup.get_text(separator="\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return title, text.strip()

def chunk_text(text, chunk_size=600, overlap=100):
    words = text.split()
    chunks = []
    i = 0
    while i < len(words):
        chunk = " ".join(words[i:i + chunk_size])
        chunks.append(chunk)
        i += (chunk_size - overlap)
    return chunks

# Delete older chunks/sources for asst_default, asst_dd54f019, asst_ecomalign to have a fresh clean index
target_asst_ids = ["asst_default", "asst_dd54f019", "asst_ecomalign"]
for aid in target_asst_ids:
    cursor.execute("DELETE FROM chunks WHERE assistant_id = ?", (aid,))
    cursor.execute("DELETE FROM sources WHERE assistant_id = ?", (aid,))
conn.commit()

scraped_data = []
for url in urls_to_crawl:
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=12) as response:
            html = response.read().decode("utf-8", errors="ignore")
            title, content = clean_html(html, url)
            if len(content) > 100:
                scraped_data.append({"url": url, "title": title, "content": content})
                print(f"Scraped {url}: {len(content)} chars")
    except Exception as e:
        print(f"Failed to scrape {url}: {e}")

# Insert into database for each target assistant
for item in scraped_data:
    url = item["url"]
    title = item["title"]
    content = item["content"]
    chunks = chunk_text(content)
    
    for aid in target_asst_ids:
        cursor.execute("""
            INSERT INTO sources (assistant_id, source_type, title, url, content, chunk_count)
            VALUES (?, 'website', ?, ?, ?, ?)
        """, (aid, title, url, content, len(chunks)))
        source_id = cursor.lastrowid
        
        for idx, ch in enumerate(chunks):
            cursor.execute("""
                INSERT INTO chunks (assistant_id, source_id, chunk_index, content, title, url, embedding)
                VALUES (?, ?, ?, ?, ?, ?, '')
            """, (aid, source_id, idx, ch, title, url))

conn.commit()
print("All sources and chunks indexed.")

for aid in target_asst_ids:
    cursor.execute("SELECT count(*) FROM chunks WHERE assistant_id = ?", (aid,))
    c_cnt = cursor.fetchone()[0]
    cursor.execute("SELECT count(*) FROM sources WHERE assistant_id = ?", (aid,))
    s_cnt = cursor.fetchone()[0]
    print(f"Assistant {aid}: {s_cnt} sources, {c_cnt} chunks.")

conn.close()
