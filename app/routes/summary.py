"""Routes and logic for generating document summaries and risk assessments."""

from __future__ import annotations

import datetime
import json
import logging
import re
import uuid
from string import Template
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
from prompts import RISK_MATRIX_PROMPT, TEMPLATE
from routes.qna import retrieve_and_generate_prioritized_doc
from services.chat_history_service import store_interaction
from services.memory import ChatMessageHistory
from services.memory_helpers import load_history, save_history
from utils import (
    extract_keywords_from_query,
    extract_pdf_contents,
    extract_text_from_word,
    generate_prompt_risk,
    get_file_type,
    get_risk_matrix_details,
    prompt_query_cat,
)

# ───────────────────────── config & constants ──────────────────────────
logger = logging.getLogger(__name__)

s3 = boto3.client("s3")
MAX_SEARCH_LEN = 2000
BUCKET_CONTAINER = get_secret("BUCKET_CONTAINER")
MODEL_ID = get_secret("MODEL_ID")
IRRELEVANT = get_secret("IRRELEVANT_KEYWORD")
SUMMARY_FLOW_NAME = get_secret("SUMMARY_FLOW_NAME")
PRIOR_DOC = "CAN HANDBOOK Third Edition.pdf"

router = APIRouter(tags=["Summary"], dependencies=[Depends(verify_token)])

# ───────────────────────── helper functions ────────────────────────────


def _extract_json(text: str) -> dict | None:
    """Return first JSON object inside *text* (even if fenced); else None."""
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
    """Wrap free-text summary into the expected dict shape."""
    return {
        "ans": ans,
        "highRisksClauses": [],
        "mediumRisksClauses": [],
        "lowRisksClauses": [],
        "similarities": [],
        "differences": [],
    }


def _fallback_kb(prompt: str, session_id: str, folder: str = "general") -> str:
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


# ─────────────────────────────── route ─────────────────────────────────


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
    """Summarize an uploaded document or a plain query text."""
    msg_id = str(uuid.uuid4())
    session_id = sessionId or str(uuid.uuid4())

    content = ""
    file_name = ""
    folder_path = ""
    if file is not None:
        try:
            file_bytes = await file.read()
            ftype = get_file_type(file.filename)
        except Exception as exc:
            raise HTTPException(400, f"Error reading file: {exc}") from exc

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
            logger.exception("S3 upload failed")
            raise HTTPException(500, "S3 upload failed") from exc

        try:
            if ftype == ".pdf":
                content = extract_pdf_contents(file_bytes)
            elif ftype in {".doc", ".docx"}:
                content = extract_text_from_word(file_bytes)
            else:
                raise ValueError(f"Unsupported file type {ftype}")
        except ValueError as exc:
            raise HTTPException(
                400, f"Failed to extract content: {exc}"
            ) from exc

    # ── 2. default query text ────────────────────────────────────────
    if not queryText or not queryText.strip():
        queryText = "Summarize the document content"

    # ── 3. build prompt with stored history ───────────────────────────
    chat_mem: ChatMessageHistory = load_history(session_id)
    history_block = "".join(
        ("User: " if isinstance(m, HumanMessage) else "Assistant: ")
        + m.content
        + "\n"
        for m in chat_mem.messages
    )

    try:
        cat_prompt = prompt_query_cat(queryText.lower())
        category = ChatBedrock(model_id=MODEL_ID).invoke(cat_prompt).content
    except Exception as exc:
        raise HTTPException(500, f"Error invoking LLM: {exc}") from exc

    if category == "1":
        body_prompt = generate_prompt_risk(
            content, get_risk_matrix_details(), queryText, RISK_MATRIX_PROMPT
        )
    else:
        body_prompt = Template(TEMPLATE).safe_substitute(
            {
                "Instruction": queryText,
                "search_results_formatted": "",
                "prompt": "",
            }
        )

    full_prompt = f"{history_block}{body_prompt}"

    # ── 4. call Bedrock ──────────────────────────────────────────────
    try:
        llm_resp = ChatBedrock(model_id=MODEL_ID).invoke(full_prompt)
    except Exception as exc:
        raise HTTPException(500, f"Error invoking LLM: {exc}") from exc

    raw_answer = llm_resp.content.strip()

    # ── 5. normalise response into dict shape ────────────────────────
    payload = _extract_json(raw_answer)

    if payload is None:
        # maybe the JSON blob is nested (```json {…} ``` inside prose)
        inner = _extract_json(raw_answer.replace("```json", "```"))
        if inner and "response" in inner:
            answer = _wrap_plain(inner["response"])
            if isinstance(answer, dict) and isinstance(answer.get("ans"), str):
                inner = _extract_json(answer["ans"])
                if inner and "response" in inner:  # TEMPLATE scaffold
                    answer["ans"] = inner["response"]
                elif inner:  # any other JSON shape
                    # merge keys but keep default arrays if absent
                    inner.setdefault("similarities", [])
                    inner.setdefault("differences", [])
                    answer = inner
        elif inner:
            answer = inner | {"similarities": [], "differences": []}
        else:
            answer = _wrap_plain(raw_answer)
    elif "response" in payload:  # came from TEMPLATE scaffold
        answer = _wrap_plain(payload["response"])
    else:
        answer = payload
        answer.setdefault("similarities", [])
        answer.setdefault("differences", [])

    # ── 6. fallback if answer contains IRRELEVANT token ──────────────
    if IRRELEVANT in raw_answer:
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

    bot_response_search = (
        raw_answer.lower()[:MAX_SEARCH_LEN]
        if len(raw_answer) > MAX_SEARCH_LEN
        else raw_answer.lower()
    )

    # ── 7. persist chat history ──────────────────────────────────────
    chat_mem.add_user_message(queryText)
    chat_mem.add_ai_message(raw_answer)
    save_history(chat_mem)

    # ── 8. build API response & store interaction ────────────────────
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

    return api_resp
