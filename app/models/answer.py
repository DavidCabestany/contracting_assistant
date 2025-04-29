from __future__ import annotations

from typing import List

from pydantic import BaseModel


class DocumentAnswer(BaseModel):
    """
    Formerly `QnaAnswer` – the ‘file & path’ flavour.
    (Renamed to avoid colliding with QnAAnswer below.)
    """

    answer: str
    filename: str
    filepath: str
    knowledgeId: str
    sessionId: str


class QnAAnswer(BaseModel):
    """The ‘similarities / differences’ flavour."""

    ans: str
    similarities: List[str] = []
    differences: List[str] = []
