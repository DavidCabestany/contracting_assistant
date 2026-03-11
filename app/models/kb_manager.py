from typing import List, Optional

from pydantic import BaseModel


class FileOperationResult(BaseModel):
    filename: str
    status: str
    detail: Optional[str] = None


class FileOperationResponse(BaseModel):
    results: List[FileOperationResult]


class DocumentInfo(BaseModel):
    filename: str
    timestamp: Optional[str] = None


class ListDocumentsResponse(BaseModel):
    documents: List[DocumentInfo]
    count: int