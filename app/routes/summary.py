"""Routes and logic for generating document summaries and risk assessments."""

from __future__ import annotations

import datetime
import json
import logging
import re
import uuid
from typing import Optional

import boto3
from auth.utils import verify_token
from botocore.exceptions import BotoCoreError, ClientError
from config import get_secret
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from langchain_aws import ChatBedrock
from langchain_core.messages import HumanMessage
from models import (
    ChatInteraction,
    ChatMetadata,
    Feedback,
    FeedbackDisplayOptions,
    QueryResponse,
    Result,
)
from prompts import BASE_PROMPT, RISK_MATRIX_PROMPT
from routes.qna import (
    retrieve_and_generate_prioritized_doc,
)
from services.chat_history_service import store_interaction
from services.memory import ChatMessageHistory
from services.memory_helpers import load_history, save_history
from utils import (
    extract_keywords_from_query,
    extract_pdf_contents,
    extract_text_from_word,
    generate_prompt,
    generate_prompt_risk,
    get_file_type,
    get_risk_matrix_details,
    prompt_query_cat,
)

# Logger and configuration constants.
logger = logging.getLogger(__name__)

s3 = boto3.client("s3")
MAX_SEARCH_LEN = 2000
BUCKET_CONTAINER = get_secret("BUCKET_CONTAINER")
MODEL_ID = get_secret("MODEL_ID")
IRRELEVANT = get_secret("IRRELEVANT_KEYWORD")
SUMMARY_FLOW_NAME = get_secret("SUMMARY_FLOW_NAME")
PRIOR_DOC = "CAN HANDBOOK Third Edition.pdf"

router = APIRouter(tags=["Summary"], dependencies=[Depends(verify_token)])


