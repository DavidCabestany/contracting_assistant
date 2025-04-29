"""Binary-file handling, auth helpers, and error-response generators."""

from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Iterable

import PyPDF2
from docx import Document
from fastapi import HTTPException
from models import Feedback, FeedbackDisplayOptions, QueryResponse, Result

from .constants import ERROR_MESSAGE

logger = logging.getLogger(__name__)


def extract_pdf_contents(file_bytes: bytes) -> str:
    """Return *all* text in a PDF (best-effort)."""
    try:
        reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
        return "".join(page.extract_text() or "" for page in reader.pages)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=400, detail=f"Error reading PDF: {exc}"
        ) from exc


def extract_text_from_word(byte_array: bytes) -> str:
    """Return plain text from a DOCX byte stream."""
    try:
        document = Document(io.BytesIO(byte_array))
        return "\n".join(para.text for para in document.paragraphs)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=400, detail=f"Error reading DOCX: {exc}"
        ) from exc


def get_file_type(file_name: str) -> str:
    """`.pdf`, `.docx`, …  (always lower-case)."""
    try:
        return Path(file_name).suffix.lower()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=400, detail=f"Bad filename: {exc}"
        ) from exc


# ───────────────────────────── misc helpers ───────────────────────────── #
def generate_technical_error_message(
    msg_id: str,
    transaction_count: int,
    user_query: str,
    session_id: str,
    exc: Exception | None = None,
) -> QueryResponse:
    """Return a QueryResponse with a safe error string for the UI."""
    feedback = Feedback(
        feedbackDisplayOptions=FeedbackDisplayOptions(
            thumbsUp="N",
            thumbsDown="N",
            feedbackText="N",
        )
    )
    result = Result(
        messageId=str(msg_id),
        answer=str(exc) if exc else ERROR_MESSAGE,
        transactionCount=transaction_count,
        feedback=feedback,
    )
    return QueryResponse(
        status="error",
        sessionId=session_id,
        userQuery=user_query,
        result=result,
    )


def validate_api_key(api_key: str) -> bool:
    """Constant-time equality check for your public endpoint."""
    from hmac import compare_digest

    from . import API_KEY  # local import to avoid circulars

    try:
        return bool(api_key) and compare_digest(api_key, API_KEY)
    except Exception as exc:  # noqa: BLE001
        logger.info("validate_api_key failed: %r", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Authentication verification failed: {exc}",
        ) from exc


def extract_chat_history(data: dict) -> list[tuple[str, str]]:
    """
    Flatten a DynamoDB-style structure into a list of *(question, answer)* tuples.
    Silently skips malformed records.
    """
    history: list[tuple[str, str]] = []
    if not isinstance(data, dict):
        logger.info("Chat history must be dict, got %s", type(data))
        return history

    for session_id, messages in data.items():
        if not isinstance(messages, Iterable):
            logger.info("Session %s is not iterable, skipping", session_id)
            continue

        for message in messages:
            if not isinstance(message, dict):
                logger.info("Bad message in %s, skipping", session_id)
                continue
            question, answer = (
                message.get("UserMessageSearch"),
                message.get("BotResponse"),
            )
            if question and answer:
                history.append((question, answer))
    return history
