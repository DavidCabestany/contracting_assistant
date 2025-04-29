from __future__ import annotations

import datetime
import logging
import re
import uuid

from auth.utils import verify_token
from chathistory import store_interaction  # Dynamo write
from data import (
    ChatInteraction,
    ChatMetadata,
    Feedback,
    FeedbackDisplayOptions,
    QnAAnswer,
    QueryResponse,
    RequestQuery,
    Result,
)
from fastapi import APIRouter, Depends
from langchain_aws import ChatBedrock
from prompts import FOLLOW_UP_PROMPT
from services import (
    generate_answer_with_context,
    retrieve_and_generate,
    retrieve_and_generate_prioritized_doc,
    retrieve_documents,
)
from services.memory import load_chat_history
from utils import (
    business_unit_prompt,
    extract_chat_history,
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


# ───────────────────────── helpers ────────────────────────────
def _fallback_qna(
    query: str,
    answer: str,
    session_id: str,
    content: str,
    category: str,
    kb_folder: str,
    hist_txt: str,
) -> str:
    """
    If answer contains IRRELEVANT, call the general KB and possibly replace it.
    """
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
                prompt, GEN_ENQ_KB_ID, session_id=kb_session
            )
        _qna_sessions[session_id] = resp["sessionId"]
        if resp.get("citations") and resp["citations"][0].get(
            "retrievedReferences"
        ):
            return resp["output"]["text"]
    except Exception:  # soft-fail – just log
        logger.exception("QnA fallback failed")
    return answer.replace(IRRELEVANT, "")


# ───────────────────────── route ──────────────────────────────
@router.post("/getqnaanswer/")
async def ask_question(request: RequestQuery) -> QueryResponse:
    msg_id = str(uuid.uuid4())
    user_txt = request.query.text.strip()
    session_id = request.user.sessionId
    files = request.query.files

    # ─── Guard-rail: summary detection ─────────────────────────
    if needs_summary(user_txt):
        summary = QnAAnswer(ans=llm_summarise(user_txt))
        return QueryResponse(
            status="success",
            sessionId=session_id or str(uuid.uuid4()),
            userQuery=user_txt,
            result=Result(
                messageId=msg_id,
                answer=summary,
                transactionCount=request.query.transactionCount,
                citations=[],
                feedback=Feedback(
                    feedbackDisplayOptions=FeedbackDisplayOptions(
                        thumbsUp="Y", thumbsDown="Y", feedbackText="Y"
                    )
                ),
            ),
        )

    # ─── Build history prompt & follow-up check ────────────────
    history_txt = ""
    if session_id:
        hist = load_chat_history(session_id)
        for q, a in extract_chat_history(hist):
            history_txt += f"User: {q}\nAssistant: {a}\n"
    follow = generate_answer_with_context(
        FOLLOW_UP_PROMPT.format(history_txt, user_txt)
    )
    if "follow-up" in follow["content"][0]["text"].lower():
        prompt = history_txt + f"User:{user_txt}"
    else:
        prompt = f"User:{user_txt}"

    # ─── Business-unit classification ──────────────────────────
    kb_prompt = business_unit_prompt(user_txt)
    kb_unit = ChatBedrock(model_id=MODEL_ID).invoke(kb_prompt).content.strip()
    note_if_off = (
        ""
        if request.query.knowledgeType.lower() == kb_unit.lower()
        else (
            "\n<b>Note</b>: The search results do not contain specific information "
            "regarding your query. Please consider switching tabs…"
        )
    )

    # ─── Retrieval stage ① prioritised docs ────────────────────
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
            logger.exception("prioritised-doc retrieval failed")

    # ─── Retrieval stage ② fallbacks ---------------------------
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

    session_id = resp["sessionId"]  # final KB session
    if re.search(r"Sorry, I am unable to assist", answer, re.I):
        answer += note_if_off

    # ─── Optional IRRELEVANT fallback --------------------------
    # category detection for risk / clause handled via utils.prompt_query_cat
    cat = prompt_query_cat(user_txt.lower())
    answer = _fallback_qna(
        user_txt, answer, session_id, "", cat, "general", history_txt
    )

    # ─── Build DTO & log interaction --------------------------
    result = Result(
        messageId=msg_id,
        answer=QnAAnswer(ans=answer),
        transactionCount=request.query.transactionCount,
        citations=citations,
        feedback=Feedback(
            feedbackDisplayOptions=FeedbackDisplayOptions(
                thumbsUp="Y", thumbsDown="Y", feedbackText="Y"
            )
        ),
    )
    # Store chat interaction if user ID is present
    if request.user.id:
        now = datetime.datetime.now().isoformat()
        user_msg_search = (
            extract_keywords_from_query(user_txt.lower())
            if len(user_txt) > 2046
            else user_txt.lower()
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
                UserMessage=user_txt,
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

    return QueryResponse(
        status="success",
        sessionId=session_id,
        userQuery=user_txt,
        result=result,
    )
