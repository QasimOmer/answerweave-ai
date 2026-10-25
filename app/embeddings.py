"""
Embedding generation and hybrid search, partitioned per assistant.

- Gemini embeddings with separate query/document task types, batched.
- Every stored vector is tagged with the model that made it, so vectors from a
  retired model are never compared with new ones (re-index to upgrade them).
- Search uses a cached per-assistant index (tokens, BM25 stats, vector matrix)
  and keeps only passages that are actually relevant to the question.
"""

import math
import re
import hashlib
from collections import Counter
try:
    import numpy as np
except Exception:
    np = None

from typing import List, Dict, Any, Optional, Tuple
from google import genai
from google.genai import types

from app.config import get_api_key, EMBEDDING_MODEL, EMBEDDING_DIM
from app.db import get_chunks_for_assistant, assistant_workspace_id

PSEUDO_DIM = 256
PSEUDO_TAG = f"pseudo-{PSEUDO_DIM}"
EMBED_BATCH_SIZE = 100

_CLIENTS: Dict[str, genai.Client] = {}


def current_embedding_tag() -> str:
    return f"{EMBEDDING_MODEL}@{EMBEDDING_DIM}"


def embedding_tag(vec: List[float]) -> str:
    """Tag stored next to a vector: which model space it lives in."""
    if not vec:
        return ""
    if len(vec) == PSEUDO_DIM:
        return PSEUDO_TAG
    if len(vec) == EMBEDDING_DIM:
        return current_embedding_tag()
    return f"unknown@{len(vec)}"


def get_genai_client(workspace_id: Optional[str] = None) -> Optional[genai.Client]:
    """Gemini client for the workspace's key (its own, else the platform's if allowed)."""
    api_key = get_api_key("gemini", workspace_id)
    if not api_key:
        return None
    client = _CLIENTS.get(api_key)
    if client is None:
        try:
            client = genai.Client(api_key=api_key)
        except Exception:
            return None
        if len(_CLIENTS) > 50:
            _CLIENTS.clear()
        _CLIENTS[api_key] = client
    return client


def _embed(client: genai.Client, texts: List[str], task_type: str) -> List[List[float]]:
    response = client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=texts,
        config=types.EmbedContentConfig(task_type=task_type, output_dimensionality=EMBEDDING_DIM),
    )
    vectors = [list(e.values) for e in (response.embeddings or [])]
    if len(vectors) != len(texts) or any(len(v) != EMBEDDING_DIM for v in vectors):
        raise ValueError("embedding response did not match the request")
    return vectors


def generate_embedding(text: str, task: str = "query", workspace_id: Optional[str] = None) -> List[float]:
    """Embed one text. `task` is "query" for visitor questions, "document" for knowledge chunks.

    Falls back to a keyword-hash vector when Gemini isn't configured or fails.
    """
    client = get_genai_client(workspace_id)
    if client:
        try:
            task_type = "RETRIEVAL_QUERY" if task == "query" else "RETRIEVAL_DOCUMENT"
            return _embed(client, [text], task_type)[0]
        except Exception as e:
            print(f"Embedding failed ({EMBEDDING_MODEL}), using keyword vector: {e}")
    return _pseudo_embedding(text)


def generate_embeddings_batch(texts: List[str], titles: Optional[List[str]] = None,
                              workspace_id: Optional[str] = None) -> List[List[float]]:
    """Embed knowledge chunks in batches. Titles, when given, are prepended for context."""
    docs = [f"{t}\n{x}" if t else x for t, x in zip(titles, texts)] if titles else list(texts)
    client = get_genai_client(workspace_id)
    if not client:
        return [_pseudo_embedding(t) for t in texts]
    out: List[List[float]] = []
    for i in range(0, len(docs), EMBED_BATCH_SIZE):
        batch = docs[i:i + EMBED_BATCH_SIZE]
        try:
            out.extend(_embed(client, batch, "RETRIEVAL_DOCUMENT"))
        except Exception as e:
            print(f"Batch embedding failed, retrying one by one: {e}")
            for j, doc in enumerate(batch):
                try:
                    out.append(_embed(client, [doc], "RETRIEVAL_DOCUMENT")[0])
                except Exception:
                    out.append(_pseudo_embedding(texts[i + j]))
    return out

STOPWORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are", "aren't",
    "as", "at", "be", "because", "been", "before", "being", "below", "between", "both", "but", "by",
    "can", "can't", "cannot", "could", "couldn't", "did", "didn't", "do", "does", "doesn't", "doing",
    "don't", "down", "during", "each", "few", "for", "from", "further", "had", "hadn't", "has", "hasn't",
    "have", "haven't", "having", "he", "he'd", "he'll", "he's", "her", "here", "here's", "hers", "herself",
    "him", "himself", "his", "how", "how's", "i", "i'd", "i'll", "i'm", "i've", "if", "in", "into", "is",
    "isn't", "it", "it's", "its", "itself", "let's", "me", "more", "most", "mustn't", "my", "myself",
    "no", "nor", "not", "of", "off", "on", "once", "only", "or", "other", "ought", "our", "ours",
    "ourselves", "out", "over", "own", "same", "shan't", "she", "she'd", "she'll", "she's", "should",
    "shouldn't", "so", "some", "such", "than", "that", "that's", "the", "their", "theirs", "them",
    "themselves", "then", "there", "there's", "these", "they", "they'd", "they'll", "they're", "they've",
    "this", "those", "through", "to", "too", "under", "until", "up", "very", "was", "wasn't", "we",
    "we'd", "we'll", "we're", "we've", "were", "weren't", "what", "what's", "when", "when's", "where",
    "where's", "which", "while", "who", "who's", "whom", "why", "why's", "with", "won't", "would",
    "wouldn't", "you", "you'd", "you'll", "you're", "you've", "your", "yours", "yourself", "yourselves",
    # Conversational verbs and noise words
    "can", "u", "ur", "share", "tell", "give", "show", "send", "list", "provide",
    "please", "pls", "want", "need", "looking", "find", "get", "help", "know", "see",
    "some", "seome", "got", "hi", "hey", "hello"
}

def normalize_query_terms(text: str) -> str:
    """Corrects common typos in visitor queries for e-commerce and real estate."""
    clean = text.lower()
    typos = {
        r'\brenatl\b': 'rental',
        r'\brentl\b': 'rental',
        r'\brentals\b': 'rental properties',
        r'\bseome\b': 'some',
        r'\bpropertis\b': 'properties',
        r'\bpropertie\b': 'property',
        r'\bproprty\b': 'property',
        r'\bproprties\b': 'properties',
        r'\bprperty\b': 'property',
        r'\bprperties\b': 'properties',
        r'\bappartment\b': 'apartment',
        r'\bappartments\b': 'apartments',
        r'\baprtment\b': 'apartment',
        r'\baprtments\b': 'apartments',
        r'\baprtmnt\b': 'apartment',
        r'\baprtmnts\b': 'apartments',
        r'\bapts?\b': 'apartments',
        r'\bbdrms?\b': 'bedroom',
        r'\bfor\s+sell\b': 'for sale',
        r'\bto\s+sell\b': 'to sell',
        r'\bproperties\s+for\s+sell\b': 'properties for sale',
        r'\bproperty\s+for\s+sell\b': 'property for sale',
        r'\bvila\b': 'villa',
        r'\bvilas\b': 'villas',
        r'\bstudioes\b': 'studios',
        r'\bpenhouse\b': 'penthouse',
        r'\btonwhouse\b': 'townhouse',
    }
    for pat, repl in typos.items():
        clean = re.sub(pat, repl, clean)
    return clean

def _pseudo_embedding(text: str, dim: int = 256) -> List[float]:
    """Deterministic MD5-based fallback vector when no API key is provided."""
    vec = [0.0] * dim
    words = [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOPWORDS and len(w) > 2]
    if not words:
        return vec
    for w in words:
        idx = int(hashlib.md5(w.encode("utf-8")).hexdigest()[:8], 16) % dim
        vec[idx] += 1.0
    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 0:
        vec = [x / norm for x in vec]
    return vec

