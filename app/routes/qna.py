"""Routes and logic for handling user QnA requests via chat interface."""

from __future__ import annotations

import datetime
import json
import logging
import re
import uuid

import boto3
from auth.utils import verify_token
from fastapi import APIRouter, Depends, HTTPException
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
    HIGH_PRIORITY_QUERIES,
    IRRELEVANT,
    PRIOR_DOC,
    QNA_FLOW_NAME,
    REGION_ID,
    SESSION_STATUS,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["QnA"], dependencies=[Depends(verify_token)])

# Mapping from UI session IDs to Bedrock session IDs.
_bedrock_sessions: dict[str, str] = {}


def load_known_files_from_s3() -> dict[str, str]:
    """Build a filename-to-kb_path mapping from S3 buckets."""
    s3 = boto3.client("s3")
    bucket = "azcdi-us-ops-procure-ds-dev"
    kb_paths = ["general", "privacy", "alexion"]
    known_files = {}

    for kb_path in kb_paths:
        prefix = f"{kb_path}/"
        paginator = s3.get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=bucket, Prefix=prefix)

        for page in pages:
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if key.endswith(".pdf"):
                    file_name = key.split("/")[-1]
                    known_files[file_name] = kb_path

    return known_files


KNOWN_FILES = load_known_files_from_s3()


def auto_attach_files(user_txt: str, kb_path: str) -> list[tuple[str, str]]:
    """Auto-match files from S3 based on query contents and restrict to given kb_path."""
    query_lc = user_txt.lower()
    start_end_query = query_lc[:50] + query_lc[-50:]
    matched_files = []

    for file_name, file_kb_path in KNOWN_FILES.items():
        # Only consider files from the active kb_path
        if file_kb_path != kb_path:
            continue

        base_name = file_name.lower().replace(".pdf", "")
        words = re.findall(r"\b\w+\b", base_name)

        for i in range(len(words) - 1):
            phrase = " ".join(words[i : i + 2])
            if phrase in start_end_query:
                matched_files.append(file_name)
                break

    return matched_files


def is_invalid_response(text: str) -> bool:
    """Check whether the response text is considered invalid or irrelevant."""
    lowered = text.lower().strip()
    return (
        not lowered
        or lowered in {"sorry, i am unable to assist you with this request."}
        or "unable to assist" in lowered
        or "i cannot help" in lowered
        or "no information available" in lowered
        or "i'm not sure" in lowered
        or IRRELEVANT in lowered
    )


def is_high_priority_query(query: str, category: str) -> bool:
    """Check if teh initial user query is part of the standard queries."""
    normalized_query = query.lower().strip()
    normalized_category = category.strip().title()
    return normalized_query in HIGH_PRIORITY_QUERIES.get(
        normalized_category, set()
    )


def detect_prior_doc_from_query(query: str) -> str:
    """Detect a relevant prior document from the user query."""
    DOCUMENT_TOPICS = [
        {
            "file": "Playbook_Data Protection Appendix – Controller to Dual Role Processor.pdf",
            "keywords": ["supplier", "controller", "processor"],
        }
    ]
    query_lower = query.lower()
    for doc in DOCUMENT_TOPICS:
        if all(k in query_lower for k in doc["keywords"]):
            return doc["file"]
    return PRIOR_DOC


def _was_last_answer_from_kb(session_id: str) -> bool:
    """Check if the last answer in session history came from the knowledge base."""
    logger.info(
        "000 ▶ ENTER _was_last_answer_from_kb(session_id=%s)", session_id
    )
    try:
        history = session_history(session_id).get(session_id, [])
        logger.info("010 ▶ Retrieved %d history entries", len(history))

        if not history:
            logger.info("020 ▶ No history found – returning False")
            return False

        last = history[-1]
        logger.info("030 ▶ Last history entry: %s", last)

        file_used = last.get("ChatMetadata", {}).get("FileName")
        logger.info("040 ▶ FileName in last entry = %s", file_used)

        is_kb_used = file_used == "USED_KB"
        logger.info("050 ▶ is_kb_used = %s", is_kb_used)

        logger.info("060 ◀ EXIT _was_last_answer_from_kb")
        return is_kb_used

    except Exception as e:
        logger.warning(
            "EXCEPTION:  070 ▶ Failed to check KB usage from history: %s", e
        )
        logger.info(
            "080 ◀ EXIT _was_last_answer_from_kb with False (exception)"
        )
        return False


