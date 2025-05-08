"""Routes and logic for handling user QnA requests via chat interface."""

from __future__ import annotations

import datetime
import logging
import re
import uuid

from auth.utils import verify_token
from fastapi import APIRouter, Depends, HTTPException
from langchain_aws import ChatBedrock
from models import (
    ChatInteraction,
    ChatMetadata,
    Feedback,
    FeedbackDisplayOptions,
    QnAAnswer,
    QueryResponse,
    RequestQuery,
    Result,
)
from prompts import FOLLOW_UP_PROMPT
from services import (
    generate_answer_with_context,
    retrieve_and_generate,
    retrieve_and_generate_prioritized_doc,
    retrieve_documents,
    session_history,
)
from services.chat_history_service import store_interaction
from starlette.status import HTTP_500_INTERNAL_SERVER_ERROR
from utils import (
    business_unit_prompt,
    extract_file_locations,
    extract_keywords_from_query,
    get_knowledge_base_folder,
    get_knowledge_base_id,
    llm_summarise,
    needs_summary,
    prompt_query_cat,
)

from .constants import (
    GEN_ENQ_KB_ID,
    IRRELEVANT,
    MODEL_ID,
    PRIOR_DOC,
    QNA_FLOW_NAME,
    REGION_ID,
    SESSION_STATUS,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["QnA"], dependencies=[Depends(verify_token)])

# Mapping from UI session IDs to Bedrock session IDs.
_bedrock_sessions: dict[str, str] = {}


def _get_session_chat_history(session_id: str) -> str:
    """Retrieve the chat history for a given session.

    Args:
        session_id: The session ID from the UI.

    Returns:
        A formatted string containing prior user and assistant messages.
    """
    history_txt = ""
    try:
        history = session_history(session_id)
        for item in history.get(session_id, []):
            user_msg, bot_msg = item.get("UserMessage"), item.get(
                "BotResponse"
            )
            if user_msg and bot_msg:
                history_txt += f"User: {user_msg}\nAssistant: {bot_msg}\n"
    except Exception as e:
        logger.warning(f"Failed to fetch session history: {e}")
    return history_txt


def _get_kb_classification(
    user_txt: str, knowledge_type: str
) -> tuple[str, str]:
    """Classify the user's query into a business unit.

    Args:
        user_txt: The user's question text.
        knowledge_type: The expected KB type.

    Returns:
        A tuple of (detected business unit, warning note if mismatch).
    """
    try:
        prompt = business_unit_prompt(user_txt)
        detected_unit = (
            ChatBedrock(model_id=MODEL_ID).invoke(prompt).content.strip()
        )
        note_if_off = ""
        if knowledge_type.lower() != detected_unit.lower():
            note_if_off = (
                "\n<b>Note</b>: The search results do not contain specific information "
                "regarding your query. Please consider switching tabs …"
            )
        return detected_unit, note_if_off
    except Exception as e:
        logger.warning(f"Classification failed: {e}")
        return knowledge_type, ""


def _build_prompt_with_optional_history(
    user_txt: str, tx_count: int, ui_session_id: str
) -> tuple[str, str]:
    """Build a user prompt, optionally including session history.

    Args:
        user_txt: Current user message.
        tx_count: Number of messages exchanged in the session.
        ui_session_id: The session ID from the UI.

    Returns:
        A tuple of (full prompt text, session history text).
    """
    if tx_count == 0:
        logger.info("FOLLOW-UP | tx=0 | history=skipped")
        return f"User: {user_txt}", ""

    history_txt = _get_session_chat_history(ui_session_id)
    if not history_txt.strip():
        logger.info("FOLLOW-UP | tx=%d | history=empty", tx_count)
        return f"User: {user_txt}", ""

    try:
        classification_prompt = FOLLOW_UP_PROMPT.format(
            context=history_txt, query=user_txt
        )
        resp = generate_answer_with_context(classification_prompt)
        result_text = (resp.get("content", [{}])[0].get("text", "")).strip()

        logger.info(f"[Follow-up Classification] Result: {result_text}")

        if result_text.startswith("IS_FOLLOW_UP"):
            full_prompt = f"{history_txt}\nUser: {user_txt}"
        elif result_text.startswith("NEW_QUESTION"):
            full_prompt = f"{history_txt}\nUser: {user_txt}"
        else:
            logger.warning(
                "Unexpected classification result — defaulting to include history."
            )
            full_prompt = f"{history_txt}\nUser: {user_txt}"

    except Exception:
        logger.exception(
            "Classification failed — defaulting to include history."
        )
        full_prompt = f"{history_txt}\nUser: {user_txt}"

    logger.info(
        "FOLLOW-UP | prompt_preview='%s'", full_prompt.replace("\n", " ")
    )
    return full_prompt, history_txt


