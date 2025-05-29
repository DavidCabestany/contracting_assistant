"""Loads configuration values and initializes constants for QnA services."""

import logging

from config import get_secret

logger = logging.getLogger(__name__)

# ─────── Dynamic config values (loaded at runtime) ───────
REGION_ID: str = get_secret("REGION_ID")
MODEL_ARN: str = get_secret("MODEL_ARN")
EMBEDDING_MODEL_ID: str = get_secret("EMBEDDING_MODEL_ID")
MODEL_ID: str = get_secret("MODEL_ID")
BUCKET_CONTAINER: str = get_secret("BUCKET_CONTAINER")
QNA_FLOW_NAME: str = get_secret("QNA_FLOW_NAME")
SUMMARY_FLOW_NAME: str = get_secret("SUMMARY_FLOW_NAME")
GEN_ENQ_KB_ID: str = get_secret("GEN_ENQ_KB_ID")
SESSION_STATUS: str = get_secret("SESSION_STATUS_ACTIVE")
IRRELEVANT: str = get_secret("IRRELEVANT_KEYWORD")
QNA_SEARCH_TYPE: str = get_secret("QNA_SEARCH_TYPE")
GUARDRAIL_ID: str = get_secret("GUARDRAIL_ID")
GUARDRAIL_VERSION_ID: str = get_secret("GUARDRAIL_VERSION_ID")
QNA_MAX_TOKENS_VALUE: str = get_secret("QNA_MAX_TOKENS_VALUE")
PRIOR_DOC: str = get_secret("PRIOR_DOC")
