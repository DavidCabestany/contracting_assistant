"""Chat message history manager using AWS S3 for session persistence."""

import logging
import pickle
from collections.abc import Sequence

import boto3
from config import get_config_value
from fastapi import HTTPException
from langchain.schema import BaseChatMessageHistory, BaseMessage

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

BUCKET_CONTAINER = get_config_value("BUCKET_CONTAINER")
s3 = boto3.client("s3")


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

        TODO(@toloko): Add S3 retry/backoff strategy for robustness
        """
        self.messages.extend(messages)
        try:
            updated_pickle_data = pickle.dumps(self)

            # Upload the updated pickle file back to S3
            s3.put_object(
                Bucket=BUCKET_CONTAINER,
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
