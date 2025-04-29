import datetime
import logging
import pickle
import re
import uuid
from typing import Optional

import boto3
from auth.auth import auth_router
from auth.utils import verify_token
from botocore.exceptions import BotoCoreError, ClientError
from chat_message_history import ChatMessageHistory
from chathistory import chat_history_router, session_history, store_interaction
from config import config_router, get_config_value
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
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from langchain_aws import ChatBedrock
from langchain_core.runnables.history import RunnableWithMessageHistory
from utils import (
    business_unit_prompt,
    extract_chat_history,
    extract_file_locations,
    extract_keywords_from_query,
    extract_pdf_contents,
    extract_text_from_word,
    generate_prompt,
    generate_prompt_risk,
    generate_technical_error_message,
    get_file_type,
    get_knowledge_base_folder,
    get_knowledge_base_id,
    get_risk_matrix_details,
    llm_summarise,
    needs_summary,
    parse_risk_assessment_output,
    prompt_query_cat,
)

from app.qna_service import (
    follow_up_prompt,
    generate_answer_with_context,
    retrieve_and_generate,
    retrieve_and_generate_prioritized_doc,
    retrieve_documents,
)
from app.utils.prompts import BASE_PROMPT, RISK_MATRIX_PROMPT

file_handler = logging.FileHandler("report.log", mode="a")
stream_handler = logging.StreamHandler()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    handlers=[file_handler, stream_handler],
)

logger = logging.getLogger(__name__)
logger.info("Logging initialized")

qna_session_id_store = {}

s3 = boto3.client("s3")

BUCKET_CONTAINER = get_config_value("BUCKET_CONTAINER")
QNA_FLOW_NAME = get_config_value("QNA_FLOW_NAME")
MODEL_ID = get_config_value("MODEL_ID")
REGION_ID = get_config_value("REGION_ID")
SESSION_STATUS_ACTIVE = get_config_value("SESSION_STATUS_ACTIVE")
IRRELEVANT_KEYWORD = get_config_value("IRRELEVANT_KEYWORD")
GEN_ENQ_KB_ID = get_config_value("GEN_ENQ_KB_ID")
SUMMARY_FLOW_NAME = get_config_value("SUMMARY_FLOW_NAME")
PRIORITZE_DOCUMENT = "CAN HANDBOOK Third Edition.pdf"


app = FastAPI()
app.include_router(auth_router, prefix="/auth", tags=["Auth"])
app.include_router(config_router, prefix="/load", tags=["Config"])
app.include_router(
    chat_history_router,
    prefix="/chat",
    tags=["Chat history"],
    dependencies=[Depends(verify_token)],
)

# Configure CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_user_memory(session_id):
    """
    Fetches the chat memory object from S3.
    Returns a ChatMessageHistory object if not found or on error.
    """
    try:
        response = s3.get_object(
            Bucket=BUCKET_CONTAINER, Key=f"cache/{session_id}.pkl"
        )
        with response["Body"] as file:
            my_object = pickle.load(file)
        return my_object
    except ClientError as e:
        # Make sure e.response is defined before checking inside it
        if e.response and "Error" in e.response:
            # Check specific error code
            if e.response["Error"]["Code"] == "NoSuchKey":
                logger.info(
                    f"File not found in bucket {BUCKET_CONTAINER}. Returning an empty chat history."
                )
                return ChatMessageHistory(session_id)
            else:
                logger.info(f"ClientError: {str(e)}")
        else:
            # ClientError but unknown or missing response
            logger.info(f"Unhandled ClientError: {str(e)}")
        # Fallback: return empty chat history on error
        return ChatMessageHistory(session_id)
    except BotoCoreError as e:
        logger.info(f"BotoCoreError encountered: {str(e)}")
        return ChatMessageHistory(session_id)
    except Exception as e:
        logger.error(
            f"Unknown error retrieving user memory: {str(e)}", exc_info=True
        )
        return ChatMessageHistory(session_id)


@app.get("/")
async def read_root():
    return {"message": "Welcome to the Contracting Assistant API!"}


