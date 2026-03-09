from fastapi import APIRouter, Query, UploadFile, File, HTTPException
from routes.kb_manager.doc_manager_logic import DocumentManager
from routes.constants import BUCKET_CONTAINER

upload_router = APIRouter()


@upload_router.post("/admin/kb-documents/upload/")
async def upload_kb_documents(
    folder: str = Query(..., description="Folder name: 'general' or 'privacy'"), files: list[UploadFile] = File(...)
):
    """
    Upload multiple documents. Existing files are skipped.
    """
    manager = DocumentManager(BUCKET_CONTAINER)
    return {"results": manager.upload_documents(folder, files)}
