"""Centralised config and hard constants."""

import logging

from config import get_config_value

# Dynamic values
REGION_ID: str = get_config_value("REGION_ID")
MODEL_ARN: str = get_config_value("MODEL_ARN")
EMBEDDING_MODEL_ID: str = get_config_value("EMBEDDING_MODEL_ID")
MODEL_ID: str = get_config_value("MODEL_ID")
BUCKET_CONTAINER: str = get_config_value("BUCKET_CONTAINER")
QNA_SEARCH_TYPE: str = get_config_value("QNA_SEARCH_TYPE")
GUARDRAIL_ID: str = get_config_value("GUARDRAIL_ID")
GUARDRAIL_VERSION_ID: str = get_config_value("GUARDRAIL_VERSION_ID")

# Static tuning knobs
QNA_MAX_TOKENS_VALUE: int = 4096
QNA_TEMPERATURE_VALUE: float = 0.1
QNA_TOP_P_VALUE: float = 0.7

# Prompt-mapping file
EXCEL_FILE_PATH: str = "mappings/prompt_map.xlsx"
AZ_MAPPING_SHEET_NAME: str = "Sheet1"

# Logging
logger = logging.getLogger("services")
logger.setLevel(logging.INFO)
