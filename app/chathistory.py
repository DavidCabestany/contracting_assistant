"""Chat history FastAPI routes for storing, querying, downloading, and managing user-bot interactions.

This module connects to DynamoDB and S3 to provide chat storage, retrieval, and feedback features.
"""

import logging
from collections import defaultdict
from datetime import datetime

import boto3
import pandas as pd
from boto3.dynamodb.conditions import Attr, Key
from botocore.config import Config
from config import get_config_value
from fastapi import APIRouter, HTTPException
from models import ChatHistorySearchRequest, ChatInteraction, FeedbackRequest
from utils import generate_presigned_url, generate_technical_error_message

logger = logging.getLogger(__name__)

REGION_ID = get_config_value("REGION_ID")
CHAT_TABLE = get_config_value("CHAT_TABLE")
BUCKET_CONTAINER = get_config_value("BUCKET_CONTAINER")

chat_history_router = APIRouter()
boto_config = Config(retries={"max_attempts": 3}, max_pool_connections=50)
s3_client = boto3.client("s3", config=boto_config)
dynamodb = boto3.resource("dynamodb", region_name=REGION_ID)
table = dynamodb.Table(CHAT_TABLE)


def store_interaction(interaction: ChatInteraction):
    """Store a user-bot interaction in DynamoDB.

    Args:
        interaction (ChatInteraction): Interaction to persist.

    Returns:
        dict: Success message if stored properly.

    Raises:
        HTTPException: If the write operation fails.
    """
    try:
        item = interaction.dict()
        table.put_item(Item=item)
        return {"message": "User-bot interaction stored successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def session_history(session_id):
    """Retrieve a full conversation history by session ID.

    Args:
        session_id (str): The session to search for.

    Returns:
        dict: Messages grouped by session ID.

    TODO(@toloko): Add pagination for long sessions.
    """
    try:
        response = table.query(
            IndexName="SessionId-index",
            KeyConditionExpression=Key("SessionId").eq(session_id),
        )
        sorted_items = sorted(response["Items"], key=lambda x: x["Timestamp"])
        return {session_id: sorted_items}
    except Exception as e:
        logger.info(f"Error in chat search: {e}")
        return generate_technical_error_message("", 0, "", session_id, e)


@chat_history_router.post("/search/")
def search_chat(request: ChatHistorySearchRequest):
    """Search chats by UserId, keyword, date range, and sort order.

    Args:
        request (ChatHistorySearchRequest): Search filters.

    Returns:
        dict: Grouped chat summaries by date and session ID.
    """
    try:
        apiKey = request.apiKey  # noqa: F841
        userId = request.userId
        keyword = request.keyword
        start_date = request.start_date
        end_date = request.end_date
        sort_order = request.sort_order

        start_timestamp = (
            datetime.fromisoformat(start_date).isoformat()
            if start_date
            else None
        )
        end_timestamp = (
            datetime.fromisoformat(end_date).isoformat() if end_date else None
        )

        query_params = {}
        if userId:
            key_condition = Key("UserId").eq(userId)
            if start_timestamp and end_timestamp:
                key_condition &= Key("Timestamp").between(
                    start_timestamp, end_timestamp
                )
            elif start_timestamp:
                key_condition &= Key("Timestamp").gte(start_timestamp)
            elif end_timestamp:
                key_condition &= Key("Timestamp").lte(end_timestamp)
            query_params["KeyConditionExpression"] = key_condition
        else:
            query_params["FilterExpression"] = (
                Attr("Timestamp").between(start_timestamp, end_timestamp)
                if start_timestamp and end_timestamp
                else None
            )

        if keyword:
            words = keyword.lower().split()
            keyword_filters = [
                Attr("UserMessageSearch").contains(word)
                | Attr("BotResponseSearch").contains(word)
                for word in words
            ]
            combined_filter = keyword_filters[0]
            for kf in keyword_filters[1:]:
                combined_filter &= kf

            if query_params.get("FilterExpression"):
                query_params["FilterExpression"] &= combined_filter
            else:
                query_params["FilterExpression"] = combined_filter

        query_params["ScanIndexForward"] = sort_order.lower() != "desc"

        response = (
            table.query(**query_params, Limit=100)
            if userId
            else table.scan(**query_params, Limit=100)
        )

        response["Items"].sort(
            key=lambda x: datetime.fromisoformat(x["Timestamp"]),
            reverse=(sort_order.lower() == "desc"),
        )

        grouped_conversations = defaultdict(lambda: defaultdict(list))
        seen_sessions = set()

        for item in response["Items"]:
            date_str = (
                datetime.fromisoformat(item["Timestamp"]).date().isoformat()
            )
            session_id = item["SessionId"]
            if session_id in seen_sessions:
                continue
            grouped_conversations[date_str][session_id] = {
                "UserMessage": item["UserMessage"],
                "Timestamp": item["Timestamp"],
                "SessionId": session_id,
                "UserId": item["UserId"],
            }
            seen_sessions.add(session_id)

        return {
            date: dict(sessions)
            for date, sessions in grouped_conversations.items()
        }
    except Exception as e:
        logger.info(f"Error in chat search: {e}")
        return generate_technical_error_message("", 0, "", "", e)


@chat_history_router.post("/session/")
def view_chat_by_session(
    request: ChatHistorySearchRequest,
) -> dict[str, list[dict]]:
    """Get full session history for a given session ID.

    Args:
        request (ChatHistorySearchRequest): Request containing session ID.

    Returns:
        dict: Sorted message list for that session.
    """
    try:
        response = table.query(
            IndexName="SessionId-index",
            KeyConditionExpression=Key("SessionId").eq(request.session_id),
        )
        sorted_items = sorted(response["Items"], key=lambda x: x["Timestamp"])
        return {request.session_id: sorted_items}
    except Exception as e:
        logger.info(f"Error in chat search: {e}")
        return generate_technical_error_message(
            "", 0, "", request.session_id, e
        )


@chat_history_router.post("/download/")
async def download_chat(request: ChatHistorySearchRequest):
    """Generate and upload Excel file for a user's chat history and return presigned S3 URL.

    Args:
        request (ChatHistorySearchRequest): Filters to apply.

    Returns:
        dict: Download status and presigned URL.

    TODO(@toloko): Clean up temp files after upload.
    """
    try:
        chat_history = search_chat(request)
        df = pd.DataFrame(chat_history)
        file_path = f"/tmp/{request.userId}_chat_history.xlsx"
        df.to_excel(file_path, index=False)

        s3_key = f"{request.userId}_chat_history.xlsx"
        s3_client.upload_file(file_path, BUCKET_CONTAINER, s3_key)
        s3_url = f"s3://{BUCKET_CONTAINER}/{s3_key}"
        presigned_url = generate_presigned_url(s3_url, page_number=1)
        return {"status": "success", "downloadUrl": presigned_url}
    except Exception as e:
        logger.info(f"Error in downloading chat: {e}")
        return generate_technical_error_message("", 0, "", "", e)


@chat_history_router.post("/feedback/")
def update_feedback(feedback: FeedbackRequest):
    """Update feedback for a specific chat message.

    Args:
        feedback (FeedbackRequest): Feedback fields and message ID.

    Returns:
        dict: Update status.
    """
    try:
        if feedback.isFeedbackPositive is None:
            raise HTTPException(
                status_code=400,
                detail="IsFeedbackPositive must be provided.",
            )

        response = table.query(
            IndexName="MessageId-index",
            KeyConditionExpression=Key("MessageId").eq(feedback.messageId),
        )

        if response["Items"]:
            item = response["Items"][0]
            user_id = item["UserId"]
            timestamp = item["Timestamp"]
            update_expression = "SET IsFeedbackPositive = :IsFeedbackPositive"
            expression_attribute_values = {
                ":IsFeedbackPositive": feedback.isFeedbackPositive,
            }

            if feedback.feedbackComment is not None:
                update_expression += ", FeedbackComment = :FeedbackComment"
                expression_attribute_values[":FeedbackComment"] = (
                    feedback.feedbackComment
                )

            key = {"UserId": user_id, "Timestamp": timestamp}
            update_response = table.update_item(
                Key=key,
                UpdateExpression=update_expression,
                ExpressionAttributeValues=expression_attribute_values,
                ReturnValues="UPDATED_NEW",
            )
            logger.info(f"{update_response}")
            return {"status": "success"}

        return {"status": "error"}
    except Exception as e:
        logger.info(f"Error updating feedback: {e!s}")
        return generate_technical_error_message(
            feedback.messageId, 0, "", feedback.sessionId
        )


@chat_history_router.post("/recents/")
def get_latest_active_sessions(request: ChatHistorySearchRequest):
    """Get up to 3 recent active QnA sessions with first messages.

    Args:
        request (ChatHistorySearchRequest): User ID to filter.

    Returns:
        list: Recent sessions with SessionId, message, and KbType.
    """
    try:
        response = []
        last_evaluated_key = None

        while len(response) < 3:
            query_params = {
                "KeyConditionExpression": Key("UserId").eq(request.userId),
                "FilterExpression": Attr("SessionStatus").eq("Active")
                & Attr("ChatMetadata.FlowName").eq("QnA"),
                "ScanIndexForward": False,
                "Limit": 10,
            }
            if last_evaluated_key:
                query_params["ExclusiveStartKey"] = last_evaluated_key

            output = table.query(**query_params)
            response.extend(output["Items"])
            last_evaluated_key = output.get("LastEvaluatedKey")
            if not last_evaluated_key:
                break

        active_sessions = []
        seen_session_ids = set()

        for item in response:
            session_id = item["SessionId"]
            if session_id in seen_session_ids:
                continue

            session_message_response = table.query(
                IndexName="SessionId-Timestamp-index",
                KeyConditionExpression=Key("SessionId").eq(session_id),
                ScanIndexForward=True,
                Limit=1,
            )

            if session_message_response["Items"]:
                first_item = session_message_response["Items"][0]
                first_message = first_item.get("UserMessage")
                kb_type = first_item.get("ChatMetadata", {}).get(
                    "KbType", None
                )

                active_sessions.append(
                    {
                        "SessionId": session_id,
                        "Message": first_message,
                        "KbType": kb_type,
                    }
                )
                seen_session_ids.add(session_id)
                if len(seen_session_ids) >= 3:
                    break

        return active_sessions
    except Exception as e:
        logger.info(f"Error retrieving latest active sessions: {e}")
        raise HTTPException(
            status_code=500,
            detail="Error retrieving latest active sessions",
        )