def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    if np is not None:
        try:
            a = np.array(v1, dtype=np.float32)
            b = np.array(v2, dtype=np.float32)
            norm_a = np.linalg.norm(a)
            norm_b = np.linalg.norm(b)
            if norm_a == 0 or norm_b == 0:
                return 0.0
            return float(np.dot(a, b) / (norm_a * norm_b))
        except Exception:
            pass
    # Pure Python fallback
    dot = sum(x * y for x, y in zip(v1, v2))
    norm_a = math.sqrt(sum(x * x for x in v1))
    norm_b = math.sqrt(sum(y * y for y in v2))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(dot / (norm_a * norm_b))


# ---------------------------------------------------------------- search index

# Relevance thresholds for gemini-embedding-001 at 768 dimensions. Unrelated
# question/passage pairs typically score ~0.45-0.55, related ones 0.65+.
# Re-check with scripts/eval_answers.py if the embedding model changes.
DENSE_FLOOR = 0.45        # similarity treated as "no signal"
DENSE_MIN_RELEVANT = 0.60 # a passage this close is relevant even without shared keywords
PSEUDO_MIN_RELEVANT = 0.30
RELATIVE_CUTOFF = 0.35    # drop passages scoring under 35% of the best one

_LEGAL_MARKERS = ("privacy policy", "terms of service", "terms & conditions", "privacy-policy",
                  "terms-of", "cookie policy", "disclaimer")
_PRICE_MARKERS = ("PRODUCT SPECIFICATION", "PROPERTY LISTING", "• Price:", "Price:", "AED", "$")


class _Index:
    """Per-assistant search structures, rebuilt only when the assistant's chunks change."""

    def __init__(self, chunks: List[Dict[str, Any]]):
        self.chunks = chunks
        self.lower = [c["content"].lower() for c in chunks]
        self.tokens = [Counter(re.findall(r"[a-z0-9]+", t)) for t in self.lower]
        self.lengths = [sum(t.values()) for t in self.tokens]
        self.avgdl = (sum(self.lengths) / len(self.lengths)) if self.lengths else 1.0
        self.df: Counter = Counter()
        for t in self.tokens:
            self.df.update(t.keys())
        self.is_legal = [
            any(m in f"{c.get('title') or ''} {c.get('url') or ''}".lower() for m in _LEGAL_MARKERS)
            for c in chunks
        ]
        self.tags = [self._tag(c) for c in chunks]
        self.groups: Dict[str, Tuple[List[int], Any]] = {}
        by_tag: Dict[str, List[int]] = {}
        for i, tag in enumerate(self.tags):
            if tag in (current_embedding_tag(), PSEUDO_TAG):
                by_tag.setdefault(tag, []).append(i)
        for tag, rows in by_tag.items():
            vecs = [self.chunks[i]["embedding"] for i in rows]
            if np is not None:
                m = np.asarray(vecs, dtype=np.float32)
                norms = np.linalg.norm(m, axis=1, keepdims=True)
                norms[norms == 0] = 1.0
                self.groups[tag] = (rows, m / norms)
            else:
                self.groups[tag] = (rows, vecs)
        self._catalog: Dict[int, List[Dict[str, Any]]] = {}

    @staticmethod
    def _tag(chunk: Dict[str, Any]) -> str:
        if chunk.get("embedding_model"):
            return chunk["embedding_model"]
        vec = chunk.get("embedding") or []
        if len(vec) == PSEUDO_DIM:
            return PSEUDO_TAG
        return "legacy" if vec else ""  # made by a retired model before tagging existed

    def bm25(self, terms: List[str], k1: float = 1.5, b: float = 0.75) -> List[float]:
        n = len(self.chunks)
        idf = {t: math.log((n - self.df.get(t, 0) + 0.5) / (self.df.get(t, 0) + 0.5) + 1.0) for t in terms}
        scores = []
        for tf, dl in zip(self.tokens, self.lengths):
            s = 0.0
            for t in terms:
                f = tf.get(t)
                if f:
                    s += idf[t] * (f * (k1 + 1.0)) / (f + k1 * (1.0 - b + b * dl / (self.avgdl or 1.0)))
            scores.append(s)
        return scores

    def dense(self, query: str, workspace_id: Optional[str] = None) -> List[Optional[float]]:
        """Cosine similarity per chunk, or None where the chunk's vector can't be compared."""
        sims: List[Optional[float]] = [None] * len(self.chunks)
        for tag, (rows, matrix) in self.groups.items():
            if tag == PSEUDO_TAG:
                qv = _pseudo_embedding(query)
            else:
                qv = generate_embedding(query, task="query", workspace_id=workspace_id)
                if len(qv) != EMBEDDING_DIM:
                    continue  # Gemini unavailable right now; lexical signals still work
            if np is not None:
                q = np.asarray(qv, dtype=np.float32)
                qn = float(np.linalg.norm(q))
                if qn == 0:
                    continue
                values = (matrix @ (q / qn)).tolist()
            else:
                values = [cosine_similarity(qv, v) for v in matrix]
            for i, v in zip(rows, values):
                sims[i] = float(v)
        return sims

    def catalog_items(self, i: int) -> List[Dict[str, Any]]:
        if i not in self._catalog:
            from app.catalog_intelligence import extract_catalog_items_from_chunk
            c = self.chunks[i]
            self._catalog[i] = extract_catalog_items_from_chunk(
                c["content"], chunk_index=c.get("chunk_index", 1), url=c.get("url", ""), title=c.get("title", "")
            )
        return self._catalog[i]


