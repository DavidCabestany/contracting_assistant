# services/qna.py
"""High-level Bedrock Q&A helpers.

This module handles prompt formatting, configuration building, and calls to
Bedrock's retrieve-and-generate APIs with optional guardrails and source filtering.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

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
    """Perform a basic prompt completion call using Bedrock's chat model.

    Args:
        formatted_prompt (str): The prompt text to send to the model.

    Returns:
        dict: Parsed JSON result from Bedrock's model invocation.
    """
    body = json.dumps(
        {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": QNA_MAX_TOKENS_VALUE,
            "messages": [{"role": "user", "content": formatted_prompt}],
        },
    )

    # TODO(@kvcn639): Handle timeout, invalid response, or empty completions gracefully
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
    """Render a complete prompt string using a base template and user input.

    Args:
        user_query (str): The original user question.
        base_prompt (Optional[str]): A custom template, if provided.

    Returns:
        str: A complete prompt ready for LLM ingestion.
    """
    tmpl = (
        base_prompt
        if base_prompt is not None
        else retrieve_template(user_query)
    )
    tmpl = str(tmpl)
    tmpl += "\n\n%ADDITIONAL INSTRUCTIONS%:\nPlease treat suppliers and vendors as aliases in the chunks."
    tmpl += f"\n\n%USER QUERY:\n{user_query}\n"
    return tmpl


def _build_gen_cfg() -> dict:
    """Build the generation configuration including temperature, top-p, and guardrails.

    Returns:
        dict: Configuration block for generation.
    """
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
            },
        },
    }


def retrieve_and_generate(
    query: str,
    kb_id: str,
    *,
    session_id: str | None = None,
    kb_path: str | None = None,
):
    """Run Bedrock's retrieve-and-generate pipeline using the general KB.

    Args:
        query (str): The user query.
        kb_id (str): Knowledge base ID.
        session_id (Optional[str]): Optional session identifier.
        kb_path (Optional[str]): S3 prefix path for the documents.

    Returns:
        dict: Retrieved and generated output from Bedrock.
    """

    # Define query to document mapping
    query_reference_document_mapping = {
        "supplier controller processor": "Playbook_Data Protection Appendix – Controller to Dual Role Processor.pdf",
        "gcp clause": "SAAS Agreement (Standalone).pdf",
        "can handbook": "CAN HANDBOOK Third Edition.pdf",
        "payment terms vendor": "CAN HANDBOOK Third Edition.pdf",
        "liability data protection": "Playbook_Data Protection Appendix - AZ Controller to Supplier Processor.pdf",
        "template clarifies govern": "General Rules Document.pdf"
    }

    prompt_text = _render_prompt(query)

    # Determine document filter based on query content
    filter_config = {}
    query_lower = query.lower()
    
    # Find matching document based on keywords
    for keywords, document in query_reference_document_mapping.items():
        if any(keyword in query_lower for keyword in keywords.split()):
            filter_config = {
                "equals": {
                    "key": "x-amz-bedrock-kb-source-uri",
                    "value": f"s3://{BUCKET_CONTAINER}/{kb_path}/{document}"
                }
            }
            break

    return bedrock_agent_runtime.retrieve_and_generate(
        input={"text": prompt_text},
        retrieveAndGenerateConfiguration={
            "knowledgeBaseConfiguration": {
                "knowledgeBaseId": kb_id,
                "modelArn": MODEL_ARN,
                "retrievalConfiguration": {
                    "vectorSearchConfiguration": {
                        "overrideSearchType": QNA_SEARCH_TYPE,
                            "numberOfResults": 5, # TODO(@kvcn639): Make result limit configurable
                            **({
                                "filter": filter_config
                            } if filter_config else {})
                    },
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
    """Same as retrieve_and_generate, but limits the search to specific files only.

    Args:
        query (str): The user question.
        kb_id (str): The knowledge base ID.
        knowledge_base_folder (str): S3 prefix path for the documents.
        files (Sequence[str]): List of file names to filter retrieval on.
        session_id (Optional[str]): Optional session identifier.

    Returns:
        dict: Retrieved and generated output limited to selected files.
    """
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
                            },
                        },
                        "numberOfResults": 3,  # TODO restrict the number of docs to 1 when prioritized document
                    },
                },
                "generationConfiguration": _build_gen_cfg(),
            },
            "type": "KNOWLEDGE_BASE",
        },
        **({"sessionId": session_id} if session_id else {}),
    )