@app.post("/getqnaanswer/")
async def ask_question(
    request: RequestQuery, token: str = Depends(verify_token)
):
    logger.info("ask_question endpoint triggered")
    logger.debug(f"Request: {request}")

    msg_id = str(uuid.uuid4())
    files = request.query.files
    sessionId = request.user.sessionId
    user_txt = request.query.text.strip()

    # ──────────────────── 1. LLM guard-rail  ──────────────────────────────
    if needs_summary(user_txt):
        summary_obj = QnAAnswer(
            ans=llm_summarise(user_txt)
        )  # similarities/differences default to []
        result = Result(
            messageId=msg_id,
            answer=summary_obj,
            transactionCount=request.query.transactionCount,
            citations=[],
            feedback=Feedback(
                feedbackDisplayOptions=FeedbackDisplayOptions(
                    thumbsUp="Y", thumbsDown="Y", feedbackText="Y"
                )
            ),
        )
        return QueryResponse(
            status="success",
            sessionId=sessionId or str(uuid.uuid4()),
            userQuery=user_txt,
            result=result,
        )
    # ──────────────────── 2. normal QnA flow ────────────────────

    try:
        # -------------- build prompt from chat history  --------------
        prompt = ""
        if sessionId:
            history = session_history(sessionId)
            chat_history = extract_chat_history(history)
            for question, answer in chat_history:
                # FIXME this might consume all tokens just retrieving the chatHistory
                # TODO make a filter and a buffer so we avoid extra costs for recurrent DynamoDB call
                prompt += f"User: {question}\nAssistant: {answer}\n"
            formatted_prompt = follow_up_prompt.format(prompt, user_txt)
            follow_up = generate_answer_with_context(formatted_prompt)
            try:
                follow_up_text = follow_up["content"][0]["text"]
                if "follow-up" in follow_up_text.lower():
                    prompt += f"User:{user_txt}"
                else:
                    prompt = f"User:{user_txt}"
            except Exception as e:
                raise HTTPException(
                    status_code=500,
                    detail=f"Error in follow_up_text: {str(e)} the follow up text variable is: {follow_up_text}",
                )
        else:
            prompt = f"User:{user_txt}"

        # ---------------- business-unit classification  -------------
        kb_prompt = business_unit_prompt(user_txt)

        def get_business_unit(kb_prompt):
            llm = ChatBedrock(model_id=MODEL_ID)
            try:
                answer = llm.invoke(kb_prompt)
            except Exception as e:
                raise HTTPException(
                    status_code=500, detail=f"Error invoking the LLM: {str(e)}"
                )
            return answer

        raw_response = get_business_unit(kb_prompt)
        response = None
        answer = None
        citations = []
        categorized_knowledge_type = getattr(
            raw_response, "content", str(raw_response)
        ).strip()
        if (
            request.query.knowledgeType.lower()
            == categorized_knowledge_type.lower()
        ):
            text = ""
        else:
            text = """\n<b>Note</b>: The search results do not contain specific information regarding your query.
            Please consider switching tabs from the top right corner if the query pertains to a different Business Unit."""

        # ---------------- prioritized-doc retrieval  -----------------
        if files:
            try:
                response = retrieve_and_generate_prioritized_doc(
                    user_txt,
                    get_knowledge_base_id(request.query.knowledgeType),
                    get_knowledge_base_folder(request.query.knowledgeType),
                    MODEL_ID,
                    REGION_ID,
                    sessionId,
                    files,
                )
                answer = response["output"]["text"]
                citations = extract_file_locations(response)
            except Exception as e:
                logger.info(
                    f"Error in retrieve_and_generate_prioritized_doc: {str(e)}"
                )

        # ---------------- fallback retrieval paths  ------------------
        if response is None or not answer:
            doc = retrieve_documents(
                prompt,
                get_knowledge_base_id(request.query.knowledgeType),
                REGION_ID,
                filter_value=None,
            )
            for result in doc.get("retrievalResults", []):
                if (
                    "metadata" in result
                    and "x-amz-bedrock-kb-source-uri" in result["metadata"]
                    and PRIORITZE_DOCUMENT
                    in result["metadata"]["x-amz-bedrock-kb-source-uri"]
                ):
                    response = retrieve_and_generate_prioritized_doc(
                        user_txt,
                        get_knowledge_base_id(request.query.knowledgeType),
                        get_knowledge_base_folder(request.query.knowledgeType),
                        MODEL_ID,
                        REGION_ID,
                        sessionId,
                        [PRIORITZE_DOCUMENT],
                    )
                    break

            if response:
                citations = extract_file_locations(response)
                answer = response["output"]["text"]
                if not citations:
                    response = retrieve_and_generate(
                        user_txt,
                        get_knowledge_base_id(request.query.knowledgeType),
                        MODEL_ID,
                        REGION_ID,
                        sessionId,
                    )
                    citations = extract_file_locations(response)
                    answer = response["output"]["text"]
            else:
                response = retrieve_and_generate(
                    user_txt,
                    get_knowledge_base_id(request.query.knowledgeType),
                    MODEL_ID,
                    REGION_ID,
                    sessionId,
                )
                citations = extract_file_locations(response)
                answer = response["output"]["text"]

        sessionId = response["sessionId"]
        if re.search(r"Sorry, I am unable to assist", answer, re.IGNORECASE):
            answer += text

        answer_obj = QnAAnswer(ans=answer)

        # quickreply = QuickReply(
        #     text="Rate the overall risk to AZ this contract",
        #     payload="Rate the overall risk to AZ this contract",
        # )
        feedbackoptions = FeedbackDisplayOptions(
            thumbsUp="Y", thumbsDown="Y", feedbackText="Y"
        )
        feedback = Feedback(feedbackDisplayOptions=feedbackoptions)

        result = Result(
            messageId=msg_id,
            answer=answer_obj,  # ← validated schema
            transactionCount=request.query.transactionCount,
            citations=citations,
            feedback=feedback,
        )
        queryResponse = QueryResponse(
            status="success",
            sessionId=sessionId,
            userQuery=user_txt,
            result=result,
        )

        # ---------------- logging interaction  -----------------------
        if request.user.id:
            current_datetime = datetime.datetime.now().isoformat()
            user_message_search = (
                extract_keywords_from_query(user_txt.lower())
                if len(user_txt) > 2046
                else user_txt.lower()
            )
            chat_metadata = ChatMetadata(
                FileName="",
                FileLocation="",
                FlowName=QNA_FLOW_NAME,
                KbType=request.query.knowledgeType,
            )
            chat_interaction = ChatInteraction(
                UserId=request.user.id,
                SessionId=sessionId,
                UserMessage=user_txt,
                UserMessageSearch=user_message_search,
                BotResponse=answer,
                BotResponseSearch=answer,
                FeedbackComment="",
                Timestamp=current_datetime,
                SessionStatus=SESSION_STATUS_ACTIVE,
                MessageId=msg_id,
                ChatMetadata=chat_metadata,
            )
            store_interaction(chat_interaction)

        return queryResponse

    # ------------------------- error handling  -----------------------
    except (ClientError, BotoCoreError) as e:
        logger.error(f"AWS error occurred: {str(e)}", exc_info=True)
        return generate_technical_error_message(
            msg_id, request.query.transactionCount, user_txt, sessionId, exc=e
        )
    except HTTPException as e:
        logger.info(f"HTTP exception: {str(e)}")
        raise  # Let FastAPI handle it
    except Exception as e:
        logger.error(f"Unknown error in ask_question: {str(e)}", exc_info=True)
        return generate_technical_error_message(
            msg_id, request.query.transactionCount, user_txt, sessionId, exc=e
        )