def _get_session_chat_history(session_id: str) -> str:
    """Retrieve the chat history for a given session.

    Args:
        session_id: The session ID from the UI.

    Returns:
        A formatted string containing prior user and assistant messages.
    """
    logger.info("ENTER ▶ _get_session_chat_history(session_id=%s)", session_id)
    history_txt = ""
    try:
        history = session_history(session_id)
        logger.info(
            "▶ fetched raw history for session: %s", history.get(session_id)
        )
        for i, item in enumerate(history.get(session_id, [])):
            user_msg, bot_msg = item.get("UserMessage"), item.get(
                "BotResponse"
            )
            logger.info(
                "  ▶ loop[%d] user_msg=%s | bot_msg=%s", i, user_msg, bot_msg
            )
            if user_msg and bot_msg:
                history_txt += f"User: {user_msg}\nAssistant: {bot_msg}\n"
        logger.info("▶ built history_txt (len=%d)", len(history_txt))
    except Exception as e:
        logger.warning("EXCEPTION:  Failed to fetch session history: %s", e)
    logger.info(
        "EXIT  ◀ _get_session_chat_history -> %.200s",
        history_txt.replace("\n", " "),
    )
    return history_txt


def _build_prompt_with_optional_history(
    user_txt: str, tx_count: int, ui_session_id: str
) -> tuple[str, str]:
    logger.info(
        "ENTER ▶ _build_prompt_with_optional_history(user_txt=%.100s, tx_count=%d, ui_session_id=%s)",
        user_txt,
        tx_count,
        ui_session_id,
    )
    # first message in session
    is_follow_up = False
    if tx_count == 0:
        existing_history = session_history(ui_session_id)
        logger.info(
            "▶ tx_count==0, existing_history=%s", bool(existing_history)
        )
        if existing_history:
            logger.warning("EXCEPTION:  tx_count==0 but session has history")
            history_txt = _get_session_chat_history(ui_session_id)
            prompt = f"{history_txt}\nUser: {user_txt}"
            logger.info(
                "EXIT  ◀ _build_prompt | using existing_history -> prompt_preview=%.200s",
                prompt.replace("\n", " "),
            )
            return prompt, history_txt, is_follow_up
        else:
            logger.info("▶ no existing_history — skipping history")
            prompt = f"User: {user_txt}"
            logger.info(
                "EXIT  ◀ _build_prompt | new session -> prompt=%s", prompt
            )
            return prompt, "", is_follow_up

    history_txt = _get_session_chat_history(ui_session_id)
    logger.info("▶ loaded history_txt (len=%d)", len(history_txt))
    if not history_txt.strip():
        logger.info("▶ history empty for tx_count=%d", tx_count)
        prompt = f"User: {user_txt}"
        logger.info(
            "EXIT  ◀ _build_prompt | empty history -> prompt=%s", prompt
        )
        return prompt, "", is_follow_up

    try:
        classification_prompt = FOLLOW_UP_PROMPT.format(
            context=history_txt, query=user_txt
        )
        logger.info(
            "▶ follow-up classification_prompt=%.200s",
            classification_prompt.replace("\n", " "),
        )
        resp = generate_answer_with_context(classification_prompt)
        logger.info(f"▶ follow up response line 148 {resp}")

        result_text = resp.get("content", [{}])[0].get("text", "").strip()
        logger.info("▶ classification result_text=%.200s", result_text)
        is_follow_up = result_text.startswith("IS_FOLLOW_UP:")
        full_prompt = f"{history_txt}\nUser: {user_txt}"
    except Exception as e:
        logger.exception(
            "EXCEPTION: Classification failed, defaulting to include history: %s",
            e,
        )
        full_prompt = f"{history_txt}\nUser: {user_txt}"

    logger.info(
        "EXIT  ◀ _build_prompt | full_prompt_preview=%.200s",
        full_prompt.replace("\n", " "),
    )
    return full_prompt, history_txt, is_follow_up


