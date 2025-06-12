"""Routes and logic for handling user QnA requests via chat interface."""

from __future__ import annotations

import datetime
import json
import logging
import re
import uuid

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
from prompts import AUGMENTED_PROMPT, FOLLOW_UP_PROMPT
from services import (
    auto_attach_files,
    auto_attach_files_gxp_citation,
    detect_prior_doc_from_query,
    extract_file_locations,
    generate_answer_with_context,
    is_invalid_response,
    retrieve_and_generate,
    retrieve_and_generate_prioritized_doc,
    retrieve_citations_from_query,
    retrieve_documents,
    retrieve_file_chunks,
    session_history,
    store_interaction,
    tia_followup_user_query,
    tia_trigger_initial_clarification,
)
from starlette.status import HTTP_500_INTERNAL_SERVER_ERROR
from utils import (
    db_tab_checker,
    extract_keywords_from_query,
    get_knowledge_base_folder,
    get_knowledge_base_id,
    llm_summarise,
    needs_summary,
)

from .constants import (
    PRIOR_DOC,
    QNA_FLOW_NAME,
    REGION_ID,
    SESSION_STATUS,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["QnA"], dependencies=[Depends(verify_token)])

# Mapping from UI session IDs to Bedrock session IDs.
_bedrock_sessions: dict[str, str] = {}


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

            resp = generate_answer_with_context(classification_prompt)

            result_text = resp.get("content", [{}])[0].get("text", "").strip()
            logger.info(f"▶ follow up response line 148 {result_text}")
            logger.info("▶ classification result_text=%.200s", result_text)
            is_follow_up = result_text.startswith("IS_FOLLOW_UP:")
            if is_follow_up:
                full_prompt = f"{history_txt}\nUser: {user_txt}"
            else:
                full_prompt = user_txt

    except Exception as e:
        logger.exception(
            "EXCEPTION: Classification failed, defaulting to include history: %s",
            e,
        )

    logger.info(
        "EXIT  ◀ _build_prompt | full_prompt_preview=%.200s",
        full_prompt.replace("\n", " "),
    )
    return full_prompt, history_txt, is_follow_up


def _store_chat_log(
    request: RequestQuery,
    answer: str,
    msg_id: str,
    session_id: str,
    start_time: str,
    end_time: str,
    citations: list,
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
            FileName=citations,
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
                IsFeedbackPositive="no_feedback",
                Timestamp=now,
                StartTime=start_time,
                EndTime=end_time,
                SessionStatus=SESSION_STATUS,
                MessageId=msg_id,
                ChatMetadata=chat_meta,
            )
        )
        logger.info("▶ store_interaction completed")
    except Exception as e:
        logger.exception("EXCEPTION:  Failed to store interaction: %s", e)
        raise


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


