"""Embedding utilities (with an in-process cache).

This module handles text embedding generation and cosine similarity computation
using a Bedrock embedding model. It also includes an LRU cache to avoid
repeated embedding calls for the same input.
"""

from __future__ import annotations

import json
from functools import lru_cache

from sklearn.metrics.pairwise import cosine_similarity

from .clients import bedrock_client
from .config import EMBEDDING_MODEL_ID, logger


def get_embeddings(text: str) -> list[float]:
    """
    Invoke the Bedrock embedding model to compute a vector representation of input text.

    Args:
        text (str): The input string to embed.

    Returns:
        list[float]: A list of floats representing the embedding vector.

    Raises:
        Exception: If the embedding request to Bedrock fails.
    """
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
        raise  # FIXME: Raise specific exception class (e.g., EmbeddingError)


@lru_cache(maxsize=1024)
def _cached_embedding(text: str) -> tuple[float, ...]:
    """
    Get embedding vector from cache if available, otherwise compute it.

    Args:
        text (str): The input string to embed.

    Returns:
        tuple[float, ...]: Cached or computed embedding vector as an immutable tuple.
    """
    return tuple(
        get_embeddings(text)
    )  # TODO: Consider TTL cache instead if embeddings change


def similarity(source_emb: list[float], target_text: str) -> float:
    """
    Compute cosine similarity between a given source embedding and a target text.

    Args:
        source_emb (list[float]): Precomputed embedding of the source text.
        target_text (str): Raw text to embed and compare against the source.

    Returns:
        float: Cosine similarity score between -1 and 1.
    """
    target_emb = _cached_embedding(target_text)
    return float(
        cosine_similarity([source_emb], [list(target_emb)], dense_output=True)[
            0, 0
        ]
    )  # FIXME: Handle edge case where embeddings are empty or None
