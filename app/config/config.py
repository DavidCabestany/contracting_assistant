import json
import logging
import os

import boto3
from fastapi import APIRouter, HTTPException

# Setup logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

if not logger.hasHandlers():
    ch = logging.StreamHandler()
    ch.setFormatter(
        logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    )
    logger.addHandler(ch)

config_router = APIRouter()

_secret_values = {}


def _load_values():
    """
    Loads secrets from AWS Secrets Manager and populates the _secret_values dictionary.
    Automatically called on module import but can also be triggered via /config endpoint.
    """
    try:
        client = boto3.client(
            service_name="secretsmanager", region_name="us-east-1"
        )
        secret_name = os.getenv(
            "secret_name", "azcdi-us-ops-procure-ds-secret-dev"
        )

        logger.info(f"Loading config from secret: {secret_name}")
        response = client.get_secret_value(SecretId=secret_name)

        secret_str = response.get("SecretString")
        if not secret_str:
            raise ValueError("SecretString is missing in the response")

        global _secret_values
        _secret_values = json.loads(secret_str)
        logger.info("Configuration values loaded successfully")

    except Exception as e:
        logger.error(f"Failed to load configuration: {str(e)}")
        raise Exception(f"Error loading config data: {str(e)}")


def get_config_value(key: str, default=None):
    """
    Public helper to retrieve a single config value.
    Returns default if not found.
    """
    return _secret_values.get(key, default)


@config_router.get("/config")
async def reload_config():
    """
    API endpoint to reload the config manually at runtime.
    """
    try:
        _load_values()
        return {"message": "Config reloaded successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@config_router.get("/config/{key}")
async def get_config_item(key: str):
    """
    API endpoint to retrieve a specific config key.
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
    """
    API endpoint to list all available config keys.
    """
    return {"keys": list(_secret_values.keys())}


_load_values()
