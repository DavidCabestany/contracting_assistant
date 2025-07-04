"""Load (and later, persist) per-session ChatMessageHistory objects in S3.

Only I/O lives here; higher-level logic sits in utils or routes.
"""

from __future__ import annotations

import logging
import pickle
from collections.abc import Sequence

from botocore.exceptions import BotoCoreError, ClientError
from config import get_secret
from fastapi import HTTPException
from langchain.schema import BaseChatMessageHistory, BaseMessage

from .clients import s3_client

logger = logging.getLogger(__name__)

_BUCKET = get_secret("BUCKET_CONTAINER")
_CACHE_PREFIX = "cache/"


class ChatMessageHistory(BaseChatMessageHistory):
    """Manages chat history messages for a given session, with persistence to S3.

    Attributes:
        session_id (str): Unique identifier for the session.
        messages (list): List of BaseMessage objects stored in the session.
    """

    def __init__(self, session_id: str):
        """Initialize a chat history object for a specific session.

        Args:
            session_id (str): Unique identifier for the user/session.
        """
        self.session_id = session_id
        self.messages = []

    def add_messages(self, messages: Sequence[BaseMessage]):
        """Add multiple messages to the session and persist them to S3.

        Args:
            messages (Sequence[BaseMessage]): List of messages to append.

        Raises:
            HTTPException: If saving the pickle file to S3 fails.
        """
        self.messages.extend(messages)
        try:
            updated_pickle_data = pickle.dumps(self)

            # Upload the updated pickle file back to S3
            s3_client.put_object(
                Bucket=_BUCKET,
                Key=f"cache/{self.session_id}.pkl",
                Body=updated_pickle_data,
            )
        except Exception as e:
            logger.info(str(e))
            raise HTTPException(
                status_code=500,
                detail=f"Error while {self.session_id} storing the memory pkl file qna answer: {e!s}",
            )

    def clear(self):
        """Clear all messages from the current session history."""
        self.messages.clear()


def get_file_memory(session_id: str) -> ChatMessageHistory:
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
        obj = s3_client.get_object(Bucket=_BUCKET, Key=key)
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
