"""
Embedding generation and vector similarity search supporting multi-assistant partitioning.
"""

import math
import re
import numpy as np
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
    "wouldn't", "you", "you'd", "you'll", "you're", "you've", "your", "yours", "yourself", "yourselves"
}

def _pseudo_embedding(text: str, dim: int = 256) -> List[float]:
    """Deterministic hash-based fallback vector when no API key is provided."""
    vec = [0.0] * dim
    words = [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOPWORDS and len(w) > 2]
    if not words:
        return vec
    for w in words:
        idx = (hash(w) % dim + dim) % dim
        vec[idx] += 1.0
    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 0:
        vec = [x / norm for x in vec]
    return vec

def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    a = np.array(v1, dtype=np.float32)
    b = np.array(v2, dtype=np.float32)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))

def search_relevant_chunks(
    query: str,
    assistant_id: str = "asst_default",
    top_k: int = 5,
    min_similarity: float = 0.12
) -> List[Dict[str, Any]]:
    """Retrieves top_k most relevant chunks for a user query isolated to specific assistant with budget awareness."""
    from app.catalog_intelligence import parse_user_query_intent, extract_catalog_items_from_chunk, match_items_against_query

    query_emb = generate_embedding(query)
    if not query_emb:
        return []
        
    chunks = get_chunks_for_assistant(assistant_id)
    if not chunks:
        return []
        
    # Analyze query intent (catalog, budget, deal type, entity type)
    intent = parse_user_query_intent(query)
    is_catalog_query = intent.get("is_catalog_query", False)
    effective_top_k = max(top_k, 8) if is_catalog_query else top_k

    # Extract query words including numbers, price symbols, and specs (e.g. 2, 50, 500k, 2bhk)
    query_lower = query.lower()
    meaningful_query_words = set(
        w for w in re.findall(r"[a-z0-9]+", query_lower)
        if w not in STOPWORDS and (len(w) >= 3 or w.isdigit() or any(c.isdigit() for c in w))
    )

    scored_chunks = []
    for c in chunks:
        sim = cosine_similarity(query_emb, c["embedding"])
        content_lower = c["content"].lower()
        
        # Keyword boost: calculate overlap of words
        keyword_hits = sum(1 for w in meaningful_query_words if w in content_lower) if meaningful_query_words else 0
        effective_sim = sim + (keyword_hits * 0.18)

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
        client = get_genai_client()
        if not client and meaningful_query_words and keyword_hits == 0 and not (is_catalog_query and any(p in c["content"] for p in ["• Price:", "Price:", "AED", "$"])):
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
                "similarity": round(effective_sim, 4)
            })
            
    scored_chunks.sort(key=lambda x: x["similarity"], reverse=True)
    return scored_chunks[:effective_top_k]

