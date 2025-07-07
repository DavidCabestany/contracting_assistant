"""Routes and logic for generating document summaries and risk assessments."""

from __future__ import annotations

import datetime
import json
import logging
import os
import uuid
from typing import Optional

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
from prompts import (  # RISK_MATRIX_ALL_RISKS_PROMPT,; RISK_MATRIX_SPC_RISK_PROMPT,
    BASE_PROMPT,
    RISK_MITIGATION_PROMPT,
)
from routes.qna import (
    retrieve_and_generate,
)
from services.chat_history_service import store_interaction
from services.memory import ChatMessageHistory
from services.memory_helpers import load_history, save_history
from services.risk_categorization import (
    _extract_json,
    _wrap_plain,
    get_all_clauses_froms3,
    get_category4,
    get_risks_from_query,
    risk_categorization_fn,
)
from utils import (
    extract_keywords_from_query,
    extract_pdf_contents,
    extract_text_from_word,
    generate_prompt,
    get_clauses,
    get_contract_risk_from_s3,
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
    start_time = datetime.datetime.now().isoformat()

    file_bytes_to_process = None
    file_name_to_process = None

    if file is not None:
        try:
            file_bytes_to_process = await file.read()
            file_name_to_process = file.filename
            logger.info(
                f"[{msg_id}] File received: name={file_name_to_process}, size={len(file_bytes_to_process)}"
            )

            folder_path = f"contracts/{userId}/{session_id}"
            s3_key = f"{folder_path}/{file_name_to_process}"

            s3.put_object(
                Bucket=BUCKET_CONTAINER,
                Key=s3_key,
                Body=file_bytes_to_process,
                ContentType=file.content_type,
            )
            logger.info(f"[{msg_id}] File uploaded to S3: {s3_key}")

        except (BotoCoreError, ClientError) as exc:
            logger.exception(f"[{msg_id}] S3 upload failed")
            raise HTTPException(500, "S3 upload failed") from exc
        except Exception as exc:
            logger.exception(f"[{msg_id}] Failed to read uploaded file")
            raise HTTPException(400, f"Error reading file: {exc}") from exc

    elif transactionCount != "0":
        logger.info(
            f"[{msg_id}] No new file uploaded. Checking S3 for existing session file."
        )
        file_bytes_to_process, file_name_to_process = (
            _get_session_file_from_s3(
                s3, BUCKET_CONTAINER, userId, session_id, msg_id
            )
        )

    if file_bytes_to_process and file_name_to_process:
        content = _extract_content_from_bytes(
            file_bytes_to_process, file_name_to_process, msg_id
        )
        logger.debug(
            f"[{msg_id}] Successfully extracted content from {file_name_to_process}"
        )
    else:
        logger.info(f"[{msg_id}] No file provided or found for this session.")
        raw_answer = "Please upload your contract first, then ask a specific question related to it."
        chat_mem: ChatMessageHistory = ChatMessageHistory(session_id)
        if not queryText or not queryText.strip():
            queryText = "No text was provided"

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
                logger.info(f"[{msg_id}] Response: {answer}")

            if category == "1" or category == "2":
                logger.info(f"[{msg_id}] Checking contract risk file on s3 ")
                payload_json2 = get_contract_risk_from_s3(
                    userId, session_id, BUCKET_CONTAINER
                )
                if payload_json2 == "NoFile":
                    logger.info(f"Entering risk_categorization.py to generate contract risk file")
                    ans, response_data_intermediate = risk_categorization_fn(
                        content, queryText, msg_id, userId, session_id
                    )
                    answer = ans
                    raw_answer = json.dumps(answer)
                    if category == "1":
                        logger.info(f"Loading risk matrix file")
                        risk_rules = get_risk_matrix_details()
                        clauses_lst = extract_clause_names_from_risk_rules(risk_rules)
                        clause_prompt = get_clauses(queryText, clauses_lst)
                        try:
                            llm_resp = ChatBedrock(
                                model_id=MODEL_ID, max_tokens=4000
                            ).invoke(clause_prompt)
                            clauses_identified = llm_resp.content.strip()  ##list
                            logger.info(f"Clauses asked by user: {clauses_identified}")
                        except Exception as exc:
                            logger.exception(f"[{msg_id}] LLM call failed for returning the relevant clauses")
                            raise HTTPException(500, f"Error invoking LLM: {exc}") from exc
                        answer = get_risks_from_query(clauses_identified, response_data_intermediate)
                        raw_answer = json.dumps(answer)

                else:
                    if category == "2":
                        answer = get_all_clauses_froms3(payload_json2)
                        raw_answer = json.dumps(answer)
                    else:
                        logger.info(f"Loading risk matrix file")
                        risk_rules = get_risk_matrix_details()
                        clauses_lst = extract_clause_names_from_risk_rules(
                            risk_rules
                        )
                        clause_prompt = get_clauses(queryText, clauses_lst)
                        try:
                            llm_resp = ChatBedrock(
                            model_id=MODEL_ID, max_tokens=4000).invoke(clause_prompt)
                            clauses_identified = llm_resp.content.strip()  ##list
                            answer = get_risks_from_query(
                            clauses_identified, payload_json2)
                            raw_answer = json.dumps(answer)
                        except Exception as exc:
                            logger.exception(f"[{msg_id}] LLM call failed for returning the relevant clauses")
                            raise HTTPException(500, f"Error invoking LLM: {exc}") from exc 
            elif category == "3":
                body_prompt = generate_prompt(
                    content, queryText, RISK_MITIGATION_PROMPT
                )
            # elif category == "4":
            #     body_prompt = generate_prompt(content, queryText, BASE_PROMPT)
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
        if category in ("4"):
            raw_answer, payload = get_category4(msg_id, full_prompt)
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

            # logger.info("User requires Risk mitigation strategies")
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
            thumbsUp="N", thumbsDown="N", feedbackText="N"
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
                StartTime=start_time,
                EndTime=now,
                SessionStatus=get_secret("SESSION_STATUS_ACTIVE"),
                MessageId=msg_id,
                ChatMetadata=ChatMetadata(
                    FileName=[file_name],
                    FileLocation=file_loc,
                    FlowName=SUMMARY_FLOW_NAME,
                    Department="",
                ),
            )
        )
        logger.info(f"[{msg_id}] Interaction stored for userId={userId}")

    return api_resp


