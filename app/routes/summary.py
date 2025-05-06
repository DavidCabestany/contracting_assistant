"""Routes and logic for generating document summaries and risk assessments.

This module provides endpoints to summarize uploaded documents or plain text queries
and assess associated risks. It does not depend on RunnableWithMessageHistory;
instead, session context is managed via load_history and save_history in
memory_helpers.py, eliminating Pydantic attribute errors while preserving all functionality.
"""

from __future__ import annotations

import datetime
import json
import logging
import uuid
from typing import Optional

import boto3
from auth.utils import verify_token
from botocore.exceptions import BotoCoreError, ClientError
from config import get_secret
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from langchain_aws import ChatBedrock
from models import (
    ChatInteraction,
    ChatMetadata,
    Feedback,
    FeedbackDisplayOptions,
    QueryResponse,
    Result,
)
from prompts import BASE_PROMPT, RISK_MATRIX_PROMPT
from routes.qna import retrieve_and_generate_prioritized_doc
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

# Configure logging
logger = logging.getLogger(__name__)

# Initialize S3 client and constants
s3 = boto3.client("s3")
MAX_SEARCH_LEN = 2000
BUCKET_CONTAINER: str = get_secret("BUCKET_CONTAINER")
MODEL_ID: str = get_secret("MODEL_ID")
REGION_ID: str = get_secret("REGION_ID")
IRRELEVANT: str = get_secret("IRRELEVANT_KEYWORD")
SUMMARY_FLOW_NAME: str = get_secret("SUMMARY_FLOW_NAME")
PRIOR_DOC: str = "CAN HANDBOOK Third Edition.pdf"

router = APIRouter(
    tags=["Summary"],
    dependencies=[Depends(verify_token)],
)


def fallback_via_kb(
    prompt: str,
    session_id: str,
    knowledge_base_folder: str = "general",
) -> tuple[str, list]:
    """Attempt Bedrock KB retrieval and prioritized document generation.

    Returns:
        A tuple containing the answer text and a list of citations.
        If retrieval fails, the answer text is empty and citations list is empty.
    """
    try:
        response = retrieve_and_generate_prioritized_doc(
            prompt,
            get_secret("GEN_ENQ_KB_ID"),
            knowledge_base_folder,
            [PRIOR_DOC],
            session_id=session_id,
        )
        if response.get("citations"):
            return response["output"]["text"], response["citations"]
    except Exception:
        logger.exception("Fallback retrieval via knowledge base failed.")

    return "", []