def check_qna(
    queryText: str,
    answer: str,
    session_id: str,
    content: str,
    category,
    knowledge_base_folder,
    history,
):
    """
    Checks if the IRRELEVANT_KEYWORD is present in the 'answer'
    and, if so, attempts to retrieve a fallback answer from GEN_ENQ_KB_ID.
    """
    qna_answer = answer
    session_qna_id = qna_session_id_store.get(session_id, "")
    try:
        if IRRELEVANT_KEYWORD in answer:
            # prompt="Contract: "+content+"\n\n"+history+"User:"+queryText
            prompt = history + "User:" + queryText
            if category == "2":
                response = retrieve_and_generate_prioritized_doc(
                    prompt,
                    GEN_ENQ_KB_ID,
                    knowledge_base_folder,
                    MODEL_ID,
                    REGION_ID,
                    session_qna_id,
                    [PRIORITZE_DOCUMENT],
                )
            else:
                response = retrieve_and_generate(
                    prompt, GEN_ENQ_KB_ID, MODEL_ID, REGION_ID, session_qna_id
                )
            qna_session_id_store[session_id] = response["sessionId"]
            if (
                "citations" in response
                and response["citations"]
                and response["citations"][0].get("retrievedReferences") != []
            ):
                qna_answer = response["output"]["text"]
            else:
                # remove IRRELEVANT_KEYWORD if the fallback didn't help
                qna_answer = qna_answer.replace(IRRELEVANT_KEYWORD, "")
    except (ClientError, BotoCoreError) as e:
        logger.error(f"AWS error in check_qna: {str(e)}", exc_info=True)
        # Optionally raise or just return original
        return qna_answer
    except Exception as e:
        logger.error(f"Unknown error in check_qna: {str(e)}", exc_info=True)
    return qna_answer


