"""Routes and logic for generating document summaries and risk assessments."""

from __future__ import annotations

import datetime
import json
import logging
import re
import uuid
from typing import Optional, Union

import boto3
from auth.utils import verify_token
from botocore.exceptions import BotoCoreError, ClientError
from config import get_secret
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from langchain_aws import ChatBedrock
from langchain_core.messages import HumanMessage
from models import (
    ChatInteraction,
    ChatMetadata,
    Feedback,
    FeedbackDisplayOptions,
    QueryResponse,
    Result,
    RiskAssessmentAnswer,
    RiskAssessmentResponse,
)
from prompts import (
    BASE_PROMPT,
    RISK_MATRIX_ALL_RISKS_PROMPT,
    RISK_MATRIX_SPC_RISK_PROMPT,
    RISK_MITIGATION_PROMPT,
)
from pydantic import ValidationError
from routes.qna import (
    retrieve_and_generate,
)
from services.chat_history_service import store_interaction
from services.memory import ChatMessageHistory
from services.memory_helpers import load_history, save_history
from utils import (
    extract_keywords_from_query,
    extract_pdf_contents,
    extract_text_from_word,
    generate_prompt,
    generate_prompt_risk,
    get_file_type,
    get_risk_matrix_details,
    prompt_query_cat,
)

# Logger and configuration constants.
logger = logging.getLogger(__name__)

s3 = boto3.client("s3")
MAX_SEARCH_LEN = 2000
BUCKET_CONTAINER = get_secret("BUCKET_CONTAINER")
MODEL_ID = get_secret("MODEL_ID")
IRRELEVANT = get_secret("IRRELEVANT_KEYWORD")
SUMMARY_FLOW_NAME = get_secret("SUMMARY_FLOW_NAME")
PRIOR_DOC = "CAN HANDBOOK 4.0.pdf"

router = APIRouter(tags=["Summary"], dependencies=[Depends(verify_token)])


