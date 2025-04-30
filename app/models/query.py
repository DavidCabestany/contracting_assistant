from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class QueryRequest(BaseModel):
    """
    Represents a basic query sent by the user to the system.

    Attributes:
        input_text (str): The raw text input provided by the user.
        knowledge_base (str): The identifier of the knowledge base to query.
        session_id (str): The session ID associated with the user's current session.
    """

    input_text: str
    knowledge_base: str
    session_id: str


class AnswerRequest(BaseModel):
    """
    Optional wrapper for passing extra instructions alongside a query.

    Attributes:
        additional_instructions (Optional[str]): Supplementary instructions to guide the response.
    """

    additional_instructions: Optional[str] = None


class User(BaseModel):
    """
    Represents a user interacting with the system.

    Attributes:
        id (str): Unique identifier for the user.
        sessionId (str): Current session ID for the user.
        language (str): Preferred language of the user (e.g., "en", "es").
        platform (str): Platform from which the user is accessing the system (e.g., "web", "mobile").
    """

    id: str
    sessionId: str
    language: str
    platform: str


class Query(BaseModel):
    """
    Describes the structure of a user query within a session.

    Attributes:
        text (str): The question or command provided by the user.
        knowledgeType (str): Type of knowledge to consult (e.g., "faq", "documents").
        transactionCount (int): The number of interactions so far in the session.
        files (Optional[list[str]]): Optional list of filenames involved in the query context.
    """

    text: str
    knowledgeType: str
    transactionCount: int
    files: Optional[list[str]] = None


class RequestQuery(BaseModel):
    """
    Full query request payload including user and query details.

    Attributes:
        apiKey (str): API key for authentication.
        user (User): User metadata.
        query (Query): Query details including text, knowledge type, and more.
    """

    apiKey: str
    user: User
    query: Query
