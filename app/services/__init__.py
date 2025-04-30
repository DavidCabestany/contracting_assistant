"""services package init  re-export submodules."""

from .doc_retriever import retrieve_documents
from .embeddings import get_embeddings, similarity
from .qna import (
    generate_answer_with_context,
    retrieve_and_generate,
    retrieve_and_generate_prioritized_doc,
)
from .templates import retrieve_template

__all__ = [
    # qna
    "retrieve_and_generate",
    "retrieve_and_generate_prioritized_doc",
    "retrieve_documents",
    "generate_answer_with_context",
    # templates / embeddings
    "retrieve_template",
    "get_embeddings",
    "similarity",
]
