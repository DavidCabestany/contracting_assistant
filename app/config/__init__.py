"""Init file for the config package."""

from .config import config_router, get_config_item, get_secret

__all__ = ["config_router", "get_config_item", "get_secret"]
