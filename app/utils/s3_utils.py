"""Utility functions for S3 paths and presigned URLs.

This module provides functions for:
- Generating presigned S3 URLs with support for PDF page linking.
- Extracting referenced document locations from Bedrock responses.
- Parsing filenames from S3 URIs.
"""

from __future__ import annotations

import re
from typing import Any

import boto3
from botocore.config import Config

from .constants import logger

s3_client = boto3.client(
    "s3",
    config=Config(retries={"max_attempts": 3}, max_pool_connections=50),
)


def generate_presigned_url(
    s3_url: str,
    page_number: int,
    *,
    expiration: int = 3_600,
) -> str | None:
    """Generate a presigned URL for an S3 object, with support for page reference.

    Args:
        s3_url (str): The full S3 URI (e.g., 's3://my-bucket/my-object.pdf').
        page_number (int): The page number to link to using a `#page=` fragment.
        expiration (int, optional): Time in seconds before the URL expires. Defaults to 3600.

    Returns:
        str | None: The presigned URL or None if generation fails.
    """
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
        url = s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expiration,
        )
        return f"{url}#page={page_number}"
    except Exception as exc:  # noqa: BLE001
        logger.info("Presign failed: %r", exc)
        return None


def extract_file_locations(
    data: dict[str, Any], allowed_files: list[str] | None = None
) -> list[dict[str, Any]]:
    """Extract deduplicated citations, optionally restricted to allowed files only."""
    citations: list[dict[str, Any]] = []
    allowed_files_set = (
        set(f.lower() for f in allowed_files) if allowed_files else None
    )

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
            filename = get_filename_from_path(s3_uri)

            # Filter: If allowed_files provided, skip non-allowed
            if allowed_files_set and filename.lower() not in allowed_files_set:
                continue

            obj = {
                "filePath": generate_presigned_url(s3_uri, page) or "",
                "pageNumber": page,
                "fileName": filename,
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
    """Extract the file name from an S3 URI.

    Args:
        s3_path (str): A URI of the form 's3://bucket/key/path/file.ext'.

    Returns:
        str: The filename component, or an empty string on error.
    """
    try:
        if not s3_path.startswith("s3://"):
            raise ValueError("must start with s3://")
        return s3_path.rsplit("/", 1)[-1]
    except Exception as exc:  # noqa: BLE001
        logger.info("Bad S3 path %s - %r", s3_path, exc)
        return ""