def _extract_json(text: str) -> dict | None:
    """Extract the first JSON object found in a text.

    Args:
        text: A string potentially containing JSON.

    Returns:
        A dictionary if a JSON object is found and parsed successfully, otherwise None.
    """
    cleaned = "\n".join(
        ln for ln in text.splitlines() if not ln.lstrip().startswith("```")
    )
    match = re.search(r"{.*}", cleaned, flags=re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _wrap_plain(ans: str) -> dict:
    """Wrap plain text answer in structured summary format.

    Args:
        ans: Free-text summary.

    Returns:
        A dictionary with default summary fields.
    """
    return {
        "ans": ans,
        "highRisksClauses": [],
        "mediumRisksClauses": [],
        "lowRisksClauses": [],
        "similarities": [],
        "differences": [],
    }


def _fallback_kb(prompt: str, session_id: str, folder: str = "general") -> str:
    """Trigger fallback knowledge base search if model output is irrelevant.

    Args:
        prompt: The original full prompt.
        session_id: Current session ID.
        folder: Name of the knowledge folder (default is 'general').

    Returns:
        Text response from fallback knowledge base or empty string if failed.
    """
    try:
        resp = retrieve_and_generate_prioritized_doc(
            prompt,
            get_secret("GEN_ENQ_KB_ID"),
            "general",
            [PRIOR_DOC],
            session_id=session_id,
        )
        if resp.get("citations"):
            return resp["output"]["text"]
    except Exception:
        logger.exception("KB fallback failed")
    return ""


@router.post("/getsummary/")
async def generate_summary(
    file: UploadFile = File(None),
    apiKey: Optional[str] = Form(None),
    userId: Optional[str] = Form(None),
    sessionId: Optional[str] = Form(None),
    language: Optional[str] = Form(None),
    platform: Optional[str] = Form(None),
    queryText: Optional[str] = Form(None),
    transactionCount: Optional[str] = Form(None),
) -> QueryResponse:
    """Generate a document summary and risk analysis using an LLM.

    This endpoint accepts a file or plain query text. It handles:
    - File parsing and S3 upload
    - Query classification and prompt generation
    - LLM invocation
    - Result parsing, fallback handling, and response formatting

    Args:
        file: Optional uploaded document (PDF, DOC, DOCX).
        apiKey: Optional API key (currently unused).
        userId: Optional identifier of the user.
        sessionId: Optional session identifier.
        language: Optional language preference.
        platform: Optional source platform.
        queryText: Optional free-text user query.
        transactionCount: Optional transaction metadata.

    Returns:
        A QueryResponse object with structured result.
    """
    msg_id = str(uuid.uuid4())
    session_id = sessionId or str(uuid.uuid4())
    content = ""
    file_name = ""
    folder_path = ""

    # Step 1: Process uploaded file, if any
    if file is not None:
        try:
            # Read file and detect file type
            file_bytes = await file.read()
            ftype = get_file_type(file.filename)
            file_name = file.filename
            logger.info(
                f"[{msg_id}] File received: name={file_name}, type={ftype}"
            )
        except Exception as exc:
            logger.exception(f"[{msg_id}] Failed to read uploaded file")
            raise HTTPException(400, f"Error reading file: {exc}") from exc

        # Upload to S3
        folder_path = f"contracts/{userId or 'anonymous'}/{session_id}"
        try:
            s3.put_object(Bucket=BUCKET_CONTAINER, Key=f"{folder_path}/")
            s3.put_object(
                Bucket=BUCKET_CONTAINER,
                Key=f"{folder_path}/{file_name}",
                Body=file_bytes,
                ContentType=file.content_type,
            )
            logger.info(
                f"[{msg_id}] File uploaded to S3: {folder_path}/{file_name}"
            )
        except (BotoCoreError, ClientError) as exc:
            logger.exception(f"[{msg_id}] S3 upload failed")
            raise HTTPException(500, "S3 upload failed") from exc

        # Extract content
        try:
            if ftype == ".pdf":
                content = extract_pdf_contents(file_bytes)
            elif ftype in {".doc", ".docx"}:
                content = extract_text_from_word(file_bytes)
            else:
                raise ValueError(f"Unsupported file type: {ftype}")
            logger.debug(f"[{msg_id}] Extracted content from file")
        except Exception as exc:
            logger.exception(f"[{msg_id}] Failed to extract content from file")
            raise HTTPException(
                400, f"Failed to extract content: {exc}"
            ) from exc

    # Step 2: Default query if none provided
    if not queryText or not queryText.strip():
        queryText = "Summarize the document content"
        logger.info(f"[{msg_id}] No queryText provided. Default applied.")

    # Step 3: Load chat memory
    chat_mem: ChatMessageHistory = load_history(session_id)
    logger.debug(
        f"[{msg_id}] Loaded chat history with {len(chat_mem.messages)} messages"
    )

    history_block = "".join(
        ("User: " if isinstance(m, HumanMessage) else "Assistant: ")
        + m.content
        + "\n"
        for m in chat_mem.messages
    )

    # Step 4: Classify query
    try:
        cat_prompt = prompt_query_cat(queryText.lower())
        category = ChatBedrock(model_id=MODEL_ID).invoke(cat_prompt).content
        logger.info(f"[{msg_id}] Query category determined: {category}")
    except Exception as exc:
        logger.exception(f"[{msg_id}] Failed to classify query prompt")
        raise HTTPException(500, f"Error classifying prompt: {exc}") from exc

    # Step 5: Generate prompt based on category
    try:
        if category in {"1", "2"}:
            body_prompt = generate_prompt_risk(
                content,
                get_risk_matrix_details(),
                queryText,
                RISK_MATRIX_PROMPT,
            )
        elif category == "3":
            body_prompt = generate_prompt(content, queryText, BASE_PROMPT)
        else:
            body_prompt = generate_prompt(content, queryText, BASE_PROMPT)
        logger.debug(f"[{msg_id}] Prompt built for LLM.")
    except Exception as exc:
        logger.exception(f"[{msg_id}] Failed to generate body prompt")
        raise HTTPException(500, f"Prompt generation failed: {exc}") from exc

    full_prompt = f"{history_block}{body_prompt}"
    logger.debug(
        f"[{msg_id}] Final prompt constructed (truncated):\n{full_prompt[:1000]}"
    )

    # Step 6: Call LLM
    try:
        llm_resp = ChatBedrock(model_id=MODEL_ID).invoke(full_prompt)
        raw_answer = llm_resp.content.strip()
        logger.info(f"[{msg_id}] LLM responded successfully")
        logger.debug(
            f"[{msg_id}] Raw LLM response (truncated): {raw_answer[:1000]}"
        )
    except Exception as exc:
        logger.exception(f"[{msg_id}] LLM call failed")
        raise HTTPException(500, f"Error invoking LLM: {exc}") from exc

    # Step 7: Normalize response
    payload = _extract_json(raw_answer)
    logger.debug(f"[{msg_id}] Primary JSON parsed: {payload is not None}")

    if payload is None:
        inner = _extract_json(raw_answer.replace("```json", "```"))
        if inner and "response" in inner:
            answer = _wrap_plain(inner["response"])
            inner2 = _extract_json(answer["ans"])
            if inner2 and "response" in inner2:
                answer["ans"] = inner2["response"]
            elif inner2:
                inner2.setdefault("similarities", [])
                inner2.setdefault("differences", [])
                answer = inner2
        elif inner:
            answer = inner | {"similarities": [], "differences": []}
        else:
            answer = _wrap_plain(raw_answer)
        logger.debug(f"[{msg_id}] Applied fallback JSON normalization")
    elif "response" in payload:
        answer = _wrap_plain(payload["response"])
        logger.debug(f"[{msg_id}] Parsed from TEMPLATE scaffold")
    else:
        answer = payload
        answer.setdefault("similarities", [])
        answer.setdefault("differences", [])
        logger.debug(f"[{msg_id}] Used raw parsed JSON directly")

    # Step 8: Fallback if response is irrelevant
    if IRRELEVANT in raw_answer:
        logger.warning(
            f"[{msg_id}] Detected IRRELEVANT content, trying KB fallback"
        )
        fb = _fallback_kb(full_prompt, session_id)
        if fb:
            raw_answer = fb
            payload = _extract_json(raw_answer)
            answer = (
                _wrap_plain(payload["response"])
                if payload and "response" in payload
                else _wrap_plain(raw_answer) if payload is None else payload
            )
            if isinstance(answer, dict):
                answer.setdefault("similarities", [])
                answer.setdefault("differences", [])
            logger.info(f"[{msg_id}] Fallback response used")

    # Step 9: Save chat history
    chat_mem.add_user_message(queryText)
    chat_mem.add_ai_message(raw_answer)
    save_history(chat_mem)
    logger.debug(f"[{msg_id}] Updated and saved chat history")

    # Step 10: Build API response
    feedback = Feedback(
        feedbackDisplayOptions=FeedbackDisplayOptions(
            thumbsUp="Y", thumbsDown="Y", feedbackText="Y"
        )
    )
    result = Result(
        messageId=msg_id,
        answer=answer,
        transactionCount=transactionCount,
        feedback=feedback,
    )
    api_resp = QueryResponse(
        status="success",
        sessionId=session_id,
        userQuery=queryText,
        result=result,
    )
    logger.info(f"[{msg_id}] Summary generation complete")

    # Step 11: Store interaction
    if userId:
        now = datetime.datetime.now().isoformat()
        file_loc = (
            f"{BUCKET_CONTAINER}{folder_path}{file_name}" if file_name else ""
        )
        store_interaction(
            ChatInteraction(
                UserId=userId,
                SessionId=session_id,
                UserMessage=queryText,
                UserMessageSearch=(
                    extract_keywords_from_query(queryText.lower())
                    if len(queryText) > MAX_SEARCH_LEN
                    else queryText.lower()
                ),
                BotResponse=raw_answer,
                BotResponseSearch=raw_answer.lower()[:MAX_SEARCH_LEN],
                FeedbackComment="",
                Timestamp=now,
                SessionStatus=get_secret("SESSION_STATUS_ACTIVE"),
                MessageId=msg_id,
                ChatMetadata=ChatMetadata(
                    FileName=file_name,
                    FileLocation=file_loc,
                    FlowName=SUMMARY_FLOW_NAME,
                    Department="",
                ),
            )
        )
        logger.info(f"[{msg_id}] Interaction stored for userId={userId}")

    return api_resp