def _extract_json(text: str) -> dict | None:
    """Extract the first JSON object found in a text.

    Args:
        text: A string potentially containing JSON.

    Returns:
        A dictionary if a JSON object is found and parsed successfully, otherwise None.
    """
    cleaned = "\n".join(
        ln for ln in text.splitlines() if not ln.lstrip().startswith("```")
    ).strip()
    match = re.search(r"{.*}", cleaned, flags=re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _wrap_plain(ans: str) -> dict:
    """Wrap plain text answer in structured summary format.

    Args:
        ans: Free-text summary.

    Returns:
        A dictionary with default summary fields.
    """
    return {
        "ans": ans,
        "ContractualRisks": {},
        "StandardAZRisks": {},
        "AdditionalPotentialRisks": [],
        "similarities": [],
        "differences": [],
    }


# ... (imports and other functions like _extract_json, _wrap_plain remain the same) ...


def parse_llm_output_to_assessment(
    raw_json_dict: Optional[dict],
    msg_id: str = "parse",
    raw_llm_text_for_fallback: Optional[str] = None,
) -> Union[RiskAssessmentResponse, RiskAssessmentAnswer]:
    """Parses a pre-extracted JSON dictionary from LLM output into a structured `RiskAssessmentResponse` or `RiskAssessmentAnswer` Pydantic object.

    Args:
        raw_json_dict: Dictionary from initial JSON extraction
            of LLM output, or None if extraction failed.
        msg_id: Logger message ID. Defaults to "parse".
        raw_llm_text_for_fallback: Original raw LLM text,
            used if `raw_json_dict` is None or unparsable.

    Returns:
        A parsed Pydantic object (`RiskAssessmentResponse` or `RiskAssessmentAnswer`).
        This function will always return one of these types, using fallbacks if necessary.
    """
    # Handle cases where raw_json_dict is None or empty at the very beginning
    if not raw_json_dict:
        logger.warning(
            f"[{msg_id}] `raw_json_dict` is None or empty. Using fallback text."
        )
        fallback_text = (
            raw_llm_text_for_fallback
            if raw_llm_text_for_fallback
            else "No input data provided to parse."
        )
        # This call to _wrap_plain now uses the corrected version above
        return RiskAssessmentAnswer(**_wrap_plain(fallback_text))

    extracted_data: Optional[dict] = None

    # Attempt 1: Parse as RiskAssessmentResponse
    # The `answer` field within RiskAssessmentResponse is of type RiskAssessmentAnswer
    if "answer" in raw_json_dict and isinstance(
        raw_json_dict.get("answer"), dict
    ):
        try:
            # Pydantic will recursively validate. If raw_json_dict["answer"]
            # is missing ContractualRisks, default_factory will kick in.
            # If it provides an empty list for ContractualRisks, it *should* now fail here
            # if the structure isn't a valid dict for RiskCategory.
            response_obj = RiskAssessmentResponse(**raw_json_dict["answer"])
            logger.info(
                f"[{msg_id}] Successfully parsed as RiskAssessmentResponse structure."
            )
            return response_obj
        except ValidationError as e:
            logger.warning(
                f"[{msg_id}] Validation failed for RiskAssessmentResponse structure: {e.errors()}"
            )
            extracted_data = raw_json_dict.get("answer")
        except Exception as e:
            logger.error(
                f"[{msg_id}] Unexpected error parsing as RiskAssessmentResponse: {e}"
            )
            extracted_data = raw_json_dict.get("answer")

    if extracted_data is None:
        extracted_data = raw_json_dict  # Use the whole dict if 'answer' wasn't present or suitable

    # Attempt 2: Parse `extracted_data` as RiskAssessmentAnswer
    if isinstance(extracted_data, dict):
        try:
            # If extracted_data has ContractualRisks: [], this will fail as expected.
            # If ContractualRisks is missing, default_factory will create it.
            # If ContractualRisks: {}, default_factory within RiskCategory will fill its lists.
            parsed_obj = RiskAssessmentAnswer(**extracted_data)
            logger.info(
                f"[{msg_id}] Successfully parsed `extracted_data` as RiskAssessmentAnswer structure."
            )
            return parsed_obj
        except ValidationError as e:
            logger.warning(
                f"[{msg_id}] Validation failed for RiskAssessmentAnswer from `extracted_data`: {e.errors()}"
            )
        except Exception as e:
            logger.error(
                f"[{msg_id}] Unexpected error parsing `extracted_data` as RiskAssessmentAnswer: {e}"
            )

    # Attempt 3: "response" field contains a string (JSON or plain text)
    if (
        isinstance(extracted_data, dict)
        and "response" in extracted_data
        and isinstance(extracted_data["response"], str)
    ):
        text_from_response_field = extracted_data["response"]
        logger.info(
            f"[{msg_id}] Found 'response' field with string content. Attempting to process it."
        )
        nested_json_dict = _extract_json(text_from_response_field)
        if nested_json_dict:
            try:
                # If nested_json_dict has ContractualRisks: [], this will fail.
                parsed_obj = RiskAssessmentAnswer(**nested_json_dict)
                logger.info(
                    f"[{msg_id}] Successfully parsed nested JSON from 'response' field as RiskAssessmentAnswer."
                )
                return parsed_obj
            except ValidationError as e:
                logger.warning(
                    f"[{msg_id}] Validation failed for nested JSON in 'response': {e.errors()}. Using 'response' string as 'ans'."
                )
                return RiskAssessmentAnswer(
                    **_wrap_plain(text_from_response_field)
                )
            except Exception as e:
                logger.error(
                    f"[{msg_id}] Unexpected error parsing nested JSON in 'response': {e}. Using 'response' string as 'ans'."
                )
                return RiskAssessmentAnswer(
                    **_wrap_plain(text_from_response_field)
                )
        else:  # No valid nested JSON
            logger.info(
                f"[{msg_id}] Using plain text from 'response' field as 'ans'."
            )
            return RiskAssessmentAnswer(
                **_wrap_plain(text_from_response_field)
            )

    # Attempt 4: `extracted_data` has an "ans" field as a string (weakest structured fallback)
    if (
        isinstance(extracted_data, dict)
        and "ans" in extracted_data
        and isinstance(extracted_data["ans"], str)
    ):
        logger.info(
            f"[{msg_id}] `extracted_data` has 'ans' string. Using it via _wrap_plain."
        )
        return RiskAssessmentAnswer(**_wrap_plain(extracted_data["ans"]))

    # FINAL FALLBACK
    logger.warning(
        f"[{msg_id}] All structured parsing attempts for `raw_json_dict` failed. Using `raw_llm_text_for_fallback` or default."
    )
    fallback_text = (
        raw_llm_text_for_fallback
        if raw_llm_text_for_fallback
        else "Could not interpret LLM output into a structured format."
    )
    # This call to _wrap_plain now uses the corrected version
    return RiskAssessmentAnswer(**_wrap_plain(fallback_text))


def _fallback_kb(prompt: str, session_id: str, folder: str = "general") -> str:
    """Trigger fallback knowledge base search if model output is irrelevant.

    Args:
        prompt: The original full prompt.
        session_id: Current session ID.
        folder: Name of the knowledge folder (default is 'general').

    Returns:
        Text response from fallback knowledge base or empty string if failed.
    """
    try:
        resp = retrieve_and_generate(
            prompt,
            get_secret("GEN_ENQ_KB_ID"),
            session_id=session_id,
            kb_path=folder,
        )
        if resp.get("citations"):
            return resp["output"]["text"]
    except Exception:
        logger.exception("KB fallback failed")
    return ""


@router.post("/getsummary/")
async def generate_summary(
    file: UploadFile = File(None),
    apiKey: Optional[str] = Form(None),
    userId: Optional[str] = Form(None),
    sessionId: Optional[str] = Form(None),
    language: Optional[str] = Form(None),
    platform: Optional[str] = Form(None),
    queryText: Optional[str] = Form(None),
    transactionCount: Optional[str] = Form(None),
) -> QueryResponse:
    """Generate a document summary and risk analysis using an LLM.

    This endpoint accepts a file or plain query text. It handles:
    - File parsing and S3 upload
    - Query classification and prompt generation
    - LLM invocation
    - Result parsing, fallback handling, and response formatting

    Args:
        file: Optional uploaded document (PDF, DOC, DOCX).
        apiKey: Optional API key (currently unused).
        userId: Optional identifier of the user.
        sessionId: Optional session identifier.
        language: Optional language preference.
        platform: Optional source platform.
        queryText: Optional free-text user query.
        transactionCount: Optional transaction metadata.

    Returns:
        A QueryResponse object with structured result.
    """
    msg_id = str(uuid.uuid4())
    session_id = sessionId or str(uuid.uuid4())
    content = ""
    file_name = ""
    folder_path = ""
    answer = ""
    raw_answer = None

    # Step 1: Process uploaded file, if any
    if file is not None:
        try:
            # Read file and detect file type
            file_bytes = await file.read()
            ftype = get_file_type(file.filename)
            file_name = file.filename
            logger.info(
                f"[{msg_id}] File received: name={file_name}, type={ftype}"
            )
        except Exception as exc:
            logger.exception(f"[{msg_id}] Failed to read uploaded file")
            raise HTTPException(400, f"Error reading file: {exc}") from exc

        # Upload to S3
        folder_path = f"contracts/{userId or 'anonymous'}/{session_id}"
        try:
            s3.put_object(Bucket=BUCKET_CONTAINER, Key=f"{folder_path}/")
            s3.put_object(
                Bucket=BUCKET_CONTAINER,
                Key=f"{folder_path}/{file_name}",
                Body=file_bytes,
                ContentType=file.content_type,
            )
            logger.info(
                f"[{msg_id}] File uploaded to S3: {folder_path}/{file_name}"
            )
        except (BotoCoreError, ClientError) as exc:
            logger.exception(f"[{msg_id}] S3 upload failed")
            raise HTTPException(500, "S3 upload failed") from exc

        # Extract content
        try:
            if ftype == ".pdf":
                content = extract_pdf_contents(file_bytes)
            elif ftype in {".doc", ".docx"}:
                content = extract_text_from_word(file_bytes)
            else:
                raise ValueError(f"Unsupported file type: {ftype}")
            logger.debug(f"[{msg_id}] Extracted content from file")
        except Exception as exc:
            logger.exception(f"[{msg_id}] Failed to extract content from file")
            raise HTTPException(
                400, f"Failed to extract content: {exc}"
            ) from exc

    elif file is None and transactionCount != "0":
        file_bytes_for_processing = None
        file_name_for_processing = None
        logger.info(
            f"[{msg_id}] No new file uploaded. Attempting to read existing file from S3 for session."
        )
        s3_folder_prefix = f"contracts/{userId}/{session_id}/"
        retrieved_object_key = None
        try:
            list_response = s3.list_objects_v2(
                Bucket=BUCKET_CONTAINER, Prefix=s3_folder_prefix, MaxKeys=2
            )
            if (
                "Contents" in list_response
                and len(list_response["Contents"]) > 0
            ):
                potential_objects = list_response["Contents"]
                # Filter out the "folder" object itself if it exists
                actual_file_objects = [
                    obj
                    for obj in potential_objects
                    if obj["Key"] != s3_folder_prefix and obj["Size"] > 0
                ]
                if actual_file_objects:
                    retrieved_object_key = actual_file_objects[0][
                        "Key"
                    ]  # Take the first actual file
                    file_name_for_processing = retrieved_object_key.split("/")[
                        -1
                    ]
                    logger.info(
                        f"S3 List: Found object '{retrieved_object_key}' (filename: '{file_name_for_processing}') under prefix '{s3_folder_prefix}'."
                    )
                    # Now get the object content
                    obj_response = s3.get_object(
                        Bucket=BUCKET_CONTAINER, Key=retrieved_object_key
                    )
                    file_bytes_for_processing = obj_response["Body"].read()
                    logger.info(
                        f"Successfully read {len(file_bytes_for_processing)} bytes from S3 object '{retrieved_object_key}'."
                    )
                else:
                    logger.warning(
                        f"S3 List: No actual file objects found under prefix '{s3_folder_prefix}' in bucket '{BUCKET_CONTAINER}'. Only folder object or empty."
                    )
            else:
                logger.warning(
                    f"S3 List: No objects found under prefix '{s3_folder_prefix}' in bucket '{BUCKET_CONTAINER}'."
                )
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code")
            if error_code == "AccessDenied":
                logger.error(
                    f"S3 Error: Access Denied for listing/reading prefix '{s3_folder_prefix}'."
                )
                raise HTTPException(
                    500, "S3 access error for session file."
                ) from e
            else:
                logger.exception(
                    f"An S3 ClientError occurred for prefix '{s3_folder_prefix}': {e}"
                )
                raise HTTPException(
                    500, "S3 error retrieving session file."
                ) from e
        except Exception as e:
            logger.exception(
                f"An unexpected error occurred with S3 for prefix '{s3_folder_prefix}': {e}"
            )
            raise HTTPException(500, "Error retrieving session file.") from e

        if file_bytes_for_processing and file_name_for_processing:
            try:
                ftype = get_file_type(file_name_for_processing)
                logger.info(
                    f"[{msg_id}] Processing file: '{file_name_for_processing}', type: {ftype}"
                )
                if ftype == ".pdf":
                    content = extract_pdf_contents(file_bytes_for_processing)
                elif ftype in {".doc", ".docx"}:
                    content = extract_text_from_word(file_bytes_for_processing)
                elif (
                    ftype is None and file_bytes_for_processing
                ):  # Handle case where extension might be missing but we have bytes
                    logger.warning(
                        f"[{msg_id}] Could not determine file type for '{file_name_for_processing}'. Attempting as plain text."
                    )
                    try:
                        content = file_bytes_for_processing.decode(
                            "utf-8", errors="replace"
                        )
                    except Exception:
                        content = f"Binary content of {len(file_bytes_for_processing)} bytes (filename: {file_name_for_processing})."
                elif (
                    file_bytes_for_processing
                ):  # Has bytes, but type is not pdf/doc/docx and not None (e.g. .txt, .csv)
                    logger.info(
                        f"[{msg_id}] File type '{ftype}' not specifically handled for extraction, attempting decode as text."
                    )
                    try:
                        content = file_bytes_for_processing.decode(
                            "utf-8", errors="replace"
                        )
                    except Exception:
                        content = f"Content of {len(file_bytes_for_processing)} bytes for {file_name_for_processing} (type {ftype})."
                else:
                    # This case should ideally not be hit if file_bytes_for_processing is None already handled
                    logger.error(
                        f"[{msg_id}] Unsupported file type '{ftype}' or no bytes for file '{file_name_for_processing}'."
                    )
                    raise ValueError(
                        f"Unsupported file type or no data: {ftype}"
                    )
                logger.debug(
                    f"[{msg_id}] Extracted content from file '{file_name_for_processing}'"
                )
            except (
                ValueError
            ) as ve:  # Catch specific ValueError for unsupported types
                logger.error(
                    f"[{msg_id}] Value error during content extraction for '{file_name_for_processing}': {ve}"
                )
                raise HTTPException(400, str(ve)) from ve
            except Exception as exc:
                logger.exception(
                    f"[{msg_id}] Failed to extract content from file '{file_name_for_processing}'"
                )
                raise HTTPException(
                    400, f"Failed to extract content from file: {exc}"
                ) from exc
        else:
            logger.info(f"[{msg_id}] No file exists")
            raw_answer = "Please upload your contract first, then ask a specific question related to it."
            chat_mem: ChatMessageHistory = ChatMessageHistory(session_id)
            if not queryText or not queryText.strip():
                queryText = "No text was provided"
            logger.info(f"[{msg_id}] No queryText provided.")
    else:
        logger.info(f"[{msg_id}] No file is uploaded and its a first question")
        raw_answer = "Please upload your contract first, then ask a specific question related to it."
        chat_mem: ChatMessageHistory = ChatMessageHistory(session_id)
        if not queryText or not queryText.strip():
            queryText = "No text was provided"
            logger.info(f"[{msg_id}] No queryText provided.")

    if raw_answer is None:
        # Step 2: Load chat memory
        chat_mem: ChatMessageHistory = load_history(session_id)
        logger.debug(
            f"[{msg_id}] Loaded chat history with {len(chat_mem.messages)} messages"
        )

        history_block = "".join(
            ("User: " if isinstance(m, HumanMessage) else "Assistant: ")
            + m.content
            + "\n"
            for m in chat_mem.messages
        )
        body_prompt = ""

        # Step 3: Default query if none provided
        if not queryText or not queryText.strip():
            queryText = "Summarize the document content"
            logger.info(f"[{msg_id}] No queryText provided. Default applied.")
        # Step 4: Classify query
        try:
            cat_prompt = prompt_query_cat(queryText.lower())
            category = (
                ChatBedrock(model_id=MODEL_ID).invoke(cat_prompt).content
            )
            logger.info(f"[{msg_id}] Query category determined: {category}")
        except Exception as exc:
            logger.exception(f"[{msg_id}] Failed to classify query prompt")
            raise HTTPException(
                500, f"Error classifying prompt: {exc}"
            ) from exc

        # Step 5: Generate prompt based on category
        try:
            if category == "5":
                raw_answer = "Your question doesn't seem related to the contract you uploaded. Please ask something relevant to the document."
                answer = _wrap_plain(raw_answer)

            if category == "1":
                body_prompt = generate_prompt_risk(
                    content,
                    queryText,
                    RISK_MATRIX_SPC_RISK_PROMPT,
                    risk_rules=get_risk_matrix_details(),
                )
            elif category == "2":
                body_prompt = generate_prompt_risk(
                    content,
                    queryText,
                    RISK_MATRIX_ALL_RISKS_PROMPT,
                    risk_rules=get_risk_matrix_details(),
                )
            elif category == "3":
                body_prompt = generate_prompt(
                    content, queryText, RISK_MITIGATION_PROMPT
                )
            elif category == "4":
                body_prompt = generate_prompt(content, queryText, BASE_PROMPT)
            else:
                body_prompt = generate_prompt(content, queryText, BASE_PROMPT)
            logger.debug(f"[{msg_id}] Prompt built for LLM.")
        except Exception as exc:
            logger.exception(f"[{msg_id}] Failed to generate body prompt")
            raise HTTPException(
                500, f"Prompt generation failed: {exc}"
            ) from exc
        full_prompt = f"{history_block}{body_prompt}"
        logger.debug(
            f"[{msg_id}] Final prompt constructed (truncated):\n{full_prompt[:1000]}"
        )
        if category in ("1", "2", "4"):
            try:
                llm_resp = ChatBedrock(model_id=MODEL_ID,max_tokens=4000).invoke(full_prompt)
                raw_answer = llm_resp.content.strip()
                logger.info(f"[{msg_id}] LLM responded successfully")
                logger.debug(
                    f"[{msg_id}] Raw LLM response (truncated): {raw_answer[:1000]}"
                )
            except Exception as exc:
                logger.exception(f"[{msg_id}] LLM call failed")
                raise HTTPException(500, f"Error invoking LLM: {exc}") from exc

            # Step 7: Normalize response
            payload_json = _extract_json(raw_answer)
            payload = parse_llm_output_to_assessment(
                payload_json, msg_id, raw_llm_text_for_fallback=raw_answer
            )

            logger.debug(
                f"[{msg_id}] Primary JSON parsed: {payload is not None}"
            )

            if payload is None:
                inner = _extract_json(raw_answer.replace("```json", "```"))
                if inner and "response" in inner:
                    answer = _wrap_plain(inner["response"])
                    inner2 = _extract_json(answer["ans"])
                    if inner2 and "response" in inner2:
                        answer["ans"] = inner2["response"]
                    elif inner2:
                        inner2.setdefault("similarities", [])
                        inner2.setdefault("differences", [])
                        answer = inner2
                elif inner:
                    answer = inner | {"similarities": [], "differences": []}
                else:
                    answer = _wrap_plain(raw_answer)
                logger.debug(f"[{msg_id}] Applied fallback JSON normalization")
            elif "response" in payload:
                answer = _wrap_plain(payload["response"])
                logger.debug(f"[{msg_id}] Parsed from TEMPLATE scaffold")
            else:
                answer = payload.model_dump()
                # answer.setdefault("similarities", [])
                # answer.setdefault("differences", [])
                logger.debug(f"[{msg_id}] Used raw parsed JSON directly")
        else:
            if not isinstance(
                answer, (RiskAssessmentAnswer, RiskAssessmentResponse)
            ) and not isinstance(answer, dict):
                current_ans_text = (
                    raw_answer
                    if raw_answer
                    else "Response for this category is being processed."
                )
                answer = _wrap_plain(current_ans_text)

            logger.info("User requires Risk mitigation strategies")
        # Step 8: Fallback if response is irrelevant
        if IRRELEVANT in answer.get("ans") or "3" in category:
            logger.warning(
                f"[{msg_id}] Detected IRRELEVANT content or risk mitigation, trying KB fallback"
            )
            ##TODO:kgnp684 change the limit. 
            if len(full_prompt) > 18000:
                llm_resp = ChatBedrock(model_id=MODEL_ID).invoke(
                    full_prompt
                    + "User : Just provide the user history along with summarization of contract in 18000 character length so that my query can be answered"
                )
                query_summary = llm_resp.content.strip()
                full_prompt = query_summary + "User:" + queryText

            fb = _fallback_kb(full_prompt, session_id=None)
            if fb:
                raw_answer = fb
                payload = _extract_json(raw_answer)
                answer = (
                    _wrap_plain(payload["response"])
                    if payload and "response" in payload
                    else (
                        _wrap_plain(raw_answer) if payload is None else payload
                    )
                )
                if isinstance(answer, dict):
                    answer.setdefault("similarities", [])
                    answer.setdefault("differences", [])
                logger.info(f"[{msg_id}] Fallback response used")
    else:
        answer = _wrap_plain(raw_answer)
    # Step 9: Save chat history
    chat_mem.add_user_message(queryText)
    chat_mem.add_ai_message(raw_answer)
    save_history(chat_mem)
    logger.debug(f"[{msg_id}] Updated and saved chat history")

    # Step 10: Build API response
    feedback = Feedback(
        feedbackDisplayOptions=FeedbackDisplayOptions(
            thumbsUp="Y", thumbsDown="Y", feedbackText="Y"
        )
    )
    result = Result(
        messageId=msg_id,
        answer=answer,
        transactionCount=transactionCount,
        feedback=feedback,
    )
    api_resp = QueryResponse(
        status="success",
        sessionId=session_id,
        userQuery=queryText,
        result=result,
    )
    logger.info(f"[{msg_id}] Summary generation complete")

    # Step 11: Store interaction
    if userId:
        now = datetime.datetime.now().isoformat()
        file_loc = (
            f"{BUCKET_CONTAINER}{folder_path}{file_name}" if file_name else ""
        )
        store_interaction(
            ChatInteraction(
                UserId=userId,
                SessionId=session_id,
                UserMessage=queryText,
                UserMessageSearch=(
                    extract_keywords_from_query(queryText.lower())
                    if len(queryText) > MAX_SEARCH_LEN
                    else queryText.lower()
                ),
                BotResponse=raw_answer,
                BotResponseSearch=raw_answer.lower()[:MAX_SEARCH_LEN],
                FeedbackComment="",
                Timestamp=now,
                SessionStatus=get_secret("SESSION_STATUS_ACTIVE"),
                MessageId=msg_id,
                ChatMetadata=ChatMetadata(
                    FileName=file_name,
                    FileLocation=file_loc,
                    FlowName=SUMMARY_FLOW_NAME,
                    Department="",
                ),
            )
        )
        logger.info(f"[{msg_id}] Interaction stored for userId={userId}")

    return api_resp
