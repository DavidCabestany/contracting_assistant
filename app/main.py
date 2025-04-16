import datetime
import pickle
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
    QueryResponse,
    QuickReply,
    RequestQuery,
    Result,
)
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from langchain_aws import ChatBedrock
from langchain_core.runnables.history import RunnableWithMessageHistory
from prompt import (
    follow_up_prompt,
    generate_answer_with_context,
    retrieve_and_generate,
    retrieve_and_generate_prioritized_doc,
    retrieve_documents,
)
from utils import (
    extract_chat_history,
    extract_file_locations,
    extract_pdf_contents,
    extract_text_from_word,
    generate_prompt,
    generate_technical_error_message,
    get_file_type,
    get_knowledge_base_folder,
    get_knowledge_base_id,
)

qna_session_id_store = {}

s3 = boto3.client("s3")

BUCKET_NAME = get_config_value("BUCKET_NAME")
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
    try:
        response = s3.get_object(Bucket=BUCKET_NAME, Key=f"cache/{session_id}.pkl")
        # Load the content of the pickle file
        with response["Body"] as file:
            my_object = pickle.load(file)
        return my_object
    except Exception as e:
        # Handle the case where the file doesn't exist
        if e.response["Error"]["Code"] == "NoSuchKey":
            print(f"File not found in bucket {BUCKET_NAME}. Returning an empty list.")
            return ChatMessageHistory(session_id)


# Root endpoint
@app.get("/")
async def read_root():
    return {"message": "Welcome to the Contracting Assistant API!"}


# POST endpoint for retrieving and generating Q&A answers
# @app.post("/qna/answer/")
@app.post("/getqnaanswer/")
async def ask_question(request: RequestQuery, token: str = Depends(verify_token)):
    # if not validate_api_key(request.apiKey):
    #     raise HTTPException(status_code=401, detail=f"Authetication failed")
    knowledge_base_id = get_knowledge_base_id(request.query.knowledgeType)
    knowledge_base_folder = get_knowledge_base_folder(request.query.knowledgeType)
    sessionId = request.user.sessionId
    filepath = ""
    filename = ""
    citations = []
    msg_id = str(uuid.uuid4())
    files = request.query.files
    try:
        current_datetime = datetime.now()
        if sessionId:
            history = session_history(sessionId)
            chat_history = extract_chat_history(history)
            prompt = ""
            for question, answer in chat_history:
                prompt += f"User: {question}\nAssistant: {answer}\n"
            formatted_prompt = follow_up_prompt.format(prompt, request.query.text)
            follow_up = generate_answer_with_context(formatted_prompt)
            if "follow-up" in follow_up["content"][0]["text"].lower():
                prompt += f"User:{request.query.text}"
            else:
                prompt = f"User:{request.query.text}"
        else:
            prompt = f"User:{request.query.text}"

        response = None
        if files:
            response = retrieve_and_generate_prioritized_doc(
                request.query.text,
                knowledge_base_id,
                knowledge_base_folder,
                MODEL_ID,
                REGION_ID,
                sessionId,
                files,
            )
            answer = response["output"]["text"]
            print(answer)
            citations = extract_file_locations(response)
            if citations != []:
                print(citations[0]["fileName"])

        if response is None:
            doc = retrieve_documents(
                prompt, knowledge_base_id, REGION_ID, filter_value=None
            )
            for result in doc["retrievalResults"]:
                if (
                    "metadata" in result
                    and "x-amz-bedrock-kb-source-uri" in result["metadata"]
                ):
                    source_uri = result["metadata"]["x-amz-bedrock-kb-source-uri"]
                    if PRIORITZE_DOCUMENT in source_uri:
                        response = retrieve_and_generate_prioritized_doc(
                            request.query.text,
                            knowledge_base_id,
                            knowledge_base_folder,
                            MODEL_ID,
                            REGION_ID,
                            sessionId,
                            [PRIORITZE_DOCUMENT],
                        )
                        break
            if response:
                citations = extract_file_locations(response)
                answer = response["output"]["text"]
                if citations != []:
                    print("found citations")
                else:
                    response = retrieve_and_generate(
                        request.query.text,
                        knowledge_base_id,
                        MODEL_ID,
                        REGION_ID,
                        sessionId,
                    )
                    citations = extract_file_locations(response)
                    answer = response["output"]["text"]
            else:
                response = retrieve_and_generate(
                    request.query.text,
                    knowledge_base_id,
                    MODEL_ID,
                    REGION_ID,
                    sessionId,
                )
                citations = extract_file_locations(response)
                answer = response["output"]["text"]

        sessionId = response["sessionId"]

        # Hardcoded values, should be modified as needed
        quickreply = QuickReply(
            text="Rate the overall risk to AZ this contract",
            payload="Rate the overall risk to AZ this contract",
        )
        quickreplies = [quickreply]
        # citation = Citation(fileName=filename, filePath=filepath)
        citations = extract_file_locations(response)
        feedbackoptions = FeedbackDisplayOptions(
            thumbsUp="Y", thumbsDown="Y", feedbackText="Y"
        )
        feedback = Feedback(feedbackDisplayOptions=feedbackoptions)
        result = Result(
            messageId=str(msg_id),
            answer=answer,
            transactionCount=request.query.transactionCount,
            citations=citations,
            feedback=feedback,
        )
        queryResponse = QueryResponse(
            status="success",
            sessionId=sessionId,
            userQuery=request.query.text,
            result=result,
        )
        current_datetime = datetime.now()
        formatted_timestamp = current_datetime.isoformat()
        if request.user.id:
            chat_metadata = ChatMetadata(
                FileName=filename,
                FileLocation=filepath,
                FlowName=QNA_FLOW_NAME,
                KbType=request.query.knowledgeType,
            )
            chat_interaction = ChatInteraction(
                UserId=request.user.id,
                SessionId=sessionId,
                UserMessage=request.query.text,
                UserMessageSearch=request.query.text.lower(),
                BotResponse=answer,
                BotResponseSearch=answer.lower(),
                # IsFeedbackPositive=True,
                FeedbackComment="",
                Timestamp=formatted_timestamp,
                SessionStatus=SESSION_STATUS_ACTIVE,
                MessageId=str(msg_id),
                ChatMetadata=chat_metadata,
            )
            store_interaction(chat_interaction)
        return queryResponse
    except Exception as e:
        print(str(e))
        return generate_technical_error_message(
            str(msg_id), request.query.transactionCount, request.query.text, sessionId
        )


