from __future__ import annotations

import logging
from pathlib import Path

from config import get_config_value

from .file_utils import (
    extract_chat_history,
    extract_pdf_contents,
    extract_text_from_word,
    generate_technical_error_message,
    get_file_type,
    validate_api_key,
)
from .llm_utils import (
    extract_keywords_from_query,
    llm_summarise,
    needs_summary,
    parse_risk_assessment_output,
)
from .prompt_utils import (
    business_unit_prompt,
    generate_prompt,
    generate_prompt_risk,
    get_knowledge_base_folder,
    get_knowledge_base_id,
    get_risk_matrix_details,
    prompt_query_cat,
)
from .s3_utils import (
    extract_file_locations,
    generate_presigned_url,
    get_filename_from_path,
)

logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parent
DOCS_DIR = ROOT_DIR / "docs"

REGION_ID = get_config_value("REGION_ID")
CHAT_TABLE = get_config_value("CHAT_TABLE")
BUCKET_CONTAINER = get_config_value("BUCKET_CONTAINER")
PRIVACY_KB_ID = get_config_value("PRIVACY_KB_ID")
ALEXION_ID = get_config_value("ALEXION_ID")
GEN_ENQ_KB_ID = get_config_value("GEN_ENQ_KB_ID")
API_KEY = get_config_value("API_KEY")
MODEL_ID = get_config_value("MODEL_ID")

ERROR_MESSAGE = (
    "Oops! It seems there’s a network issue. "
    "Please check your connection and try again in a moment."
)

__all__ = [
    # llm_utils
    "needs_summary",
    "llm_summarise",
    "parse_risk_assessment_output",
    "extract_keywords_from_query",
    # s3_utils
    "generate_presigned_url",
    "extract_file_locations",
    "get_filename_from_path",
    # prompt_utils
    "business_unit_prompt",
    "get_knowledge_base_id",
    "get_knowledge_base_folder",
    "get_risk_matrix_details",
    "generate_prompt",
    "generate_prompt_risk",
    "prompt_query_cat",
    # file_utils
    "extract_pdf_contents",
    "extract_text_from_word",
    "get_file_type",
    "generate_technical_error_message",
    "validate_api_key",
    "extract_chat_history",
]
