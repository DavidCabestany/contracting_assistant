from datetime import datetime, timedelta
from typing import Optional, List, Dict
import boto3
import re 
from pathlib import Path
from langchain_core.prompts import PromptTemplate
import PyPDF2
from io import BytesIO
from pathlib import Path
from PyPDF2 import PdfReader
from docx import Document
from botocore.config import Config
import io
from data import (
    QueryRequest, QnaAnswer, AnswerRequest, User, Query, RequestQuery, Citation, 
    QuickReply, Result, QueryResponse, FeedbackDisplayOptions, Feedback, ChatInteraction, ChatMetadata, ChatHistorySearchRequest, FeedbackRequest
)
from config import *

boto_config = Config(retries={'max_attempts': 3}, max_pool_connections=50)
s3_client = boto3.client('s3',config=boto_config)

ERROR_MESSAGE = "Oops! It seems there’s a network issue. Please check your connection and try again in a moment."

def generate_technical_error_message (msg_id, transaction_count , user_query, sessionId):        
        feedbackoptions = FeedbackDisplayOptions(thumbsUp="N", thumbsDown="N", feedbackText="N")
        feedback = Feedback(feedbackDisplayOptions=feedbackoptions)        
        result = Result(
            messageId=str(msg_id),
            answer=ERROR_MESSAGE,
            transactionCount=transaction_count,
            #citations=citations,
            feedback=feedback
        )        
        queryResponse = QueryResponse(
            status="error",
            sessionId=sessionId,
            userQuery=user_query,
            result=result
        )        
        return queryResponse

def get_knowledge_base_id(data: str):
    know_base = data.lower()
    know_base_id = ""
    if (know_base == 'privacy') :
        know_base_id = PRIVACY_KB_ID        
    elif (know_base == 'rnd') :
        know_base_id = RND_KB_ID        
    else:   
        know_base_id = GEN_ENQ_KB_ID
    return know_base_id

def generate_presigned_url(s3_url: str, page_number:int, expiration=3600):
    # Initialize the S3 client    
    try:
        expiration = int(expiration)  # Expiration time in seconds
    except ValueError:
        print("Invalid expiration time: must be an integer.")
        return None       
    # Parse the S3 URL to extract the bucket and key
    pattern = r's3://([^/]+)/(.+)'
    match = re.match(pattern, s3_url)
    if not match:
        print("Invalid S3 URL format. Must start with 's3://'.")
        return None
    bucket_name = str(match.group(1)).strip()
    object_key = str(match.group(2)).strip()
    # Generate presigned URL
    try:
        presigned_url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': bucket_name, 'Key': object_key},
            ExpiresIn=expiration  # Expiration in seconds
        )
        return presigned_url +"#page="+ str(page_number)
    except Exception as e:
        print(f"Error generating presigned URL: {e}")
        return None
    
def extract_file_locations(data):
    citations_list = []
    for citation in data.get("citations", []):
        for reference in citation.get("retrievedReferences", []):
            # Extract the necessary fields for each citation
            page_number = reference.get("metadata", {}).get("x-amz-bedrock-kb-document-page-number")
            file_path = generate_presigned_url(reference.get("location", {}).get("s3Location", {}).get("uri", ""), page_number)
            citation_object = {
                "filePath": file_path if isinstance(file_path, str) else str(file_path),
                "pageNumber": int(page_number) if page_number is not None else 0,
                "fileName": get_filename_from_path(reference.get("location", {}).get("s3Location", {}).get("uri", ""))
            }            
            # Check if the citation_object already exists in the list
            is_duplicate = any(
                (item["fileName"] == citation_object["fileName"] and 
                 (item["pageNumber"] == citation_object["pageNumber"] or item["pageNumber"] == 0 or citation_object["pageNumber"] == 0))
                for item in citations_list
            )            
            # Only add the citation_object if it's not a duplicate
            if not is_duplicate:
                citations_list.append(citation_object)
    return citations_list
    
def get_filename_from_path(s3_path):
    """Extract the filename from an S3 path."""
    filename = ""    
    try:
        # Validate that the input is a string
        if not isinstance(s3_path, str):
            raise ValueError("The S3 path must be a string.")
        # Check if the path starts with 's3://'
        if not s3_path.startswith("s3://"):
            raise ValueError("The S3 path must start with 's3://'.")
        # Extract the file name using Path
        filename = Path(s3_path).name        
    except ValueError as ve:
        print(f"ValueError: {ve}")
    except Exception as e:
        print(f"An unexpected error occurred 1: {e}")        
    return filename

    
def generate_prompt(content: str, additional_instructions: Optional[str]) -> str:
    """Generate a prompt for the language model based on content and additional instructions."""
    # Define the base template for the prompt
    base_template = """
    %INSTRUCTIONS:
    Your task is to summarize the document content. Use the content if its already present in the previous chat interactions.The summary should include the following six sections: Summary (two sentences), Parties involved, Payment terms, Contract duration/expiry date, Liability cap and exclusions, Summary of the scope of work and associated costs.Please validate if the USER_QUERY is not relevant to the document content using cosine similarity and append only the keyword, not extra words or phrase - 'IRRELEVANT_TOPIC' at the end of original answer."    
    """
    # Add the content of the file to the template
    if content:
        base_template += f"\n\n%TEXT:\n{content}\n"
        
    # Append the user query (additional instructions) if provided
    if additional_instructions:
        base_template += f"\n\n%USER QUERY:\n{additional_instructions}\n"

    # The PromptTemplate can now be created using the combined template
    prompt = PromptTemplate(
        input_variables=[],  # No need for dynamic variables here as we have formatted the string manually
        template=base_template,
    )
    # Return the final prompt with all components
    return base_template

def extract_pdf_contents(file_bytes: bytes) -> str:
    """Extract text content from a PDF file."""
    try:
        pdf_stream = BytesIO(file_bytes)
        reader = PyPDF2.PdfReader(pdf_stream)
        text = ""
        for page in range(len(reader.pages)):
            page_obj = reader.pages[page]
            text += page_obj.extract_text() or ""
        return text
    except Exception as e:
         raise HTTPException(status_code=400, detail=f"Error reading file: {str(e)}")
    
def get_file_type(file_name):
    try:
        return Path(file_name).suffix.lower()
    except Exception as e:
         raise HTTPException(status_code=400, detail=f"Error reading file: {str(e)}")

def extract_text_from_word(byte_array):
    try:
        doc_file = io.BytesIO(byte_array)    
        # Read the Word document
        doc = Document(doc_file)
        text = ''   
        for para in doc.paragraphs:
            text += para.text + '\n'        
        return text
    except Exception as e:
         raise HTTPException(status_code=400, detail=f"Error reading file: {str(e)}")