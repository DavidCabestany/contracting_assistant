"""Routes and logic for handling user QnA requests via chat interface."""

import json
import logging
from collections.abc import Sequence
from typing import Optional

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


def generate_answer_with_context(formatted_prompt: str) -> dict:
    """Perform a basic prompt completion call using Bedrock's chat model.

    Args:
        formatted_prompt (str): The prompt text to send to the model.

    Returns:
        dict: Parsed JSON result from Bedrock's model invocation.
    """
    logger.info(
        "ENTER ▶ generate_answer_with_context(formatted_prompt=%.100s)",
        formatted_prompt,
    )
    # Step 1: Build request body
    logger.info("[TRACE] Step 1: Building request body...")
    body_dict = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": QNA_MAX_TOKENS_VALUE,
        "messages": [{"role": "user", "content": formatted_prompt}],
    }
    body = json.dumps(body_dict)
    logger.info("[TRACE] Built body: %.200s", body)

    # Step 2: Invoke model
    logger.info("[TRACE] Step 2: Invoking Bedrock model...")
    try:
        response = bedrock_client.invoke_model(
            body=body,
            modelId=MODEL_ID,
            accept="application/json",
            contentType="application/json",
            guardrailIdentifier=GUARDRAIL_ID,
            guardrailVersion=GUARDRAIL_VERSION_ID,
        )
        logger.info("[TRACE] Bedrock invocation succeeded: %s", response)
    except Exception as e:
        logger.info("[ERROR] Bedrock invocation failed: %s", e)
        raise

    # Step 3: Decode response
    logger.info("[TRACE] Step 3: Decoding response...")
    try:
        raw = response["body"].read().decode()
        logger.info("[TRACE] Raw response: %.200s", raw)
        result = json.loads(raw)
        logger.info("[TRACE] Parsed JSON result successfully.")
        logger.info(
            "EXIT  ◀ generate_answer_with_context -> %s",
            {k: result.get(k) for k in ("content",)},
        )
        return result
    except Exception as e:
        logger.info("[ERROR] Response parsing failed: %s", e)
        raise


def _render_prompt(user_query: str, base_prompt: Optional[str] = None) -> str:
    """Render a complete prompt string using a base template and user input.

    Args:
        user_query (str): The original user question.
        base_prompt (Optional[str]): A custom template, if provided.

    Returns:
        str: A complete prompt ready for LLM ingestion.
    """
    logger.info("ENTER ▶ _render_prompt(user_query=%.100s)", user_query)
    tmpl = (
        base_prompt
        if base_prompt is not None
        else retrieve_template(user_query)
    )
    logger.info("[TRACE] Template fetched: %.200s", str(tmpl))
    tmpl_str = str(tmpl)
    tmpl_str += "\n\n%ADDITIONAL INSTRUCTIONS%:\nPlease treat suppliers and vendors as aliases in the chunks."
    tmpl_str += f"\n\n%USER QUERY:\n{user_query}\n"
    logger.info("EXIT  ◀ _render_prompt -> %.200s", tmpl_str)
    return tmpl_str


def _build_gen_cfg() -> dict:
    """Build the generation configuration including temperature, top-p, and guardrails.

    Returns:
        dict: Configuration block for generation.
    """
    logger.info("ENTER ▶ _build_gen_cfg()")
    cfg = {
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
    logger.info("EXIT  ◀ _build_gen_cfg -> %s", cfg)
    return cfg


def retrieve_and_generate(
    query: str,
    kb_id: str,
    *,
    session_id: str,
    kb_path: str,
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
    logger.info(
        "ENTER ▶ retrieve_and_generate(query=%.100s, kb_id=%s, session_id=%s, kb_path=%s)",
        query,
        kb_id,
        session_id,
        kb_path,
    )
    # Render prompt
    prompt_text = _render_prompt(query)
    logger.info("[TRACE] prompt_text=%.200s", prompt_text)

    # Build filter_config
    filter_config = {}
    query_lower = query.lower()
    logger.info("[TRACE] query_lower=%.100s", query_lower)

    mapping = {
        "Could you please advise how to solve the situation when Supplier can be a Controller and a Processor": "Playbook_Data Protection Appendix – Controller to Dual Role Processor.pdf"
    }
    for keywords, document in mapping.items():
        if all(keyword.lower() in query_lower for keyword in keywords.split()):
            path = f"s3://{BUCKET_CONTAINER}/{kb_path}/{document}"
            filter_config = {
                "equals": {"key": "x-amz-bedrock-kb-source-uri", "value": path}
            }
            logger.info("[TRACE] filter_config set to %s", filter_config)
            break

    # Call retrieve_and_generate
    logger.info(
        "[TRACE] Calling bedrock_agent_runtime.retrieve_and_generate..."
    )
    result = bedrock_agent_runtime.retrieve_and_generate(
        input={"text": prompt_text},
        retrieveAndGenerateConfiguration={
            "knowledgeBaseConfiguration": {
                "knowledgeBaseId": kb_id,
                "modelArn": MODEL_ARN,
                "retrievalConfiguration": {
                    "vectorSearchConfiguration": {
                        "overrideSearchType": QNA_SEARCH_TYPE,
                        "numberOfResults": 3,
                        **({"filter": filter_config} if filter_config else {}),
                    },
                },
                "generationConfiguration": _build_gen_cfg(),
            },
            "type": "KNOWLEDGE_BASE",
        },
        **({"sessionId": session_id} if session_id else {}),
    )
    logger.info("EXIT  ◀ retrieve_and_generate -> %s", result)
    return result


def retrieve_and_generate_prioritized_doc(
    query: str,
    kb_id: str,
    knowledge_base_folder: str,
    files: Sequence[str],
    *,
    session_id: str,
) -> dict:
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
    logger.info(
        "ENTER ▶ retrieve_and_generate_prioritized_doc(query=%.100s, kb_id=%s, files=%s, session_id=%s)",
        query,
        kb_id,
        files,
        session_id,
    )
    prompt_text = _render_prompt(query)
    logger.info("[TRACE] prompt_text=%.200s", prompt_text)

    allowed_paths = add_prefix(files, BUCKET_CONTAINER, knowledge_base_folder)
    logger.info("[TRACE] allowed_paths=%s", allowed_paths)

    result = bedrock_agent_runtime.retrieve_and_generate(
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
                        "numberOfResults": 3,
                    },
                },
                "generationConfiguration": _build_gen_cfg(),
            },
            "type": "KNOWLEDGE_BASE",
        },
        **({"sessionId": session_id} if session_id else {}),
    )
    logger.info("EXIT  ◀ retrieve_and_generate_prioritized_doc -> %s", result)
    return result
