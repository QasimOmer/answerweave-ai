"""
Embedding generation and vector similarity search supporting multi-assistant partitioning.
"""

import math
import re
import hashlib
try:
    import numpy as np
except Exception:
    np = None

from typing import List, Dict, Any, Optional
from google import genai
from google.genai import types

from app.config import get_api_key, EMBEDDING_MODEL
from app.db import get_chunks_for_assistant

def get_genai_client() -> Optional[genai.Client]:
    api_key = get_api_key("gemini")
    if not api_key:
        return None
    try:
        return genai.Client(api_key=api_key)
    except Exception:
        return None

def generate_embedding(text: str) -> List[float]:
    """Generates an embedding vector for a single text using Gemini, or fallback hash vector."""
    client = get_genai_client()
    if not client:
        return _pseudo_embedding(text)
        
    try:
        response = client.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=text
        )
        if response.embeddings and len(response.embeddings) > 0:
            return response.embeddings[0].values
        return []
    except Exception as e:
        return _pseudo_embedding(text)

def generate_embeddings_batch(texts: List[str]) -> List[List[float]]:
    """Generates embeddings for multiple texts."""
    return [generate_embedding(t) for t in texts]

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

def compute_bm25_scores(query_tokens: List[str], chunk_token_lists: List[List[str]], k1: float = 1.5, b: float = 0.75) -> List[float]:
    """
    Industrial BM25 lexical ranking algorithm with Robertson-Spärck Jones IDF.
    """
    N = len(chunk_token_lists)
    if N == 0 or not query_tokens:
        return [0.0] * N
    
    doc_lengths = [len(tokens) for tokens in chunk_token_lists]
    avgdl = (sum(doc_lengths) / N) if N > 0 else 1.0
    
    # Document frequencies (df)
    df = {}
    for term in query_tokens:
        df[term] = sum(1 for tokens in chunk_token_lists if term in tokens)
        
    scores = []
    for i, tokens in enumerate(chunk_token_lists):
        doc_len = doc_lengths[i]
        tf_dict = {}
        for t in tokens:
            tf_dict[t] = tf_dict.get(t, 0) + 1
            
        score = 0.0
        for term in query_tokens:
            if term not in tf_dict:
                continue
            tf = tf_dict[term]
            term_df = df.get(term, 0)
            idf = math.log((N - term_df + 0.5) / (term_df + 0.5) + 1.0)
            denom = tf + k1 * (1.0 - b + b * (doc_len / (avgdl or 1.0)))
            score += idf * (tf * (k1 + 1.0) / (denom or 1.0))
        scores.append(score)
    return scores

