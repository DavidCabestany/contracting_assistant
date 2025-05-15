# services/qna.py
"""High-level Bedrock Q&A helpers.

This module handles prompt formatting, configuration building, and calls to
Bedrock's retrieve-and-generate APIs with optional guardrails and source filtering.
"""

from __future__ import annotations

import json
import logging
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

logger = logging.getLogger(__name__)


QNA_MAX_RESULTS = 3


def generate_answer_with_context(formatted_prompt: str) -> dict:
    """Perform a basic prompt completion call using Bedrock's chat model.

    Args:
        formatted_prompt (str): The prompt text to send to the model.

    Returns:
        dict: Parsed JSON result from Bedrock's model invocation.
    """
    logger.info(
        "[Checkpoint] Step 1: Building request body for Bedrock model..."
    )
    body = json.dumps(
        {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": QNA_MAX_TOKENS_VALUE,
            "messages": [{"role": "user", "content": formatted_prompt}],
        },
    )
    logger.info(f"[Checkpoint] Request body built: {body}")

    logger.info("[Checkpoint] Step 2: Invoking Bedrock model...")
    try:
        response = bedrock_client.invoke_model(
            body=body,
            modelId=MODEL_ID,
            accept="application/json",
            contentType="application/json",
            guardrailIdentifier=GUARDRAIL_ID,
            guardrailVersion=GUARDRAIL_VERSION_ID,
        )
        logger.info("[Checkpoint] Bedrock model invoked successfully.")
    except Exception as e:
        logger.info(
            f"[Error] Failed to invoke Bedrock model: {str(e)}",
        )
        raise

    logger.info("[Checkpoint] Step 3: Reading and decoding response...")
    try:
        raw_response = response["body"].read().decode()
        logger.info(
            f"[Checkpoint] Raw response: {raw_response} ",
        )
        result = json.loads(raw_response)
        logger.info("[Checkpoint] JSON parsed successfully.")
        return result
    except Exception as e:
        logger.info(
            f"[Error] Failed to decode or parse response: {str(e)}",
        )
        raise


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


# def retrieve_and_generate(
#     query: str,
#     kb_id: str,
#     *,
#     document: str | None = None,
#     session_id: str | None = None,
#     kb_path: str | None = None,
# ):
#     """Run Bedrock's retrieve-and-generate pipeline using the general KB.

#     Args:
#         query: The user query text.
#         kb_id: Knowledge base identifier.
#         session_id: Optional Bedrock session ID.
#         kb_path: Knowledge base folder name.
#         document: Optional specific document to prioritize in the search.

#     Returns:
#         dict: Retrieved and generated output from Bedrock.
#     """
#     # Define query to document mapping
#     # query_reference_document_mapping = {
#     #     "Could you please advise how to solve the situation when Supplier can be a Controller and a Processor": "Playbook_Data Protection Appendix – Controller to Dual Role Processor.pdf"
#     # }
#     # s3://azcdi-us-ops-procure-ds-dev/privacy/Playbook_Data Protection Appendix – Controller to Dual Role Processor.pdf
#     # s3://azcdi-us-ops-procure-ds-dev/privacy/Playbook_Data Protection Appendix - Controller to Dual Role Processor.pdf
#     prompt_text = _render_prompt(query)

#     # Determine document filter based on query content
#     filter_config = {}
#     # query_lower = query.lower()

#     # Find matching document based on keywords
#     # for keywords, document in query_reference_document_mapping.items():
#     #     if all(keyword in query_lower for keyword in keywords.split()):
#     filter_config = {
#         "equals": {
#             "key": "x-amz-bedrock-kb-source-uri",
#             "value": f"s3://{BUCKET_CONTAINER}/{kb_path}/{document}",
#         }
#     }
#     # break

#     return bedrock_agent_runtime.retrieve_and_generate(
#         input={"text": prompt_text},
#         retrieveAndGenerateConfiguration={
#             "knowledgeBaseConfiguration": {
#                 "knowledgeBaseId": kb_id,
#                 "modelArn": MODEL_ARN,
#                 "retrievalConfiguration": {
#                     "vectorSearchConfiguration": {
#                         "overrideSearchType": QNA_SEARCH_TYPE,
#                         "numberOfResults": QNA_MAX_RESULTS,
#                         **({"filter": filter_config} if filter_config else {}),
#                     },
#                 },
#                 "generationConfiguration": _build_gen_cfg(),
#             },
#             "type": "KNOWLEDGE_BASE",
#         },
#         **({"sessionId": session_id} if session_id else {}),
#     )


