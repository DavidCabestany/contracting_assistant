from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class QueryRequest(BaseModel):
    input_text: str
    knowledge_base: str
    session_id: str


class AnswerRequest(BaseModel):
    """Optional ‘extra instructions’ wrapper you sometimes send before an answer."""

    additional_instructions: Optional[str] = None


class User(BaseModel):
    id: str
    sessionId: str
    language: str
    platform: str


class Query(BaseModel):
    text: str
    knowledgeType: str
    transactionCount: int
    files: Optional[list[str]] = None


class RequestQuery(BaseModel):
    apiKey: str
    user: User
    query: Query
