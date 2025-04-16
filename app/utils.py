import io
import logging
import re
from io import BytesIO
from pathlib import Path

import boto3
import PyPDF2
from botocore.config import Config
from config import get_config_value
from data import (
    Feedback,
    FeedbackDisplayOptions,
    QueryResponse,
    Result,
)
from docx import Document
from fastapi import HTTPException
from langchain_core.prompts import PromptTemplate
from langchain_aws import ChatBedrock
logger = logging.getLogger(__name__)
boto_config = Config(retries={"max_attempts": 3}, max_pool_connections=50)
s3_client = boto3.client("s3", config=boto_config)

ERROR_MESSAGE = "Oops! It seems there’s a network issue. Please check your connection and try again in a moment."

REGION_ID = get_config_value("REGION_ID")
TABLE_NAME = get_config_value("TABLE_NAME")
BUCKET_NAME = get_config_value("BUCKET_NAME")
PRIVACY_KB_ID = get_config_value("PRIVACY_KB_ID")
ALEXION_ID = get_config_value("ALEXION_ID")
GEN_ENQ_KB_ID = get_config_value("GEN_ENQ_KB_ID")
API_KEY = get_config_value("API_KEY")

keyword_llm = ChatBedrock(
    model_id="anthropic.claude-3-haiku-20240307-v1:0",
    model_kwargs={"temperature": 0},
)

def extract_keywords_from_query(query: str, max_char: int = 2000) -> str:
    """
    Extracts a compact set of keywords from the user's query for indexing.
    Returns a comma-separated, lowercase string of keywords.
    """
    if not query or not query.strip():
        return ""

    prompt = f"""
    Extract the most meaningful keywords up to {max_char} characters from the following user query to help with document search indexing.
    - Use lowercase only
    - Exclude stopwords and punctuation
    - Return keywords as a comma-separated list

    Query:
    {query}
    """

    try:
        response = keyword_llm.invoke(prompt)
        keywords = response.content.strip()
        logger.info(f"[Keyword Extractor] Extracted keywords: {keywords}")
        return keywords
    except Exception as e:
        logger.warning(f"[Keyword Extractor] Claude failed to extract keywords: {e}")
        return query[:2046].lower()

def generate_technical_error_message(
    msg_id, transaction_count, user_query, sessionId, exc: Exception = None
):
    if exc:
        error_message = str(exc)
    else:
        error_message = "An unexpected error occurred. Please try again later."

    feedbackoptions = FeedbackDisplayOptions(
        thumbsUp="N", thumbsDown="N", feedbackText="N"
    )
    feedback = Feedback(feedbackDisplayOptions=feedbackoptions)
    result = Result(
        messageId=str(msg_id),
        answer=error_message,
        transactionCount=transaction_count,
        feedback=feedback,
    )
    queryResponse = QueryResponse(
        status="error", sessionId=sessionId, userQuery=user_query, result=result
    )
    return queryResponse


def get_knowledge_base_id(data: str):
    know_base = data.lower()
    know_base_id = ""
    if know_base == "privacy":
        know_base_id = PRIVACY_KB_ID
    # elif (know_base == 'rnd') :
    #     know_base_id = RND_KB_ID
    elif know_base == "alexion":
        know_base_id = ALEXION_ID
    else:
        know_base_id = GEN_ENQ_KB_ID
    return know_base_id


def get_knowledge_base_folder(data: str):
    know_base = data.lower()
    know_base_id = ""
    if know_base == "privacy":
        know_base_folder = know_base
    elif know_base == "alexion":
        know_base_folder = know_base
    else:
        know_base_folder = "general"
    return know_base_folder


def generate_presigned_url(s3_url: str, page_number: int, expiration=3600):
    # Initialize the S3 client
    try:
        expiration = int(expiration)  # Expiration time in seconds
    except ValueError:
        logger.info("Invalid expiration time: must be an integer.")
        return None
    # Parse the S3 URL to extract the bucket and key
    pattern = r"s3://([^/]+)/(.+)"
    match = re.match(pattern, s3_url)
    if not match:
        logger.info("Invalid S3 URL format. Must start with 's3://'.")
        return None
    bucket_name = str(match.group(1)).strip()
    object_key = str(match.group(2)).strip()
    # Generate presigned URL
    try:
        presigned_url = s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket_name, "Key": object_key},
            ExpiresIn=expiration,  # Expiration in seconds
        )
        return presigned_url + "#page=" + str(page_number)
    except Exception as e:
        logger.info(f"Error generating presigned URL: {e}")
        return None


