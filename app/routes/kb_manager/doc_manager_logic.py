from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
import boto3
from config import get_secret
import os
from tempfile import NamedTemporaryFile

try:
    from docx2pdf import convert as docx2pdf_convert
except ImportError:
    docx2pdf_convert = None

doc_manager_router = APIRouter()


class DocumentManager:
    """
    Handles S3 document operations for admin KB management.
    Supports listing, uploading (multi-file), updating (single-file), and deleting (multi-file).
    """

    def __init__(self, bucket: str):
        self.bucket = bucket
        self.s3 = boto3.client("s3")

    def list_documents(self, folder: str):
        """
        List all documents in the specified folder in the S3 bucket.
        Args:
            folder (str): The folder (prefix) to list docs from (e.g., 'general', 'privacy').
        Returns:
            list[str]: List of document keys (filenames only).
        """
        prefix = f"{folder}/"
        response = self.s3.list_objects_v2(Bucket=self.bucket, Prefix=prefix)
        return [obj["Key"].replace(prefix, "") for obj in response.get("Contents", []) if obj["Key"] != prefix]

    def upload_documents(self, folder: str, files: list[UploadFile]):
        """
        Upload multiple documents to S3. Converts .docx to .pdf if needed.
        Args:
            folder (str): The folder (prefix) to upload docs to (e.g., 'general', 'privacy').
            files (list[UploadFile]): The files to upload.
        Returns:
            list[dict]: List of upload status and filenames.
        """
        prefix = f"{folder}/"
        uploaded = []
        existing_files = self.list_documents(folder)
        for file in files:
            filename = file.filename
            if filename.lower().endswith(".docx"):
                filename = filename.rsplit(".", 1)[0] + ".pdf"
            if filename in existing_files:
                uploaded.append({"filename": filename, "status": "exists"})
                continue
            # Upload logic
            key = prefix + filename
            if file.filename.lower().endswith(".docx"):
                if not docx2pdf_convert:
                    raise HTTPException(status_code=500, detail="docx2pdf is not installed on the server.")
                with NamedTemporaryFile(delete=False, suffix=".docx") as tmp_docx:
                    tmp_docx.write(file.file.read())
                    tmp_docx.flush()
                    pdf_path = tmp_docx.name.replace(".docx", ".pdf")
                    docx2pdf_convert(tmp_docx.name, pdf_path)
                with open(pdf_path, "rb") as pdf_file:
                    self.s3.upload_fileobj(pdf_file, self.bucket, key)
                os.remove(tmp_docx.name)
                os.remove(pdf_path)
            elif file.filename.lower().endswith(".pdf"):
                self.s3.upload_fileobj(file.file, self.bucket, key)
            else:
                uploaded.append({"filename": filename, "status": "unsupported"})
                continue
            uploaded.append({"filename": filename, "status": "uploaded"})
        return uploaded

    def update_document(self, folder: str, file: UploadFile):
        """
        Update a document in S3. Converts .docx to .pdf if needed.
        Args:
            folder (str): The folder (prefix) to update doc in (e.g., 'general', 'privacy').
            file (UploadFile): The file to update.
        Returns:
            dict: Update status and filename.
        """
        prefix = f"{folder}/"
        filename = file.filename
        if filename.lower().endswith(".docx"):
            filename = filename.rsplit(".", 1)[0] + ".pdf"
        existing_files = self.list_documents(folder)
        if filename not in existing_files:
            raise HTTPException(
                status_code=404, detail=f"No file named '{filename}' found in '{folder}'. Use upload for new files."
            )
        key = prefix + filename
        # Overwrite logic
        if file.filename.lower().endswith(".docx"):
            if not docx2pdf_convert:
                raise HTTPException(status_code=500, detail="docx2pdf is not installed on the server.")
            with NamedTemporaryFile(delete=False, suffix=".docx") as tmp_docx:
                tmp_docx.write(file.file.read())
                tmp_docx.flush()
                pdf_path = tmp_docx.name.replace(".docx", ".pdf")
                docx2pdf_convert(tmp_docx.name, pdf_path)
            with open(pdf_path, "rb") as pdf_file:
                self.s3.upload_fileobj(pdf_file, self.bucket, key)
            os.remove(tmp_docx.name)
            os.remove(pdf_path)
        elif file.filename.lower().endswith(".pdf"):
            self.s3.upload_fileobj(file.file, self.bucket, key)
        else:
            raise HTTPException(status_code=400, detail="Only .pdf or .docx files are supported.")
        return {"filename": filename, "status": "updated"}

    def delete_documents(self, folder: str, filenames: list[str]):
        """
        Delete multiple documents from S3.
        Args:
            folder (str): The folder (prefix) to delete docs from (e.g., 'general', 'privacy').
            filenames (list[str]): The files to delete.
        Returns:
            list[dict]: List of deletion status and filenames.
        """
        prefix = f"{folder}/"
        deleted = []
        for filename in filenames:
            key = prefix + filename
            self.s3.delete_object(Bucket=self.bucket, Key=key)
            deleted.append({"filename": filename, "status": "deleted"})
        return deleted
