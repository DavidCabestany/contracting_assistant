# services/templates.py
"""Pick the most relevant prompt template from the mapping sheet."""

from __future__ import annotations

import warnings
from typing import Tuple

import numpy as np

from .config import (
    AZ_MAPPING_SHEET_NAME,
    EXCEL_FILE_PATH,
    logger,
)
from .embeddings import get_embeddings, similarity
from .storage import read_excel_from_s3

warnings.filterwarnings(
    "ignore", message="Passing bytes to 'read_excel' is deprecated"
)


def _load_mapping() -> Tuple[list[str], list[str]]:
    df = read_excel_from_s3(EXCEL_FILE_PATH, AZ_MAPPING_SHEET_NAME)
    return df["Question"].tolist(), df["Prompt"].tolist()


def retrieve_template(user_query: str, threshold: float = 0.6) -> str:
    questions, prompts = _load_mapping()
    source_emb = get_embeddings(user_query)
    sims = np.array([similarity(source_emb, q) for q in questions])
    idx = int(np.argmax(sims))
    logger.debug("Best match - %.3f «%s»", sims[idx], questions[idx])
    return prompts[idx] if sims[idx] >= threshold else ""