_INDEX_CACHE: Dict[str, Tuple[List[Dict[str, Any]], _Index]] = {}


def _get_index(assistant_id: str) -> _Index:
    chunks = get_chunks_for_assistant(assistant_id)
    cached = _INDEX_CACHE.get(assistant_id)
    # The chunk cache hands back the same list object until the data changes or expires.
    if cached and cached[0] is chunks:
        return cached[1]
    index = _Index(chunks)
    _INDEX_CACHE[assistant_id] = (chunks, index)
    return index


def _catalog_boost(index: _Index, i: int, intent: Dict[str, Any]) -> float:
    from app.catalog_intelligence import match_items_against_query
    items = index.catalog_items(i)
    if not items:
        return 0.05 if any(tag in index.chunks[i]["content"] for tag in _PRICE_MARKERS) else 0.0
    matched = match_items_against_query(items, intent)
    boost = 0.35 if any(it.get("within_budget", False) for it in matched) else (0.15 if matched else 0.05)
    if intent.get("deal_type") == "rent" and any(it.get("deal_type") == "rent" for it in items):
        boost += 0.10
    if intent.get("bedrooms") and any(it.get("bedrooms") == intent["bedrooms"] for it in items):
        boost += 0.10
    locs = intent.get("locations") or []
    if locs and any(any(loc in (it.get("location", "") + it.get("name", "")).lower() for loc in locs) for it in items):
        boost += 0.10
    return boost


