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


def auto_attach_files(user_txt: str, kb_path: str) -> list[str]:
    """Auto-match files from S3 based on query contents and restrict to given kb_path."""
    known_files = load_known_files_from_s3()
    query_lc = user_txt.lower()
    start_end_query = query_lc[:50] + query_lc[-50:]
    matched_files = set()

    # Existing logic — match filenames
    for file_name, file_kb_path in known_files.items():
        if file_kb_path != kb_path:
            continue

        base_name = file_name.lower().replace(".pdf", "")
        words = re.findall(r"\b\w+\b", base_name)

        for i in range(len(words) - 1):
            phrase = " ".join(words[i : i + 2])
            if phrase in start_end_query:
                matched_files.add(file_name)
                break

    # ✅ FORCE-INJECT GCP if clinical trial keywords are detected
    gcp_keywords = [
        "clinical trial",
        "clinical trials",
        "cro",
        "cros",
        "contract research organization",
        "service provider",
        "service providers",
        "gcp",
    ]
    gcp_file = "Good Clinical Practice Module - Playbook.pdf"
    if any(keyword in query_lc for keyword in gcp_keywords):
        if gcp_file in known_files and known_files[gcp_file] == kb_path:
            if gcp_file not in matched_files:
                matched_files.append(gcp_file)

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

    # ✅ GCP-specific LLM guidance if CRO/service providers mentioned
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


## TIA Clarification
# Triggers and Clarification Questions
PRIMARY_CLARIFICATION_TRIGGERS = {
    "TIA",
    "Tia assessment",
    "tia",
    "Transfer Impact Assessment",
    "Exhibit",
    "exhibit",
    "Agreement",
    "agreement",
}
SECONDARY_CONTEXTUAL_KEYWORDS = {
    "vendor",
    "institution",
    "location",
    "database",
    "clinical trial",
    "clinical trials",
    "medical communication",
    "Medical Communications",
    "publications",
    "UK",
    "EU",
}


# -------------------------
# CLARIFICATION LOGIC
# -------------------------

INITIAL_FIXED_QUESTIONS = [
    "What type of data is being processed?",
    "What is the direction of the data flow (are we sharing data with the vendor or are we receiving data from the vendor)?",
    "If we share data, will the vendor process it on our behalf or for its own purposes?",
    "If we receive data, do we receive it for our own purposes?",
]

FOLLOWUP_KEYWORDS = {
    "type of data": ["patient", "clinical", "trial", "sensitive", "health"],
    "data flow": ["share", "receive", "send", "transfer"],
    "vendor role": ["on our behalf", "own purpose", "vendor process"],
    "purpose": ["r&d", "objective", "purpose", "communication"],
    "vendor identity": ["vendor", "institution"],
    "location": ["uk", "eu", "outside", "location", "international"],
}

QUESTION_MAP = {
    "type of data": INITIAL_FIXED_QUESTIONS[0],
    "data flow": INITIAL_FIXED_QUESTIONS[1],
    "vendor role": INITIAL_FIXED_QUESTIONS[2],
    "receive data": INITIAL_FIXED_QUESTIONS[3],
}


def trigger_initial_clarification(query: str) -> bool:
    """Determines if the user query contains any initial trigger keywords requiring clarification.

    Args:
        query (str): The user's input query string.

    Returns:
        bool: True if any initial trigger keywords from the question map are found in the query,
              indicating that clarification questions should be asked; False otherwise.
    """
    q = query.lower()
    primary_hits = sum(
        1
        for word in map(str.lower, PRIMARY_CLARIFICATION_TRIGGERS)
        if word in q
    )
    secondary_hits = sum(
        1
        for word in map(str.lower, SECONDARY_CONTEXTUAL_KEYWORDS)
        if word in q
    )
    logger.info(
        f"[Trigger Check] Primary hits: {primary_hits}, Secondary hits: {secondary_hits}"
    )
    return primary_hits >= 2 and secondary_hits >= 2


def detect_present_keywords(text: str) -> set[str]:
    """Detects which predefined keyword categories are present in the input text.

    Args:
        text (str): The input string to analyze.

    Returns:
        set[str]: A set of keys from FOLLOWUP_KEYWORDS that were detected in the text.
    """
    text = text.lower()
    found = set()
    for key, keywords in FOLLOWUP_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            found.add(key)
    logger.info(f"[Keyword Detection] Found fields: {found}")
    return found


def detect_missing_keywords(context_text: str) -> list[str]:
    """Identifies which required keyword categories are missing from the context text.

    Args:
        context_text (str): The text containing accumulated user input and chat context.

    Returns:
        list[str]: A list of questions (from QUESTION_MAP) that correspond to missing keyword categories.
    """
    context_lc = context_text.lower()
    missing = []
    for key, words in FOLLOWUP_KEYWORDS.items():
        if key not in QUESTION_MAP:
            continue  # ← avoid KeyError by skipping unmapped keys
        if not any(word in context_lc for word in words):
            missing.append(QUESTION_MAP[key])
    logger.info(f"[Missing Keywords] → {missing}")
    return missing