def search_relevant_chunks(
    query: str,
    assistant_id: str = "asst_default",
    top_k: int = 5,
    min_similarity: float = 0.10
) -> List[Dict[str, Any]]:
    """
    Enterprise Hybrid Search combining:
    - BM25 Sparse Lexical Matching (exact alphanumeric SKUs, names, phone numbers)
    - Dense Vector Cosine Similarity (semantic understanding)
    - Reciprocal Rank Fusion (RRF) with Catalog & Budget Intelligence Boosts.
    """
    from app.catalog_intelligence import parse_user_query_intent, extract_catalog_items_from_chunk, match_items_against_query

    norm_query = normalize_query_terms(query)
    query_emb = generate_embedding(norm_query)
    if not query_emb:
        return []
        
    chunks = get_chunks_for_assistant(assistant_id)
    if not chunks:
        return []
        
    # Analyze query intent (catalog, budget, deal type, entity type)
    intent = parse_user_query_intent(norm_query)
    is_catalog_query = intent.get("is_catalog_query", False)
    effective_top_k = max(top_k, 8) if is_catalog_query else top_k

    # Extract query words including numbers, price symbols, and specs
    query_lower = norm_query.lower()
    meaningful_query_words = [
        w for w in re.findall(r"[a-z0-9]+", query_lower)
        if w not in STOPWORDS and (len(w) >= 3 or w.isdigit() or any(c.isdigit() for c in w))
    ]

    # Pre-filter candidate chunks (filter out legal/policy unless explicitly queried)
    user_wants_legal = any(w in query_lower for w in ["privacy", "policy", "terms", "cookie", "gdpr", "legal", "data protection"])
    valid_chunks = []
    chunk_tokens_list = []
    
    for c in chunks:
        is_legal_chunk = any(t in (c.get("title", "") + " " + c.get("url", "")).lower() for t in [
            "privacy policy", "terms of service", "terms & conditions", "privacy-policy",
            "terms-of", "cookie policy", "disclaimer"
        ])
        if is_legal_chunk and not user_wants_legal:
            continue
        valid_chunks.append(c)
        chunk_tokens_list.append(re.findall(r"[a-z0-9]+", c["content"].lower()))

    if not valid_chunks:
        return []

    # 1. Compute BM25 lexical scores
    bm25_scores = compute_bm25_scores(meaningful_query_words, chunk_tokens_list)
    bm25_indexed = sorted(range(len(valid_chunks)), key=lambda i: bm25_scores[i], reverse=True)
    bm25_ranks = {orig_idx: rank + 1 for rank, orig_idx in enumerate(bm25_indexed)}

    # 2. Compute Dense vector cosine similarities
    dense_sims = [cosine_similarity(query_emb, c["embedding"]) for c in valid_chunks]
    dense_indexed = sorted(range(len(valid_chunks)), key=lambda i: dense_sims[i], reverse=True)
    dense_ranks = {orig_idx: rank + 1 for rank, orig_idx in enumerate(dense_indexed)}

    # 3. Fuse via Reciprocal Rank Fusion (RRF) with constant k=60
    has_dense_client = get_genai_client() is not None
    scored_chunks = []
    for i, c in enumerate(valid_chunks):
        r_bm25 = bm25_ranks[i]
        r_dense = dense_ranks[i]
        bm25_val = bm25_scores[i]
        dense_val = dense_sims[i]

        # RRF formula
        rrf = (1.0 / (60.0 + r_bm25)) + (1.0 / (60.0 + r_dense))
        
        # Base effective similarity scaled from RRF + dense baseline
        content_lower = c["content"].lower()
        keyword_hits = sum(1 for w in meaningful_query_words if w in content_lower) if meaningful_query_words else 0
        effective_sim = dense_val + (rrf * 12.0) + (keyword_hits * 0.15)

        # Catalog & Budget Intelligence Boost
        if is_catalog_query:
            items = extract_catalog_items_from_chunk(
                c["content"],
                chunk_index=c.get("chunk_index", 1),
                url=c.get("url", ""),
                title=c.get("title", "")
            )
            if items:
                matched_items = match_items_against_query(items, intent)
                has_fitting = any(it.get("within_budget", False) for it in matched_items)
                
                if has_fitting:
                    # Item fits user's budget and criteria! Massive priority boost
                    effective_sim += 0.85
                elif matched_items:
                    # Items match entity/category even if over budget
                    effective_sim += 0.35
                else:
                    effective_sim += 0.15

                # Rent vs Sale deal-type match
                if intent.get("deal_type") == "rent" and any(it.get("deal_type") == "rent" for it in items):
                    effective_sim += 0.30

                # Bedroom count match
                if intent.get("bedrooms") and any(it.get("bedrooms") == intent["bedrooms"] for it in items):
                    effective_sim += 0.25

                # Location match
                if intent.get("locations") and any(any(loc in (it.get("location", "") + it.get("name", "")).lower() for loc in intent["locations"]) for it in items):
                    effective_sim += 0.30
            else:
                # If chunk is not structured catalog but has pricing info or catalog tags
                if any(tag in c["content"] for tag in ["PRODUCT SPECIFICATION", "PROPERTY LISTING", "• Price:", "Price:", "AED", "$"]):
                    effective_sim += 0.15

        # Grounding condition: require at least 1 keyword hit if using fallback pseudo-embedding
        if not has_dense_client and meaningful_query_words and keyword_hits == 0 and bm25_val == 0.0 and not (is_catalog_query and any(p in c["content"] for p in ["• Price:", "Price:", "AED", "$"])):
            continue

        if effective_sim >= min_similarity:
            scored_chunks.append({
                "id": c["id"],
                "assistant_id": c["assistant_id"],
                "source_id": c["source_id"],
                "chunk_index": c["chunk_index"],
                "title": c["title"],
                "url": c["url"],
                "content": c["content"],
                "similarity": round(effective_sim, 4),
                "bm25_score": round(bm25_val, 4)
            })
            
    scored_chunks.sort(key=lambda x: x["similarity"], reverse=True)

    # Crawls often store the same boilerplate (service lists, footers, repeated
    # sections) under many URLs. Keep only the best-scoring copy so duplicates
    # don't crowd distinct, relevant passages out of the top-k.
    unique_chunks = []
    seen_fingerprints = set()
    for sc in scored_chunks:
        fingerprint = re.sub(r"\s+", " ", sc["content"].lower()).strip()[:300]
        if fingerprint in seen_fingerprints:
            continue
        seen_fingerprints.add(fingerprint)
        unique_chunks.append(sc)
        if len(unique_chunks) >= effective_top_k:
            break
    return unique_chunks


