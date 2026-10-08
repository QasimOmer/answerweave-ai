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
    top_k: int = 4,
    min_similarity: float = 0.15
) -> List[Dict[str, Any]]:
    """Retrieves top_k most relevant chunks for a user query isolated to specific assistant."""
    query_emb = generate_embedding(query)
    if not query_emb:
        return []
        
    chunks = get_chunks_for_assistant(assistant_id)
    if not chunks:
        return []
        
    meaningful_query_words = set(w for w in re.findall(r"[a-z0-9]{3,}", query.lower()) if w not in STOPWORDS)

    scored_chunks = []
    for c in chunks:
        sim = cosine_similarity(query_emb, c["embedding"])
        
        # Keyword boost: calculate overlap of words
        content_lower = c["content"].lower()
        keyword_hits = sum(1 for w in meaningful_query_words if w in content_lower) if meaningful_query_words else 0
        effective_sim = sim + (keyword_hits * 0.15)

        # Grounding condition: require at least 1 keyword hit if using fallback pseudo-embedding
        client = get_genai_client()
        if not client and meaningful_query_words and keyword_hits == 0:
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
    return scored_chunks[:top_k]

