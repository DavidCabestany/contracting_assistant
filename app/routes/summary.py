"""Routes and logic for generating document summaries and risk assessments."""

from __future__ import annotations

import datetime
import logging
import uuid
from typing import Optional

from auth.utils import verify_token
from config import get_config_value
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from langchain_aws import ChatBedrock
from langchain_core.runnables.history import RunnableWithMessageHistory
from models import (
    ChatInteraction,
    ChatMetadata,
    Feedback,
    FeedbackDisplayOptions,
    QueryResponse,
    Result,
)
from prompts import BASE_PROMPT, RISK_MATRIX_PROMPT
from services import retrieve_and_generate_prioritized_doc
from services.chat_history_service import store_interaction
from services.memory import load_chat_history
from utils import (
    extract_keywords_from_query,
    extract_pdf_contents,
    extract_text_from_word,
    generate_prompt,
    generate_prompt_risk,
    get_file_type,
    get_risk_matrix_details,
    parse_risk_assessment_output,
    prompt_query_cat,
)

from .constants import (
    BUCKET_CONTAINER,
    IRRELEVANT,
    MODEL_ID,
    PRIOR_DOC,
    S3,
    SESSION_STATUS,
    SUMMARY_FLOW_NAME,
)

logger = logging.getLogger(__name__)
router = APIRouter(
    tags=["Summary"],
    dependencies=[Depends(verify_token)],
)


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
    """Endpoint for generating a summary from an uploaded document or query text.

    Optionally classifies the type of summary and applies fallback mechanisms if needed.
    Stores the full interaction metadata for audit and training purposes.
    """
    msg_id = str(uuid.uuid4())
    session_id = sessionId or str(uuid.uuid4())
    file_name = ""
    folder = ""

    content = ""
    if file:
        try:
            file_bytes = await file.read()
            ftype = get_file_type(file.filename)
            # TODO(@kvcn639): Add file size limit guardrail to prevent memory overload
        except Exception as exc:
            raise HTTPException(400, f"Error reading file: {exc}") from exc

        try:
            folder = f"contracts/{userId}/{session_id}"
            S3.put_object(
                Bucket=BUCKET_CONTAINER,
                Key=f"{folder}/",
            )  # TODO(@kvcn639): Validate if this is necessary as a separate call
            file_name = file.filename
            S3.put_object(
                Bucket=BUCKET_CONTAINER,
                Key=f"{folder}/{file_name}",
                Body=file_bytes,
                ContentType=file.content_type,
            )
        except Exception as exc:
            raise HTTPException(500, f"S3 upload failed: {exc}") from exc

        try:
            if ftype == ".pdf":
                content = extract_pdf_contents(file_bytes)
            elif ftype in (".doc", ".docx"):
                content = extract_text_from_word(file_bytes)
        except ValueError as exc:
            raise HTTPException(
                400,
                f"Failed to extract content: {exc}",
            ) from exc

    if not queryText:
        queryText = "Summarize the document content"

    # TODO(@kvcn639): Add try-except block for prompt_query_cat to handle edge cases or unexpected output
    prompt_cat = prompt_query_cat(queryText.lower())
    category = ChatBedrock(model_id=MODEL_ID).invoke(prompt_cat).content

    if category == "1":
        prompt = generate_prompt_risk(
            content,
            get_risk_matrix_details(),
            queryText,
            RISK_MATRIX_PROMPT,
        )
    else:
        prompt = generate_prompt(content, queryText, BASE_PROMPT)

    llm = ChatBedrock(model_id=MODEL_ID)
    chain = RunnableWithMessageHistory(llm, load_chat_history)

    # include previous chat for better coherence
    user_hist = ""
    # TODO(@kvcn639): Add truncation if session history is too long to fit in prompt
    for q, a in extract_keywords_from_query(load_chat_history(session_id)):
        user_hist += f"User: {q}\nAssistant: {a}\n"

    try:
        summary = chain.invoke(
            prompt,
            config={"configurable": {"session_id": session_id}},
        )
    except Exception as exc:
        raise HTTPException(500, f"Error invoking the LLM: {exc}") from exc

    answer = summary.content
    if IRRELEVANT in answer:
        try:
            resp = retrieve_and_generate_prioritized_doc(
                prompt,
                get_config_value("GEN_ENQ_KB_ID"),
                "general",
                [PRIOR_DOC],
                session_id=session_id,
            )
            if resp.get("citations"):
                answer = resp["output"]["text"]
        except Exception:
            logger.exception(
                "Summary fallback failed",
            )  # TODO(@kvcn639): Add alerting or retry strategy here

    try:
        structured = parse_risk_assessment_output(answer)
        final_ans = structured.dict()["answer"]
    except ValueError:
        final_ans = {
            "ans": answer,
        }  # TODO(@kvcn639): Add fallback schema validation for unexpected answer shapes

    result = Result(
        messageId=msg_id,
        answer=final_ans,
        transactionCount=transactionCount,
        feedback=Feedback(
            feedbackDisplayOptions=FeedbackDisplayOptions(
                thumbsUp="Y",
                thumbsDown="Y",
                feedbackText="Y",
            ),
        ),
    )

    if userId:
        now = datetime.datetime.now().isoformat()
        # TODO(@kvcn639): Validate final file path format is correct
        file_loc = f"{BUCKET_CONTAINER}{folder}{file_name}"
        store_interaction(
            ChatInteraction(
                UserId=userId,
                SessionId=session_id,
                UserMessage=queryText or file_name,
                UserMessageSearch=(
                    extract_keywords_from_query(queryText.lower())
                    if len(queryText) > 2046
                    else queryText
                ),
                BotResponse=answer,
                BotResponseSearch=answer,
                FeedbackComment="",
                Timestamp=now,
                SessionStatus=SESSION_STATUS,
                MessageId=msg_id,
                ChatMetadata=ChatMetadata(
                    FileName=file_name,
                    FileLocation=file_loc,
                    FlowName=SUMMARY_FLOW_NAME,
                    Department="",
                ),
            ),
        )

    return QueryResponse(
        status="success",
        sessionId=session_id,
        userQuery=queryText,
        result=result,
    )
