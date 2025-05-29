"""Retrieve documents from Bedrock Knowledge Base without generating answers.

This module provides a thin wrapper around the Bedrock Agent Runtime API to
perform document-only search queries using vector-based retrieval.
"""

from __future__ import annotations

from typing import Any, Dict

from .clients import bedrock_agent_runtime
from .constants import QNA_SEARCH_TYPE

QNA_MAX_RESULTS = 3


def retrieve_documents(
    query: str,
    kb_id: str,
    region_id: str,
    *,
    filter_value: str | None = None,
) -> Dict[str, Any]:
    """Queries the Bedrock Knowledge Base for documents related to a given user query.

    Args:
        query (str): The user input text to search against the knowledge base.
        kb_id (str): The identifier of the Knowledge Base to search in.
        region_id (str): AWS region where the KB is hosted.
        filter_value (Optional[str]): Optional filter on document source URI.

    Returns:
        Dict[str, Any]: Raw response from the Bedrock Agent Runtime API.
    """
    # TODO(@kvcn639): Validate region_id matches configured region; log warning if not

    vector_cfg = {
        "overrideSearchType": QNA_SEARCH_TYPE,  # e.g., semantic or keyword
        "numberOfResults": QNA_MAX_RESULTS,  # TODO(@kvcn639): Make result count configurable
    }

    if filter_value:
        # Filter to only return documents matching specific source URI
        vector_cfg["filter"] = {
            "equals": {
                "key": "x-amz-bedrock-kb-source-uri",
                "value": filter_value,
            },
        }

    request = {
        "knowledgeBaseId": kb_id,
        "retrievalQuery": {"text": query},
        "retrievalConfiguration": {"vectorSearchConfiguration": vector_cfg},
    }

    # TODO(@kvcn639): Add error handling for the Bedrock retrieve() call (try/except)
    return bedrock_agent_runtime.retrieve(**request)