def fallback_final_answer(context_text: str) -> str:
    """Generates a final fallback answer based on keywords found in the context text.

    If the context contains sufficient detail about data transfer, returns a definitive
    answer about the need for a Transfer Impact Assessment (TIA). Otherwise, requests
    additional information.

    Args:
        context_text (str): The full context accumulated from the chat.

    Returns:
        str: A final answer or a request for additional clarification.
    """
    context = context_text.lower()
    if all(
        term in context
        for term in ["clinical", "patient", "az", "vendor", "on our behalf"]
    ):
        if "outside" in context or "international" in context:
            return (
                "Yes, a Transfer Impact Assessment (TIA) is required in this case. "
                "Since the data is being shared outside the UK or EU, a TIA must be conducted to assess the risks."
            )
        else:
            return (
                "No, a Transfer Impact Assessment (TIA) is not required if the data remains within the UK or EU. "
                "You should still ensure a Data Processing Agreement is in place."
            )
    return (
        "To answer your question correctly, I need more information:\n"
        "- " + "\n- ".join(detect_missing_keywords(context_text)[:2])
    )


def build_clarification_prompt(
    original_user_query: str, bot_questions: list[str], followup_input: str
) -> str:
    """Generates a clarification prompt for a Legal/Contract Assistant.

    This function constructs a formatted string used as a prompt for a
    Legal/Contract Assistant specializing in Transfer Impact Assessments
    (TIAs). The prompt includes context from an original user query,
    questions from the bot for clarification, and responses to follow-up
    input.

    Args:
        original_user_query: The initial query or request from the user.
        bot_questions: A list of questions generated by the bot to clarify
            the initial query.
        followup_input: The user's response to the bot's clarification questions.

    Returns:
        A formatted string that guides the Legal/Contract Assistant on how
        to proceed based on the provided input and responses.
    """
    return f"""
You are a Legal/Contract Assistant specializing in Transfer Impact Assessments (TIAs).

Context:
Original user query:
{original_user_query}

Bot clarification:
{chr(10).join(bot_questions)}

User's clarification:
{followup_input}

Instructions:
- If all of the following are clearly answered:
  * Type of data
  * Flow of data (shared/received)
  * Role of vendor
  * Purpose of processing
  * Vendor identity
  * Location of data
Then return: FINAL_RESPONSE_REQUIRED

Otherwise, ask 1–2 missing clarification questions.
Do NOT repeat previously answered ones.
""".strip()


session_context_memory = defaultdict(set)
REQUIRED_KEYS = set(FOLLOWUP_KEYWORDS.keys())


def process_user_query(
    user_query: str, tx_count: int, chat_history: list[str], session_id: str
) -> str:
    """Processes the user's query in the context of a session and chat history.

    Depending on the transaction count and the completeness of information, this function
    may request more clarification or provide a final answer about the need for a TIA.

    Args:
        user_query (str): The latest user input.
        tx_count (int): The current transaction count for the session.
        chat_history (list[str]): A list of previous user and assistant messages.
        session_id (str): A unique identifier for the user's session.

    Returns:
        str: A clarification message, final answer, or an empty string if no response is needed.
    """
    logger.info(
        f"[Follow-up Detected] Building clarification prompt at tx_count={tx_count}"
    )
    original_query = chat_history[0] if chat_history else ""
    bot_reply = chat_history[-2] if len(chat_history) >= 2 else ""
    user_followup = user_query

    # Build prompt containing full context
    formatted_prompt = build_clarification_prompt(
        original_user_query=original_query,
        bot_questions=[bot_reply],
        followup_input=user_followup,
    )
    logger.debug(f"[Clarification Prompt]\n{formatted_prompt}")

    # Update memory based on structured full prompt
    context_set = session_context_memory[session_id]
    context_set.update(detect_present_keywords(formatted_prompt))

    logger.info(
        f"[Context Set] TX={tx_count} Session={session_id} → Context Keys: {context_set}"
    )

    # Use full context for keyword detection
    full_context_text = formatted_prompt
    missing = detect_missing_keywords(full_context_text)

    if tx_count == 0:
        if trigger_initial_clarification(user_query):
            logger.info("[Initial Trigger Fired] Sending initial 4 questions.")
            return (
                "To answer your question correctly, I need more information:\n"
                + "\n".join(INITIAL_FIXED_QUESTIONS)
            )
        else:
            logger.info("[Initial Check] No TIA clarification needed.")
            return ""

    # Start composite prompt at follow-up 1 or higher
    logger.info(
        f"[Follow-up Detected] Building clarification prompt at tx_count={tx_count}"
    )
    original_query = chat_history[0] if chat_history else ""
    bot_reply = chat_history[-2] if len(chat_history) >= 2 else ""
    user_followup = user_query

    formatted_prompt = build_clarification_prompt(
        original_user_query=original_query,
        bot_questions=[bot_reply],
        followup_input=user_followup,
    )

    logger.debug(f"[Clarification Prompt]\n{formatted_prompt}")

    missing = detect_missing_keywords(full_context_text)

    if tx_count < 3:
        if missing:
            logger.info(f"[Follow-up Missing Fields] → {missing}")
            return (
                "To answer your question correctly, I need more information:\n"
                + "\n".join(f"- {q}" for q in missing[:2])
            )
        logger.info("[Clarification Complete] All required fields found.")
        return FINAL_RESPONSE_REQUIRED

    # Final fallbck (tx_count >=3): assess only from structured context
    logger.info("[LLM-style fallback at tx_count >= 3]")
    if not missing:
        return FINAL_RESPONSE_REQUIRED
    return (
        "To answer your question correctly, I need more information:\n"
        + "\n".join(f"- {q}" for q in missing[:2])
    )
