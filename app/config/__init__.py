# config/__init__.py
from .api import router as config_router
from .settings import settings

__all__ = ["config_router", "settings"]