@router.post("/getsummary/")
async def generate_summary(
    file: UploadFile = File(None),
    apiKey: Optional[str] = Form(
        None
    ),  # maintained for signature parity, unused
    userId: Optional[str] = Form(None),
    sessionId: Optional[str] = Form(None),
    language: Optional[str] = Form(None),  # reserved, not used yet
    platform: Optional[str] = Form(None),  # reserved, not used yet
    queryText: Optional[str] = Form(None),
    transactionCount: Optional[str] = Form(None),
) -> QueryResponse:
    """Summarize an uploaded document or a plain query text.

    Steps:
    1. If `file` is provided, upload it to S3 and extract its text.
    2. Default `queryText` to a generic summary request if it is empty.
    3. Load per-session chat history from S3 via memory_helpers.
    4. Determine query category (risk vs. normal) and build the prompt.
    5. Invoke the Bedrock model directly without LangChain history wrapper.
    6. If the response contains the `IRRELEVANT` keyword, attempt KB fallback.
    7. Persist the updated chat history for future turns.
    8. Build and return the API response, logging interaction to the database.
    """
    msg_id = str(uuid.uuid4())
    session_id = sessionId or str(uuid.uuid4())
    file_name = ""
    folder_path = ""
    content = ""

    # 1. Handle file upload and text extraction
    if file is not None:
        try:
            file_bytes = await file.read()
            file_type = get_file_type(file.filename)
        except Exception as exc:
            raise HTTPException(400, f"Error reading file: {exc}") from exc

        # Upload to S3
        try:
            folder_path = f"contracts/{userId or 'anonymous'}/{session_id}"
            s3.put_object(Bucket=BUCKET_CONTAINER, Key=f"{folder_path}/")
            file_name = file.filename
            s3.put_object(
                Bucket=BUCKET_CONTAINER,
                Key=f"{folder_path}/{file_name}",
                Body=file_bytes,
                ContentType=file.content_type,
            )
        except (BotoCoreError, ClientError) as exc:
            logger.exception("S3 upload failed.")
            raise HTTPException(500, "S3 upload failed.") from exc

        # Extract text based on file type
        try:
            if file_type == ".pdf":
                content = extract_pdf_contents(file_bytes)
            elif file_type in {".doc", ".docx"}:
                content = extract_text_from_word(file_bytes)
            else:
                raise ValueError(f"Unsupported file type {file_type}")
        except ValueError as exc:
            raise HTTPException(
                400, f"Failed to extract content: {exc}"
            ) from exc

    # 2. Default query text if missing
    if not queryText or not queryText.strip():
        queryText = "Summarize the document content"

    # 3. Load previous chat history and build prompt
    chat_mem: ChatMessageHistory = load_history(session_id)

    history_block = "".join(
        (
            f"User: {m.content}\n"
            if m.role == "user"
            else f"Assistant: {m.content}\n"
        )
        for m in chat_mem.messages
    )

    # Determine query category and prepare prompt
    prompt_cat = prompt_query_cat(queryText.lower())
    try:
        category = ChatBedrock(model_id=MODEL_ID).invoke(prompt_cat).content
    except Exception as exc:
        raise HTTPException(500, f"Error invoking the LLM: {exc}") from exc

    if category == "1":
        prompt = generate_prompt_risk(
            content,
            get_risk_matrix_details(),
            queryText,
            RISK_MATRIX_PROMPT,
        )
    else:
        prompt = generate_prompt(content, queryText, BASE_PROMPT)

    full_prompt = f"{history_block}{prompt}"

    # 4. Invoke the model
    llm = ChatBedrock(model_id=MODEL_ID)
    try:
        llm_response = llm.invoke(full_prompt)
    except Exception as exc:
        raise HTTPException(500, f"Error invoking the LLM: {exc}") from exc

    raw_answer = llm_response.content.strip()

    # Strip markdown code fences from the response
    if raw_answer.startswith("```"):
        lines = raw_answer.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        raw_answer = "\n".join(lines).strip()

    # Attempt to parse JSON output, fallback to raw string
    try:
        answer = json.loads(raw_answer)
    except json.JSONDecodeError:
        answer = raw_answer
    if isinstance(answer, dict):
        answer.setdefault("similarities", [])
        answer.setdefault("differences", [])
    else:
        # model gave us just text: package it in the expected structure
        answer = {
            "ans": answer,
            "highRisksClauses": [],
            "mediumRisksClauses": [],
            "lowRisksClauses": [],
            "similarities": [],
            "differences": [],
        }
    bot_response_search = (
        raw_answer.lower()[:MAX_SEARCH_LEN]
        if len(raw_answer) > MAX_SEARCH_LEN
        else raw_answer.lower()
    )

    # 5. Fallback if the response is irrelevant
    if IRRELEVANT in raw_answer:
        fb_answer, _ = fallback_via_kb(prompt, session_id)
        raw_answer = fb_answer or raw_answer.replace(IRRELEVANT, "")
        try:
            answer = json.loads(raw_answer)
        except json.JSONDecodeError:
            answer = raw_answer
        if isinstance(answer, dict):
            answer.setdefault("similarities", [])
            answer.setdefault("differences", [])
        else:
            # model gave us just text: package it in the expected structure
            answer = {
                "ans": answer,
                "highRisksClauses": [],
                "mediumRisksClauses": [],
                "lowRisksClauses": [],
                "similarities": [],
                "differences": [],
            }

    # 6. Persist chat history
    chat_mem.add_user_message(queryText)
    chat_mem.add_ai_message(raw_answer)
    save_history(chat_mem)

    # 7. Build API response and log interaction
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
    response = QueryResponse(
        status="success",
        sessionId=session_id,
        userQuery=queryText,
        result=result,
    )

    # Log interaction to database if userId is provided
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
                BotResponseSearch=bot_response_search,
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

    return response
