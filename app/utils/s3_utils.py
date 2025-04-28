"""Utility functions for S3 paths and presigned URLs."""

from __future__ import annotations

import re
from typing import Any

import boto3
from botocore.config import Config

from . import logger

_S3 = boto3.client(
    "s3",
    config=Config(retries={"max_attempts": 3}, max_pool_connections=50),
)


def generate_presigned_url(
    s3_url: str, page_number: int, *, expiration: int = 3_600
) -> str | None:
    """Return a presigned HTTPS URL (with `#page=`), or *None* on failure."""
    try:
        expiration = int(expiration)
    except ValueError:
        logger.info("Expiration must be int, got %s", expiration)
        return None

    match = re.match(r"s3://([^/]+)/(.+)", s3_url)
    if match is None:
        logger.info("Invalid S3 URL: %s", s3_url)
        return None

    bucket, key = match.groups()
    try:
        url = _S3.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expiration,
        )
        return f"{url}#page={page_number}"
    except Exception as exc:  # noqa: BLE001
        logger.info("Presign failed: %r", exc)
        return None


def extract_file_locations(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten Bedrock KB citations into a deduplicated list of dicts."""
    citations: list[dict[str, Any]] = []
    for citation in data.get("citations", []):
        for ref in citation.get("retrievedReferences", []):
            page = int(
                ref.get("metadata", {}).get(
                    "x-amz-bedrock-kb-document-page-number", 0
                )
            )
            s3_uri = (
                ref.get("location", {}).get("s3Location", {}).get("uri", "")
            )
            obj = {
                "filePath": generate_presigned_url(s3_uri, page) or "",
                "pageNumber": page,
                "fileName": get_filename_from_path(s3_uri),
            }
            if not any(
                x["fileName"] == obj["fileName"]
                and (
                    x["pageNumber"] in {obj["pageNumber"], 0}
                    or obj["pageNumber"] == 0
                )
                for x in citations
            ):
                citations.append(obj)
    return citations


def get_filename_from_path(s3_path: str) -> str:
    """Return the trailing filename component of a `s3://` URI."""
    try:
        if not s3_path.startswith("s3://"):
            raise ValueError("must start with s3://")
        return s3_path.rsplit("/", 1)[-1]
    except Exception as exc:  # noqa: BLE001
        logger.info("Bad S3 path %s – %r", s3_path, exc)
        return ""
