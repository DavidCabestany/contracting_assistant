"""S3 helpers & URI utilities.

This module provides functions for:
- Constructing S3 URIs
- Prefixing file paths for retrieval
- Reading Excel files from S3

Legacy alias functions are provided for backward compatibility.
"""

from __future__ import annotations

from collections.abc import Sequence
from io import BytesIO

import pandas as pd

from .clients import s3_client
from .constants import BUCKET_CONTAINER, logger


def s3_uri(bucket: str, key: str) -> str:
    """Construct an S3 URI given a bucket and object key.

    Args:
        bucket (str): The S3 bucket name.
        key (str): The object key (path inside the bucket).

    Returns:
        str: A full S3 URI string.
    """
    return f"s3://{bucket}/{key}"


def add_prefix(files: Sequence[str], bucket: str, folder: str) -> list[str]:
    """Build S3 URIs for a list of filenames located in a specific bucket/folder.

    Ensures that there is exactly one slash between the folder and file name.

    Args:
        files (Sequence[str]): List of filenames (no path).
        bucket (str): S3 bucket name.
        folder (str): Folder inside the bucket.

    Returns:
        list[str]: List of full S3 URIs.
    """
    folder_clean = folder.rstrip("/")
    prefix = f"s3://{bucket}/{folder_clean}/"
    return [f"{prefix}{file}" for file in files]


def read_excel_from_s3(key: str, sheet: str) -> pd.DataFrame:
    """Read an Excel file from S3 and return it as a Pandas DataFrame.

    Args:
        key (str): The object key (file path in the bucket).
        sheet (str): Sheet name to read from the Excel workbook.

    Returns:
        pd.DataFrame: The content of the Excel sheet.

    Raises:
        Exception: If fetching or reading fails.
    """
    try:
        obj = s3_client.get_object(Bucket=BUCKET_CONTAINER, Key=key)
        data = obj["Body"].read()

        # TODO(@kvcn639): Validate ContentType is an Excel MIME type
        # TODO(@kvcn639): Optionally validate file extension to guard against malformed keys

        df = pd.read_excel(BytesIO(data), sheet_name=sheet)
        return df
    except Exception as exc:
        logger.error("Unable to fetch mapping sheet %s — %s", key, exc)
        # TODO(@kvcn639): Catch specific S3 errors (e.g. NoSuchKey, AccessDenied) and log them more meaningfully
        raise


def get_s3_path(bucket_name: str, folder_name: str) -> str:
    """Legacy alias for `s3_uri()`.

    Args:
        bucket_name (str): Name of the S3 bucket.
        folder_name (str): Path to the folder.

    Returns:
        str: The full S3 URI path.
    """
    return s3_uri(bucket_name, folder_name)


def add_s3_prefix_to_files(
    files: Sequence[str],
    bucket_name: str,
    folder_name: str,
) -> list[str]:
    """Legacy alias for `add_prefix()`.

    Args:
        files (Sequence[str]): List of filenames.
        bucket_name (str): S3 bucket name.
        folder_name (str): Path prefix.

    Returns:
        list[str]: List of full S3 URIs.
    """
    return add_prefix(files, bucket_name, folder_name)
