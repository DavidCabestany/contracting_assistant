"""Centralised configuration and constant values.

This module defines:
- Dynamic values fetched from AWS Secrets Manager via `get_secret`
- Static constants used for tuning (e.g., temperature, max tokens)
- Prompt mapping paths
- Logging setup for downstream service modules
"""

import logging

from config import get_secret

# ─────── Dynamic config values (loaded at runtime from Secrets Manager) ───────
REGION_ID: str = get_secret("REGION_ID")
MODEL_ARN: str = get_secret("MODEL_ARN")
EMBEDDING_MODEL_ID: str = get_secret("EMBEDDING_MODEL_ID")
MODEL_ID: str = get_secret("MODEL_ID")
BUCKET_CONTAINER: str = get_secret("BUCKET_CONTAINER")
QNA_SEARCH_TYPE: str = get_secret("QNA_SEARCH_TYPE")
GUARDRAIL_ID: str = get_secret("GUARDRAIL_ID")
GUARDRAIL_VERSION_ID: str = get_secret("GUARDRAIL_VERSION_ID")


BUCKET_CONTAINER = get_secret("BUCKET_CONTAINER")
QNA_FLOW_NAME = get_secret("QNA_FLOW_NAME")
MODEL_ID = get_secret("MODEL_ID")

SESSION_STATUS = get_secret("SESSION_STATUS_ACTIVE")
IRRELEVANT = get_secret("IRRELEVANT_KEYWORD")
GEN_ENQ_KB_ID = get_secret("GEN_ENQ_KB_ID")
SUMMARY_FLOW_NAME = get_secret("SUMMARY_FLOW_NAME")
PRIOR_DOC = get_secret("SUMMARY_FLOW_NAME")
# TODO(@kvcn639): Add fallback defaults or error handling if any value above is missing or None

# ─────── Static tuning knobs ───────
QNA_MAX_TOKENS_VALUE: int = 4096
QNA_TEMPERATURE_VALUE: float = 0.1
QNA_TOP_P_VALUE: float = 0.7


# ─────── Prompt mapping file location ───────
EXCEL_FILE_PATH: str = "mappings/prompt_map.xlsx"
AZ_MAPPING_SHEET_NAME: str = "Sheet1"
# TODO(@kvcn639): Validate path existence at app startup, or use Pathlib for safety

# ─────── Logger setup ───────
logger = logging.getLogger("services")
logger.setLevel(logging.INFO)