@router.post("/getqnaanswer/")
async def ask_question(request: RequestQuery) -> QueryResponse:
    """Handle a QnA request from the user."""
    logger.info("000 ▶ enter ask_question")
    try:
        # Step 1: Generate message/session IDs
        start_time = datetime.datetime.now().isoformat()
        msg_id = str(uuid.uuid4())
        logger.info("010 ▶ msg_id = %s", msg_id)

        user_txt = request.query.text.strip()
        ui_session_id = request.user.sessionId.strip() or str(uuid.uuid4())
        request.user.sessionId = ui_session_id
        tx_count = request.query.transactionCount
        files = request.query.files
        detected_unit = request.query.knowledgeType
        kb_path = get_knowledge_base_folder(detected_unit)
        kb_id = get_knowledge_base_id(detected_unit)
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
        logger.info("080 ▶ files after auto attach = %s", files)

        # Step 2-b: Attach files for GxP citation-related issues
        if not files:
            logger.info(
                "075 ▶ No files provided – checking for auto-attach opportunities"
            )

            # Use defect-specific file matcher for GCP citations (CROs, Service Providers)
            matches = auto_attach_files_gxp_citation(user_txt, kb_path)
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

        logger.info("080 ▶ files after auto attach = %s", files)

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
            end_time = datetime.datetime.now().isoformat()
            _store_chat_log(
                request,
                default_msg,
                msg_id,
                ui_session_id,
                start_time,
                end_time,
                citations=[],
            )
            logger.info("090 ◀ returning IRRELEVANT response")
            return QueryResponse(
                startTime=start_time,
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
                            thumbsUp="N", thumbsDown="N", feedbackText="N"
                        )
                    ),
                ),
            )

        elif label == "SUMMARY":
            logger.info("081 ▶ Summary requested – entering summary flow")
            summary_text = llm_summarise(user_txt)
            end_time = datetime.datetime.now().isoformat()
            _store_chat_log(
                request,
                summary_text,
                msg_id,
                ui_session_id,
                start_time,
                end_time,
                citations=[],
            )
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
                            thumbsUp="N", thumbsDown="N", feedbackText="N"
                        )
                    ),
                ),
            )

        if user_txt.lower() == "continue":
            logger.info(
                "User override: skipping tab check and continuing as requested."
            )
            # Proceed directly to QnA/answer logic using the current tab.
        else:
            topic_check = await db_tab_checker(user_txt)
            kb_map = {"general": "A", "alexion": "B", "privacy": "C"}
            tab_names = {
                "A": "General Queries",
                "B": "Alexion",
                "C": "Privacy",
            }
            selected_tab = kb_map.get(kb_path)

            if topic_check != selected_tab:
                logger.info(
                    "Tab mismatch: user in %s, LLM suggests %s for query: %r",
                    tab_names.get(selected_tab, selected_tab),
                    tab_names.get(topic_check, topic_check),
                    user_txt,
                )
                confirmation_msg = (
                    f"The question you’re asking looks like it belongs to the {tab_names[topic_check]} tab, "
                    f"but you’re currently in {tab_names[selected_tab]}.\n"
                    "Please consider switch tabs and ask again.\n"
                    'Or, if you want to continue here anyway, just reply "continue".'
                )
                end_time = datetime.datetime.now().isoformat()
                _store_chat_log(
                    request,
                    confirmation_msg,
                    msg_id,
                    ui_session_id,
                    start_time,
                    end_time,
                    citations=[],
                )
                return QueryResponse(
                    status="success",
                    sessionId=ui_session_id,
                    userQuery=user_txt,
                    result=Result(
                        messageId=msg_id,
                        answer=QnAAnswer(ans=confirmation_msg),
                        transactionCount=tx_count,
                        citations=[],
                        feedback=Feedback(
                            feedbackDisplayOptions=FeedbackDisplayOptions(
                                thumbsUp="N", thumbsDown="N", feedbackText="N"
                            )
                        ),
                    ),
                )

        # Step 3-b: TIA clarification and detection
        logger.info("085 ▶ Checking for TIA clarification")
        chat_history_list = [
            msg["UserMessage"]
            for msg in session_history(ui_session_id).get(ui_session_id, [])
            if msg.get("UserMessage")
        ]
        # Only proceed with TIA logic if query is TIA-relevant
        if tia_trigger_initial_clarification(user_txt):
            tia_clarification_text = tia_followup_user_query(
                user_txt, int(tx_count), chat_history_list, ui_session_id
            )

            try:
                if (
                    tia_clarification_text
                    and tia_clarification_text != "FINAL_RESPONSE_REQUIRED"
                ):
                    logger.info(
                        "[Clarification Needed] Skipping KB and responding with follow-up questions."
                    )
                    end_time = datetime.datetime.now().isoformat()
                    _store_chat_log(
                        request,
                        tia_clarification_text,
                        msg_id,
                        ui_session_id,
                        start_time,
                        end_time,
                        citations=[],
                    )
                    return QueryResponse(
                        status="success",
                        sessionId=ui_session_id,
                        userQuery=user_txt,
                        result=Result(
                            messageId=msg_id,
                            answer=QnAAnswer(ans=tia_clarification_text),
                            transactionCount=tx_count,
                            citations=[],
                            feedback=Feedback(
                                feedbackDisplayOptions=FeedbackDisplayOptions(
                                    thumbsUp="N",
                                    thumbsDown="N",
                                    feedbackText="N",
                                )
                            ),
                        ),
                    )
            except Exception as e:
                logger.warning(
                    "Clarification for TIA failed: %s",
                    e,
                )
            pass

        # Step 4: Prompt construction and follow-up detection

        ## Backdating temporary fix
        user_txt_lower = user_txt.lower()
        reset_history_for_backdating = any(
            kw in user_txt_lower
            for kw in ["backdating", "backdate", "backdated"]
        )

        if reset_history_for_backdating:
            logger.info(
                "Backdating detected. Prompt will be built without previous history/context."
            )
            chat_history_list = []  # ensure it's always empty for backdating
        else:
            chat_history_list = [
                msg["UserMessage"]
                for msg in session_history(ui_session_id).get(
                    ui_session_id, []
                )
                if msg.get("UserMessage")
            ]

        # Usual followup flow

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
            files = selected_doc
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
                        augmented_prompt = AUGMENTED_PROMPT.format(
                            history_txt=history_txt,
                            user_txt=user_txt,
                            kb_text=kb_text,
                        )

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
                        if is_invalid_response(answer):
                            citations = []
                        else:
                            citations = retrieve_citations_from_query(
                                query=answer,
                                kb_id=kb_id,
                                kb_path=kb_path,
                                files=files,
                            )
                        end_time = datetime.datetime.now().isoformat()
                        _store_chat_log(
                            request,
                            answer,
                            msg_id,
                            ui_session_id,
                            start_time,
                            end_time,
                            citations,
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
                                feedbackDisplayOptions=FeedbackDisplayOptions(
                                    thumbsUp="N",
                                    thumbsDown="N",
                                    feedbackText="N",
                                ),
                            ),
                        )

                    augmented_prompt = AUGMENTED_PROMPT.format(
                        history_txt=history_txt,
                        user_txt=user_txt,
                        kb_text=kb_text,
                    )

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
                    if is_invalid_response(answer):
                        citations = []
                    else:
                        citations = retrieve_citations_from_query(
                            query=answer,
                            kb_id=kb_id,
                            kb_path=kb_path,
                            files=files,
                        )
                    end_time = datetime.datetime.now().isoformat()
                    _store_chat_log(
                        request,
                        answer,
                        msg_id,
                        ui_session_id,
                        start_time,
                        end_time,
                        citations,
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
                                    thumbsUp="N",
                                    thumbsDown="N",
                                    feedbackText="N",
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
                                    "123 ⚠ No fallback KB content - will use unavailable template"
                                )
                                augmented_prompt = AUGMENTED_PROMPT.format(
                                    history_txt=history_txt,
                                    user_txt=user_txt,
                                    kb_text=kb_text,
                                )

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
                                if is_invalid_response(answer):
                                    citations = []
                                else:
                                    citations = retrieve_citations_from_query(
                                        query=answer,
                                        kb_id=kb_id,
                                        kb_path=kb_path,
                                        files=files,
                                    )
                                end_time = datetime.datetime.now().isoformat()
                                _store_chat_log(
                                    request,
                                    answer,
                                    msg_id,
                                    ui_session_id,
                                    start_time,
                                    end_time,
                                    citations,
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
                                                thumbsUp="N",
                                                thumbsDown="N",
                                                feedbackText="N",
                                            )
                                        ),
                                    ),
                                )

                            augmented_prompt = AUGMENTED_PROMPT.format(
                                history_txt=history_txt,
                                user_txt=user_txt,
                                kb_text=kb_text,
                            )

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
                            if is_invalid_response(answer):
                                citations = []
                            else:
                                citations = retrieve_citations_from_query(
                                    query=answer,
                                    kb_id=kb_id,
                                    kb_path=kb_path,
                                    files=files,
                                )
                            end_time = datetime.datetime.now().isoformat()
                            _store_chat_log(
                                request,
                                answer,
                                msg_id,
                                ui_session_id,
                                start_time,
                                end_time,
                                citations,
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
                                            thumbsUp="N",
                                            thumbsDown="N",
                                            feedbackText="N",
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
                        if is_invalid_response(answer):
                            citations = []
                        else:
                            citations = extract_file_locations(
                                resp, allowed_files=files if files else None
                            )
                        end_time = datetime.datetime.now().isoformat()
                        _store_chat_log(
                            request,
                            answer,
                            msg_id,
                            ui_session_id,
                            start_time,
                            end_time,
                            citations,
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
                                feedbackDisplayOptions=FeedbackDisplayOptions(
                                    thumbsUp="N",
                                    thumbsDown="N",
                                    feedbackText="N",
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

                    if is_invalid_response(answer):
                        citations = []
                    else:
                        citations = retrieve_citations_from_query(
                            query=answer,
                            kb_id=kb_id,
                            kb_path=kb_path,
                            files=files,
                        )
                    end_time = datetime.datetime.now().isoformat()
                    _store_chat_log(
                        request,
                        answer,
                        msg_id,
                        ui_session_id,
                        start_time,
                        end_time,
                        citations,
                    )

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
                                    thumbsUp="N",
                                    thumbsDown="N",
                                    feedbackText="N",
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
                    if is_invalid_response(answer):
                        citations = []
                    else:
                        citations = retrieve_citations_from_query(
                            query=answer,
                            kb_id=kb_id,
                            kb_path=kb_path,
                            files=files,
                        )
                    end_time = datetime.datetime.now().isoformat()
                    _store_chat_log(
                        request,
                        answer,
                        msg_id,
                        ui_session_id,
                        start_time,
                        end_time,
                        citations,
                    )

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
                                    thumbsUp="N",
                                    thumbsDown="N",
                                    feedbackText="N",
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

                if is_invalid_response(answer):
                    citations = []
                else:
                    citations = extract_file_locations(
                        resp, allowed_files=files if files else None
                    )
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
                    if is_invalid_response(answer):
                        citations = []
                    else:
                        citations = retrieve_citations_from_query(
                            query=answer,
                            kb_id=kb_id,
                            kb_path=kb_path,
                            files=files,
                        )
            except Exception as e:
                logger.warning("223 EXCEPTION:  Direct LLM failed: %s", e)

        # Step 8: Always try KB retrieval for citation and answer upgrade
        try:
            doc = {}
            logger.info(
                "300 ▶ Entering KB retrieval for citations and answer refinement"
            )
            if not files:
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
            if is_invalid_response(kb_answer):
                kb_citations = []
            else:
                kb_citations = extract_file_locations(
                    resp, allowed_files=files if files else None
                )

            if kb_answer and not is_invalid_response(kb_answer):
                logger.info(
                    "307 ▶ KB answer deemed valid, will overwrite previous LLM answer"
                )
                answer = kb_answer
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
                    citations = extract_file_locations(
                        resp, allowed_files=files if files else None
                    )
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

        end_time = datetime.datetime.now().isoformat()
        _store_chat_log(
            request,
            answer,
            msg_id,
            ui_session_id,
            start_time,
            end_time,
            citations,
        )

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
                        thumbsUp="N", thumbsDown="N", feedbackText="N"
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