def _fallback_qna(
    query: str,
    answer: str,
    ui_session_id: str,
    category: str,
    kb_folder: str,
    hist_txt: str,
    fallback_doc: str = PRIOR_DOC,
) -> str:
    logger.info(
        "ENTER ▶ _fallback_qna(query=%.100s, answer=%.100s, ui_session_id=%s, category=%s, kb_folder=%s)",
        query,
        answer,
        ui_session_id,
        category,
        kb_folder,
    )
    if IRRELEVANT not in answer:
        logger.info("▶ answer clean, skipping fallback")
        return answer

    try:
        bedrock_session = _bedrock_sessions.get(ui_session_id)
        prompt = f"History: {hist_txt}\nUser:{query}"
        logger.info("▶ fallback prompt=%.200s", prompt.replace("\n", " "))
        if category == "2" or fallback_doc != PRIOR_DOC:
            resp = retrieve_and_generate(
                prompt,
                GEN_ENQ_KB_ID,
                document=fallback_doc,
                session_id=bedrock_session,
                kb_path=kb_folder,
            )
        if category == "3":
            resp = retrieve_and_generate_prioritized_doc(
                prompt,
                GEN_ENQ_KB_ID,
                kb_folder,
                [PRIOR_DOC],
                session_id=bedrock_session,
            )
            logger.info("▶ used prioritized fallback")
        else:
            resp = retrieve_and_generate(
                prompt,
                GEN_ENQ_KB_ID,
                session_id=bedrock_session,
                kb_path=kb_folder,
            )
            logger.info("▶ used standard fallback")

        _bedrock_sessions[ui_session_id] = resp["sessionId"]
        logger.info("▶ new bedrock_session_id=%s", resp["sessionId"])

        if resp.get("citations") and resp["citations"][0].get(
            "retrievedReferences"
        ):
            new_ans = resp["output"]["text"]
            logger.info("EXIT  ◀ _fallback_qna -> new answer=%.200s", new_ans)
            return new_ans
    except Exception as e:
        logger.warning("EXCEPTION:  Fallback QnA failed: %s", e)

    cleaned = answer.replace(IRRELEVANT, "")
    logger.info("EXIT  ◀ _fallback_qna -> cleaned answer=%.200s", cleaned)
    return cleaned


def _store_chat_log(
    request: RequestQuery, answer: str, msg_id: str, session_id: str
) -> None:
    logger.info(
        "ENTER ▶ _store_chat_log(request.user.id=%s, msg_id=%s, session_id=%s)",
        request.user.id,
        msg_id,
        session_id,
    )
    if not request.user.id:
        logger.info("▶ no user.id — skipping store_interaction")
        return

    try:
        now = datetime.datetime.now().isoformat()
        logger.info("▶ timestamp = %s", now)
        if len(request.query.text) > 2046:
            user_msg_search = extract_keywords_from_query(
                request.query.text.lower()
            )
            logger.info("▶ extracted keywords for long text")
        else:
            user_msg_search = request.query.text.lower()
            logger.info("▶ user_msg_search = %.200s", user_msg_search)

        chat_meta = ChatMetadata(
            FileName="",
            FileLocation="",
            FlowName=QNA_FLOW_NAME,
            KbType=request.query.knowledgeType,
        )
        logger.info("▶ chat_meta = %s", chat_meta)
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
        logger.info("▶ store_interaction completed")
    except Exception as e:
        logger.exception("EXCEPTION:  Failed to store interaction: %s", e)
        raise


