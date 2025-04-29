# services/embeddings.py
"""Embedding utilities (with an in-process cache)."""

from __future__ import annotations

import json
from functools import lru_cache

from sklearn.metrics.pairwise import cosine_similarity

from .clients import bedrock_client
from .config import EMBEDDING_MODEL_ID, logger


def get_embeddings(text: str) -> list[float]:
    """Call Bedrock embedding model and return the vector."""
    body = {"inputText": text}
    try:
        response = bedrock_client.invoke_model(
            modelId=EMBEDDING_MODEL_ID,
            contentType="application/json",
            accept="*/*",
            body=json.dumps(body).encode(),
        )
        return json.loads(response["body"].read().decode())["embedding"]
    except Exception as exc:  # noqa: BLE001
        logger.error("Cannot invoke %s — %s", EMBEDDING_MODEL_ID, exc)
        raise


@lru_cache(maxsize=1024)
def _cached_embedding(text: str) -> tuple[float, ...]:
    """LRU-cached helper around `get_embeddings`."""
    return tuple(get_embeddings(text))


def similarity(source_emb: list[float], target_text: str) -> float:
    """Cosine similarity between a ready embedding and some text."""
    target_emb = _cached_embedding(target_text)
    return float(
        cosine_similarity([source_emb], [list(target_emb)], dense_output=True)[
            0, 0
        ]
    )
