"""
Vector store for verification learnings.
Uses Qdrant in-memory + Gemini embeddings.
No external dependencies — runs entirely locally.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from google import genai

load_dotenv()

EMBEDDING_MODEL = "text-embedding-004"

_client = None
_collection_name = "verification_learnings"


def initialize():
    global _client
    if _client is not None:
        return

    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import VectorParams, Distance
    except ImportError:
        raise RuntimeError(
            "qdrant-client not installed. Run: pip install qdrant-client"
        )

    _client = QdrantClient(":memory:")
    _client.recreate_collection(
        collection_name=_collection_name,
        vectors_config=VectorParams(size=768, distance=Distance.COSINE),
    )


def _get_client():
    if _client is None:
        initialize()
    return _client


def _embed(text: str) -> list[float]:
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not set in .env")
    client = genai.Client(api_key=api_key)
    result = client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=text,
    )
    return result.embeddings[0].values


def add_learning(text: str, metadata: dict | None = None) -> int:
    from qdrant_client.models import PointStruct

    embedding = _embed(text)
    point_id = abs(hash(text + str(metadata or {}))) % (10 ** 12)
    payload = {"text": text, **(metadata or {})}

    _get_client().upsert(
        collection_name=_collection_name,
        points=[PointStruct(id=point_id, vector=embedding, payload=payload)],
    )
    return point_id


def search(query: str, top_k: int = 5) -> list[dict]:
    embedding = _embed(query)
    results = _get_client().search(
        collection_name=_collection_name,
        query_vector=embedding,
        limit=top_k,
    )
    return [r.payload for r in results]


def count() -> int:
    return _get_client().count(collection_name=_collection_name).count



