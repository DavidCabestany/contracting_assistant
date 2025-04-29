# services/doc_retriever.py
"""Retrieve documents only (no generation)."""

from __future__ import annotations

from typing import Any, Dict

import boto3

from .config import QNA_SEARCH_TYPE


def retrieve_documents(
    query: str,
    kb_id: str,
    region_id: str,
    *,
    filter_value: str | None = None,
) -> Dict[str, Any]:
    runtime = boto3.client("bedrock-agent-runtime", region_name=region_id)

    vector_cfg = {
        "overrideSearchType": QNA_SEARCH_TYPE,
        "numberOfResults": 3,
    }
    if filter_value:
        vector_cfg["filter"] = {
            "equals": {
                "key": "x-amz-bedrock-kb-source-uri",
                "value": filter_value,
            }
        }

    request = {
        "knowledgeBaseId": kb_id,
        "retrievalQuery": {"text": query},
        "retrievalConfiguration": {"vectorSearchConfiguration": vector_cfg},
    }
    return runtime.retrieve(**request)
