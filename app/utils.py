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
    # elif (know_base == 'rnd') :
    #     know_base_id = RND_KB_ID   
    elif (know_base == 'alexion') :
        know_base_id = ALEXION_ID        
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


PROMPT_TEMPLATE = """
<s>[INST] <<SYS>>
You are a helpful and precise assistant specializing in analyzing document content and leveraging conversation history to answer user questions.

Your primary task is to answer the user's question based on the content of the provided document AND any relevant information from previous chat interactions within the same session. Pay close attention to the document content and prior conversation history, referencing them directly when answering the question. If information is contained within the document, then provide the information directly and not simply state 'The document contains the answer to your question'.
**Under no circumstances should you include phrases like "Thank you," "You're welcome," "I hope this helps," or any similar expressions. Your responses must be factual and directly answer the user's question.**

First, identify whether the user's query is a request for a summary or a direct question:
1. **If the user's query is a request for a summary:**
   **Summary:** (Two sentences) A brief overview of the document's main points.
   **Parties Involved:** Identify the key parties or entities mentioned in the document.
   **Payment Terms:** Describe the payment terms, including amounts, frequency, and methods.
   **Contract Duration/Expiry Date:** State the contract's duration or the expiry date, if specified.
   **Liability Cap and Exclusions:** Summarize any limitations or exclusions of liability.
   **Scope of Work and Associated Costs:** Provide a concise overview of the work to be performed and associated costs.
   When providing the summary, do not include the terms "Start of Summary" and "End of Summary" in the response.

2. **If the user's query is a direct question (e.g., "What are the payment terms?"):**
   Extract the relevant information from the document and chat history to provide a direct and accurate answer. Cite the source of the information (document or conversation history).


If the document and chat history do not contain the answer to the user's question, state that you cannot provide an answer based on the available information.

**PLEASE PAY CLOSE ATTENTION**: Validate if the USER_QUERY is not relevant to the document content (including previous chat interactions) using cosine similarity. If the cosine similarity is below the relevance threshold **OR if you have responded with "I cannot answer this question based on the available information.", then append the keyword 'IRRELEVANT_TOPIC' to the end of your answer.** Do not add any extra words or phrases.
**Do not add any closing statements like 'Thank you' or similar.**

<</SYS>>

Document Content:
{content}

User Query:
{Query} [/INST]
"""



def generate_prompt(content: str, Query: str) -> str:
    prompt = PromptTemplate(
        input_variables=["content", "Query"], #Keep content here 
        template=PROMPT_TEMPLATE,
    )
    # Format the prompt with the provided values
    formatted_prompt = prompt.format(content=content, Query=Query) #format content here 
    return formatted_prompt


# def generate_prompt(content: str, additional_instructions: Optional[str]) -> str:
#     """Generate a prompt for the language model based on content and additional instructions."""
#     # Define the base template for the prompt
#     base_template = """
#     %INSTRUCTIONS:
#     Your task is to summarize the document content. Use the content if its already present in the previous chat interactions.The summary should include the following six sections: Summary (two sentences), Parties involved, Payment terms, Contract duration/expiry date, Liability cap and exclusions, Summary of the scope of work and associated costs.Please validate if the USER_QUERY is not relevant to the document content using cosine similarity and append only the keyword, not extra words or phrase - 'IRRELEVANT_TOPIC' at the end of original answer."    
#     """
#     # Add the content of the file to the template
#     if content:
#         base_template += f"\n\n%TEXT:\n{content}\n"
        
#     # Append the user query (additional instructions) if provided
#     if additional_instructions:
#         base_template += f"\n\n%USER QUERY:\n{additional_instructions}\n"

#     # The PromptTemplate can now be created using the combined template
#     prompt = PromptTemplate(
#         input_variables=[],  # No need for dynamic variables here as we have formatted the string manually
#         template=base_template,
#     )
#     # Return the final prompt with all components
#     return base_template

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
            
# def validate_api_key(apiKey: str):
#     try:       
#         if not apiKey or apiKey != API_KEY:
#             return True
#         return False
#     except Exception as e:
#         print(str(e))
#         raise HTTPException(status_code=500, detail=f"Authentication verification failed {str(e)}")
    
def validate_api_key(apiKey: str) -> bool:
    try:
        if apiKey and apiKey == API_KEY: 
            return True  
        else:
            return False 
    except Exception as e:
        print(str(e))
        raise HTTPException(status_code=500, detail=f"Authentication verification failed: {str(e)}")