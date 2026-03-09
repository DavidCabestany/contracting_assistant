from fastapi import APIRouter, Query, UploadFile, File, HTTPException
from routes.kb_manager.doc_manager_logic import DocumentManager
from routes.constants import BUCKET_CONTAINER

update_router = APIRouter()
upload_router = APIRouter()


@update_router.post("/admin/kb-documents/update/")
async def update_kb_document(
    folder: str = Query(..., description="Folder name: 'general' or 'privacy'"), file: UploadFile = File(...)
):
    """
    Update (replace) a single document. Only one file at a time.
    """
    manager = DocumentManager(BUCKET_CONTAINER)
    return manager.update_document(folder, file)


@upload_router.post("/admin/kb-documents/upload/")
async def upload_kb_documents(
    folder: str = Query(..., description="Folder name: 'general' or 'privacy'"), files: list[UploadFile] = File(...)
):
    """
    Upload multiple documents. Existing files are skipped.
    """
    manager = DocumentManager(BUCKET_CONTAINER)
    return {"results": manager.upload_documents(folder, files)}


### Note - "A file with this name already exists. Uploading will replace the existing file. Do you want to continue?"
