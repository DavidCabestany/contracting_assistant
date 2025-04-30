"""Data models for representing chat metadata, interactions, and search requests."""

from __future__ import annotations

from pydantic import BaseModel


class Citation(BaseModel):
    """Represents a reference to a specific location in a document.

    Attributes:
        fileName (str): Name of the source file.
        filePath (str): Full path to the file on the system or storage.
        pageNumber (int): Page number where the referenced content appears.
    """

    fileName: str
    filePath: str
    pageNumber: int


class QuickReply(BaseModel):
    """Represents a suggested quick reply option for a chatbot response.

    Attributes:
        text (str): The text shown to the user.
        payload (str): The value sent back to the system when selected.
    """

    text: str
    payload: str
