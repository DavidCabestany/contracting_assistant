"""Centralised configuration and constant values for QnA services.

This module defines:
- Dynamic values fetched at runtime from AWS Secrets Manager via `get_secret`
- Static constants used for tuning (e.g., temperature, max tokens)
- Prompt mapping file locations
- Logging and AWS client setup
- Priority query definitions
"""

import logging

from config import get_secret

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
QNA_MAX_TOKENS_VALUE: int = 4000
PRIOR_DOC: str = get_secret("PRIOR_DOC")

# ─────── Static tuning knobs ───────
QNA_MAX_TOKENS: int = 4096
QNA_TEMPERATURE: float = 0.1
QNA_TOP_P: float = 0.7

# ─────── Prompt mapping file location ───────
EXCEL_FILE_PATH: str = "mappings/prompt_map.xlsx"
AZ_MAPPING_SHEET_NAME: str = "Sheet1"


# ─────── Logger setup ───────
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ─────── High-priority queries ───────
HIGH_PRIORITY_QUERIES = {
    "General Queries": {
        "what are az standard payment terms?",
        "what are AZ standard payment terms for Vendors located in France?",
        "what are AZ standard payment terms for France",
        "what minimum audit rights do we require in a contract?",
        "the supplier doesn't want to accept out standard payment terms, what can i do?",
        "who decides on the liability cap?",
        "What payment terms should be used in France",
        "What payment terms should be used in Germany",
    },
    "Privacy": {
        "what are the mandatory incident reporting timeframes depending on jurisdiction?",
        "when should i add swiss or uk addendum to privacy terms?",
        "i have technological measures listed already in data privacy appendix. can i refer to them in sccs or i should copy them explicitly?",
        "i do not see list of affiliates covered by data privacy terms and sccs in the documents. where should relevant controllers (affiliates) be listed?",
        "Can the liability for a cyber security incydent be capped?",
        "What to do in case of an cyber security incident?",
        "Im in procurement, can I decide on the liability cap?",
    },
    "Alexion": {
        "what are the thresholds for legal review of contracts at alexion?",
        "what is the process for creating and approving a contract in icertis at alexion?",
        "who are the local legal contacts for different countries in alexion's procurement process?",
        "what is the role of 3prm (third-party risk management) in alexion's vendor onboarding process?",
    },
}