def _fallback_qna(
    query: str,
    answer: str,
    ui_session_id: str,
    category: str,
    kb_folder: str,
    hist_txt: str,
) -> str:
    """Attempt a fallback QnA generation if the original answer is irrelevant.

    Args:
        query: User query.
        answer: Original generated answer.
        ui_session_id: Session ID from the UI.
        category: Detected category for fallback.
        kb_folder: Path to the knowledge base.
        hist_txt: Chat history text.

    Returns:
        Revised answer string.
    """
    if IRRELEVANT not in answer:
        return answer

    try:
        bedrock_session = _bedrock_sessions.get(ui_session_id)
        prompt = f"{hist_txt}\nUser:{query}"

        if category == "2":
            resp = retrieve_and_generate_prioritized_doc(
                prompt,
                GEN_ENQ_KB_ID,
                kb_folder,
                [PRIOR_DOC],
                session_id=bedrock_session,
            )
        else:
            resp = retrieve_and_generate(
                prompt,
                GEN_ENQ_KB_ID,
                session_id=bedrock_session,
                kb_path=kb_folder,
            )

        _bedrock_sessions[ui_session_id] = resp["sessionId"]

        if resp.get("citations") and resp["citations"][0].get(
            "retrievedReferences"
        ):
            return resp["output"]["text"]
    except Exception as e:
        logger.warning(f"Fallback QnA failed: {e}")

    return answer.replace(IRRELEVANT, "")


def _store_chat_log(
    request: RequestQuery, answer: str, msg_id: str, session_id: str
) -> None:
    """Persist the user-assistant chat interaction.

    Args:
        request: Original user request.
        answer: Assistant's response.
        msg_id: Message UUID.
        session_id: Chat session ID.
    """
    if not request.user.id:
        return

    try:
        now = datetime.datetime.now().isoformat()
        user_msg_search = (
            extract_keywords_from_query(request.query.text.lower())
            if len(request.query.text) > 2046
            else request.query.text.lower()
        )
        chat_meta = ChatMetadata(
            FileName="",
            FileLocation="",
            FlowName=QNA_FLOW_NAME,
            KbType=request.query.knowledgeType,
        )
        store_interaction(
            ChatInteraction(
                UserId=request.user.id,
                SessionId=session_id,
                UserMessage=request.query.text,
                UserMessageSearch=user_msg_search,
                BotResponse=answer,
                BotResponseSearch=answer,
                FeedbackComment="",
                Timestamp=now,
                SessionStatus=SESSION_STATUS,
                MessageId=msg_id,
                ChatMetadata=chat_meta,
            )
        )
    except Exception:
        logger.exception("Failed to store interaction")
        raise


