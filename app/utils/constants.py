"""Constants used across utility modules and shared service logic.

Includes paths, AWS configuration, knowledge base identifiers, model IDs,
and user-facing error messages.
"""

import logging
from pathlib import Path

from config import get_secret

logger = logging.getLogger(__name__)

# — Paths — #
ROOT_DIR = Path(__file__).resolve().parent
DOCS_DIR = (
    ROOT_DIR / "docs"
)  # TODO(@kvcn639): Ensure 'docs' folder exists at startup if it's required for runtime ops

# — AWS / Dynamo / S3 / KB settings — #
REGION_ID = get_secret("REGION_ID")
CHAT_TABLE = get_secret("CHAT_TABLE")
BUCKET_CONTAINER = get_secret("BUCKET_CONTAINER")
PRIVACY_KB_ID = get_secret("PRIVACY_KB_ID")
ALEXION_ID = get_secret("ALEXION_ID")
GEN_ENQ_KB_ID = get_secret("GEN_ENQ_KB_ID")

# TODO(@kvcn639): Raise errors or log warnings if any of these are None or misconfigured

# — API / LLM settings — #
API_KEY = get_secret("API_KEY")
MODEL_ID = get_secret("MODEL_ID")

# — Errors — #
ERROR_MESSAGE = "Oops! It seems there’s a network issue. Please check your connection and try again in a moment."
