from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class FeedbackDisplayOptions(BaseModel):
    """
    Controls which feedback UI options are visible to the user.

    Attributes:
        thumbsUp (Optional[str]): Whether the thumbs-up option is shown ("Y" or "N").
        thumbsDown (Optional[str]): Whether the thumbs-down option is shown ("Y" or "N").
        feedbackText (Optional[str]): Whether the free-text feedback field is shown ("Y" or "N").
    """

    thumbsUp: Optional[str] = "N"
    thumbsDown: Optional[str] = "N"
    feedbackText: Optional[str] = "N"


class Feedback(BaseModel):
    """
    Represents a configuration object that defines how feedback options should be displayed.

    Attributes:
        feedbackDisplayOptions (FeedbackDisplayOptions): The visual options for feedback UI.
    """

    feedbackDisplayOptions: FeedbackDisplayOptions


class FeedbackRequest(BaseModel):
    """
    Represents a user's submitted feedback for a specific message.

    Attributes:
        apiKey (Optional[str]): API key associated with the request.
        userId (Optional[str]): Identifier of the user providing feedback.
        sessionId (Optional[str]): Identifier of the chat session.
        messageId (Optional[str]): Identifier of the message being evaluated.
        isFeedbackPositive (bool): Indicates if the feedback was positive.
        feedbackComment (Optional[str]): Optional free-text comment from the user.
    """

    apiKey: Optional[str] = None
    userId: Optional[str] = None
    sessionId: Optional[str] = None
    messageId: Optional[str] = None
    isFeedbackPositive: bool
    feedbackComment: Optional[str] = None