@router.post("/getqnaanswer/")
async def ask_question(request: RequestQuery) -> QueryResponse:
    """FastAPI route to handle user question and return QnA response.

    Args:
        request: JSON request containing query text and metadata.

    Returns:
        A structured QueryResponse object with answer, metadata, and feedback options.

    Raises:
        HTTPException: On unrecoverable internal error.
    """
    try:
        msg_id = str(uuid.uuid4())
        user_txt = request.query.text.strip()
        ui_session_id = request.user.sessionId or str(uuid.uuid4())
        request.user.sessionId = ui_session_id
        tx_count = request.query.transactionCount
        files = request.query.files
        kb_path = get_knowledge_base_folder(request.query.knowledgeType)
        bedrock_session_id = _bedrock_sessions.get(ui_session_id)

        # Summary-only path
        if needs_summary(user_txt):
            summary_text = llm_summarise(user_txt)
            _store_chat_log(request, summary_text, msg_id, ui_session_id)
            return QueryResponse(
                status="success",
                sessionId=ui_session_id,
                userQuery=user_txt,
                result=Result(
                    messageId=msg_id,
                    answer=QnAAnswer(ans=summary_text),
                    transactionCount=tx_count,
                    citations=[],
                    feedback=Feedback(
                        feedbackDisplayOptions=FeedbackDisplayOptions(
                            thumbsUp="Y", thumbsDown="Y", feedbackText="Y"
                        )
                    ),
                ),
            )

        # Build full prompt
        prompt, history_txt = _build_prompt_with_optional_history(
            user_txt, tx_count, ui_session_id
        )
        _, note_if_off = _get_kb_classification(
            user_txt, request.query.knowledgeType
        )

        resp = None
        answer = None
        citations = []
        try:
            if not files:
                # Fallback to direct LLM generation if nothing is retrieved
                if not answer:
                    logger.info(
                        "No documents/files provided — using generate_answer_with_context."
                    )
                    direct_resp = generate_answer_with_context(prompt)
                    answer = (
                        direct_resp.get("content", [{}])[0]
                        .get("text", "")
                        .strip()
                    )
        except Exception as e:
            logger.warning(f"Direct context generation failed: {e}")

        # Retrieval: Prioritized
        if files:
            try:
                resp = retrieve_and_generate_prioritized_doc(
                    prompt,
                    get_knowledge_base_id(request.query.knowledgeType),
                    get_knowledge_base_folder(request.query.knowledgeType),
                    files,
                    session_id=bedrock_session_id,
                )
                answer = resp["output"]["text"]
                citations = extract_file_locations(resp)
                _bedrock_sessions[ui_session_id] = resp["sessionId"]
                bedrock_session_id = resp["sessionId"]
            except Exception as e:
                logger.warning(f"Prioritized retrieval failed: {e}")

        # Retrieval: Standard if no prioritized answer
        if not answer:
            try:
                doc = retrieve_documents(
                    prompt,
                    get_knowledge_base_id(request.query.knowledgeType),
                    REGION_ID,
                )
                for hit in doc.get("retrievalResults", []):
                    if PRIOR_DOC in hit.get("metadata", {}).get(
                        "x-amz-bedrock-kb-source-uri", ""
                    ):
                        resp = retrieve_and_generate_prioritized_doc(
                            prompt,
                            get_knowledge_base_id(request.query.knowledgeType),
                            get_knowledge_base_folder(
                                request.query.knowledgeType
                            ),
                            [PRIOR_DOC],
                            session_id=bedrock_session_id,
                        )
                        break
                if not resp:
                    resp = retrieve_and_generate(
                        prompt,
                        get_knowledge_base_id(request.query.knowledgeType),
                        session_id=bedrock_session_id,
                        kb_path=kb_path,
                    )
                answer = resp["output"]["text"]
                citations = extract_file_locations(resp)
                _bedrock_sessions[ui_session_id] = resp["sessionId"]
            except Exception as e:
                logger.exception("Document retrieval failed")
                raise HTTPException(
                    HTTP_500_INTERNAL_SERVER_ERROR,
                    f"Doc retrieval failed: {e}",
                )

        if not answer:
            logger.error("No answer generated")
            raise HTTPException(
                HTTP_500_INTERNAL_SERVER_ERROR, "Unable to generate an answer."
            )

        if re.search(r"Sorry, I am unable to assist", answer, re.IGNORECASE):
            answer += note_if_off

        try:
            cat = prompt_query_cat(prompt.lower())
            answer = _fallback_qna(
                prompt, answer, ui_session_id, cat, "general", history_txt
            )
        except Exception as e:
            logger.warning(f"Fallback QnA logic failed: {e}")

        _store_chat_log(request, answer, msg_id, ui_session_id)

        return QueryResponse(
            status="success",
            sessionId=ui_session_id,
            userQuery=user_txt,
            result=Result(
                messageId=msg_id,
                answer=QnAAnswer(ans=answer),
                transactionCount=tx_count,
                citations=citations,
                feedback=Feedback(
                    feedbackDisplayOptions=FeedbackDisplayOptions(
                        thumbsUp="Y", thumbsDown="Y", feedbackText="Y"
                    )
                ),
            ),
        )

    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        logger.exception("Unhandled exception in QnA route")
        raise HTTPException(
            HTTP_500_INTERNAL_SERVER_ERROR, f"Unexpected error: {e}"
        )
