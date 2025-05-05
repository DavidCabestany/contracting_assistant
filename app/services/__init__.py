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
from .doc_retriever import retrieve_documents
from .embeddings import get_embeddings, similarity
from .memory import get_file_memory
from .qna import (
    generate_answer_with_context,
    retrieve_and_generate,
    retrieve_and_generate_prioritized_doc,
)
from .templates import retrieve_template

__all__ = [
    "get_file_memory",
    # qna
    "retrieve_and_generate",
    "retrieve_and_generate_prioritized_doc",
    "retrieve_documents",
    "generate_answer_with_context",
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
