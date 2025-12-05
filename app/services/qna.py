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
    DOCUMENT_TOPICS,
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

QNA_MAX_RESULTS = 14


def load_known_files_from_s3() -> dict[str, str]:
    """Build a filename-to-kb_path mapping from S3 buckets."""
    bucket = "azcdi-us-ops-procure-ds-dev"
    kb_paths = ["general", "privacy", "rnd"]  # add "alexion" if needed
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


def auto_attach_files_gxp_citation(user_txt: str, kb_path: str) -> list[str]:
    """Return all compliance files clearly needed for GxP scenarios."""
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

        for i in range(len(words) - 2):
            phrase = " ".join(words[i : i + 3])
            if phrase in start_end_query:
                matched_files.append(file_name)
                break

    # FORCE-INJECT GCP if clinical trial keywords are detected
    gcp_keywords = [
        "publication terms",
        "standard publication",
        "clinical trial",
        "clinical trials",
        "CRO",
        "CROS",
        "contract research organization",
        "service provider",
        "service providers",
        "gcp",
    ]
    gcp_files = [
        "Good Clinical Practice Module - Playbook.pdf",
        "CRO-Clinical Study Agreement AZ Contractual Principles.pdf",
    ]

    def keyword_in_text(keyword: str, text: str) -> bool:
        if keyword.lower() in {"cro", "cros", "gcp"}:
            pattern = rf"\b{re.escape(keyword)}\b"
            return bool(
                re.search(pattern, text, flags=re.IGNORECASE | re.ASCII)
            )
        return keyword.lower() in text.lower()

    if any(keyword_in_text(keyword, query_lc) for keyword in gcp_keywords):
        for gcp_file in gcp_files:
            if gcp_file in known_files and known_files[gcp_file] == kb_path:
                if gcp_file not in matched_files:
                    matched_files.append(gcp_file)

    # FORCE-INJECT GDP if distribution keywords are detected
    gdp_keywords = [
        "good distribution practice",
        "GDP",
        "gdp",
    ]
    gdp_file = "GLP GMP GDP Module - Playbook.pdf"
    if any(keyword in query_lc for keyword in gdp_keywords):
        if gdp_file in known_files and known_files[gdp_file] == kb_path:
            if gdp_file not in matched_files:
                matched_files.append(gdp_file)
    return list(matched_files)


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
        or refusal_regex.search(lowered)
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

    # GCP-specific LLM guidance if CRO/service providers mentioned
    if any(
        term in user_query.lower()
        for term in [
            "cro",
            "cros",
            "contract research organization",
            "service provider",
            "service providers",
            "clinical trial",
            "clinical trials",
        ]
    ):
        tmpl += (
            "\nIf the Good Clinical Practice (GCP) module is relevant based on the user query, "
            "please cite it appropriately and ensure a detailed, context-rich answer is generated from that module."
        )
    # GDP clarification
    if "gdp" in user_query.lower():
        tmpl += (
            "\n\n⚠️ IMPORTANT:\n"
            "**In this domain, 'GDP' refers exclusively to Good Distribution Practice (not Gross Domestic Product).**\n"
            "Please ignore any macroeconomic definitions of GDP. This question relates to pharmaceutical distribution compliance standards.\n"
            "Ensure the answer is aligned with the GDP Module (Good Distribution Practice) content and regulatory context.\n"
        )

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
                # "topP": 1.0,
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
    logger.info(" query: %s", query)
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
            # Sort by relevanceScore if present, descending
            logger.info("Retrieved %d chunks for %s", len(chunks), doc, "the chunks are", chunks)
            sorted_chunks = sorted(
            chunks,
            key=lambda c: c.get("relevanceScore", 0),
            reverse=True,
            )
            # Limit to top 3 relevant chunks
            top_chunks = sorted_chunks[:3]
            file_text = "\n\n".join(
            c["generatedResponsePart"]["textResponsePart"]["text"]
            for c in top_chunks
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

    # Auto-attach trigger if no doc passed
    if not document and kb_path:
        matched = auto_attach_files(query, kb_path)
        logger.info(f"Auto-attached files from query: {matched}")

        if matched:
            return retrieve_and_generate_prioritized_doc(
                query=query,
                kb_id=kb_id,
                knowledge_base_folder=kb_path,
                files=matched,
                session_id=session_id,
            )

    # Fallback: regular full-KB search
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
        if not response or not isinstance(response, dict):
            raise ValueError("Malformed response from Bedrock")
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
        if not response or not isinstance(response, dict):
            raise ValueError("Empty or invalid Bedrock response.")
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


# ## TIA Clarification
# # Triggers and Clarification Questions
# TIA_PRIMARY_CLARIFICATION_TRIGGERS = {
#     "TIA",
#     "Tia assessment",
#     "tia",
#     "Transfer Impact Assessment",
#     "Exhibit",
#     "exhibit",
#     "Agreement",
#     "agreement",
# }
# TIA_SECONDARY_CONTEXTUAL_KEYWORDS = {
#     "vendor",
#     "institution",
#     "location",
#     "database",
#     "clinical trial",
#     "clinical trials",
#     "medical communication",
#     "Medical Communications",
#     "publications",
#     "UK",
#     "EU",
# }

# # -------------------------
# # CLARIFICATION LOGIC
# # -------------------------


# def tia_trigger_initial_clarification(query: str) -> bool:
#     """Determines if the user query contains any initial trigger keywords requiring clarification.

#     Args:
#         query (str): The user's input query string.

#     Returns:
#         bool: True if any initial trigger keywords from the question map are found in the query,
#               indicating that clarification questions should be asked; False otherwise.
#     """
#     q = query.lower()
#     primary_hits = sum(
#         1
#         for word in map(str.lower, TIA_PRIMARY_CLARIFICATION_TRIGGERS)
#         if word in q
#     )
#     secondary_hits = sum(
#         1
#         for word in map(str.lower, TIA_SECONDARY_CONTEXTUAL_KEYWORDS)
#         if word in q
#     )
#     logger.info(
#         f"[Trigger Check] Primary hits: {primary_hits}, Secondary hits: {secondary_hits}"
#     )
#     return primary_hits >= 2 and secondary_hits >= 2


# def detect_present_keywords_for_tia(text: str) -> set[str]:
#     """Detects which predefined keyword categories are present in the input text.

#     Args:
#         text (str): The input string to analyze.

#     Returns:
#         set[str]: A set of keys from FOLLOWUP_KEYWORDS that were detected in the text.
#     """
#     text = text.lower()
#     found = set()
#     for key, keywords in TIA_FOLLOWUP_KEYWORDS.items():
#         if any(kw in text for kw in keywords):
#             found.add(key)
#     logger.info(f"[Keyword Detection] Found fields: {found}")
#     return found


# def detect_missing_keywords_for_tia(context_text: str) -> list[str]:
#     """Identifies which required keyword categories are missing from the context text.

#     Args:
#         context_text (str): The text containing accumulated user input and chat context.

#     Returns:
#         list[str]: A list of questions (from QUESTION_MAP) that correspond to missing keyword categories.
#     """
#     context_lc = context_text.lower()
#     missing = []
#     for key, words in TIA_FOLLOWUP_KEYWORDS.items():
#         if key not in QUESTION_MAP:
#             continue  # ← avoid KeyError by skipping unmapped keys
#         if not any(word in context_lc for word in words):
#             missing.append(QUESTION_MAP[key])
#     logger.info(f"[Missing Keywords] → {missing}")
#     return missing


# def fallback_final_answer_for_tia(context_text: str) -> str:
#     """Generates a final fallback answer based on keywords found in the context text.

#     If the context contains sufficient detail about data transfer, returns a definitive
#     answer about the need for a Transfer Impact Assessment (TIA). Otherwise, requests
#     additional information.

#     Args:
#         context_text (str): The full context accumulated from the chat.

#     Returns:
#         str: A final answer or a request for additional clarification.
#     """
#     context = context_text.lower()
#     if all(
#         term in context
#         for term in ["clinical", "patient", "vendor", "on our behalf"]
#     ):
#         if "outside" in context or "international" in context:
#             return "Yes, a Transfer Impact Assessment (TIA) is required because data is being transferred outside the UK or EU."
#         return (
#             "A TIA is not required as long as data stays within the UK or EU. "
#             "Ensure a Data Processing Agreement is still in place."
#         )
#     return (
#         "To answer your question correctly, I need more information:\n"
#         + "\n".join(
#             "- " + q for q in detect_missing_keywords_for_tia(context)[:2]
#         )
#     )


# session_context_memory = defaultdict(set)
# REQUIRED_KEYS = set(TIA_FOLLOWUP_KEYWORDS.keys())


# def build_clarification_prompt_for_tia(
#     all_user_msgs: list[str], all_bot_msgs: list[str], session_id: str
# ) -> str:
#     """Builds a prompt for the LLM to process based on accumulated user and assistant interactions.

#     Args:
#         all_user_msgs (list[str]): A list of all user messages in the session.
#         all_bot_msgs (list[str]): A list of all bot messages in the session.
#         session_id (str): The unique session identifier.

#     Returns:
#         str: A formatted prompt detailing context and instructions for the LLM.
#     """
#     # Construct the history block for the entire conversation
#     history_block = "\n".join(all_user_msgs + all_bot_msgs)

#     # Update session context with detected keywords
#     current_context = session_context_memory[session_id]
#     detected_keywords = detect_present_keywords_for_tia(history_block)
#     current_context.update(detected_keywords)

#     # Determine missing keywords for the current context
#     missing_questions = detect_missing_keywords_for_tia(history_block)

#     # Compile the LLM prompt with context and instructions
#     prompt = f"""
#     You are a Legal/Contract Assistant specializing in Transfer Impact Assessments (TIAs).

#     Below is the full context of the discussion between the user and assistant. Your primary goal is to synthesize this context
#     to determine if further clarification is needed or if a final response can be provided.

#     Context:
#     {history_block}

#     Instructions:
#     - Use the accumulated session context to inform your response.
#     - Avoid asking any questions already answered in previous interactions.
#     - If all of the following are clearly answered:
#       * Type of data
#       * Flow of data (shared/received)
#       * Role of vendor
#       * Purpose of processing
#       * Vendor identity
#       * Location of data
#     Then return: FINAL_RESPONSE_REQUIRED.

#     - If some aspects are still unclear, ask 1–2 missing clarification questions from: {missing_questions}.
#     - Ensure the conversation is cohesive and contextually coherent.

#     Your response should seamlessly continue the current conversation without unnecessary repetition.
#     """.strip()

#     return prompt


# def tia_followup_user_query(
#     user_query: str, tx_count: int, chat_history: list[str], session_id: str
# ) -> str:
#     """Processes a user query in the context of a TIA-related session.

#     This function manages user interactions by processing queries related to
#     Transfer Impact Assessments (TIAs). It determines whether additional
#     clarification is needed or if a final response can be issued, based on
#     session-specific context and past interactions.

#     Args:
#         user_query: The current query provided by the user as a string.
#         tx_count: An integer representing the number of interactions in the
#             current session.
#         chat_history: A list of strings representing prior messages exchanged
#             between the user and the assistant in the session.
#         session_id: A string uniquely identifying the session for context tracking.

#     Returns:
#         A string containing either a request for additional clarification or a
#         final response to the user's query, depending on the sufficiency of
#         the gathered information.
#     """
#     logger.info(f"[Follow-up Detected] TX={tx_count}, Session={session_id}")

#     all_user_msgs = [
#         msg for i, msg in enumerate(chat_history) if i % 2 == 0
#     ] + [user_query]
#     all_bot_msgs = [msg for i, msg in enumerate(chat_history) if i % 2 == 1]

#     context_block = "\n".join(all_user_msgs + all_bot_msgs)

#     detected = detect_present_keywords_for_tia(context_block)
#     session_context_memory[session_id].update(detected)

#     missing = detect_missing_keywords_for_tia(context_block)

#     if tx_count == 0 and tia_trigger_initial_clarification(user_query):
#         logger.info("]Trigger Fired] Asking for initial clarification set")
#         if len(missing) == 0:
#             return FINAL_RESPONSE_REQUIRED
#         return (
#             "To answer your question correctly, I need more information:\n"
#             + "\n".join(f"- {q}" for q in missing[:2])
#         )

#     if tx_count < 3:
#         if not missing:
#             logger.info("[Clarification Complete] All required fields found")
#             return FINAL_RESPONSE_REQUIRED
#         logger.info(f"[Follow-up] Still missing fields → {missing}")
#         return (
#             "To answer your question correctly, I need more information:\n"
#             + "\n".join(f"- {q}" for q in missing[:2])
#         )

#     logger.info("[TX >= 3] Fallback final answer logic triggered")
#     return fallback_final_answer_for_tia(context_block)
