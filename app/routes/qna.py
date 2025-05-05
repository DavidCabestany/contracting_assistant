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
from utils import generate_technical_error_message  # NEW
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

# ui-session-id  →  bedrock-session-id
_bedrock_sessions: dict[str, str] = (
    {}
)  # TODO(@kvcn639): persist for multi-worker


# ───────────────────────── helpers ─────────────────────────────────────
def _get_session_chat_history(session_id: str) -> str:
    history_txt = ""
    if session_id:
        history = session_history(session_id)
        for item in history.get(session_id, []):
            user_msg, bot_msg = item.get("UserMessage"), item.get(
                "BotResponse"
            )
            if user_msg and bot_msg:
                history_txt += f"User: {user_msg}\nAssistant: {bot_msg}\n"
    return history_txt


def _get_kb_classification(
    user_txt: str, knowledge_type: str
) -> tuple[str, str]:
    prompt = business_unit_prompt(user_txt)
    # TODO(@kvcn639): add error handling if Bedrock call fails
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


def _build_prompt_with_optional_history(
    user_txt: str, tx_count: int, ui_session_id: str
) -> tuple[str, str]:
    """Return (prompt, history_txt).  Writes a FOLLOW-UP line to report.log."""
    if tx_count == 0:
        logger.info("FOLLOW-UP | tx=0 | history=skipped")
        return f"User:{user_txt}", ""

    try:
        history_txt = _get_session_chat_history(ui_session_id)
        logger.info(
            "FOLLOW-UP | tx=%d | history_len=%d", tx_count, len(history_txt)
        )
    except Exception:
        logger.exception("FOLLOW-UP | history fetch failed")
        history_txt = ""

    if not history_txt.strip():
        logger.info("FOLLOW-UP | tx=%d | history=empty", tx_count)
        return f"User:{user_txt}", history_txt

    # helper LLM decides if truly a follow-up
    try:
        resp = generate_answer_with_context(
            FOLLOW_UP_PROMPT.format(history_txt, user_txt)
        )
        verdict = (resp.get("content", [{}])[0].get("text", "")).lower()
        is_follow_up = "follow-up" in verdict
        logger.info(
            "FOLLOW-UP | detector_text='%s' | is_follow_up=%s",
            verdict[:60].replace("\n", " "),
            is_follow_up,
        )
    except Exception:
        logger.exception(
            "FOLLOW-UP | detector failed – default include history"
        )
        is_follow_up = True

    prompt = (
        f"{history_txt}User:{user_txt}" if is_follow_up else f"User:{user_txt}"
    )
    # -- DEBUG: log history + final prompt --------------------
    logger.info(
        "FOLLOW-UP | history_preview='%s' | prompt_preview='%s'",
        history_txt[:200].replace("\n", " "),
        prompt[:200].replace("\n", " "),
    )
    return prompt, history_txt


def _fallback_qna(
    query: str,
    answer: str,
    ui_session_id: str,
    category: str,
    kb_folder: str,
    hist_txt: str,
) -> str:
    if IRRELEVANT not in answer:
        return answer

    bedrock_session = _bedrock_sessions.get(ui_session_id)
    prompt = f"{hist_txt}User:{query}"
    try:
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
                prompt, GEN_ENQ_KB_ID, session_id=bedrock_session
            )
        _bedrock_sessions[ui_session_id] = resp["sessionId"]
        if resp.get("citations") and resp["citations"][0].get(
            "retrievedReferences"
        ):
            return resp["output"]["text"]
    except Exception:
        logger.exception("QnA fallback failed")  # TODO(@kvcn639): retry logic
    return answer.replace(IRRELEVANT, "")


