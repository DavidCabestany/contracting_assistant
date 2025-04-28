# config/api.py
import os

from fastapi import APIRouter, HTTPException

from .loader import SecretsLoader
from .settings import settings

router = APIRouter()


@router.get("/config")
async def reload_config():
    try:
        # clear & reload the underlying secrets cache
        loader = SecretsLoader(
            region_name=settings.REGION_ID,
            secret_name=os.getenv("SECRET_NAME", "your-default-secret"),
        )
        loader._cache.clear()
        loader.load()
        return {"message": "Config reloaded successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/config/keys")
async def list_config_keys():
    return {"keys": list(settings.dict().keys())}


@router.get("/config/{key}")
async def get_config_item(key: str):
    val = settings.dict().get(key)
    if val is None:
        raise HTTPException(status_code=404, detail=f"Key '{key}' not found")
    return {key: val}
