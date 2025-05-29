"""Data models for representing chat metadata, interactions, and search requests."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel


class ChatMetadata(BaseModel):
    """Metadata associated with a chat session.

    Attributes:
        FileName (Optional[str]): Name of the source file, if any.
        FileLocation (Optional[str]): File path or storage location.
        FlowName (Optional[str]): Name of the conversation flow or scenario.
        KbType (Optional[str]): Type of knowledge base used in the session.
        Department (Optional[str]): Department to which the chat context belongs.
    """

    FileName: Optional[list] = None
    FileLocation: Optional[str] = None
    FlowName: Optional[str] = None
    KbType: Optional[str] = None
    Department: Optional[str] = None


class ChatInteraction(BaseModel):
    """Represents a single chat interaction between a user and a bot.

    Attributes:
        UserId (Optional[str]): Identifier for the user.
        SessionId (Optional[str]): Identifier for the chat session.
        MessageId (Optional[str]): Unique identifier for this interaction.
        UserMessage (Optional[str]): Raw message sent by the user.
        UserMessageSearch (Optional[str]): Preprocessed version of user message for search.
        BotResponse (Optional[str]): Bot's response to the user.
        BotResponseSearch (Optional[str]): Preprocessed bot response for search indexing.
        IsFeedbackPositive (Optional[bool]): Whether user feedback was positive.
        FeedbackComment (Optional[str]): Additional comment from user as feedback.
        Timestamp (Optional[str]): Timestamp of the interaction (ISO 8601 recommended).
        SessionStatus (Optional[str]): Status of the session (e.g., active, closed).
        ChatMetadata (ChatMetadata): Metadata providing context about the session.
        apiKey (Optional[str]): API key associated with the request (if relevant).
    """

    UserId: Optional[str] = None
    SessionId: Optional[str] = None
    MessageId: Optional[str] = None
    UserMessage: Optional[str] = None
    UserMessageSearch: Optional[str] = None
    BotResponse: Optional[str] = None
    BotResponseSearch: Optional[str] = None
    IsFeedbackPositive: Optional[bool] = None
    FeedbackComment: Optional[str] = None
    Timestamp: Optional[str] = None
    StartTime: Optional[str] = None
    EndTime: Optional[str] = None
    SessionStatus: Optional[str] = None
    ChatMetadata: ChatMetadata
    apiKey: Optional[str] = None


class ChatHistorySearchRequest(BaseModel):
    """Represents a search query for retrieving chat history records.

    Attributes:
        apiKey (Optional[str]): API key to authenticate the request.
        userId (Optional[str]): Filter by user ID.
        keyword (Optional[str]): Keyword to search in chat messages.
        start_date (Optional[str]): Start date for the search (e.g., "2024-01-01").
        end_date (Optional[str]): End date for the search (e.g., "2024-12-31").
        session_id (Optional[str]): Filter by a specific session ID.
        sort_order (Optional[Literal["asc", "desc"]]): Sort order for results.
    """

    apiKey: Optional[str] = None
    userId: Optional[str] = None
    keyword: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    session_id: Optional[str] = None
    sort_order: Optional[Literal["asc", "desc"]] = "asc"