def search_relevant_chunks(
    query: str,
    assistant_id: str = "asst_default",
    top_k: int = 5,
    min_similarity: Optional[float] = None
) -> List[Dict[str, Any]]:
    """
    Hybrid search that returns only passages relevant to the question:
    - BM25 lexical matching (exact names, SKUs, numbers)
    - Dense vector similarity (meaning), compared only within the same embedding model
    - Query-word coverage, catalog/budget boosts, then absolute and relative cutoffs.
    `min_similarity`, if given, is an extra floor on the final score (0-1).
    """
    from app.catalog_intelligence import parse_user_query_intent

    norm_query = normalize_query_terms(query)
    index = _get_index(assistant_id)
    if not index.chunks:
        return []

    intent = parse_user_query_intent(norm_query)
    is_catalog_query = intent.get("is_catalog_query", False)
    effective_top_k = max(top_k, 8) if is_catalog_query else top_k

    query_lower = norm_query.lower()
    query_words = list(dict.fromkeys(
        w for w in re.findall(r"[a-z0-9]+", query_lower)
        if w not in STOPWORDS and (len(w) >= 3 or any(ch.isdigit() for ch in w))
    ))
    wants_legal = any(w in query_lower for w in ["privacy", "policy", "terms", "cookie", "gdpr", "legal", "data protection"])

    bm25 = index.bm25(query_words) if query_words else [0.0] * len(index.chunks)
    max_bm25 = max(bm25) if bm25 else 0.0
    dense = index.dense(norm_query, assistant_workspace_id(assistant_id))
    current_tag = current_embedding_tag()

    scored = []
    for i, c in enumerate(index.chunks):
        if index.is_legal[i] and not wants_legal:
            continue
        coverage = (sum(1 for w in query_words if w in index.lower[i]) / len(query_words)) if query_words else 0.0
        lex = bm25[i] / max_bm25 if max_bm25 > 0 else 0.0
        sim, tag = dense[i], index.tags[i]
        if sim is None:
            dense_norm = 0.0
        elif tag == PSEUDO_TAG:
            dense_norm = sim
        else:
            dense_norm = min(1.0, max(0.0, (sim - DENSE_FLOOR) / (1.0 - DENSE_FLOOR)))
        boost = _catalog_boost(index, i, intent) if is_catalog_query else 0.0

        relevant = (
            coverage >= 0.5
            or (bm25[i] > 0 and lex >= 0.5)
            or (sim is not None and tag == current_tag and sim >= DENSE_MIN_RELEVANT)
            or (sim is not None and tag == PSEUDO_TAG and sim >= PSEUDO_MIN_RELEVANT)
            or boost >= 0.15
        )
        if not relevant:
            continue
        score = 0.5 * dense_norm + 0.3 * lex + 0.2 * coverage + boost
        if min_similarity is not None and score < min_similarity:
            continue
        scored.append((score, i))

    if not scored:
        return []
    scored.sort(reverse=True)
    best = scored[0][0]

    results = []
    seen_fingerprints = set()
    for score, i in scored:
        if score < best * RELATIVE_CUTOFF:
            break
        c = index.chunks[i]
        # Crawls often store the same boilerplate under many URLs; keep the best copy only.
        fingerprint = re.sub(r"\s+", " ", index.lower[i]).strip()[:300]
        if fingerprint in seen_fingerprints:
            continue
        seen_fingerprints.add(fingerprint)
        results.append({
            "id": c["id"],
            "assistant_id": c["assistant_id"],
            "source_id": c["source_id"],
            "chunk_index": c["chunk_index"],
            "title": c["title"],
            "url": c["url"],
            "content": c["content"],
            "similarity": round(score, 4),
            "bm25_score": round(bm25[i], 4),
        })
        if len(results) >= effective_top_k:
            break
    return results


def reindex_assistant(assistant_id: str, max_chunks: int = 200, after_id: Optional[int] = None) -> Dict[str, Any]:
    """Re-embed up to `max_chunks` chunks with the current model. Call again with
    `next_after_id` until `done` is true (keeps each request short on serverless hosts).

    Without `after_id`, only chunks made by another model are processed. With it, a
    full rebuild continues from that chunk id (pass 0 to start one).
    """
    from app.db import list_chunks_to_reindex, update_chunk_embeddings, get_embedding_status
    tag = current_embedding_tag()
    workspace_id = assistant_workspace_id(assistant_id)
    if not get_genai_client(workspace_id):
        return {"processed": 0, "upgraded": 0, "next_after_id": None, "done": True,
                "error": "Add a Gemini API key in Settings to use semantic embeddings.",
                **get_embedding_status(assistant_id, tag)}

    rows = list_chunks_to_reindex(assistant_id, tag, max_chunks, after_id=after_id)
    vectors = generate_embeddings_batch([r["content"] for r in rows], titles=[r.get("title") or "" for r in rows],
                                        workspace_id=workspace_id)
    update_chunk_embeddings(assistant_id, [(r["id"], v, embedding_tag(v)) for r, v in zip(rows, vectors)])
    upgraded = sum(1 for v in vectors if embedding_tag(v) == tag)
    status = get_embedding_status(assistant_id, tag)

    if after_id is not None:
        next_after_id = rows[-1]["id"] if len(rows) == max_chunks else None
        done = next_after_id is None
    else:
        next_after_id = None
        # Chunks that failed to embed stay stale; stop rather than retry them forever.
        done = status["stale_chunks"] == 0 or upgraded < len(rows)
    result = {"processed": len(rows), "upgraded": upgraded, "next_after_id": next_after_id, "done": done, **status}
    if upgraded < len(rows):
        result["error"] = f"{len(rows) - upgraded} chunk(s) could not be embedded (rate limit or API error). Try again later."
    return result
