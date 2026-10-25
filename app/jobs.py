"""
Background crawl jobs: resumable, change-aware, and safe on serverless hosts.

A job keeps its crawl frontier in the database and is processed in short steps
(`run_job_step`), each within a time budget, so no single request runs long.
Steps are driven by whichever is available:
  - the dashboard, which asks for the next step while someone watches progress,
  - a cron hit on /api/cron/tick (Vercel Cron or any scheduler), which also starts
    scheduled re-crawls, and
  - a background thread when the app runs as a normal long-lived server.

Re-crawls only re-embed pages whose content changed, add pages that are new
(new listings/products), and remove pages that now return 404/410.
"""

import hashlib
import os
import threading
import time
from typing import Any, Dict, List, Optional

from app import db
from app.ingestion import (
    chunk_text,
    crawl_sitemap,
    discover_sitemap_urls,
    fetch_page_with_links,
    normalize_crawl_url,
    EXCLUDE_URL_PATTERN,
    PAGINATION_PATTERN,
)
from app.embeddings import generate_embeddings_batch
from app.netsafe import check_public_url

STEP_BUDGET_SECONDS = 20      # long-lived server worker
# Cron ticks must finish inside the host's function time limit (10s by default on Vercel Hobby).
TICK_BUDGET_SECONDS = float(os.environ.get("AW_TICK_BUDGET_SECONDS", "8"))
PAGE_TIMEOUT_SECONDS = 6
LEASE_SECONDS = 90            # a crashed step frees its job after this
SAVE_EVERY_PAGES = 5
MAX_PAGES_LIMIT = 500
JOB_KINDS = ("crawl", "sitemap", "resync", "page")


class JobConflict(Exception):
    """The assistant already has a crawl running."""


def _hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _root_for(asst: Dict[str, Any]) -> str:
    root = (asst.get("crawl_root_url") or "").strip()
    if root:
        return root
    domain = (asst.get("domain") or "").split(",")[0].strip()
    if domain and domain != "*" and "*" not in domain:
        return domain if domain.startswith("http") else f"https://{domain}"
    return ""


def start_crawl_job(assistant_id: str, kind: str, url: Optional[str] = None, max_pages: int = 50,
                    trigger: str = "manual", created_by: str = "") -> Dict[str, Any]:
    """Queues a crawl. kind: crawl (follow links from url), sitemap (pages listed in a sitemap),
    resync (refresh everything already indexed and pick up new pages), page (one URL)."""
    if kind not in JOB_KINDS:
        raise ValueError(f"Unknown crawl kind '{kind}'")
    existing = db.active_crawl_job(assistant_id)
    if existing:
        raise JobConflict(existing["id"])
    asst = db.get_assistant(assistant_id) or {}
    max_pages = max(1, min(MAX_PAGES_LIMIT, int(max_pages or 50)))
    url = normalize_crawl_url(url.strip()) if url else ""
    if url and not url.startswith(("http://", "https://")):
        url = "https://" + url

    if kind == "resync":
        known = db.list_url_source_urls(assistant_id)
        root = _root_for(asst)
        if not known and not root:
            raise ValueError("Nothing to re-crawl yet: add a website first.")
        frontier = list(dict.fromkeys(known + ([normalize_crawl_url(root)] if root else [])))
        max_pages = max(int(asst.get("crawl_max_pages") or 50), len(frontier))
        max_pages = min(MAX_PAGES_LIMIT, max_pages)
        state = {"frontier": frontier, "visited": [], "seeded": not root, "follow_links": bool(root),
                 "root": root, "known": known}
        url = root or (known[0] if known else "")
    else:
        if not url:
            raise ValueError("A URL is required.")
        ok, reason = check_public_url(url)
        if not ok:
            raise ValueError(reason)
        state = {
            "frontier": [] if kind == "sitemap" else [url],
            "visited": [],
            "seeded": kind == "page",
            "follow_links": kind == "crawl",
            "root": url,
            "known": db.list_url_source_urls(assistant_id),
        }
        if kind == "crawl":
            # Remember what to re-crawl on schedule.
            db.update_assistant(assistant_id, {"crawl_root_url": url, "crawl_max_pages": max_pages})
    return db.create_crawl_job(assistant_id, kind, url, max_pages, state, trigger=trigger, created_by=created_by)


