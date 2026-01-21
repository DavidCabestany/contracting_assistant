"""services package init — re-export submodules."""

from .chat_history_service import (
    download_chat,
    get_latest_active_sessions,
    search_chat,
    session_history,
    store_interaction,
    update_feedback,
    view_chat_by_session,
)
from .clients import s3_client
from .doc_retriever import retrieve_documents
from .embeddings import get_embeddings, similarity
from .memory import get_file_memory
from .qna import (  # tia_followup_user_query,; tia_trigger_initial_clarification,
    auto_attach_files,
    auto_attach_files_gxp_citation,
    detect_prior_doc_from_query,
    extract_file_locations,
    generate_answer_with_context,
    is_invalid_response,
    load_known_files_from_s3,
    retrieve_and_generate,
    retrieve_and_generate_prioritized_doc,
    retrieve_citations_from_query,
    retrieve_file_chunks,
    extract_token_usage,
)
from .templates import retrieve_template

__all__ = [
    # clients
    "s3_client",
    # memory
    "get_file_memory",
    # qna
    "load_known_files_from_s3",
    "auto_attach_files",
    "auto_attach_files_gxp_citation",
    "detect_prior_doc_from_query",
    "is_invalid_response",
    "needs_summary",
    "retrieve_citations_from_query",
    "retrieve_file_chunks",
    "retrieve_and_generate_prioritized_doc",
    "retrieve_and_generate",
    "retrieve_documents",
    "generate_answer_with_context",
    "get_knowledge_base_folder",
    "get_knowledge_base_id",
    "extract_file_locations",
    "llm_summarise",
    "tia_followup_user_query",
    "tia_trigger_initial_clarification",
    "detect_present_keywords_for_tia",
    "detect_missing_keywords_for_tia",
    "fallback_final_answer_for_tia",
    "build_clarification_prompt_for_tia",
    "extract_token_usage",
    # chat history
    "store_interaction",
    "session_history",
    "search_chat",
    "view_chat_by_session",
    "download_chat",
    "update_feedback",
    "get_latest_active_sessions",
    # templates / embeddings
    "retrieve_template",
    "get_embeddings",
    "similarity",
]
