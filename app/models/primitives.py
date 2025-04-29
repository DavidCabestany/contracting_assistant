from __future__ import annotations

from pydantic import BaseModel


class Citation(BaseModel):
    fileName: str
    filePath: str
    pageNumber: int


class QuickReply(BaseModel):
    text: str
    payload: str
