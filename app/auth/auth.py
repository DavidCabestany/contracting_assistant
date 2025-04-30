"""Authentication route handlers."""

import logging

from auth.utils import create_token, renew_token
from config import get_config_value
from fastapi import APIRouter, Header, HTTPException

logger = logging.getLogger(__name__)

auth_router = APIRouter()

# Configuration constants for token handling
SECRET_KEY = get_config_value("SECRET_KEY")
TOKEN_EXPIRE_MINUTES = get_config_value("TOKEN_EXPIRE_MINUTES")


@auth_router.post("/loadconfig")
async def load_config(api_key: str = Header(None)):
    """Authenticate and issue a new token.

    Args:
        api_key (str): API key passed in the request header.

    Returns:
        dict: A dictionary containing the JWT token and its expiration time in minutes.

    Raises:
        HTTPException: If the API key is invalid.

    TODO(@toloko): Log auth attempts and track failed API key usage
    """
    if api_key != SECRET_KEY:
        raise HTTPException(status_code=401, detail="Invalid API Key")

    # Generate a new token for the UI user
    token = create_token(data={"sub": "user-UI"})

    return {"token": token, "expire_min": TOKEN_EXPIRE_MINUTES}


@auth_router.post("/renew")
async def renew_token_route(current_token: str = Header(None)):
    """Renew an existing JWT token if valid.

    Args:
        current_token (str): The existing JWT token provided in the request header.

    Returns:
        dict: A dictionary containing the new token, its expiration, and a renewal status.
    """
    # Renew the token using utility logic
    result = renew_token(current_token)

    return {
        "token": result["token"],
        "expire_min": TOKEN_EXPIRE_MINUTES,
        "renewed": result["renewed"],
    }