@router.post("/getqnaanswer/")
async def ask_question(request: RequestQuery) -> QueryResponse:
    """Handle a QnA request from the user.

    This function processes the incoming question, determines whether a summary is needed,
    checks for follow-up context, optionally invokes a language model directly, and/or performs
    knowledge base retrieval. It supports fallback logic and maintains session-aware continuity.

    Steps:
    - Check for summary-type input.
    - Construct a prompt including session history.
    - Attempt direct LLM response if no files are provided.
    - Retrieve documents and generate KB-based answer if needed.
    - Apply fallback classification logic if the initial answer is irrelevant.
    - Store the interaction and return the final result.

    Args:
        request (RequestQuery): The incoming user query with session and metadata.

    Returns:
        QueryResponse: The answer, citations, and feedback metadata wrapped in a standard format.
    """
    logger.info("000 ▶ enter ask_question")
    try:
        # generate message ID
        msg_id = str(uuid.uuid4())
        logger.info("010 ▶ msg_id = %s", msg_id)

        # extract user text and session
        user_txt = request.query.text.strip()
        ui_session_id = request.user.sessionId.strip() or str(uuid.uuid4())
        request.user.sessionId = ui_session_id
        tx_count = request.query.transactionCount
        files = request.query.files
        detected_unit = request.query.knowledgeType
        kb_path = get_knowledge_base_folder(detected_unit)
        bedrock_session_id = _bedrock_sessions.get(ui_session_id)
        citations = []
        logger.info("020 ▶ user_txt = %s", user_txt)
        logger.info("030 ▶ ui_session_id = %s", ui_session_id)
        logger.info("040 ▶ tx_count = %s", tx_count)
        logger.info("050 ▶ files = %s", files)
        logger.info("060 ▶ kb_path = %s", kb_path)
        logger.info("070 ▶ bedrock_session_id = %s", bedrock_session_id)

        if not files:
            matches = auto_attach_files(user_txt, kb_path)
            if matches:
                files = matches
                logger.info(
                    "💡 Auto-attached files = %s | from kb_path = %s",
                    files,
                    kb_path,
                )
            else:
                files = []

        # print("matches", matches)
        # print("files", files)

        # if "can handbook" in user_txt.lower() and not files:
        #     files = ["CAN HANDBOOK 4.0.pdf"]
        #     logger.info("💡 Auto-attached CAN HANDBOOK 4.0.pdf based on user query")

        # early summarykb_answer

        if needs_summary(user_txt):
            logger.info("080 ▶ summary needed")
            summary_text = llm_summarise(user_txt)
            _store_chat_log(request, summary_text, msg_id, ui_session_id)
            logger.info("090 ◀ returning summary")
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

        # prompt construction
        prompt, history_txt, is_follow_up = (
            _build_prompt_with_optional_history(
                user_txt, tx_count, ui_session_id
            )
        )

        selected_doc = detect_prior_doc_from_query(user_txt)
        if selected_doc != PRIOR_DOC:
            files = [selected_doc]
            logger.info(
                "100 ▶ auto-selected PRIOR_DOC override = %s", selected_doc
            )

        # INIT
        answer = ""

        # llm_answer_only = False
        resp = None
        # best_kb_resp = None

        if files:
            logger.info("190 ▶ files present — PRIORITIZED retrieval")
            try:
                resp = retrieve_and_generate_prioritized_doc(
                    prompt,
                    get_knowledge_base_id(request.query.knowledgeType),
                    kb_path,
                    files,
                    session_id=bedrock_session_id,
                )
                answer = resp["output"]["text"]
                citations = extract_file_locations(resp)
                _bedrock_sessions[ui_session_id] = resp["sessionId"]
                bedrock_session_id = resp["sessionId"]
                logger.info("200 ▶ prioritized answer = %.100s", answer)
            except Exception as e:
                logger.warning("210 ⚠ prioritized retrieval failed: %s", e)

        # direct LLM if no files
        if not files:
            try:
                logger.info("110 ▶ No files – trying direct LLM fallback")
                direct_resp = generate_answer_with_context(prompt)
                logger.debug("115 ▶ LLM raw response: %s", direct_resp)
                raw_content = direct_resp.get("content", [])
                if (
                    isinstance(raw_content, list)
                    and raw_content
                    and isinstance(raw_content[0], dict)
                ):
                    answer = raw_content[0].get("text", "").strip()
                    # llm_answer_only = bool(answer)
                    logger.info("120 ▶ Direct LLM answer retrieved")
            except Exception as e:
                logger.warning("130 EXCEPTION:  Direct LLM failed: %s", e)

        # always fetch KB documents for continuity (even if LLM answered)
        try:
            doc = {}
            logger.info("140 ▶ Performing KB-based retrieval")
            if files:
                logger.info("145 ▶ Files provided by user: %s", files)
                resp = retrieve_and_generate_prioritized_doc(
                    query=user_txt,
                    kb_id=get_knowledge_base_id(detected_unit),
                    knowledge_base_folder=kb_path,
                    files=files,
                    session_id=bedrock_session_id,
                )
            else:
                logger.info("145 ▶ No user files — performing full KB search")
                doc = retrieve_documents(
                    prompt,
                    get_knowledge_base_id(detected_unit),
                    REGION_ID,
                )
                hits = doc.get("retrievalResults", [])
                logger.info("150 ▶ retrieved %d documents", len(hits))
                # print("hits", hits)

                for hit in hits:
                    uri = hit.get("metadata", {}).get(
                        "x-amz-bedrock-kb-source-uri", ""
                    )
                    if PRIOR_DOC in uri:
                        logger.info("160 ▶ PRIOR_DOC matched")
                        resp = retrieve_and_generate_prioritized_doc(
                            query=prompt,
                            kb_id=get_knowledge_base_id(detected_unit),
                            knowledge_base_folder=kb_path,
                            files=[PRIOR_DOC],
                            session_id=bedrock_session_id,
                        )
                        break

                if not resp:
                    logger.info(
                        "170 ▶ No PRIOR_DOC – using standard retrieve_and_generate"
                    )
                    resp = retrieve_and_generate(
                        prompt,
                        get_knowledge_base_id(detected_unit),
                        session_id=bedrock_session_id,
                        kb_path=kb_path,
                    )
            logger.info(
                "📦 Raw KB response before extracting citations: %s",
                json.dumps(resp, indent=2),
            )
            # citations = extract_file_locations(resp)
            _bedrock_sessions[ui_session_id] = resp.get(
                "sessionId", bedrock_session_id
            )

            kb_answer = resp.get("output", {}).get("text", "").strip()
            kb_citations = extract_file_locations(resp)
            # print("kb_citations", kb_citations)

            if kb_answer and not is_invalid_response(kb_answer):
                logger.info(
                    "📦 Raw KB response before extracting citations: %s",
                    json.dumps(resp, indent=2),
                )
                logger.info("175 ▶ Final extracted citations = %s", citations)
                # is_priority = is_high_priority_query(user_txt, detected_unit)
                # should_overwrite_llm = (
                #     is_priority or not llm_answer_only or (is_follow_up and _was_last_answer_from_kb(ui_session_id))
                # )
                # if should_overwrite_llm:

                logger.info(
                    "180 ▶ Overwriting LLM answer due to KB relevance logic"
                )
                answer = kb_answer
                logger.info(
                    "🧪 Raw KB response before extracting citations: %s", resp
                )
                if not citations and kb_citations:
                    citations = kb_citations
                    logger.info(
                        "180 ▶ Final extracted citations = %s", citations
                    )
            else:
                logger.warning(
                    "⚠ KB retrieval returned an invalid response, skipping overwrite."
                )

        except Exception as e:
            logger.warning("190 ⚠ KB retrieval failed: %s", e)
            if not answer:
                raise HTTPException(
                    HTTP_500_INTERNAL_SERVER_ERROR,
                    f"Doc retrieval failed: {e}",
                )

        if not answer:
            logger.error("200 ▶ No answer generated – aborting")
            raise HTTPException(
                HTTP_500_INTERNAL_SERVER_ERROR, "Unable to generate an answer."
            )

        # fallback QnA
        try:
            if answer and not is_invalid_response(answer):
                logger.info(
                    "593 ▶ HERE WE ARE  post-fallback answer = %.100s", answer
                )
                logger.info("✅ Citations after fallback: %s", citations)
                if not citations:
                    citations = extract_file_locations(resp)
                    logger.info(
                        "🛑 Skipping fallback — valid KB answer already present"
                    )
            else:
                cat = prompt_query_cat(user_txt.lower())
                logger.info("210 ▶ prompt_query_cat = %s", cat)
                answer = _fallback_qna(
                    prompt, answer, ui_session_id, "2", kb_path, history_txt
                )
                logger.info("220 ▶ post-fallback answer = %.100s", answer)
        except Exception as e:
            logger.warning("230 EXCEPTION:  fallback QnA failed: %s", e)
        # answer = re.split(r"\nUser:\s", answer)[0].strip()
        # sanitized_answer = response_sanitizer(answer)
        if not citations and "retrievalResults" in doc:
            logger.info(
                "📌 Citations empty — attaching fallback citations from doc retrieval."
            )
            citations = []
            for hit in doc["retrievalResults"]:
                uri = hit.get("metadata", {}).get(
                    "x-amz-bedrock-kb-source-uri", ""
                )
                page = hit.get("metadata", {}).get(
                    "x-amz-bedrock-kb-document-page-number", 0
                )
                if uri:
                    citations.append(
                        {
                            "filePath": uri,  # optional: presign it
                            "pageNumber": int(page),
                            "fileName": uri.split("/")[-1],
                        }
                    )
        # logger.info(
        #     f"230 ▶ Sanitized final answer before logging and return --> \n answer: {answer} \n sanitized answer {sanitized_answer}"
        # )

        # store
        logger.info("240 ▶ storing chat log")
        _store_chat_log(request, answer, msg_id, ui_session_id)

        logger.info("250 ◀ exit ask_question SUCCESS")

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
        logger.info("260 ◀ exit ask_question HTTPException: %s", http_exc)
        raise http_exc
    except Exception as e:
        logger.exception("270 EXCEPTION:  unhandled exception in ask_question")
        raise HTTPException(
            HTTP_500_INTERNAL_SERVER_ERROR, f"Unexpected error: {e}"
        )
