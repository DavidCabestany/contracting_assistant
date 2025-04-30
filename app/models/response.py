from __future__ import annotations

from typing import Any, Optional, Union

from pydantic import BaseModel

from .answer import QnAAnswer
from .feedback import Feedback
from .primitives import Citation, QuickReply


class Result(BaseModel):
    """
    Represents the result of a query operation.

    Attributes:
        messageId (str): Unique identifier for the message.
        answer (Union[str, dict[str, Any], QnAAnswer]): The answer to the query, which can be a string, dictionary, or QnAAnswer object.
        feedback (Feedback): Feedback associated with the result.
        transactionCount (Optional[int]): Number of transactions, if applicable. Defaults to 0.
        citations (Optional[list[Citation]]): List of citations supporting the answer, if any.
        quickReplies (Optional[list[QuickReply]]): List of quick reply options, if any.
    """

    messageId: str
    answer: Union[str, dict[str, Any], QnAAnswer]
    feedback: Feedback
    transactionCount: Optional[int] = 0
    citations: Optional[list[Citation]] = None
    quickReplies: Optional[list[QuickReply]] = None


class QueryResponse(BaseModel):
    """
    Represents the complete response to a user's query.

    Attributes:
        status (str): The status of the query response (e.g., "success", "error").
        sessionId (str): Unique identifier for the user's session.
        userQuery (str): The original query submitted by the user.
        result (Result): The result of the query operation.
    """

    status: str
    sessionId: str
    userQuery: str
    result: Result
