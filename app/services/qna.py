# services/qna.py
"""High-level Bedrock Q&A helpers."""

from __future__ import annotations

import json
from typing import Sequence

from .clients import bedrock_agent_runtime, bedrock_client
from .config import (
    BUCKET_CONTAINER,
    GUARDRAIL_ID,
    GUARDRAIL_VERSION_ID,
    MODEL_ARN,
    MODEL_ID,
    QNA_MAX_TOKENS_VALUE,
    QNA_SEARCH_TYPE,
    QNA_TEMPERATURE_VALUE,
    QNA_TOP_P_VALUE,
)
from .storage import add_prefix
from .templates import retrieve_template


def generate_answer_with_context(formatted_prompt: str) -> dict:
    """
    Fire a single Bedrock chat completion with the supplied user prompt.

    This is the direct port of the legacy `generate_answer_with_context`.
    """
    body = json.dumps(
        {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": QNA_MAX_TOKENS_VALUE,
            "messages": [{"role": "user", "content": formatted_prompt}],
        }
    )

    response = bedrock_client.invoke_model(
        body=body,
        modelId=MODEL_ID,
        accept="application/json",
        contentType="application/json",
        guardrailIdentifier=GUARDRAIL_ID,
        guardrailVersion=GUARDRAIL_VERSION_ID,
    )
    return json.loads(response["body"].read().decode())


def _render_prompt(user_query: str, base_prompt: str | None = None) -> str:
    tmpl = (
        base_prompt
        if base_prompt is not None
        else retrieve_template(user_query)
    )
    tmpl = str(tmpl)
    tmpl += (
        "\n\n%ADDITIONAL INSTRUCTIONS%:\n"
        "Please treat suppliers and vendors as aliases in the chunks."
    )
    tmpl += f"\n\n%USER QUERY:\n{user_query}\n"
    return tmpl


def _build_gen_cfg() -> dict:
    return {
        "guardrailConfiguration": {
            "guardrailId": GUARDRAIL_ID,
            "guardrailVersion": GUARDRAIL_VERSION_ID,
        },
        "inferenceConfig": {
            "textInferenceConfig": {
                "maxTokens": QNA_MAX_TOKENS_VALUE,
                "temperature": QNA_TEMPERATURE_VALUE,
                "topP": QNA_TOP_P_VALUE,
            }
        },
    }


def retrieve_and_generate(
    query: str, kb_id: str, *, session_id: str | None = None
):
    prompt_text = _render_prompt(query)
    return bedrock_agent_runtime.retrieve_and_generate(
        input={"text": prompt_text},
        retrieveAndGenerateConfiguration={
            "knowledgeBaseConfiguration": {
                "knowledgeBaseId": kb_id,
                "modelArn": MODEL_ARN,
                "retrievalConfiguration": {
                    "vectorSearchConfiguration": {
                        "overrideSearchType": QNA_SEARCH_TYPE,
                        "numberOfResults": 3,
                    }
                },
                "generationConfiguration": _build_gen_cfg(),
            },
            "type": "KNOWLEDGE_BASE",
        },
        **({"sessionId": session_id} if session_id else {}),
    )


def retrieve_and_generate_prioritized_doc(
    query: str,
    kb_id: str,
    knowledge_base_folder: str,
    files: Sequence[str],
    *,
    session_id: str | None = None,
):
    prompt_text = _render_prompt(query)
    allowed_paths = add_prefix(files, BUCKET_CONTAINER, knowledge_base_folder)
    return bedrock_agent_runtime.retrieve_and_generate(
        input={"text": prompt_text},
        retrieveAndGenerateConfiguration={
            "knowledgeBaseConfiguration": {
                "knowledgeBaseId": kb_id,
                "modelArn": MODEL_ARN,
                "retrievalConfiguration": {
                    "vectorSearchConfiguration": {
                        "overrideSearchType": QNA_SEARCH_TYPE,
                        "filter": {
                            "in": {
                                "key": "x-amz-bedrock-kb-source-uri",
                                "value": allowed_paths,
                            }
                        },
                        "numberOfResults": 3,
                    }
                },
                "generationConfiguration": _build_gen_cfg(),
            },
            "type": "KNOWLEDGE_BASE",
        },
        **({"sessionId": session_id} if session_id else {}),
    )
