from fastapi import APIRouter, Query
from routes.kb_manager.doc_manager_logic import DocumentManager
from routes.constants import BUCKET_CONTAINER

doc_manager_router = APIRouter()


@doc_manager_router.get("/admin/kb-documents/")
def list_kb_documents(folder: str = Query(..., description="Folder name: 'general' or 'privacy'")):
    """
    List all documents in the selected folder ('general' or 'privacy') inside the S3 bucket.
    """
    manager = DocumentManager(BUCKET_CONTAINER)
    return {"documents": manager.list_documents(folder)}