def check_qna(queryText: str, answer: str, session_id: str):
    qna_answer = answer
    if session_id in qna_session_id_store:
        session_qna_id = qna_session_id_store[session_id]
    else:
        session_qna_id = ""
    try:
        # Check if the irrelevant keyword is in the answer
        if IRRELEVANT_KEYWORD in answer:
            # Call the retrieve_and_generate method
            response = retrieve_and_generate(
                queryText, GEN_ENQ_KB_ID, MODEL_ID, REGION_ID, session_qna_id
            )
            qna_session_id_store[session_id] = response["sessionId"]
            if (
                "citations" in response
                and response["citations"]
                and response["citations"][0].get("retrievedReferences") != []
            ):
                qna_answer = response["output"]["text"]
            else:
                qna_answer = qna_answer.replace(IRRELEVANT_KEYWORD, "")
    except Exception as e:
        print(str(e))
        raise HTTPException(
            status_code=500, detail=f"Error fetching qna answer: {str(e)}"
        )
    return qna_answer


# POST endpoint for summarization
# @app.post("/summary/answer")
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
    # if not validate_api_key(apiKey):
    #     raise HTTPException(status_code=401, detail=f"Authetication failed")
    try:
        content = ""
        session_id = sessionId or str(uuid.uuid4())
        file_type = ""
        msg_id = uuid.uuid4()
        answer = ""
        file_name = ""
        folder_path = ""
        # Check if a file is provided
        if file:
            # Read the uploaded file as bytes (async)
            try:
                file_contents = await file.read()  # Corrected to async
                file_type = get_file_type(file.filename)
            except Exception as e:
                raise HTTPException(
                    status_code=400, detail=f"Error reading file: {str(e)}"
                )
            # Upload file to S3
            try:
                folder_path = "contracts/" + f"{userId}/{session_id}"
                s3.put_object(Bucket=BUCKET_NAME, Key=f"{folder_path}/")
                file_name = file.filename
                s3.put_object(
                    Bucket=BUCKET_NAME,
                    Key=f"{folder_path}/{file_name}",
                    Body=file_contents,
                    ContentType=file.content_type,
                )
            except (BotoCoreError, ClientError) as e:
                raise HTTPException(
                    status_code=500, detail=f"S3 upload failed: {str(e)}"
                )
            # Extract content from the PDF or Word file if applicable
            if file_contents:
                try:
                    if file_type == ".pdf":
                        content = extract_pdf_contents(file_contents)
                    elif file_type in [".doc", ".docx"]:
                        content = extract_text_from_word(file_contents)
                except ValueError as e:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Failed to extract content from the file: {str(e)}",
                    )

        if (
            not queryText or queryText.strip() == ""
        ):  # checking if the value exists, or if the value is just white spaces.
            queryText = "Summarize the document content"
            print("QueryText was blank.  Initializing with default query.")

        # Check if queryText or content is provided
        if not queryText and not content:
            raise HTTPException(
                status_code=400, detail="QueryText or content from the file is required"
            )
        prompt = generate_prompt(
            content, queryText
        )  # Generate the prompt based on queryText and content
        llm = ChatBedrock(model_id=MODEL_ID)
        chain = RunnableWithMessageHistory(llm, get_user_memory)
        # Run the model with the prompt
        try:
            summary = chain.invoke(
                prompt,
                config={"configurable": {"session_id": session_id}},
            )
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Error invoking model: {str(e)}"
            )
        answer = check_qna(queryText, summary.content, session_id)
        # Construct the feedback and result objects
        feedbackoptions = FeedbackDisplayOptions(
            thumbsUp="Y", thumbsDown="Y", feedbackText="Y"
        )
        feedback = Feedback(feedbackDisplayOptions=feedbackoptions)
        result = Result(
            messageId=str(msg_id),
            answer=answer,
            transactionCount=transactionCount,
            feedback=feedback,
        )
        queryResponse = QueryResponse(
            status="success", sessionId=session_id, userQuery=queryText, result=result
        )
        current_datetime = datetime.now()
        formatted_timestamp = current_datetime.isoformat()
        file_location = BUCKET_NAME + folder_path + file_name
        if userId:
            chat_metadata = ChatMetadata(
                FileName=file_name,
                FileLocation=file_location,
                FlowName=SUMMARY_FLOW_NAME,
                Department="",
            )
            user_message = queryText if queryText else chat_metadata.FileName
            user_message_search = (
                queryText.lower() if queryText else chat_metadata.FileName.lower()
            )
            chat_interaction = ChatInteraction(
                UserId=userId,
                SessionId=session_id,
                UserMessage=user_message,
                UserMessageSearch=user_message_search,
                BotResponse=answer,
                BotResponseSearch=answer.lower(),
                # IsFeedbackPositive=True,
                FeedbackComment="",
                Timestamp=formatted_timestamp,
                SessionStatus=SESSION_STATUS_ACTIVE,
                MessageId=str(msg_id),
                ChatMetadata=chat_metadata,
            )
            store_interaction(chat_interaction)
        return queryResponse
    except HTTPException as http_exc:
        print(str(http_exc))
        return generate_technical_error_message(
            str(msg_id), transactionCount, queryText, sessionId
        )
    except Exception as e:
        print(str(e))
        return generate_technical_error_message(
            str(msg_id), transactionCount, queryText, sessionId
        )


"""
@app.middleware("http")
async def enforce_apikey_validation(request: Request, call_next):
    if request.method == "POST":  # Exclude specific endpoints if needed
        validate_api_key(request)
    response = await call_next(request)
    return response
"""