def retrieve_and_generate(
    query: str,
    kb_id: str,
    *,
    document: str | None = None,
    session_id: str | None = None,
    kb_path: str | None = None,
):
    """Run Bedrock's retrieve-and-generate pipeline using the general KB."""
    logger.info("ENTER ▶ retrieve_and_generate")

    prompt_text = _render_prompt(query)
    logger.debug("Prompt: %.200s", prompt_text.replace("\n", " "))
    logger.debug(
        "KB ID: %s | kb_path: %s | document: %s | session_id: %s",
        kb_id,
        kb_path,
        document,
        session_id,
    )

    filter_config = {}
    if document and kb_path:
        s3_uri = f"s3://{BUCKET_CONTAINER}/{kb_path}/{document}"
        filter_config = {
            "equals": {
                "key": "x-amz-bedrock-kb-source-uri",
                "value": s3_uri,
            }
        }
        logger.info("Applying document filter on: %s", s3_uri)
    else:
        logger.info("No specific document filter applied — full KB search")

    request_body = {
        "input": {"text": prompt_text},
        "retrieveAndGenerateConfiguration": {
            "knowledgeBaseConfiguration": {
                "knowledgeBaseId": kb_id,
                "modelArn": MODEL_ARN,
                "retrievalConfiguration": {
                    "vectorSearchConfiguration": {
                        "overrideSearchType": QNA_SEARCH_TYPE,
                        "numberOfResults": QNA_MAX_RESULTS,
                        **({"filter": filter_config} if filter_config else {}),
                    },
                },
                "generationConfiguration": _build_gen_cfg(),
            },
            "type": "KNOWLEDGE_BASE",
        },
        **({"sessionId": session_id} if session_id else {}),
    }

    logger.debug("Request payload: %s", json.dumps(request_body, indent=2))

    try:
        response = bedrock_agent_runtime.retrieve_and_generate(**request_body)
        logger.info("EXIT ▶ retrieve_and_generate — success")
        logger.debug("Bedrock response: %s", json.dumps(response, indent=2))
        return response
    except Exception:
        logger.exception("Bedrock retrieve_and_generate FAILED")
        raise


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
    logger.info("ENTER ▶ retrieve_and_generate_prioritized_doc")
    logger.info("Step 1 ▶ Building prompt for query: %.100s", query)
    prompt_text = _render_prompt(query)
    logger.info(
        "Step 2 ▶ Prompt built (length=%d): %.200s",
        len(prompt_text),
        prompt_text.replace("\n", " "),
    )

    logger.info(
        "Step 3 ▶ Resolving allowed file paths from input files: %s", files
    )
    allowed_paths = add_prefix(files, BUCKET_CONTAINER, knowledge_base_folder)
    logger.info("Step 4 ▶ Allowed S3 paths: %s", allowed_paths)

    request_body = {
        "input": {"text": prompt_text},
        "retrieveAndGenerateConfiguration": {
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
                        "numberOfResults": QNA_MAX_RESULTS,
                    },
                },
                "generationConfiguration": _build_gen_cfg(),
            },
            "type": "KNOWLEDGE_BASE",
        },
    }

    if session_id:
        request_body["sessionId"] = session_id
        logger.info("Step 5 ▶ Using existing session_id: %s", session_id)
    else:
        logger.info("Step 5 ▶ No session_id provided — starting new session")

    logger.info("Step 6 ▶ Final request payload ready for Bedrock call.")
    try:
        response = bedrock_agent_runtime.retrieve_and_generate(**request_body)
        logger.info(
            "EXIT  ◀ retrieve_and_generate_prioritized_doc — SUCCESSFUL call"
        )
        return response
    except Exception as e:
        logger.error(
            "EXIT  ◀ retrieve_and_generate_prioritized_doc — FAILED call: %s",
            str(e),
        )
        raise