def extract_clause_names_from_risk_rules(risk_rules_input) -> list[str]:
    """Extracts the names of all top-level clauses from the risk_rules checklist.

    Args:
        risk_rules_input: Either a JSON string or a Python dictionary
                          representing the risk_rules structure.

    Returns:
        A list of strings, where each string is the name of a clause.
        Returns an empty list if the input is invalid or no clauses are found.
    """
    if isinstance(risk_rules_input, str):
        try:
            data = json.loads(risk_rules_input)
        except json.JSONDecodeError:
            print("Error: Invalid JSON string provided.")
            return []
    elif isinstance(risk_rules_input, dict):
        data = risk_rules_input
    else:
        print("Error: Input must be a JSON string or a Python dictionary.")
        return []

    clause_names = []
    if "clauses" in data and isinstance(data["clauses"], list):
        for clause_item in data["clauses"]:
            if isinstance(clause_item, dict) and "name" in clause_item:
                clause_names.append(clause_item["name"])
            else:
                print(
                    f"Warning: Found an item in 'clauses' list that is not a dict or lacks a 'name' key: {clause_item}"
                )
    else:
        print(
            "Warning: 'clauses' key not found in risk_rules or it's not a list."
        )
    logger.info(f"Clauses in risk matrix: {clause_names}")
    return clause_names


def _get_session_file_from_s3(s3_client, bucket, user_id, session_id, msg_id):
    """Retrieves the latest file for a given session from S3."""
    prefix = f"contracts/{user_id}/{session_id}/"
    try:
        response = s3_client.list_objects_v2(
            Bucket=bucket, Prefix=prefix, MaxKeys=2
        )
        # Find the first actual file object, ignoring the "folder" placeholder
        file_object = next(
            (
                obj
                for obj in response.get("Contents", [])
                if obj["Key"] != prefix and obj["Size"] > 0
            ),
            None,
        )

        if not file_object:
            logger.info(
                f"[{msg_id}] No existing file found in S3 at prefix: {prefix}"
            )
            return None, None

        key = file_object["Key"]
        file_name = os.path.basename(key)
        logger.info(f"[{msg_id}] Found existing file in S3: {key}")

        obj_response = s3_client.get_object(Bucket=bucket, Key=key)
        file_bytes = obj_response["Body"].read()
        logger.info(
            f"[{msg_id}] Successfully read {len(file_bytes)} bytes from S3 object: {key}"
        )
        return file_bytes, file_name

    except ClientError as e:
        logger.exception(
            f"[{msg_id}] S3 ClientError retrieving session file from {prefix}"
        )
        raise HTTPException(500, "S3 error retrieving session file.") from e
    except Exception as e:
        logger.exception(
            f"[{msg_id}] Unexpected error retrieving session file from {prefix}"
        )
        raise HTTPException(500, "Error retrieving session file.") from e


def _extract_content_from_bytes(file_bytes, file_name, msg_id):
    """Extracts text content from file bytes based on file type."""
    try:
        ftype = get_file_type(file_name)
        logger.info(
            f"[{msg_id}] Extracting content from: {file_name} (type: {ftype})"
        )

        if ftype == ".pdf":
            return extract_pdf_contents(file_bytes)
        if ftype in {".doc", ".docx"}:
            return extract_text_from_word(file_bytes)

        # Fallback for other file types (e.g., .txt) or unknown types
        logger.warning(
            f"[{msg_id}] Unsupported file type '{ftype}'. Attempting to decode as plain text."
        )
        return file_bytes.decode("utf-8", errors="replace")

    except Exception as exc:
        logger.exception(
            f"[{msg_id}] Failed to extract content from file: {file_name}"
        )
        raise HTTPException(
            400, f"Failed to extract content from {file_name}: {exc}"
        ) from exc
