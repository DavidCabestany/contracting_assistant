"""Configuration loader for AWS Secrets Manager with FastAPI endpoints."""

import json
import logging
import os

import boto3
from fastapi import APIRouter, HTTPException

# Initialize logger for this module
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Configure logging handler if none exists
if not logger.hasHandlers():
    ch = logging.StreamHandler()
    ch.setFormatter(
        logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"),
    )
    logger.addHandler(ch)

# FastAPI router to expose config-related endpoints
config_router = APIRouter()

# Internal dictionary to store secrets loaded from AWS Secrets Manager
_secret_values = {}


def _load_values():
    """Load configuration secrets from AWS Secrets Manager and store them in the `_secret_values` dictionary.

    This function:

    - Initializes the boto3 Secrets Manager client.
    - Fetches the secret identified by the environment variable 'secret_name' (or a default).
    - Parses the JSON-formatted secret string.
    - Updates the global `_secret_values` dictionary.

    Raises:
        Exception: If the secret is not retrievable or not properly formatted.
    """
    try:
        client = boto3.client(
            service_name="secretsmanager",
            region_name="us-east-1",
        )
        secret_name = os.getenv("secret_name")  # removed teh default option

        logger.info(f"Loading config from secret: {secret_name}")
        response = client.get_secret_value(SecretId=secret_name)

        secret_str = response.get("SecretString")
        if not secret_str:
            raise ValueError("SecretString is missing in the response")

        global _secret_values
        _secret_values = json.loads(secret_str)
        logger.info("Configuration values loaded successfully")

    except Exception as e:
        logger.error(f"Failed to load configuration: {e!s}")
        raise Exception(f"Error loading config data: {e!s}")


def get_config_value(key: str, default=None):
    """Retrieve a specific configuration value from `_secret_values`.

    Args:
        key (str): The key to look up.
        default (Any, optional): The default value to return if key is not found.

    Returns:
        Any: The value associated with the key, or `default` if not found.
    """
    return _secret_values.get(key, default)


@config_router.get("/config")
async def reload_config():
    """Endpoint to manually reload configuration values from AWS Secrets Manager.

    Returns:
        dict: A success message or an HTTP 500 error if loading fails.
    """
    try:
        _load_values()
        return {"message": "Config reloaded successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@config_router.get("/config/{key}")
async def get_config_item(key: str):
    """Endpoint to retrieve a specific configuration key.

    Args:
        key (str): The configuration key to retrieve.

    Returns:
        dict: The value for the key, or a message if not found.
    """
    try:
        value = get_config_value(key)
        if value is None:
            return {"message": f"Key '{key}' not found"}
        return {key: value}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@config_router.get("/config/keys")
async def list_config_keys():
    """Endpoint to list all available configuration keys currently loaded.

    Returns:
        dict: A dictionary containing the list of keys.
    """
    return {"keys": list(_secret_values.keys())}


# Load secrets immediately when this module is imported
_load_values()
