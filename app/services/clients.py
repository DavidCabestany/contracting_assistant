"""Centralized initialization of all boto3 clients used across the application.

This includes:
- Bedrock Agent Runtime
- Bedrock Runtime
- S3 Client

Clients are configured with a shared retry and connection pool policy to ensure
consistency and performance under load.
"""

import boto3
from botocore.config import Config

from .config import (  # TODO(@kvcn639): Consider renaming to AWS_REGION or moving to a central settings module
    REGION_ID,
)

# Shared boto3 config to optimize retries and connection pooling
_boto_cfg = Config(
    retries={
        "max_attempts": 3,
    },  # TODO(@kvcn639): Make retry settings configurable via environment
    max_pool_connections=50,  # TODO(@kvcn639): Monitor connection usage and adjust based on load testing
)

# Initialize Bedrock Agent Runtime client
bedrock_agent_runtime = boto3.client("bedrock-agent-runtime", config=_boto_cfg)

# Initialize Bedrock Runtime client (used for invoking foundation models)
bedrock_client = boto3.client(
    "bedrock-runtime",
    region_name=REGION_ID,
    config=_boto_cfg,
)

# Initialize Amazon S3 client
s3_client = boto3.client("s3", config=_boto_cfg)

# Define public API for this module
__all__ = ["bedrock_agent_runtime", "bedrock_client", "s3_client"]
