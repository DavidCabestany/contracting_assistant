# services/qna.py
"""High-level Bedrock Q&A helpers.

This module handles prompt formatting, configuration building, and calls to
Bedrock's retrieve-and-generate APIs with optional guardrails and source filtering.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Sequence

from utils import extract_file_locations

from .clients import (
    bedrock_agent_runtime,
    bedrock_client,
    s3_client,
)
from .constants import (
    BUCKET_CONTAINER,
    GUARDRAIL_ID,
    GUARDRAIL_VERSION_ID,
    HIGH_PRIORITY_QUERIES,
    IRRELEVANT,
    MODEL_ARN,
    MODEL_ID,
    PRIOR_DOC,
    QNA_MAX_TOKENS_VALUE,
    QNA_SEARCH_TYPE,
)
from .storage import add_prefix
from .templates import retrieve_template

logger = logging.getLogger(__name__)

QNA_MAX_RESULTS = 3


def load_known_files_from_s3() -> dict[str, str]:
    """Build a filename-to-kb_path mapping from S3 buckets."""
    bucket = "azcdi-us-ops-procure-ds-dev"
    kb_paths = ["general", "privacy", "alexion"]
    known_files = {}

    for kb_path in kb_paths:
        prefix = f"{kb_path}/"
        paginator = s3_client.get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=bucket, Prefix=prefix)

        for page in pages:
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if key.endswith(".pdf"):
                    file_name = key.split("/")[-1]
                    known_files[file_name] = kb_path

    return known_files


def auto_attach_files(user_txt: str, kb_path: str) -> list[tuple[str, str]]:
    """Auto-match files from S3 based on query contents and restrict to given kb_path."""
    known_files = load_known_files_from_s3()
    query_lc = user_txt.lower()
    start_end_query = query_lc[:50] + query_lc[-50:]
    matched_files = []

    for file_name, file_kb_path in known_files.items():
        # Only consider files from the active kb_path
        if file_kb_path != kb_path:
            continue

        base_name = file_name.lower().replace(".pdf", "")
        words = re.findall(r"\b\w+\b", base_name)

        for i in range(len(words) - 1):
            phrase = " ".join(words[i : i + 2])
            if phrase in start_end_query:
                matched_files.append(file_name)
                break

    return matched_files


def is_invalid_response(text: str) -> bool:
    """Check whether the response text is considered invalid or irrelevant."""
    lowered = text.lower().strip()
    # Regex for model refusals
    refusal_regex = re.compile(
        r"(i'?m sorry|i apologise|i apologize|i can(\'|’)t help you with (this )?request)",
        re.IGNORECASE,
    )
    return (
        not lowered
        or lowered in {"sorry, i am unable to assist you with this request."}
        or "unable to assist" in lowered
        or "i cannot help" in lowered
        or "no information available" in lowered
        or "i'm not sure" in lowered
        or IRRELEVANT in lowered
        or refusal_regex.search(lowered)  # <- add this!
    )


def is_high_priority_query(query: str, category: str) -> bool:
    """Check if teh initial user query is part of the standard queries."""
    normalized_query = query.lower().strip()
    normalized_category = category.strip().title()
    return normalized_query in HIGH_PRIORITY_QUERIES.get(
        normalized_category, set()
    )


def detect_prior_doc_from_query(query: str) -> str:
    """Detect a relevant prior document from the user query."""
    DOCUMENT_TOPICS = [
        {
            "file": [
                "Playbook_Data Protection Appendix – Controller to Dual Role Processor.pdf"
            ],
            "keywords": ["supplier", "controller", "processor"],
        },
        {
            "file": [
                "Playbook_Data Protection Appendix - AZ Controller to Supplier Processor.pdf"
            ],
            "keywords": ["dpa"],
        },
        {
            "file": [
                "Data Protection Appendix - Sharing Anonymised Data.pdf",
                "Data Protection Appendix – Receiving Anonymised Data.pdf",
                "Playbook_Data Protection Appendix – receiving Anonymised Data.pdf",
                "Playbook_Data Protection Appendix – sharing Anonymised Data.pdf",
            ],
            "keywords": ["personal", "anonymized"],
        },
        {
            "file": [
                "Data Protection Appendix - Sharing Anonymised Data.pdf",
                "Data Protection Appendix – Receiving Anonymised Data.pdf",
                "Playbook_Data Protection Appendix – receiving Anonymised Data.pdf",
                "Playbook_Data Protection Appendix – sharing Anonymised Data.pdf",
            ],
            "keywords": ["personal", "anonymised"],
        },
    ]
    query_lower = query.lower()
    for doc in DOCUMENT_TOPICS:
        if all(k in query_lower for k in doc["keywords"]):
            return doc["file"]
    return PRIOR_DOC


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

    style_prompt = """
        When generating your response, maintain a clear, professional, and direct tone. Strictly avoid the comenting.

        • Don't apologise. Don't comment about user. don't greet. don't praise.
        • avoid any kind of disclaimers (e.g., "As previously mentioned", "To clarify again", etc.)
        • Don't make open-ended invitations or offers for further questions (e.g., "Let me know if you need more", "Feel free to ask", etc.)
        • avoid irrelevant fillers — stick to concise and informative language.

        JUST GIVE THE REQUESTED INFO.

        Only provide the information requested. Do not include unnecessary commentary or emotional framing.
        The question: """
    body = json.dumps(
        {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": QNA_MAX_TOKENS_VALUE,
            "messages": [
                {"role": "user", "content": style_prompt + formatted_prompt}
            ],
        },
    )
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
                "temperature": 0,
                "topP": 1.0,
            },
        },
    }


def retrieve_file_chunks(
    kb_id: str,
    documents: list[str],
    kb_path: str,
    query: str,
) -> dict[str, str]:
    """Retrieve text specific documents.

    Args:
        kb_id (str): The Bedrock KB ID.
        documents (list[str]): List of filenames in S3.
        kb_path (str): Folder where the docs are stored.
        query (str): Initial user question for context.

    Returns:
        dict[str, str]: filename → extracted full text from matched chunks.
    """
    from .constants import BUCKET_CONTAINER, MODEL_ARN

    file_contents = {}
    logger.info("starting the retrieval")
    logger.info("✅ query: %s", query)
    for doc in documents:
        s3_uri = f"s3://{BUCKET_CONTAINER}/{kb_path}/{doc}"
        logger.info("▶ Retrieving content from: %s", s3_uri)

        request_body = {
            "input": {"text": query},
            "retrieveAndGenerateConfiguration": {
                "knowledgeBaseConfiguration": {
                    "knowledgeBaseId": kb_id,
                    "modelArn": MODEL_ARN,
                    "retrievalConfiguration": {
                        "vectorSearchConfiguration": {
                            "overrideSearchType": QNA_SEARCH_TYPE,
                            "numberOfResults": QNA_MAX_RESULTS,
                            "filter": {
                                "equals": {
                                    "key": "x-amz-bedrock-kb-source-uri",
                                    "value": s3_uri,
                                }
                            },
                        }
                    },
                    "generationConfiguration": _build_gen_cfg(),
                },
                "type": "KNOWLEDGE_BASE",
            },
        }
        try:
            response = bedrock_agent_runtime.retrieve_and_generate(
                **request_body
            )
            chunks = response.get("citations", [])
            file_text = "\n\n".join(
                c["generatedResponsePart"]["textResponsePart"]["text"]
                for c in chunks
                if "generatedResponsePart" in c
                and "textResponsePart" in c["generatedResponsePart"]
            )
            file_contents[doc] = file_text.strip()
            logger.info("✅ File contents: %s", file_contents)
            logger.info("✅ File retrieved: %s", doc)
        except Exception as e:
            logger.warning("❌ Failed to retrieve %s: %s", doc, e)
            file_contents[doc] = f"[Error: {e}]"

    return file_contents


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


def retrieve_citations_from_query(
    query: str,
    kb_id: str,
    kb_path: str = "general",  # default as needed
    files: list[str] | None = None,
    session_id: str | None = None,
) -> list[dict]:
    """Run Bedrock retrieve-and-generate and extract only citations.

    Args:
        query (str): User query string.
        kb_id (str): Knowledge Base ID.
        kb_path (str): Folder/prefix path in S3 for documents.
        files (list[str] | None): Optional list of file names to restrict retrieval.
        session_id (str | None): Optional session identifier.

    Returns:
        list[dict]: List of citations as dicts (filePath, pageNumber, fileName).
    """
    if files:
        resp = retrieve_and_generate_prioritized_doc(
            query=query,
            kb_id=kb_id,
            knowledge_base_folder=kb_path,
            files=files,
            session_id=session_id,
        )
    else:
        resp = retrieve_and_generate(
            query=query,
            kb_id=kb_id,
            session_id=session_id,
            kb_path=kb_path,
        )

    citations = extract_file_locations(resp)
    return citations