def _delete_url_sources(assistant_id: str, url: str) -> int:
    conn = db.get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM sources WHERE assistant_id = ? AND source_type = 'url' AND url = ?", (assistant_id, url))
    ids = [r["id"] for r in cursor.fetchall()]
    conn.close()
    for source_id in ids:
        db.delete_source(source_id)
    return len(ids)


def upsert_page(assistant_id: str, page: Dict[str, str]) -> Dict[str, Any]:
    """Indexes one crawled page. Unchanged pages are skipped; changed ones replace the old version."""
    content_hash = _hash(page["content"])
    existing = db.get_url_source(assistant_id, page["url"])
    if existing and existing.get("content_hash") == content_hash:
        return {"outcome": "unchanged", "chunks": 0}
    chunks = chunk_text(page["content"])
    if not chunks:
        return {"outcome": "skipped", "chunks": 0}
    if existing:
        _delete_url_sources(assistant_id, page["url"])  # also clears duplicates from older crawls
    workspace_id = db.assistant_workspace_id(assistant_id)
    source_id = db.add_source(assistant_id, "url", page["title"], page["url"], page["content"])
    vectors = generate_embeddings_batch(chunks, titles=[page["title"]] * len(chunks), workspace_id=workspace_id)
    for idx, (text, vec) in enumerate(zip(chunks, vectors)):
        db.add_chunk(assistant_id, source_id, idx, text, page["title"], page["url"], vec)
    db.update_source_chunk_count(source_id, len(chunks))
    db.set_source_content_hash(source_id, content_hash)
    return {"outcome": "updated" if existing else "added", "chunks": len(chunks)}


_COUNTERS = ("pages_done", "pages_added", "pages_updated", "pages_unchanged", "pages_removed", "pages_failed", "chunks_added")


def run_job_step(job_id: str, budget_seconds: float = STEP_BUDGET_SECONDS) -> Optional[Dict[str, Any]]:
    """Processes pages for up to `budget_seconds`, saves progress and returns the job.
    Safe to call concurrently: only the worker holding the lease does any work."""
    token = db.claim_crawl_job(job_id, LEASE_SECONDS)
    if not token:
        return db.get_crawl_job(job_id)
    job = db.get_crawl_job(job_id, with_state=True)
    state = job["state"]
    counts = {k: int(job.get(k) or 0) for k in _COUNTERS}
    assistant_id = job["assistant_id"]
    frontier: List[str] = state.get("frontier", [])
    visited = set(state.get("visited", []))
    known = set(state.get("known", []))
    max_pages = int(job["max_pages"] or 50)
    deadline = time.time() + budget_seconds

    def snapshot(**extra) -> Dict[str, Any]:
        state.update(frontier=frontier, visited=sorted(visited))
        return {**counts, "queue_size": len(frontier), "status": "running", **extra}

    try:
        if not state.get("seeded"):
            if job["kind"] == "sitemap":
                seeds = crawl_sitemap(job["start_url"], max_urls=max_pages)
                if not seeds:
                    raise RuntimeError("No page URLs found in that sitemap.")
            else:
                seeds = discover_sitemap_urls(state.get("root") or job["start_url"], max_urls=max_pages)
            for u in seeds:
                u = normalize_crawl_url(u)
                if u and u not in visited and u not in frontier:
                    frontier.append(u)
            state["seeded"] = True
            if not db.save_crawl_job(job_id, token, snapshot(), state):
                return db.get_crawl_job(job_id)

        since_save = 0
        while frontier and counts["pages_done"] < max_pages and time.time() < deadline:
            url = normalize_crawl_url(frontier.pop(0))
            if not url or url in visited or EXCLUDE_URL_PATTERN.search(url):
                continue
            visited.add(url)
            fetched = fetch_page_with_links(url, timeout=PAGE_TIMEOUT_SECONDS)
            if fetched["page"]:
                result = upsert_page(assistant_id, fetched["page"])
                key = {"added": "pages_added", "updated": "pages_updated", "unchanged": "pages_unchanged"}.get(result["outcome"])
                if key:
                    counts[key] += 1
                counts["chunks_added"] += result["chunks"]
            elif fetched["status"] in (404, 410) and url in known:
                if _delete_url_sources(assistant_id, url):
                    counts["pages_removed"] += 1
            elif fetched["status"] != 200:
                counts["pages_failed"] += 1
            counts["pages_done"] += 1

            if state.get("follow_links"):
                for link in fetched["links"]:
                    if link not in visited and link not in frontier:
                        if PAGINATION_PATTERN.search(link):
                            frontier.insert(0, link)
                        else:
                            frontier.append(link)

            since_save += 1
            if since_save >= SAVE_EVERY_PAGES:
                since_save = 0
                if not db.save_crawl_job(job_id, token, snapshot(current_url=url), state):
                    return db.get_crawl_job(job_id)  # cancelled while we worked

        finished = not frontier or counts["pages_done"] >= max_pages
        if not finished:
            db.save_crawl_job(job_id, token, snapshot(current_url=""), state, release=True)
            return db.get_crawl_job(job_id)

        indexed = counts["pages_added"] + counts["pages_updated"] + counts["pages_unchanged"]
        final = snapshot(current_url="", finished_epoch=int(time.time()))
        if indexed == 0 and counts["pages_removed"] == 0:
            final.update(status="failed", error="No readable pages were found. Check the URL is public and returns HTML.")
        else:
            final["status"] = "done"
            if job["kind"] in ("crawl", "resync"):
                db.mark_assistant_recrawled(assistant_id)
        db.invalidate_chunks_cache(assistant_id)
        db.save_crawl_job(job_id, token, final, state, release=True)
    except Exception as e:
        print(f"[Crawl job {job_id}] failed: {e}")
        db.save_crawl_job(job_id, token, snapshot(status="failed", error=str(e)[:300], current_url="",
                                                  finished_epoch=int(time.time())), state, release=True)
    return db.get_crawl_job(job_id)


