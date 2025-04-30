"""Centralised configuration and constant values.

This module defines:
- Dynamic values fetched from AWS Secrets Manager via `get_config_value`
- Static constants used for tuning (e.g., temperature, max tokens)
- Prompt mapping paths
- Logging setup for downstream service modules
"""

import logging

from config import get_config_value

# ─────── Dynamic config values (loaded at runtime from Secrets Manager) ───────
REGION_ID: str = get_config_value("REGION_ID")
MODEL_ARN: str = get_config_value("MODEL_ARN")
EMBEDDING_MODEL_ID: str = get_config_value("EMBEDDING_MODEL_ID")
MODEL_ID: str = get_config_value("MODEL_ID")
BUCKET_CONTAINER: str = get_config_value("BUCKET_CONTAINER")
QNA_SEARCH_TYPE: str = get_config_value("QNA_SEARCH_TYPE")
GUARDRAIL_ID: str = get_config_value("GUARDRAIL_ID")
GUARDRAIL_VERSION_ID: str = get_config_value("GUARDRAIL_VERSION_ID")

# TODO: Add fallback defaults or error handling if any value above is missing or None

# ─────── Static tuning knobs ───────
QNA_MAX_TOKENS_VALUE: int = 4096
QNA_TEMPERATURE_VALUE: float = 0.1
QNA_TOP_P_VALUE: float = 0.7


# ─────── Prompt mapping file location ───────
EXCEL_FILE_PATH: str = "mappings/prompt_map.xlsx"
AZ_MAPPING_SHEET_NAME: str = "Sheet1"
# FIXME: Validate path existence at app startup, or use Pathlib for safety

# ─────── Logger setup ───────
logger = logging.getLogger("services")
logger.setLevel(logging.INFO)
