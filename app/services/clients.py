# services/clients.py
"""All boto3 clients creation."""

import boto3
from botocore.config import Config

from .config import REGION_ID

_boto_cfg = Config(retries={"max_attempts": 3}, max_pool_connections=50)

bedrock_agent_runtime = boto3.client("bedrock-agent-runtime", config=_boto_cfg)
bedrock_client = boto3.client(
    "bedrock-runtime", region_name=REGION_ID, config=_boto_cfg
)
s3_client = boto3.client("s3", config=_boto_cfg)

__all__ = ["bedrock_agent_runtime", "bedrock_client", "s3_client"]