def schedule_due_recrawls() -> List[str]:
    """Queues re-crawls for assistants whose daily/weekly schedule is due."""
    started = []
    for row in db.assistants_due_for_recrawl():
        try:
            job = start_crawl_job(row["id"], "resync", trigger="schedule")
            started.append(job["id"])
        except (JobConflict, ValueError):
            db.mark_assistant_recrawled(row["id"])  # nothing to crawl; don't retry every tick
    return started


def tick(budget_seconds: float = TICK_BUDGET_SECONDS) -> Dict[str, Any]:
    """One scheduler pass: start due re-crawls, then work on queued jobs until the budget is used."""
    deadline = time.time() + budget_seconds
    scheduled = schedule_due_recrawls()
    worked: List[str] = []
    while time.time() < deadline - 1:
        ids = db.runnable_crawl_job_ids(limit=5)
        if not ids:
            break
        progressed = False
        for job_id in ids:
            remaining = deadline - time.time()
            if remaining < 2:
                break
            job = run_job_step(job_id, budget_seconds=min(STEP_BUDGET_SECONDS, remaining - 1))
            if job:
                worked.append(job_id)
                progressed = True
        if not progressed:
            break
    return {"scheduled": scheduled, "worked": sorted(set(worked))}


# ---------------------------------------------------------------- long-running server worker

_worker_started = False


def start_background_worker(interval_seconds: float = 5.0):
    """Runs `tick` in a daemon thread when the app is a normal server (not serverless).
    Disable with AW_BACKGROUND_WORKER=0."""
    global _worker_started
    if _worker_started or os.environ.get("AW_BACKGROUND_WORKER", "1") == "0":
        return
    if os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        return  # serverless instances freeze between requests; cron and the dashboard drive jobs there
    _worker_started = True

    def loop():
        while True:
            try:
                tick(budget_seconds=20)
            except Exception as e:
                print(f"[Crawl worker] {e}")
            time.sleep(interval_seconds)

    threading.Thread(target=loop, name="aw-crawl-worker", daemon=True).start()
