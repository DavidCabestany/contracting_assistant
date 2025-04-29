from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class FeedbackDisplayOptions(BaseModel):
    thumbsUp: Optional[str] = "N"
    thumbsDown: Optional[str] = "N"
    feedbackText: Optional[str] = "N"


class Feedback(BaseModel):
    feedbackDisplayOptions: FeedbackDisplayOptions


class FeedbackRequest(BaseModel):
    apiKey: Optional[str] = None
    userId: Optional[str] = None
    sessionId: Optional[str] = None
    messageId: Optional[str] = None
    isFeedbackPositive: bool
    feedbackComment: Optional[str] = None
