"""Main FastAPI app setup for Contracting Assistant API."""

import logging

from auth.auth import auth_router
from config import config_router
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routes import chat_history_router, qna_router, summary_router
from routes.admin.feedback.feedback import feedback_data_router
from routes.admin.feedback.feedbackdetails import feedbackdetails_router
from routes.admin.response_time.response_time import responseTime_router
from routes.admin.usage.usage import usage_router

# Configure root logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
file_handler = logging.FileHandler("report.log", mode="a", encoding="utf-8")
file_handler.setLevel(logging.INFO)

# Re-use the same format you defined in basicConfig
file_handler.setFormatter(
    logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
)

logging.getLogger().addHandler(file_handler)


app = FastAPI(
    title="Contracting Assistant API",
    version="1.0.0",
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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

# Admin ResponseTime
app.include_router(
    responseTime_router,
    prefix="/admin/responseTime",
    tags=["Admin only tracking"],
)

app.include_router(
    feedback_data_router,
    prefix="/admin/feedback",
    tags=["Admin only tracking"],
)

# Admin usage endpoints
app.include_router(
    usage_router,
    prefix="/admin/totalUsage",
    tags=["Admin only tracking"],
)
# Feedback Details endpoints
app.include_router(
    feedbackdetails_router,
    prefix="/admin/feedback",
    tags=["Admin only tracking"],
)


@app.get("/")
def alive():
    """Root endpoint for health check.

    Returns:
        dict: Welcome message to indicate API is running.
    """
    return {"message": "Welcome to the Contracting Assistant API!"}
