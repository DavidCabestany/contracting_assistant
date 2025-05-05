"""Router for chat history."""

from fastapi import APIRouter, HTTPException
from models import ChatHistorySearchRequest, ChatInteraction, FeedbackRequest
from services.chat_history_service import (
    download_chat,
    get_latest_active_sessions,
    search_chat,
    store_interaction,
    update_feedback,
    view_chat_by_session,
)

chat_history_router = APIRouter()


@chat_history_router.post("/store/")
def store(interaction: ChatInteraction):
    """Persist a single chat interaction record."""
    return store_interaction(interaction)


@chat_history_router.post("/session/")
def get_session_history(request: ChatHistorySearchRequest):
    """Return the full chat history for a specific session ID."""
    return view_chat_by_session(request.session_id)


@chat_history_router.post("/search/")
def search(request: ChatHistorySearchRequest):
    """Search chat history by free-text or filter criteria."""
    return search_chat(request)


@chat_history_router.post("/download/")
def download(request: ChatHistorySearchRequest):
    """Generate and stream a downloadable transcript (e.g., CSV or PDF)."""
    return download_chat(request)


@chat_history_router.post("/feedback/")
def feedback(feedback: FeedbackRequest):
    """Update an interaction with user feedback (thumbs up / down, comment)."""
    return update_feedback(feedback)


@chat_history_router.post("/recents/")
def recents(request: ChatHistorySearchRequest):
    """Return the user’s most-recent active chat sessions."""
    if not request.userId:
        raise HTTPException(
            status_code=400, detail="Missing userId in request"
        )
    return get_latest_active_sessions(request.userId)
