# config/loader.py

import json
import logging

import boto3
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)


class SecretsLoader:
    """Loads and caches secrets from AWS Secrets Manager."""

    def __init__(self, region_name: str, secret_name: str):
        self.client = boto3.client("secretsmanager", region_name=region_name)
        self.secret_name = secret_name
        self._cache: dict[str, any] = {}

    def load(self) -> dict:
        if self._cache:
            return self._cache

        try:
            logger.info(f"Loading secret: {self.secret_name}")
            resp = self.client.get_secret_value(SecretId=self.secret_name)
            secret_str = resp.get("SecretString") or "{}"
            self._cache = json.loads(secret_str)
            logger.info("Secrets loaded successfully")
            return self._cache

        except (BotoCoreError, ClientError, ValueError) as e:
            logger.error(f"Secret load failed: {e}")
            raise RuntimeError(f"Unable to load secrets: {e}")
