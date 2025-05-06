"""Code for memory former chat_message_history."""

import logging
import pickle

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from config import get_secret

from .memory import ChatMessageHistory

logger = logging.getLogger(__name__)
s3 = boto3.client("s3")
BUCKET_CONTAINER = get_secret("BUCKET_CONTAINER")


def load_history(session_id: str) -> ChatMessageHistory:
    """Return ChatMessageHistory (empty if nothing stored)."""
    try:
        obj = s3.get_object(
            Bucket=BUCKET_CONTAINER, Key=f"cache/{session_id}.pkl"
        )
        with obj["Body"] as fh:
            return pickle.load(fh)
    except (ClientError, BotoCoreError, FileNotFoundError):
        return ChatMessageHistory(session_id)


def save_history(history: ChatMessageHistory) -> None:
    """Code for saving history in s3 if needed."""
    try:
        s3.put_object(
            Bucket=BUCKET_CONTAINER,
            Key=f"cache/{history.session_id}.pkl",
            Body=pickle.dumps(history),
        )
    except Exception as exc:
        logger.warning("Could not persist chat history: %s", exc)
