"""Init file for the utils package."""

from __future__ import annotations

from .constants import (
    ALEXION_ID,
    API_KEY,
    BUCKET_CONTAINER,
    CHAT_TABLE,
    DOCS_DIR,
    GEN_ENQ_KB_ID,
    MODEL_ID,
    PRIVACY_KB_ID,
    REGION_ID,
    ROOT_DIR,
)
from .file_utils import (
    extract_chat_history,
    extract_pdf_contents,
    extract_text_from_word,
    generate_technical_error_message,
    get_file_type,
    validate_api_key,
)
from .llm_utils import (
    db_tab_checker,
    extract_keywords_from_query,
    is_refusal,
    llm_summarise,
    needs_summary,
    parse_risk_assessment_output,
    response_sanitizer,
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

__all__ = [
    # configs
    "ROOT_DIR",
    "DOCS_DIR",
    "REGION_ID",
    "CHAT_TABLE",
    "BUCKET_CONTAINER",
    "PRIVACY_KB_ID",
    "ALEXION_ID",
    "GEN_ENQ_KB_ID",
    "API_KEY",
    "MODEL_ID",
    # llm_utils
    "is_refusal",
    "db_tab_checker",
    "response_sanitizer",
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
    # parents
    "get_secret",
]
