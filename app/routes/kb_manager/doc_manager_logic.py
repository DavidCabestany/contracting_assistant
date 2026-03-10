"""S3 document manager logic for KB administration."""

from __future__ import annotations

from typing import BinaryIO

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException, UploadFile


ALLOWED_FOLDERS = {"general", "privacy"}


class DocumentManager:
    """Manage KB documents stored in an S3 bucket.

    This class supports:
      - Listing files in a folder.
      - Uploading multiple files while skipping existing ones.
      - Updating one or multiple files only if they already exist.
      - Deleting one or multiple files.
      - Uploading a DOCX file, converting it to PDF, and uploading the PDF.

    Attributes:
        bucket: Name of the target S3 bucket.
        s3: Boto3 S3 client.
    """

    def __init__(self, bucket: str) -> None:
        """Initialize the document manager.

        Args:
            bucket: Name of the S3 bucket.
        """
        self.bucket = bucket
        self.s3 = boto3.client("s3")

    def _validate_folder(self, folder: str) -> None:
        """Validate that the folder is allowed.

        Args:
            folder: Folder name requested by the caller.

        Raises:
            HTTPException: If the folder is not allowed.
        """
        if folder not in ALLOWED_FOLDERS:
            raise HTTPException(
                status_code=400,
                detail=(f"Invalid folder '{folder}'. " f"Allowed folders: {sorted(ALLOWED_FOLDERS)}."),
            )

    def _get_prefix(self, folder: str) -> str:
        """Build the S3 prefix for a folder.

        Args:
            folder: Folder name.

        Returns:
            S3 prefix ending with '/'.
        """
        self._validate_folder(folder)
        return f"{folder}/"

    def _list_existing_files(self, folder: str) -> set[str]:
        """Return the set of existing file names in a folder.

        Args:
            folder: Folder name.

        Returns:
            Set of file names present in the folder.
        """
        return set(doc["filename"] for doc in self.list_documents(folder))

    def _seek_to_start(self, file_obj: BinaryIO) -> None:
        """Move a file-like object cursor to the start when possible.

        Args:
            file_obj: File-like object.
        """
        if hasattr(file_obj, "seek"):
            file_obj.seek(0)

    def _upload_stream(self, file_obj: BinaryIO, key: str) -> None:
        """Upload a file-like object to S3.

        Args:
            file_obj: Open file-like object in binary mode.
            key: Target S3 object key.

        Raises:
            HTTPException: If the upload fails.
        """
        try:
            self._seek_to_start(file_obj)
            self.s3.upload_fileobj(file_obj, self.bucket, key)
        except (ClientError, BotoCoreError) as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to upload file to S3: {exc}",
            ) from exc

    def _build_result(
        self,
        filename: str,
        status: str,
        detail: str | None = None,
    ) -> dict[str, str]:
        """Build a standardized result dictionary.

        Args:
            filename: File name.
            status: Result status.
            detail: Optional error or extra detail.

        Returns:
            Result dictionary.
        """
        result = {"filename": filename, "status": status}
        if detail is not None:
            result["detail"] = detail
        return result

    def _process_documents(
        self,
        folder: str,
        files: list[UploadFile],
        must_exist: bool,
    ) -> list[dict[str, str]]:
        """Process upload or update operations for multiple files.

        Args:
            folder: Target folder.
            files: Uploaded files to process.
            must_exist: Whether each file must already exist in S3.

        Returns:
            A list of per-file result dictionaries.
        """
        prefix = self._get_prefix(folder)
        existing_files = self._list_existing_files(folder)
        results: list[dict[str, str]] = []

        for file in files:
            if not file.filename:
                results.append(self._build_result("unknown", "invalid"))
                continue

            filename = file.filename
            key = prefix + filename
            exists = filename in existing_files

            if must_exist and not exists:
                results.append(self._build_result(filename, "not_found"))
                continue

            if not must_exist and exists:
                results.append(self._build_result(filename, "exists"))
                continue

            try:
                self._upload_stream(file.file, key)
                status = "updated" if must_exist else "uploaded"
                results.append(self._build_result(filename, status))

                # Prevent duplicate uploads of the same file name
                # within the same request.
                existing_files.add(filename)
            except HTTPException as exc:
                results.append(
                    self._build_result(
                        filename,
                        "error",
                        str(exc.detail),
                    )
                )

        return results

    def list_documents(self, folder: str) -> list[dict]:
        """List all files in the selected folder, including creation timestamp.

        Args:
            folder: Folder name, such as 'general' or 'privacy'.

        Returns:
            List of dictionaries with file name and creation timestamp.

        Raises:
            HTTPException: If S3 listing fails.
        """
        prefix = self._get_prefix(folder)
        paginator = self.s3.get_paginator("list_objects_v2")
        documents: list[dict] = []

        try:
            for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    if key != prefix:
                        documents.append(
                            {
                                "filename": key.replace(prefix, "", 1),
                                "timestamp": obj.get("LastModified").isoformat() if obj.get("LastModified") else None,
                            }
                        )
        except (ClientError, BotoCoreError) as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to list documents from S3: {exc}",
            ) from exc

        return documents

    def upload_documents(
        self,
        folder: str,
        files: list[UploadFile],
    ) -> list[dict[str, str]]:
        """Upload multiple files and skip those that already exist.

        Args:
            folder: Target folder.
            files: Uploaded files to store.

        Returns:
            A list of per-file result dictionaries with filename and status.
        """
        return self._process_documents(folder=folder, files=files, must_exist=False)

    def update_documents(
        self,
        folder: str,
        files: list[UploadFile],
    ) -> list[dict[str, str]]:
        """Update one or multiple files only if they already exist.

        Args:
            folder: Target folder.
            files: Uploaded files that should replace existing objects.

        Returns:
            A list of per-file result dictionaries with filename and status.
        """
        return self._process_documents(folder=folder, files=files, must_exist=True)

    def delete_documents(
        self,
        folder: str,
        filenames: list[str],
    ) -> list[dict[str, str]]:
        """Delete one or multiple files from a folder.

        Args:
            folder: Target folder.
            filenames: List of file names to delete.

        Returns:
            A list of per-file result dictionaries with filename and status.
        """
        prefix = self._get_prefix(folder)
        existing_files = self._list_existing_files(folder)
        results: list[dict[str, str]] = []

        for filename in filenames:
            if filename not in existing_files:
                results.append(self._build_result(filename, "not_found"))
                continue

            key = prefix + filename

            try:
                self.s3.delete_object(Bucket=self.bucket, Key=key)
                results.append(self._build_result(filename, "deleted"))

                # Keep local state in sync during the same request.
                existing_files.discard(filename)
            except (ClientError, BotoCoreError) as exc:
                results.append(
                    self._build_result(
                        filename,
                        "error",
                        str(exc),
                    )
                )

        return results

    def rename_document(self, folder: str, old_filename: str, new_filename: str) -> dict:
        """Rename a file in the selected folder.

        Args:
            folder: Folder name.
            old_filename: Current file name.
            new_filename: New file name.

        Returns:
            Result dictionary with status and detail.
        """
        prefix = self._get_prefix(folder)
        old_key = prefix + old_filename
        new_key = prefix + new_filename

        existing_files = self._list_existing_files(folder)
        if old_filename not in existing_files:
            return self._build_result(old_filename, "not_found", "File to rename does not exist.")

        if new_filename in existing_files:
            return self._build_result(new_filename, "exists", "Target filename already exists.")

        try:
            self.s3.copy_object(Bucket=self.bucket, CopySource={"Bucket": self.bucket, "Key": old_key}, Key=new_key)
            self.s3.delete_object(Bucket=self.bucket, Key=old_key)
            return self._build_result(old_filename, "renamed", f"Renamed to {new_filename}")
        except (ClientError, BotoCoreError) as exc:
            return self._build_result(old_filename, "error", str(exc))
