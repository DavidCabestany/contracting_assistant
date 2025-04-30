"""Load (and later, persist) per-session ChatMessageHistory objects in S3.

Only I/O lives here; higher-level logic sits in utils or routes.
"""

from __future__ import annotations

import logging
import pickle

from botocore.exceptions import BotoCoreError, ClientError
from chat_message_history import ChatMessageHistory
from config import get_config_value

from .clients import s3_client as _S3

logger = logging.getLogger(__name__)

_BUCKET = get_config_value("BUCKET_CONTAINER")
_CACHE_PREFIX = "cache/"


def load_chat_history(session_id: str) -> ChatMessageHistory:
    """Fetch cached chat history for a given session ID from S3.

    If the file is not found or an error occurs, returns an empty ChatMessageHistory.
    This function is guaranteed to never raise; it logs and returns a fallback.

    Args:
        session_id (str): The unique session identifier.

    Returns:
        ChatMessageHistory: The loaded or new message history object.
    """
    key = f"{_CACHE_PREFIX}{session_id}.pkl"
    try:
        obj = _S3.get_object(Bucket=_BUCKET, Key=key)
        with obj["Body"] as fd:
            return pickle.load(fd)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "NoSuchKey":
            logger.warning("S3 ClientError while reading %s: %s", key, exc)
        else:
            logger.info("No chat history found for session: %s", session_id)
    except (BotoCoreError, pickle.UnpicklingError, Exception) as exc:
        logger.warning("Failed to load chat history %s: %s", key, exc)
        # TODO(@kvcn639): Consider deleting corrupted file from S3 if unpickling fails consistently
    return ChatMessageHistory(session_id)  # Always return valid history
