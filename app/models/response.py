from __future__ import annotations

from typing import Any, Optional, Union

from pydantic import BaseModel

from .answer import QnAAnswer
from .feedback import Feedback
from .primitives import Citation, QuickReply


class Result(BaseModel):
    messageId: str
    answer: Union[str, dict[str, Any], QnAAnswer]
    feedback: Feedback
    transactionCount: Optional[int] = 0
    citations: Optional[list[Citation]] = None
    quickReplies: Optional[list[QuickReply]] = None


class QueryResponse(BaseModel):
    status: str
    sessionId: str
    userQuery: str
    result: Result
