"""Routes and logic for handling user QnA requests via chat interface."""

from __future__ import annotations

import datetime
import logging
import re
import uuid

from auth.utils import verify_token
from fastapi import APIRouter, Depends
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

router = APIRouter(
    tags=["QnA"],
    dependencies=[Depends(verify_token)],
)

_qna_sessions: dict[str, str] = {}


def _get_session_chat_history(session_id: str) -> str:
    history_txt = ""
    if session_id:
        history = session_history(session_id)
        chat_records = history.get(session_id, [])
        for item in chat_records:
            user_msg = item.get("UserMessage")
            bot_msg = item.get("BotResponse")
            if user_msg and bot_msg:
                history_txt += f"User: {user_msg}\nAssistant: {bot_msg}\n"
    return history_txt


def _get_kb_classification(
    user_txt: str,
    knowledge_type: str,
) -> tuple[str, str]:
    prompt = business_unit_prompt(user_txt)
    # TODO(@kvcn639): Add error handling in case Bedrock call fails or returns garbage
    # Issue: TODO_OPEN/126
    detected_unit = (
        ChatBedrock(model_id=MODEL_ID).invoke(prompt).content.strip()
    )
    note_if_off = ""
    if knowledge_type.lower() != detected_unit.lower():
        note_if_off = (
            "\n<b>Note</b>: The search results do not contain specific information "
            "regarding your query. Please consider switching tabs…"
        )
    return detected_unit, note_if_off


def _fallback_qna(
    query: str,
    answer: str,
    session_id: str,
    category: str,
    kb_folder: str,
    hist_txt: str,
) -> str:
    if IRRELEVANT not in answer:
        return answer

    kb_session = _qna_sessions.get(session_id, "")
    prompt = f"{hist_txt}User:{query}"
    try:
        if category == "2":
            resp = retrieve_and_generate_prioritized_doc(
                prompt,
                GEN_ENQ_KB_ID,
                kb_folder,
                [PRIOR_DOC],
                session_id=kb_session,
            )
        else:
            resp = retrieve_and_generate(
                prompt,
                GEN_ENQ_KB_ID,
                session_id=kb_session,
            )
        _qna_sessions[session_id] = resp["sessionId"]
        if resp.get("citations") and resp["citations"][0].get(
            "retrievedReferences",
        ):
            return resp["output"]["text"]
    except Exception:
        logger.exception(
            "QnA fallback failed",
        )  # TODO(@kvcn639): Add retry logic or fallback strategy
        # Issue: TODO_OPEN/126
    return answer.replace(IRRELEVANT, "")


def _store_chat_log(
    request: RequestQuery,
    answer: str,
    msg_id: str,
    session_id: str,
):
    if request.user.id:
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
            ),
        )


@router.post("/getqnaanswer/")
async def ask_question(request: RequestQuery) -> QueryResponse:
    """Handles user questions and returns answers with context, citations, and feedback.

    Args:
        request (RequestQuery): The request payload containing the user query and metadata.

    Returns:
        QueryResponse: The response object containing the generated answer and metadata.
    """
    msg_id = str(uuid.uuid4())
    user_txt = request.query.text.strip()
    session_id = request.user.sessionId
    files = request.query.files

    if needs_summary(user_txt):
        # TODO(@kvcn639): Consider caching summaries to avoid recomputation on similar queries
        return QueryResponse(
            status="success",
            sessionId=session_id or str(uuid.uuid4()),
            userQuery=user_txt,
            result=Result(
                messageId=msg_id,
                answer=QnAAnswer(ans=llm_summarise(user_txt)),
                transactionCount=request.query.transactionCount,
                citations=[],
                feedback=Feedback(
                    feedbackDisplayOptions=FeedbackDisplayOptions(
                        thumbsUp="Y",
                        thumbsDown="Y",
                        feedbackText="Y",
                    ),
                ),
            ),
        )

    history_txt = _get_session_chat_history(session_id)
    follow = generate_answer_with_context(
        FOLLOW_UP_PROMPT.format(history_txt, user_txt),
    )
    prompt = (
        f"{history_txt}User:{user_txt}"
        if "follow-up" in follow["content"][0]["text"].lower()
        else f"User:{user_txt}"
    )

    _, note_if_off = _get_kb_classification(
        user_txt,
        request.query.knowledgeType,
    )

    resp, answer, citations = None, None, []
    if files:
        try:
            resp = retrieve_and_generate_prioritized_doc(
                user_txt,
                get_knowledge_base_id(request.query.knowledgeType),
                get_knowledge_base_folder(request.query.knowledgeType),
                files,
                session_id=session_id,
            )
            answer = resp["output"]["text"]
            citations = extract_file_locations(resp)
        except Exception:
            logger.exception(
                "prioritised-doc retrieval failed",
            )  # TODO(@kvcn639): Add error message to response for client visibility

    if not answer:
        doc = retrieve_documents(
            prompt,
            get_knowledge_base_id(request.query.knowledgeType),
            REGION_ID,
        )
        for hit in doc.get("retrievalResults", []):
            if PRIOR_DOC in hit.get("metadata", {}).get(
                "x-amz-bedrock-kb-source-uri",
                "",
            ):
                resp = retrieve_and_generate_prioritized_doc(
                    user_txt,
                    get_knowledge_base_id(request.query.knowledgeType),
                    get_knowledge_base_folder(request.query.knowledgeType),
                    [PRIOR_DOC],
                    session_id=session_id,
                )
                break
        if not resp:
            resp = retrieve_and_generate(
                user_txt,
                get_knowledge_base_id(request.query.knowledgeType),
                session_id=session_id,
            )
        answer = resp["output"]["text"]
        citations = extract_file_locations(resp)

    session_id = resp["sessionId"]
    if re.search(r"Sorry, I am unable to assist", answer, re.IGNORECASE):
        answer += note_if_off

    cat = prompt_query_cat(user_txt.lower())
    answer = _fallback_qna(
        user_txt,
        answer,
        session_id,
        cat,
        "general",
        history_txt,
    )

    _store_chat_log(request, answer, msg_id, session_id)

    return QueryResponse(
        status="success",
        sessionId=session_id,
        userQuery=user_txt,
        result=Result(
            messageId=msg_id,
            answer=QnAAnswer(ans=answer),
            transactionCount=request.query.transactionCount,
            citations=citations,
            feedback=Feedback(
                feedbackDisplayOptions=FeedbackDisplayOptions(
                    thumbsUp="Y",
                    thumbsDown="Y",
                    feedbackText="Y",
                ),
            ),
        ),
    )
