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
    retrieve_citations_from_query,
    retrieve_documents,
    retrieve_file_chunks,
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
        # logger.info("▶ fetched raw history for session: %s", history.get(session_id))
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
    user_txt: str, tx_count: int, ui_session_id: str, files: list
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
        # existing_history = session_history(ui_session_id)
        existing_history = False
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
        if files:
            classification_prompt = FOLLOW_UP_PROMPT.format(
                context=history_txt, query=user_txt
            )
            # logger.info(
            #     "▶ follow-up classification_prompt=%.200s",
            #     classification_prompt.replace("\n", " "),
            # )
            resp = generate_answer_with_context(classification_prompt)

            result_text = resp.get("content", [{}])[0].get("text", "").strip()
            logger.info(f"▶ follow up response line 148 {result_text}")
            logger.info("▶ classification result_text=%.200s", result_text)
            is_follow_up = result_text.startswith("IS_FOLLOW_UP:")
            full_prompt = (
                f"{history_txt}\nUser: {user_txt} file to compare {files}"
            )
        if not files:
            classification_prompt = FOLLOW_UP_PROMPT.format(
                context=history_txt, query=user_txt
            )
            # logger.info(
            #     "▶ follow-up classification_prompt=%.200s",
            #     classification_prompt.replace("\n", " "),
            # )
            resp = generate_answer_with_context(classification_prompt)

            result_text = resp.get("content", [{}])[0].get("text", "").strip()
            logger.info(f"▶ follow up response line 148 {result_text}")
            logger.info("▶ classification result_text=%.200s", result_text)
            is_follow_up = result_text.startswith("IS_FOLLOW_UP:")
            full_prompt = f"{history_txt}\nUser: {user_txt}"

    except Exception as e:
        logger.exception(
            "EXCEPTION: Classification failed, defaulting to include history: %s",
            e,
        )
        # full_prompt = f"{history_txt}\nUser: {user_txt}"

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
    """Handle a QnA request from the user."""
    logger.info("000 ▶ enter ask_question")
    try:
        # Step 1: Generate message/session IDs
        msg_id = str(uuid.uuid4())
        logger.info("010 ▶ msg_id = %s", msg_id)

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

        # Step 2: Attach files based on detected keywords if no files
        if not files:
            logger.info(
                "075 ▶ No files provided – checking for auto-attach opportunities"
            )
            matches = auto_attach_files(user_txt, kb_path)
            if matches:
                files = matches
                logger.info(
                    "076 ▶ Auto-attached files based on user query = %s | kb_path = %s",
                    files,
                    kb_path,
                )
            else:
                logger.info("077 ▶ No files auto-attached")
                files = []
        logger.info(
            "080 ▶ files after auto attach = %s", files
        )  # moved log for step clarity

        # Step 3: Handle summary requests first
        label = needs_summary(user_txt)
        logger.info(f"the label {label}")

        if label == "IRRELEVANT":
            logger.info(
                "080 ▶ Irrelevant query detected – returning default help response"
            )
            default_msg = (
                "Sorry, I can't help you with that request. "
                "However, I can assist you with Contracting Clauses, confidentiality agreements, and payment terms."
            )
            _store_chat_log(request, default_msg, msg_id, ui_session_id)
            logger.info("090 ◀ returning IRRELEVANT response")
            return QueryResponse(
                status="success",
                sessionId=ui_session_id,
                userQuery=user_txt,
                result=Result(
                    messageId=msg_id,
                    answer=QnAAnswer(ans=default_msg),
                    transactionCount=tx_count,
                    citations=[],
                    feedback=Feedback(
                        feedbackDisplayOptions=FeedbackDisplayOptions(
                            thumbsUp="Y", thumbsDown="Y", feedbackText="Y"
                        )
                    ),
                ),
            )

        elif label == "SUMMARY":
            logger.info("081 ▶ Summary requested – entering summary flow")
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

        # Step 4: Prompt construction and follow-up detection
        logger.info(
            "100 ▶ Building prompt, loading session history and follow-up detection"
        )
        prompt, history_txt, is_follow_up = (
            _build_prompt_with_optional_history(
                user_txt, tx_count, ui_session_id, files
            )
        )
        first_user_msg = (
            _get_session_chat_history(ui_session_id)
            .split("\n")[0]
            .removeprefix("User: ")
            .strip()
        )
        selected_doc = detect_prior_doc_from_query(user_txt)
        if selected_doc != PRIOR_DOC:
            files = [selected_doc]
            logger.info(
                "101 ▶ auto-selected PRIOR_DOC override = %s", selected_doc
            )

        answer = ""
        resp = None
        excluded = ["database", "standard", "standards", "backend"]

        # Step 5: Main flow – If it's a follow-up
        if is_follow_up:
            logger.info("110 ▶ is_follow_up detected")
            if files:
                try:
                    logger.info(
                        "111 ▶ Follow-up with files: Retrieving KB content"
                    )

                    kb_path = get_knowledge_base_folder(detected_unit)
                    kb_id = get_knowledge_base_id(detected_unit)

                    all_chunks = []

                    limited_files = files[:3]
                    logger.info(
                        "112 ▶ Retrieving file contents for: %s", limited_files
                    )

                    file_chunks_map = retrieve_file_chunks(
                        kb_id=kb_id,
                        documents=limited_files,
                        kb_path=kb_path,
                        query=first_user_msg,
                    )

                    for doc_name, file_text in file_chunks_map.items():
                        if file_text:
                            all_chunks.append(
                                f"--- Content from {doc_name} ---\n{file_text}"
                            )
                            print(
                                "✅ file text from",
                                doc_name,
                                ":",
                                file_text[:300],
                            )

                    kb_text = "\n\n".join(all_chunks).strip()

                    if not kb_text:
                        logger.warning(
                            "113 ⚠ No content extracted from files – will fallback."
                        )
                        augmented_prompt = f"You are a professional contract assistant for AstraZeneca. this is the user history: {history_txt}\n\nUser Query: {user_txt}\n\nRelevant File Content:\n{kb_text}. If you don't receive any File Content, or you receive an error you must exactly reply: I can't access to the {{file}} content for this query."

                        logger.info(
                            "114 ▶ Calling LLM with KB-augmented prompt"
                        )
                        direct_resp = generate_answer_with_context(
                            augmented_prompt
                        )
                        logger.debug("115 ▶ LLM raw response: %s", direct_resp)

                        raw_content = direct_resp.get("content", [])
                        if (
                            isinstance(raw_content, list)
                            and raw_content
                            and isinstance(raw_content[0], dict)
                        ):
                            answer = raw_content[0].get("text", "").strip()
                            logger.info(
                                "116 ▶ Direct LLM answer retrieved with files"
                            )

                        logger.info(
                            "117 ▶ Returning success response for follow-up with files"
                        )
                        answer = re.split(r"\nUser:\s", answer)[0].strip()
                        citations = retrieve_citations_from_query(answer)

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
                                        thumbsUp="Y",
                                        thumbsDown="Y",
                                        feedbackText="Y",
                                    )
                                ),
                            ),
                        )

                    augmented_prompt = f"You are a professional contract assistant for AstraZeneca. this is the user history: {history_txt}\n\nUser Query: {user_txt}\n\nRelevant File Content:\n{kb_text}. If you don't receive any File Content, or you receive an error you must exactly reply: I can't access to the {{file}} content for this query. Please consider changing tabs or refrasing the question."

                    logger.info("114 ▶ Calling LLM with KB-augmented prompt")
                    direct_resp = generate_answer_with_context(
                        augmented_prompt
                    )
                    logger.debug("115 ▶ LLM raw response: %s", direct_resp)

                    raw_content = direct_resp.get("content", [])
                    if (
                        isinstance(raw_content, list)
                        and raw_content
                        and isinstance(raw_content[0], dict)
                    ):
                        answer = raw_content[0].get("text", "").strip()
                        logger.info(
                            "116 ▶ Direct LLM answer retrieved with files"
                        )

                    logger.info(
                        "117 ▶ Returning success response for follow-up with files"
                    )
                    answer = re.split(r"\nUser:\s", answer)[0].strip()
                    citations = retrieve_citations_from_query(answer)
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
                                    thumbsUp="Y",
                                    thumbsDown="Y",
                                    feedbackText="Y",
                                )
                            ),
                        ),
                    )
                except Exception as e:
                    logger.warning(
                        "130 EXCEPTION: Direct LLM with KB context failed: %s",
                        e,
                    )
            elif not files:
                logger.info("120 ▶ Follow-up with no files")
                check = (user_txt[:50] + user_txt[-50:]).lower()
                comparing = r"(compare( the (second )?clause)? (with|to) )"

                if re.search(comparing, check):
                    if not any(term in check for term in excluded):
                        logger.info(
                            "121 ▶ User query is a comparison and no excluded terms found – fallback to PRIOR_DOC"
                        )
                        try:
                            kb_path = get_knowledge_base_folder(detected_unit)
                            kb_id = get_knowledge_base_id(detected_unit)

                            all_chunks = []

                            # Try retrieving the PRIOR_DOC fallback
                            selected_doc = detect_prior_doc_from_query(
                                user_txt
                            )
                            fallback_files = (
                                [selected_doc]
                                if selected_doc != PRIOR_DOC
                                else [PRIOR_DOC]
                            )
                            logger.info(
                                "122 ▶ Fallback to file(s): %s", fallback_files
                            )

                            file_chunks_map = retrieve_file_chunks(
                                kb_id=kb_id,
                                documents=fallback_files,
                                kb_path=kb_path,
                                query=first_user_msg,
                            )

                            for doc_name, file_text in file_chunks_map.items():
                                if file_text:
                                    all_chunks.append(
                                        f"--- Content from {doc_name} ---\n{file_text}"
                                    )
                                    print(
                                        "✅ file text from",
                                        doc_name,
                                        ":",
                                        file_text[:300],
                                    )

                            kb_text = "\n\n".join(all_chunks).strip()

                            if not kb_text:
                                logger.warning(
                                    "123 ⚠ No fallback KB content – will use unavailable template"
                                )
                                augmented_prompt = f"You are a professional contract assistant for AstraZeneca. this is the user history: {history_txt}\n\nUser Query: {user_txt}\n\nRelevant File Content: {kb_text} [Unavailable — file could not be accessed or retrieved.] . If you don't receive any File Content, or you receive an error you must exactly reply: I can't access to the {{file}} content. Please consider changing tabs."

                                direct_resp = generate_answer_with_context(
                                    augmented_prompt
                                )
                                raw_content = direct_resp.get("content", [])
                                if (
                                    isinstance(raw_content, list)
                                    and raw_content
                                    and isinstance(raw_content[0], dict)
                                ):
                                    answer = (
                                        raw_content[0].get("text", "").strip()
                                    )
                                    logger.info(
                                        "124 ▶ No KB content for compare – returning fallback LLM response"
                                    )
                                answer = re.split(r"\nUser:\s", answer)[
                                    0
                                ].strip()
                                citations = retrieve_citations_from_query(
                                    answer
                                )
                                _store_chat_log(
                                    request, answer, msg_id, ui_session_id
                                )
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
                                                thumbsUp="Y",
                                                thumbsDown="Y",
                                                feedbackText="Y",
                                            )
                                        ),
                                    ),
                                )

                            augmented_prompt = f"You are a professional contract assistant for AstraZeneca. this is the user history: {history_txt}\n\nUser Query: {user_txt}\n\nRelevant File Content:\n{kb_text}. If you don't receive any File Content, or you receive an error you must exactly reply: I can't access to the {{file}} content. Please consider changing tabs."

                            logger.info(
                                "125 ▶ Calling LLM for compare fallback"
                            )
                            direct_resp = generate_answer_with_context(
                                augmented_prompt
                            )
                            logger.debug(
                                "126 ▶ Fallback LLM response: %s", direct_resp
                            )

                            raw_content = direct_resp.get("content", [])
                            if (
                                isinstance(raw_content, list)
                                and raw_content
                                and isinstance(raw_content[0], dict)
                            ):
                                answer = raw_content[0].get("text", "").strip()
                                logger.info(
                                    "127 ▶ Fallback LLM answer retrieved"
                                )

                            answer = re.split(r"\nUser:\s", answer)[0].strip()
                            citations = retrieve_citations_from_query(answer)
                            _store_chat_log(
                                request, answer, msg_id, ui_session_id
                            )
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
                                            thumbsUp="Y",
                                            thumbsDown="Y",
                                            feedbackText="Y",
                                        )
                                    ),
                                ),
                            )
                        except Exception as e:
                            logger.warning(
                                "128 ❌ Exception in fallback compare path: %s",
                                e,
                            )
                elif any(term in check for term in excluded):
                    try:
                        logger.info(
                            "129 ▶ ELIF ANY - No files, excluded term found – using KB"
                        )
                        resp = retrieve_and_generate(
                            prompt,
                            get_knowledge_base_id(detected_unit),
                            session_id=bedrock_session_id,
                            kb_path=kb_path,
                        )
                        answer = resp["output"]["text"]
                        citations = extract_file_locations(resp)
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
                                        thumbsUp="Y",
                                        thumbsDown="Y",
                                        feedbackText="Y",
                                    )
                                ),
                            ),
                        )

                    except Exception as e:
                        logger.warning(
                            "132 EXCEPTION:  Direct LLM failed: %s", e
                        )
                elif "compare" in check:
                    logger.info(
                        "129 ▶ ELIF COMPARE - No files, excluded term found – using direct LLM"
                    )
                    direct_resp = generate_answer_with_context(prompt)
                    logger.debug("130 ▶ LLM raw response: %s", direct_resp)
                    raw_content = direct_resp.get("content", [])
                    if (
                        isinstance(raw_content, list)
                        and raw_content
                        and isinstance(raw_content[0], dict)
                    ):
                        answer = raw_content[0].get("text", "").strip()
                        logger.info(
                            "131 ▶ Direct LLM answer retrieved with excluded term"
                        )
                    answer = re.split(r"\nUser:\s", answer)[0].strip()
                    citations = retrieve_citations_from_query(answer)
                    _store_chat_log(request, answer, msg_id, ui_session_id)

                    logger.info("520 ◀ exit ask_question SUCCESS")

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
                                    thumbsUp="Y",
                                    thumbsDown="Y",
                                    feedbackText="Y",
                                )
                            ),
                        ),
                    )
                else:
                    logger.info("Else, excluded term found – using direct LLM")
                    direct_resp = generate_answer_with_context(prompt)
                    logger.debug("130 ▶ LLM raw response: %s", direct_resp)
                    raw_content = direct_resp.get("content", [])
                    if (
                        isinstance(raw_content, list)
                        and raw_content
                        and isinstance(raw_content[0], dict)
                    ):
                        answer = raw_content[0].get("text", "").strip()
                        logger.info(
                            "131 ▶ Direct LLM answer retrieved with excluded term"
                        )

                    answer = re.split(r"\nUser:\s", answer)[0].strip()
                    citations = retrieve_citations_from_query(answer)
                    _store_chat_log(request, answer, msg_id, ui_session_id)

                    logger.info("520 ◀ exit ask_question SUCCESS")

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
                                    thumbsUp="Y",
                                    thumbsDown="Y",
                                    feedbackText="Y",
                                )
                            ),
                        ),
                    )

        # Step 6: Not follow-up – If files, prioritize file-based retrieval
        elif files:
            logger.info(
                "190 ▶ Not follow-up but files present – prioritized doc retrieval"
            )
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

        # Step 7: Not follow-up and no files – use direct LLM
        elif not files:
            logger.info("220 ▶ Not follow-up and no files – using direct LLM")
            try:
                direct_resp = generate_answer_with_context(prompt)
                logger.debug("221 ▶ LLM raw response: %s", direct_resp)
                raw_content = direct_resp.get("content", [])
                if (
                    isinstance(raw_content, list)
                    and raw_content
                    and isinstance(raw_content[0], dict)
                ):
                    answer = raw_content[0].get("text", "").strip()
                    logger.info("222 ▶ Direct LLM answer retrieved")
                    citations = retrieve_citations_from_query(answer)
            except Exception as e:
                logger.warning("223 EXCEPTION:  Direct LLM failed: %s", e)

        # Step 8: Always try KB retrieval for citation and answer upgrade
        try:
            doc = {}
            logger.info(
                "300 ▶ Entering KB retrieval for citations and answer refinement"
            )
            if files:
                logger.info("301 ▶ Files provided for KB retrieval: %s", files)
                resp = retrieve_and_generate_prioritized_doc(
                    query=user_txt,
                    kb_id=get_knowledge_base_id(detected_unit),
                    knowledge_base_folder=kb_path,
                    files=files,
                    session_id=bedrock_session_id,
                )
            else:
                logger.info("302 ▶ No files for KB retrieval – full KB search")
                doc = retrieve_documents(
                    prompt,
                    get_knowledge_base_id(detected_unit),
                    REGION_ID,
                )
                hits = doc.get("retrievalResults", [])
                logger.info("303 ▶ KB search returned %d documents", len(hits))
                for hit in hits:
                    uri = hit.get("metadata", {}).get(
                        "x-amz-bedrock-kb-source-uri", ""
                    )
                    if PRIOR_DOC in uri:
                        logger.info(
                            "304 ▶ PRIOR_DOC matched in KB retrieval, using prioritized doc"
                        )
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
                        "305 ▶ No PRIOR_DOC found – using standard retrieve_and_generate"
                    )
                    resp = retrieve_and_generate(
                        prompt,
                        get_knowledge_base_id(detected_unit),
                        session_id=bedrock_session_id,
                        kb_path=kb_path,
                    )
            logger.info(
                "306 ▶ Raw KB response (pre-citation extraction): %s",
                json.dumps(resp, indent=2),
            )

            _bedrock_sessions[ui_session_id] = resp.get(
                "sessionId", bedrock_session_id
            )
            kb_answer = resp.get("output", {}).get("text", "").strip()
            kb_citations = extract_file_locations(resp)

            if kb_answer and not is_invalid_response(kb_answer):
                logger.info(
                    "307 ▶ KB answer deemed valid, will overwrite previous LLM answer"
                )
                answer = kb_answer
                if not citations and kb_citations:
                    citations = kb_citations
            else:
                logger.warning(
                    "308 ⚠ KB retrieval returned invalid/empty response – keeping prior answer"
                )

        except Exception as e:
            logger.warning("309 ⚠ KB retrieval failed: %s", e)
            if not answer:
                logger.error(
                    "310 ▶ No answer after KB failure – raising HTTPException"
                )
                raise HTTPException(
                    HTTP_500_INTERNAL_SERVER_ERROR,
                    f"Doc retrieval failed: {e}",
                )

        if not answer:
            logger.error("320 ▶ No answer generated – aborting (HTTP 500)")
            raise HTTPException(
                HTTP_500_INTERNAL_SERVER_ERROR, "Unable to generate an answer."
            )

        # Step 9: Fallback QnA logic and logging
        try:
            if answer and not is_invalid_response(answer):
                logger.info(
                    "400 ▶ Valid answer present, skipping further fallback. Answer = %.100s",
                    answer,
                )
                if not citations:
                    citations = extract_file_locations(resp)
                    logger.info(
                        "401 ▶ No citations on valid answer, extracting from resp."
                    )
            else:
                logger.info(
                    f"402 ▶ Answer is invalid/empty, would be falling in FALLBACK QNA: {answer}"
                )
        except Exception as e:
            logger.warning("403 EXCEPTION: fallback QnA failed: %s", e)

        if not citations and "retrievalResults" in doc:
            logger.info(
                "410 ▶ Citations empty, attaching fallback citations from doc retrieval."
            )
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
                            "filePath": uri,
                            "pageNumber": int(page),
                            "fileName": uri.split("/")[-1],
                        }
                    )

        logger.info("500 ▶ Final Citations to Results: %s", citations)
        logger.info("510 ▶ Storing chat log")
        answer = re.split(r"\nUser:\s", answer)[0].strip()

        _store_chat_log(request, answer, msg_id, ui_session_id)

        logger.info("520 ◀ exit ask_question SUCCESS")

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
        logger.info("600 ◀ exit ask_question HTTPException: %s", http_exc)
        raise http_exc
    except Exception as e:
        logger.exception("700 EXCEPTION:  unhandled exception in ask_question")
        raise HTTPException(
            HTTP_500_INTERNAL_SERVER_ERROR, f"Unexpected error: {e}"
        )
