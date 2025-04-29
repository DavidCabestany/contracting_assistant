import logging

from auth.auth import auth_router
from chathistory import chat_history_router
from config import config_router
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routes import qna_router, summary_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

app = FastAPI(
    title="Contracting Assistant API",
    version="1.0.0",
)

# ─── ROUTERS ───
app.include_router(auth_router, prefix="/auth", tags=["Auth"])
app.include_router(config_router, prefix="/load", tags=["Config"])
app.include_router(chat_history_router, prefix="/chat", tags=["Chat history"])
app.include_router(qna_router)
app.include_router(summary_router)

# ─── CORS ───
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def alive():
    return {"message": "Welcome to the Contracting Assistant API!"}
