# services/storage.py
"""S3 helpers & URI utilities."""

from __future__ import annotations

from io import BytesIO
from typing import Sequence

import pandas as pd

from .clients import s3_client
from .config import BUCKET_CONTAINER, logger


def s3_uri(bucket: str, key: str) -> str:
    return f"s3://{bucket}/{key}"


def add_prefix(files: Sequence[str], bucket: str, folder: str) -> list[str]:
    """
    Return full S3 URIs for *files* that live in *bucket/folder/*.

    Ensures there is always a single “/” between the folder name and the
    filename, regardless of whether *folder* already ends with “/”.
    """
    folder_clean = folder.rstrip("/")  # remove any accidental trailing slash
    prefix = f"s3://{bucket}/{folder_clean}/"
    return [f"{prefix}{file}" for file in files]


def read_excel_from_s3(key: str, sheet: str) -> pd.DataFrame:
    try:
        obj = s3_client.get_object(Bucket=BUCKET_CONTAINER, Key=key)
        return pd.read_excel(BytesIO(obj["Body"].read()), sheet_name=sheet)
    except Exception as exc:  # noqa: BLE001
        logger.error("Unable to fetch mapping sheet %s — %s", key, exc)
        raise


def get_s3_path(bucket_name: str, folder_name: str) -> str:  # noqa: N802
    """Backwards alias for legacy function name."""
    return s3_uri(bucket_name, folder_name)


def add_s3_prefix_to_files(  # noqa: N802
    files: Sequence[str], bucket_name: str, folder_name: str
) -> list[str]:
    """Backwards alias for legacy function name."""
    return add_prefix(files, bucket_name, folder_name)
