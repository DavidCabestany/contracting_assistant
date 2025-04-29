"""
Load (and later, persist) per-session ChatMessageHistory objects in S3.

Only I/O lives here; higher-level logic sits in utils or routes.
"""

from __future__ import annotations

import logging
import pickle

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from chat_message_history import ChatMessageHistory
from config import get_config_value

logger = logging.getLogger(__name__)

_S3 = boto3.client("s3")
_BUCKET = get_config_value("BUCKET_CONTAINER")
_CACHE_PREFIX = "cache/"


def load_chat_history(session_id: str) -> ChatMessageHistory:
    """
    Fetch cached history for *session_id* or return an empty container.

    No exception ever escapes this function – callers always get a valid
    ChatMessageHistory instance.
    """
    key = f"{_CACHE_PREFIX}{session_id}.pkl"
    try:
        obj = _S3.get_object(Bucket=_BUCKET, Key=key)
        with obj["Body"] as fd:
            return pickle.load(fd)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "NoSuchKey":
            logger.warning("S3 ClientError while reading %s: %s", key, exc)
    except (
        BotoCoreError,
        pickle.UnpicklingError,
        Exception,
    ) as exc:  # noqa: BLE001
        logger.warning("Failed to load chat history %s: %s", key, exc)
    return ChatMessageHistory(session_id)
