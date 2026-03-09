from fastapi import APIRouter, Query
from routes.kb_manager.doc_manager_logic import DocumentManager
from routes.constants import BUCKET_CONTAINER

delete_router = APIRouter()


@delete_router.delete("/admin/kb-documents/delete/")
def delete_kb_documents(
    folder: str = Query(..., description="Folder name: 'general' or 'privacy'"),
    filenames: list[str] = Query(..., description="List of filenames to delete"),
):
    """
    Delete multiple documents from the selected folder.
    """
    manager = DocumentManager(BUCKET_CONTAINER)
    return {"results": manager.delete_documents(folder, filenames)}