@app.post("/getsummary/")
async def generate_summary(
    file: UploadFile = File(None),
    apiKey: Optional[str] = Form(None),
    userId: Optional[str] = Form(None),
    sessionId: Optional[str] = Form(None),
    language: Optional[str] = Form(None),
    platform: Optional[str] = Form(None),
    queryText: Optional[str] = Form(None),
    transactionCount: Optional[str] = Form(None),
    token: str = Depends(verify_token),
):
    """
    Summarizes the content of an uploaded file (PDF or Word) or performs
    a summary on given text (queryText).
    """
    msg_id = str(uuid.uuid4())
    try:
        content = ""
        session_id = sessionId or str(uuid.uuid4())
        file_type = ""
        answer = ""
        file_name = ""
        folder_path = ""

        if file:
            # Try reading file
            try:
                file_contents = await file.read()
                file_type = get_file_type(file.filename)
            except Exception as e:
                raise HTTPException(
                    status_code=400, detail=f"Error reading file: {str(e)}"
                )

            # Attempt to upload file to S3
            try:
                folder_path = f"contracts/{userId}/{session_id}"
                s3.put_object(
                    Bucket=BUCKET_CONTAINER, Key=f"{folder_path}/"
                )  # ensure folder
                file_name = file.filename
                s3.put_object(
                    Bucket=BUCKET_CONTAINER,
                    Key=f"{folder_path}/{file_name}",
                    Body=file_contents,
                    ContentType=file.content_type,
                )
            except (BotoCoreError, ClientError) as e:
                logger.info(f"Error uploading to S3: {str(e)}")
                raise HTTPException(
                    status_code=500, detail="S3 upload failed."
                )

            # Extract PDF/Word contents
            if file_contents:
                try:
                    if file_type == ".pdf":
                        content = extract_pdf_contents(file_contents)
                    elif file_type in [".doc", ".docx"]:
                        content = extract_text_from_word(file_contents)
                except ValueError as e:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Failed to extract content: {str(e)}",
                    )

        # Default query if none is provided
        if not queryText or queryText.strip() == "":
            queryText = "Summarize the document content"
            logger.info(
                "QueryText was blank. Initializing with default summary query."
            )

        # If no content is available at all, raise error
        if not content and not queryText:
            raise HTTPException(
                status_code=400,
                detail="No content found. Provide a file or queryText to summarize.",
            )

        # Generate the prompt
        prompt_category = prompt_query_cat(queryText.lower())

        def query_category(prompt_category):
            llm = ChatBedrock(model_id=MODEL_ID)
            try:
                category = llm.invoke(prompt_category)
            except Exception as e:
                raise HTTPException(
                    status_code=500, detail=f"Error invoking the LLM: {str(e)}"
                )
            return category.content

        category = query_category(prompt_category)

        # if "risk" in queryText.lower() or "clause" in queryText.lower() or "risks" in queryText.lower() or "clauses" in queryText.lower():
        if category == "1":
            risk_rules = get_risk_matrix_details()
            prompt = generate_prompt_risk(
                content, risk_rules, queryText, RISK_MATRIX_PROMPT
            )
        else:
            prompt = generate_prompt(content, queryText, BASE_PROMPT)
        llm = ChatBedrock(model_id=MODEL_ID)
        chain = RunnableWithMessageHistory(llm, get_user_memory)

        user_history = ""
        if sessionId:
            history = session_history(sessionId)
            chat_history = extract_chat_history(history)
            for question, answer in chat_history:
                user_history += f"User: {question}\nAssistant: {answer}\n"

        # Invoke model
        try:
            summary = chain.invoke(
                prompt,
                config={"configurable": {"session_id": session_id}},
            )
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Error invoking the LLM: {str(e)}"
            )

        # Possibly refine answer if IRRELEVANT_KEYWORD is present

        answer = check_qna(
            queryText,
            summary.content,
            session_id,
            content,
            category,
            "general",
            user_history,
        )

        # Build final result
        feedbackoptions = FeedbackDisplayOptions(
            thumbsUp="Y", thumbsDown="Y", feedbackText="Y"
        )
        feedback = Feedback(feedbackDisplayOptions=feedbackoptions)
        try:
            structured_answer = parse_risk_assessment_output(answer)
            final_answer = structured_answer.dict()["answer"]
        except ValueError as e:
            logger.warning(f"Risk parser failed: {e}")
            final_answer = {"ans": answer}  # fallback

        result = Result(
            messageId=str(msg_id),
            answer=final_answer,
            transactionCount=transactionCount,
            feedback=feedback,
        )

        queryResponse = QueryResponse(
            status="success",
            sessionId=session_id,
            userQuery=queryText,
            result=result,
        )

        # Store interaction if userId is known
        if userId:
            current_datetime = datetime.datetime.now().isoformat()
            file_location = f"{BUCKET_CONTAINER}{folder_path}{file_name}"
            chat_metadata = ChatMetadata(
                FileName=file_name,
                FileLocation=file_location,
                FlowName=SUMMARY_FLOW_NAME,
                Department="",  # fill if needed
            )
            user_message = queryText if queryText else chat_metadata.FileName
            if len(user_message) > 2046:
                user_message_search = extract_keywords_from_query(
                    user_message.lower()
                )
            else:
                user_message_search = user_message

            chat_interaction = ChatInteraction(
                UserId=userId,
                SessionId=session_id,
                UserMessage=user_message,
                UserMessageSearch=user_message_search,
                BotResponse=answer,
                BotResponseSearch=answer,
                FeedbackComment="",
                Timestamp=current_datetime,
                SessionStatus=SESSION_STATUS_ACTIVE,
                MessageId=str(msg_id),
                ChatMetadata=chat_metadata,
            )
            store_interaction(chat_interaction)

        return queryResponse

    except HTTPException as http_exc:
        logger.info(f"HTTPException: {str(http_exc)}")
        return generate_technical_error_message(
            msg_id, transactionCount, queryText, sessionId, exc=http_exc
        )
    except (ClientError, BotoCoreError) as e:
        logger.error(f"AWS error in generate_summary: {str(e)}", exc_info=True)
        return generate_technical_error_message(
            msg_id, transactionCount, queryText, sessionId, exc=e
        )
    except Exception as e:
        logger.error(
            f"Unknown error in generate_summary: {str(e)}", exc_info=True
        )
        return generate_technical_error_message(
            msg_id, transactionCount, queryText, sessionId, exc=e
        )
