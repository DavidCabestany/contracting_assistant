# services/config.py
import logging
from pathlib import Path

from config import get_config_value

logger = logging.getLogger(__name__)

# — Paths —#
ROOT_DIR = Path(__file__).resolve().parent
DOCS_DIR = ROOT_DIR / "docs"

# — AWS / Dynamo / S3 / KB settings —#
REGION_ID = get_config_value("REGION_ID")
CHAT_TABLE = get_config_value("CHAT_TABLE")
BUCKET_CONTAINER = get_config_value("BUCKET_CONTAINER")
PRIVACY_KB_ID = get_config_value("PRIVACY_KB_ID")
ALEXION_ID = get_config_value("ALEXION_ID")
GEN_ENQ_KB_ID = get_config_value("GEN_ENQ_KB_ID")

# — API / LLM settings —#
API_KEY = get_config_value("API_KEY")
MODEL_ID = get_config_value("MODEL_ID")

# — Errors —#
ERROR_MESSAGE = (
    "Oops! It seems there’s a network issue. "
    "Please check your connection and try again in a moment."
)
