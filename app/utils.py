import io
import logging
import re
import os
from io import BytesIO
from pathlib import Path

import json
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
from data import RiskAssessmentResponse
from pydantic import ValidationError
from prompt_template import BUSINESS_UNIT_TEMPLATE, CATEGORY_TEMPLATE

logger = logging.getLogger(__name__)
boto_config = Config(retries={"max_attempts": 3}, max_pool_connections=50)
s3_client = boto3.client("s3", config=boto_config)

MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
risk_rules_file_path = os.path.join(MODULE_DIR, r"docs", "risk_rules.json")


ERROR_MESSAGE = "Oops! It seems there’s a network issue. Please check your connection and try again in a moment."

REGION_ID = get_config_value("REGION_ID")
TABLE_NAME = get_config_value("TABLE_NAME")
BUCKET_NAME = get_config_value("BUCKET_NAME")
PRIVACY_KB_ID = get_config_value("PRIVACY_KB_ID")
ALEXION_ID = get_config_value("ALEXION_ID")
GEN_ENQ_KB_ID = get_config_value("GEN_ENQ_KB_ID")
API_KEY = get_config_value("API_KEY")
MODEL_ID = get_config_value("MODEL_ID")

keyword_llm = ChatBedrock(
    model_id="anthropic.claude-3-haiku-20240307-v1:0",
    model_kwargs={"temperature": 0},
)


_CLASSIFY_PROMPT = """
    You are a routing agent.

    Return exactly one word:
    QUESTION - if the user asks anything, requests a comparison, or wants similarities / differences.
    SUMMARY - if they merely pasted text or explicitly ask "summarise".

    Examples
    ---------
    User: Summarise the following agreement.
    -> SUMMARY

    User: Compare clause 7 with the AZ standard and list similarities and differences.
    -> QUESTION

    User: What are the payment terms?
    -> QUESTION

    Now classify:
    {query}
"""


def needs_summary(query: str) -> bool:
    resp = ChatBedrock(model_id=MODEL_ID).invoke(
        _CLASSIFY_PROMPT.format(query=query.strip())
    )
    return resp.content.strip().upper() == "SUMMARY"


def llm_summarise(text: str) -> str:
    prompt = f"Give a concise summary in one descriptive paragraph:\n\n{text}"
    return ChatBedrock(model_id=MODEL_ID).invoke(prompt).content.strip()


def parse_risk_assessment_output(model_output: str) -> RiskAssessmentResponse:
    """
    Parses model output string into a RiskAssessmentResponse.
    """
    try:
        start = model_output.find("{")
        end = model_output.rfind("}") + 1
        json_str = model_output[start:end]
        parsed = json.loads(json_str)
        return RiskAssessmentResponse.parse_obj({"answer": parsed})
    except (json.JSONDecodeError, ValidationError) as e:
        raise ValueError(f"Parsing error: {str(e)}\nRaw Output:\n{model_output}")


def extract_keywords_from_query(query: str, max_char: int = 2000) -> str:
    """
    Extracts a compact set of keywords from the user's query for indexing.
    Returns a comma-separated, lowercase string of keywords.
    """
    if not query or not query.strip():
        return ""

    prompt = f"""
    Extract the most meaningful keywords up to {max_char} characters from the 
    following user query to help with document search indexing.
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

        return keywords[:2040]
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


def business_unit_prompt(query: str) -> str:
    """
    Formats a prompt template for determining the business unit based on the user's query.

    Args:
        query: The user's query string.
        business_unit_template: The prompt template for determining the business unit.

    Returns:
        The formatted prompt string.

    Raises:
        TypeError: If query or business_unit_template is not a string.
        ValueError: If query or business_unit_template is empty.
        Exception: If an unexpected error occurs during processing.
                   it will return the string "Business Unit unable to be classified"

    Example:
        formatted_prompt = get_business_unit("What are the risks of termination?", BUSINESS_UNIT_TEMPLATE)
    """

    # Input validation
    if not isinstance(query, str):
        raise TypeError("Query must be a string.")
    if not isinstance(BUSINESS_UNIT_TEMPLATE, str):
        raise TypeError("Business_unit_template must be a string.")
    if not query:
        raise ValueError("Query cannot be empty.")
    if not BUSINESS_UNIT_TEMPLATE:
        raise ValueError("Business_unit_template cannot be empty.")

    try:
        prompt = PromptTemplate(
            input_variables=["Query"],
            template=BUSINESS_UNIT_TEMPLATE,
        )
        formatted_prompt = prompt.format(Query=query)
        return formatted_prompt

    except Exception as e:
        logger.exception(f"An error occurred while formatting the prompt: {e}")
        return "Business Unit unable to be classified"


def get_risk_matrix_details() -> dict:
    """Returns risk rules from a JSON file.

    Args:
        file_path (str): The file path to the JSON file containing risk rules.

    Returns:
        dict: Risk rules data as a dictionary.
    """
    try:
        with open(risk_rules_file_path, "r", encoding="utf-8") as file:
            risk_rules = json.load(file)
    except FileNotFoundError:
        logger.info(f"ERROR: File not found: {risk_rules_file_path}")
        raise FileNotFoundError(f"File not found: {risk_rules_file_path}")
    except json.JSONDecodeError as e:
        logger.info(
            f"ERROR: Invalid JSON format in file: {risk_rules_file_path}. Reason: {e}"
        )
        raise json.JSONDecodeError(
            f"Invalid JSON format in file: {risk_rules_file_path}", e.doc, e.pos
        )
    except Exception as e:
        logger.info(
            f"ERROR: Error reading risk rules from file: {risk_rules_file_path}. Reason: {e}"
        )
        raise Exception(f"Error reading risk rules from file: {e}")

    return risk_rules


def generate_prompt(content: str, Query: str, template: str) -> str:
    prompt = PromptTemplate(
        input_variables=["content", "Query"],  # Keep content here
        template=template,
    )
    # Format the prompt with the provided values
    formatted_prompt = prompt.format(
        content=content, Query=Query
    )  # format content here
    return formatted_prompt


def generate_prompt_risk(
    contract: str, risk_rules: str, Query: str, template: str
) -> str:
    """prompt template to find the risks involved in the contract"""
    prompt = PromptTemplate(
        input_variables=["contract", "risk_rules", "Query"],  # Keep content here
        template=template,
    )
    # Format the prompt with the provided values
    formatted_prompt = prompt.format(
        Contract=contract, risk_rules=risk_rules, Query=Query
    )  # format content here
    return formatted_prompt


def prompt_query_cat(Query):
    prompt = PromptTemplate(input_variables=["Query"], template=CATEGORY_TEMPLATE)
    formatted_prompt = prompt.format(Query=Query)
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
            continue

        for message in messages:
            if not isinstance(message, dict):
                logger.info(
                    f"Warning: Invalid message format in session {session_id}. Skipping."
                )
                continue

            try:
                question = message.get("UserMessageSearch")
                answer = message.get("BotResponse")

                if question and answer:
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