def _store_chat_log(
    request: RequestQuery, answer: str, msg_id: str, session_id: str
) -> None:
    if not request.user.id:
        return
    now = datetime.datetime.now().isoformat()
    user_msg_search = (
        extract_keywords_from_query(request.query.text.lower())
        if len(request.query.text) > 2046  # TODO(@kvcn639): use constant
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


# ─────────────────────── main endpoint ────────────────────────────────
@router.post("/getqnaanswer/")
async def ask_question(request: RequestQuery) -> QueryResponse:
    """Handles user questions and returns answers with context, citations, and feedback."""
    msg_id = str(uuid.uuid4())
    user_txt = request.query.text.strip()

    ui_session_id = request.user.sessionId
    if not ui_session_id:
        ui_session_id = str(uuid.uuid4())
        request.user.sessionId = ui_session_id
    bedrock_session_id = _bedrock_sessions.get(ui_session_id)
    files = request.query.files
    tx_count = request.query.transactionCount

    # ───── Guard-rail (summary) ─────────────────────────────────────────
    if needs_summary(user_txt):
        # 1. generate summary
        summary_text = llm_summarise(user_txt)

        # 2. persist to DynamoDB so follow-ups have history
        _store_chat_log(request, summary_text, msg_id, ui_session_id)

        # 3. respond to caller
        return QueryResponse(
            status="success",
            sessionId=ui_session_id or str(uuid.uuid4()),
            userQuery=user_txt,
            result=Result(
                messageId=msg_id,
                answer=QnAAnswer(ans=summary_text),
                transactionCount=tx_count,  # unchanged
                citations=[],  # summaries have no KB cites
                feedback=Feedback(
                    feedbackDisplayOptions=FeedbackDisplayOptions(
                        thumbsUp="Y", thumbsDown="Y", feedbackText="Y"
                    )
                ),
            ),
        )

    # ───── Build prompt (may include history) ──────────────────────────
    prompt, history_txt = _build_prompt_with_optional_history(
        user_txt, tx_count, ui_session_id
    )
    _, note_if_off = _get_kb_classification(
        user_txt, request.query.knowledgeType
    )

    # ───── Retrieval & generation paths ────────────────────────────────
    resp = None
    answer: str | None = None
    citations = []

    # 1️⃣  prioritised-doc path
    if files:
        try:
            resp = retrieve_and_generate_prioritized_doc(
                user_txt,
                get_knowledge_base_id(request.query.knowledgeType),
                get_knowledge_base_folder(request.query.knowledgeType),
                files,
                session_id=bedrock_session_id,
            )
            answer = resp["output"]["text"]
            citations = extract_file_locations(resp)
            _bedrock_sessions[ui_session_id] = resp["sessionId"]
            bedrock_session_id = resp["sessionId"]
        except Exception:
            logger.exception(
                "prioritised-doc retrieval failed"
            )  # TODO(@kvcn639): add error to response

    # 2️⃣  standard path
    if not answer:
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
                    user_txt,
                    get_knowledge_base_id(request.query.knowledgeType),
                    get_knowledge_base_folder(request.query.knowledgeType),
                    [PRIOR_DOC],
                    session_id=bedrock_session_id,
                )
                break
        if not resp:
            resp = retrieve_and_generate(
                user_txt,
                get_knowledge_base_id(request.query.knowledgeType),
                session_id=bedrock_session_id,
            )
        answer = resp["output"]["text"]
        citations = extract_file_locations(resp)
        _bedrock_sessions[ui_session_id] = resp["sessionId"]
        bedrock_session_id = resp["sessionId"]

    # ───── Ensure we have an answer ─────────────────────────────────────
    if answer is None:
        logger.error(
            "RETRIEVE-ERR | No answer produced after all retrieval paths"
        )
        return generate_technical_error_message(
            msg_id,
            tx_count,
            user_txt,
            ui_session_id,
            exc=ValueError("No answer generated"),
        )

    # ───── Post-processing & fallback ──────────────────────────────────
    if re.search(r"Sorry, I am unable to assist", answer, re.IGNORECASE):
        answer += note_if_off

    cat = prompt_query_cat(user_txt.lower())
    answer = _fallback_qna(
        user_txt, answer, ui_session_id, cat, "general", history_txt
    )

    # ───── Persist & respond ───────────────────────────────────────────
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