def extract_file_locations(data):
    citations_list = []
    for citation in data.get("citations", []):
        for reference in citation.get("retrievedReferences", []):
            # Extract the necessary fields for each citation
            page_number = reference.get("metadata", {}).get(
                "x-amz-bedrock-kb-document-page-number"
            )
            file_path = generate_presigned_url(
                reference.get("location", {}).get("s3Location", {}).get("uri", ""),
                page_number,
            )
            citation_object = {
                "filePath": file_path if isinstance(file_path, str) else str(file_path),
                "pageNumber": int(page_number) if page_number is not None else 0,
                "fileName": get_filename_from_path(
                    reference.get("location", {}).get("s3Location", {}).get("uri", "")
                ),
            }
            # Check if the citation_object already exists in the list
            is_duplicate = any(
                (
                    item["fileName"] == citation_object["fileName"]
                    and (
                        item["pageNumber"] == citation_object["pageNumber"]
                        or item["pageNumber"] == 0
                        or citation_object["pageNumber"] == 0
                    )
                )
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
        logger.info(f"ValueError: {ve}")
    except Exception as e:
        logger.info(f"An unexpected error occurred 1: {e}")
    return filename

# PROMPT_TEMPLATE_RISK = """Your task is to identify below clauses from the content - 
# Termination Clause - Depending upon the penalties , whether its severe , moderate or minimal
# Liability Clause - High, moderate or low liability caps.
# Compliance Requirements - find out the compliance based upon regulations.
# Sustainability Terms - Find out the sustainability commitments based upon environmental practices
# Spend Under Contract - based upon budget or financial thresholds
# Payment Terms - find out whether the payment terms are balanced,favourable or unfavourable"""

# PROMPT_TEMPLATE_RISK  = """Your task is provide various clauses mentioned in the contract and cater them firstly on the basis of High, Medium and Low Importance and then tell the High, medium , low Risks for tha particular importance based on the Clauses definition given below - 
# Contract: {Contract} 
# Clauses: {Clauses}
# Now answer the query
# User Query:
# {Query}
# """


PROMPT_TEMPLATE_RISK  = """You are an expert in procurement, specializing in analyzing contract clauses and assessing associated risks. 
Instructions:
-Extract Clauses: Begin by thoroughly analyzing the entire contract to identify and extract relevant clauses.
-Risk Evaluation: Utilize the provided risk rules checklist to evaluate each clause for potential risks.
-Risk Classification: Assign a risk level to each clause — High, Medium, or Low — based on your assessment.
-Addressing Ambiguities: If you encounter any ambiguities regarding the risk level, clearly inform the user of the uncertainty.
-Prioritized Results: Present the assessment results in the order of priority, starting with High-risk clauses, followed by Medium and Low-risk ones.
-Accuracy Compliance: Ensure all information is factual; avoid fabricating any details.

Context Information:
Contract: {Contract} 
Clauses: {Clauses}
User Query Handling: Now address the user's query by providing the requested analysis based on the above instructions.
User Query: {Query}
"""


PROMPT_TEMPLATE = """

You are a helpful and precise assistant specializing in analyzing document content and leveraging conversation history to answer user questions.

Your primary task is to answer the user's question based on the content of the provided document AND any relevant information from previous chat interactions within the same session. Pay close attention to the document content and prior conversation history, referencing them directly when answering the question. If information is contained within the document, then provide the information directly and not simply state 'The document contains the answer to your question'.
**Under no circumstances should you include phrases like "Thank you," "You're welcome," "I hope this helps," or any similar expressions. Your responses must be factual and directly answer the user's question.**

First, identify whether the user's query is a request for a summary or a direct question:
1. **If the user's query is a request for a summary:**
   Summary: (Two sentences) A brief overview of the document's main points.
   Parties Involved: Identify the key parties or entities mentioned in the document.
   Payment Terms: Describe the payment terms, including amounts, frequency, and methods.
   Contract Duration/Expiry Date: State the contract's duration or the expiry date, if specified.
   Liability Cap and Exclusions: Summarize any limitations or exclusions of liability.
   Scope of Work and Associated Costs: Provide a concise overview of the work to be performed and associated costs.
   When providing the summary, do not include the terms "Start of Summary" and "End of Summary" in the response.

2. **If the user's query is a direct question (e.g., "What are the payment terms?"):**
   Extract the relevant information from the document and chat history to provide a direct and accurate answer. Cite the source of the information (document or conversation history).


If the document and chat history do not contain the answer to the user's question, state that you cannot provide an answer based on the available information.

**PLEASE PAY CLOSE ATTENTION**: Validate if the USER_QUERY is not relevant to the document content (including previous chat interactions) using cosine similarity. If the cosine similarity is below the relevance threshold **OR if you have responded with "I cannot answer this question based on the available information.", then append the keyword 'IRRELEVANT_TOPIC' to the end of your answer.** Do not add any extra words or phrases.
**Do not add any closing statements like 'Thank you' or similar.**

Document Content:
{content}

User Query:
{Query}
"""

clause_file_path = "mappings/risk_matrix.txt"


def get_clause_details():
    try:
        response = s3_client.get_object(Bucket=BUCKET_NAME, Key=clause_file_path)
        txt_file_content = response["Body"].read().decode('utf-8') 
    except Exception as e:
        print(f"ERROR: Error in retrieving template. Reason: {e}")
        raise Exception(f"Error in retrieving template: {e}")
    return txt_file_content


def generate_prompt(content: str, Query: str,template:str) -> str:
    prompt = PromptTemplate(
        input_variables=["content", "Query"], #Keep content here 
        template=template,
    )
    # Format the prompt with the provided values
    formatted_prompt = prompt.format(content=content, Query=Query) #format content here 
    return formatted_prompt



def generate_prompt_risk(contract: str,clauses: str, Query: str,template:str) -> str:
    """prompt template to find the risks involved in the contract"""
    prompt = PromptTemplate(
        input_variables=["contract", "clauses", "Query"],  # Keep content here
        template=template,
    )
    # Format the prompt with the provided values
    formatted_prompt = prompt.format(Contract=contract,Clauses=clauses,Query=Query)  # format content here
    return formatted_prompt



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
        text = ""
        for para in doc.paragraphs:
            text += para.text + "\n"
        return text
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error reading file: {str(e)}")


# def validate_api_key(apiKey: str):
#     try:
#         if not apiKey or apiKey != API_KEY:
#             return True
#         return False
#     except Exception as e:
#         logger.info(str(e))
#         raise HTTPException(status_code=500, detail=f"Authentication verification failed {str(e)}")


def validate_api_key(apiKey: str) -> bool:
    try:
        if apiKey and apiKey == API_KEY:
            return True
        else:
            return False
    except Exception as e:
        logger.info(str(e))
        raise HTTPException(
            status_code=500, detail=f"Authentication verification failed: {str(e)}"
        )


def extract_chat_history(data):
    chat_history = []
    # Check if the data is in the expected format
    if not isinstance(data, dict):
        logger.info("Error: Input data must be a dictionary.")
        return chat_history

    # Iterate through the dictionary (assuming the keys are session IDs)
    for session_id, messages in data.items():
        if not isinstance(messages, list):
            logger.info(
                f"Warning: Session {session_id} does not contain a list of messages. Skipping."
            )
            continue  # Skip to the next session

        for message in messages:
            if not isinstance(message, dict):
                logger.info(
                    f"Warning: Invalid message format in session {session_id}. Skipping."
                )
                continue  # skip to next message

            try:
                question = message.get(
                    "UserMessageSearch"
                )  # Use get() to handle missing keys
                answer = message.get("BotResponse")

                if (
                    question and answer
                ):  # Only add if both question and answer are present
                    chat_history.append((question, answer))
                else:
                    if not question:
                        logger.info(
                            f"Warning: Missing 'UserMessageSearch' in message from session {session_id}."
                        )
                    if not answer:
                        logger.info(
                            f"Warning: Missing 'BotResponse' in message from session {session_id}."
                        )
            except Exception as e:
                logger.info(f"Error processing message in session {session_id}: {e}")
                continue  # Continue to the next message

    return chat_history
