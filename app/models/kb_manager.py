from pydantic import BaseModel


class FileOperationResult(BaseModel):
    filename: str
    status: str
    detail: str | None = None


class FileOperationResponse(BaseModel):
    results: list[FileOperationResult]


class DocumentInfo(BaseModel):
    filename: str
    timestamp: str | None = None


class ListDocumentsResponse(BaseModel):
    documents: list[DocumentInfo]
    count: int
