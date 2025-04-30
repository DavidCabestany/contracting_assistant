from __future__ import annotations

from pydantic import BaseModel


class DocumentAnswer(BaseModel):
    """
    Represents an answer extracted from a document, including metadata.

    Attributes:
        answer (str): The extracted answer text.
        filename (str): The name of the file from which the answer was taken.
        filepath (str): The full path to the file.
        knowledgeId (str): Unique identifier linking the document to a knowledge base entry.
        sessionId (str): Identifier for the session in which the question was asked.
    """

    answer: str
    filename: str
    filepath: str
    knowledgeId: str
    sessionId: str


class QnAAnswer(BaseModel):
    """
    Represents an answer that compares or contrasts concepts.

    Attributes:
        ans (str): The main answer string.
        similarities (list[str]): list of similarities identified between compared items.
        differences (list[str]): list of differences identified between compared items.
    """

    ans: str
    similarities: list[str] = []
    differences: list[str] = []
