from pydantic import BaseModel


class FileOperationResult(BaseModel):
    filename: str
    status: str
    detail: str | None = None


class FileOperationResponse(BaseModel):
    results: list[FileOperationResult]


class ListDocumentsResponse(BaseModel):
    documents: list[str]