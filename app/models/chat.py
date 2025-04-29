from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel


class ChatMetadata(BaseModel):
    FileName: Optional[str] = None
    FileLocation: Optional[str] = None
    FlowName: Optional[str] = None
    KbType: Optional[str] = None
    Department: Optional[str] = None


class ChatInteraction(BaseModel):
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
    SessionStatus: Optional[str] = None
    ChatMetadata: ChatMetadata
    apiKey: Optional[str] = None


class ChatHistorySearchRequest(BaseModel):
    apiKey: Optional[str] = None
    userId: Optional[str] = None
    keyword: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    session_id: Optional[str] = None
    sort_order: Optional[Literal["asc", "desc"]] = "asc"
