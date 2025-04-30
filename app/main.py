"""Main FastAPI app setup for Contracting Assistant API."""

import logging

from auth.auth import auth_router
from config import config_router
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routes import chat_history_router, qna_router, summary_router

# Configure root logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

# Create FastAPI app instance
app = FastAPI(
    title="Contracting Assistant API",
    version="1.0.0",
)

# Auth endpoints
app.include_router(auth_router, prefix="/auth", tags=["Auth"])

# Config loader endpoints
app.include_router(config_router, prefix="/load", tags=["Config"])

# Q&A endpoints
app.include_router(qna_router, tags=["QnA"])

# Summarization endpoints
app.include_router(summary_router)

# Chat history endpoints
app.include_router(chat_history_router, prefix="/chat", tags=["Chat history"])

# ─── CORS CONFIGURATION ─────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def alive():
    """Root endpoint for health check.

    Returns:
        dict: Welcome message to indicate API is running.
    """
    return {"message": "Welcome to the Contracting Assistant API!"}
