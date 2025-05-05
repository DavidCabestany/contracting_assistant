"""Binary-file handling, auth helpers, and error-response generators."""

from __future__ import annotations

import io
import logging
from collections.abc import Iterable
from hmac import compare_digest
from pathlib import Path

import PyPDF2
from docx import Document
from fastapi import HTTPException
from models import Feedback, FeedbackDisplayOptions, QueryResponse, Result

from .constants import API_KEY, ERROR_MESSAGE

logger = logging.getLogger(__name__)


def extract_pdf_contents(file_bytes: bytes) -> str:
    """Extract and return all text from a PDF document as a string.

    Args:
        file_bytes (bytes): Raw PDF file contents.

    Returns:
        str: Concatenated text from all pages.
    """
    try:
        reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
        return "".join(page.extract_text() or "" for page in reader.pages)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Error reading PDF: {exc}",
        ) from exc  # TODO(@kvcn639): Catch specific PyPDF2 errors


def extract_text_from_word(byte_array: bytes) -> str:
    """Extract and return all text from a DOCX document.

    Args:
        byte_array (bytes): Raw Word file content.

    Returns:
        str: Extracted plain text joined by newlines.
    """
    try:
        document = Document(io.BytesIO(byte_array))
        return "\n".join(para.text for para in document.paragraphs)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Error reading DOCX: {exc}",
        ) from exc  # TODO(@kvcn639): Catch python-docx specific exceptions


def get_file_type(file_name: str) -> str:
    """Return the file extension in lower-case format.

    Args:
        file_name (str): Name of the uploaded file.

    Returns:
        str: Lower-case file extension (e.g., '.pdf', '.docx').
    """
    try:
        return Path(file_name).suffix.lower()
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Bad filename: {exc}",
        ) from exc
        # TODO(@kvcn639): Handle cases where Path.suffix is empty


def generate_technical_error_message(
    msg_id: str,
    transaction_count: int,
    user_query: str,
    session_id: str,
    exc: Exception | None = None,
) -> QueryResponse:
    """Generate a standard error response with optional exception message.

    Args:
        msg_id (str): The UUID for the failed message.
        transaction_count (int): Transaction count at failure time.
        user_query (str): The query that caused the failure.
        session_id (str): The user's session.
        exc (Optional[Exception]): Exception to surface (only for debug).

    Returns:
        QueryResponse: A response object containing the error info.
    """
    feedback = Feedback(
        feedbackDisplayOptions=FeedbackDisplayOptions(
            thumbsUp="N",
            thumbsDown="N",
            feedbackText="N",
        ),
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
    """Validate an API key using constant-time comparison.

    Args:
        api_key (str): The key provided by the client.

    Returns:
        bool: True if the key is valid.
    """
    try:
        return bool(api_key) and compare_digest(api_key, API_KEY)
    except Exception as exc:
        logger.info("validate_api_key failed: %r", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Authentication verification failed: {exc}",
        ) from exc
        # TODO(@kvcn639): Consider using 401/403 instead of 500 for API key failures


def extract_chat_history(data: dict) -> list[tuple[str, str]]:
    """Parse and flatten a DynamoDB-style chat structure into a list of (question, answer) pairs.

    Skips malformed sessions and message entries gracefully.

    Args:
        data (dict): Raw chat history structure.

    Returns:
        list[tuple[str, str]]: Flattened (question, answer) pairs.
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
