"""FastAPI routes for KB document administration."""

from __future__ import annotations

from fastapi import APIRouter, File, Query, UploadFile
from models.kb_manager import (
    FileOperationResponse,
    FileOperationResult,
    ListDocumentsResponse,
)
from routes.constants import BUCKET_CONTAINER
from routes.kb_manager.doc_manager_logic import DocumentManager

doc_manager_router = APIRouter()

@doc_manager_router.get(
    "/admin/kb-documents/",
    response_model=ListDocumentsResponse,
)
def list_kb_documents(
    folder: str = Query(..., description="Folder name: 'general' or 'privacy'"),
) -> ListDocumentsResponse:
    """List all files in the selected folder.

    Args:
        folder: Folder name.

    Returns:
        Response containing the list of document names.
    """
    manager = DocumentManager(BUCKET_CONTAINER)
    return ListDocumentsResponse(documents=manager.list_documents(folder))


@doc_manager_router.post(
    "/admin/kb-documents/upload/",
    response_model=FileOperationResponse,
)
async def upload_kb_documents(
    folder: str = Query(..., description="Folder name: 'general' or 'privacy'"),
    files: list[UploadFile] = File(...),
) -> FileOperationResponse:
    """Upload multiple files and skip those that already exist.

    Args:
        folder: Folder name.
        files: Files to upload.

    Returns:
        Response containing per-file upload results.
    """
    manager = DocumentManager(BUCKET_CONTAINER)
    return FileOperationResponse(
        results=[
            FileOperationResult(**result)
            for result in manager.upload_documents(folder, files)
        ]
    )


@doc_manager_router.post(
    "/admin/kb-documents/update/",
    response_model=FileOperationResponse,
)
async def update_kb_documents(
    folder: str = Query(..., description="Folder name: 'general' or 'privacy'"),
    files: list[UploadFile] = File(...),
) -> FileOperationResponse:
    """Update one or multiple files only if they already exist.

    Args:
        folder: Folder name.
        files: Files to update.

    Returns:
        Response containing per-file update results.
    """
    manager = DocumentManager(BUCKET_CONTAINER)
    return FileOperationResponse(
        results=[
            FileOperationResult(**result)
            for result in manager.update_documents(folder, files)
        ]
    )


@doc_manager_router.delete(
    "/admin/kb-documents/delete/",
    response_model=FileOperationResponse,
)
def delete_kb_documents(
    folder: str = Query(..., description="Folder name: 'general' or 'privacy'"),
    filenames: list[str] = Query(..., description="List of filenames to delete"),
) -> FileOperationResponse:
    """Delete one or multiple files from the selected folder.

    Args:
        folder: Folder name.
        filenames: Names of files to delete.

    Returns:
        Response containing per-file deletion results.
    """
    manager = DocumentManager(BUCKET_CONTAINER)
    return FileOperationResponse(
        results=[
            FileOperationResult(**result)
            for result in manager.delete_documents(folder, filenames)
        ]
    )

