"""Service layer for managing user-bot chat history using DynamoDB and S3."""

import logging
from collections import defaultdict
from datetime import datetime

import boto3
import pandas as pd
from boto3.dynamodb.conditions import Attr, Key
from botocore.config import Config
from config import get_secret
from fastapi import HTTPException
from models import ChatHistorySearchRequest, ChatInteraction, FeedbackRequest
from utils import generate_presigned_url, generate_technical_error_message

from .clients import s3_client

logger = logging.getLogger(__name__)

REGION_ID = get_secret("REGION_ID")
CHAT_TABLE = get_secret("CHAT_TABLE")
BUCKET_CONTAINER = get_secret("BUCKET_CONTAINER")

boto_config = Config(retries={"max_attempts": 3}, max_pool_connections=50)

dynamodb = boto3.resource("dynamodb", region_name=REGION_ID)
table = dynamodb.Table(CHAT_TABLE)


def store_interaction(interaction: ChatInteraction):
    """Store a user-bot chat interaction in DynamoDB."""
    try:
        interaction_instance = interaction.dict()
        # This covers both None and missing key
        if interaction_instance.get("IsFeedbackPositive") not in {
            True,
            False,
            "no_feedback",
        }:
            logging.info(
                f"Corrected IsFeedbackPositive to 'no_feedback' for item: {interaction_instance}"
            )
            interaction_instance["IsFeedbackPositive"] = "no_feedback"

        table.put_item(Item=interaction_instance)
        return {"message": "User-bot interaction stored successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def session_history(session_id):
    """Retrieve full chat history for a given session ID."""
    try:
        response = table.query(
            IndexName="SessionId-index",
            KeyConditionExpression=Key("SessionId").eq(session_id),
        )
        return {
            session_id: sorted(response["Items"], key=lambda x: x["Timestamp"])
        }
    except Exception as e:
        logger.info(f"Error in chat search: {e}")
        return generate_technical_error_message(
            msg_id="",
            transaction_count=0,
            user_query="",
            session_id=session_id,
            exc=e,
        )


def search_chat(request: ChatHistorySearchRequest):
    """Search chat history with support for date ranges, keywords, and sort order."""
    try:
        userId, keyword, start_date, end_date, sort_order = (
            request.userId,
            request.keyword,
            request.start_date,
            request.end_date,
            request.sort_order,
        )
        start_ts = (
            datetime.fromisoformat(start_date).isoformat()
            if start_date
            else None
        )
        end_ts = (
            datetime.fromisoformat(end_date).isoformat() if end_date else None
        )

        query_params = {}
        if userId:
            key_expr = Key("UserId").eq(userId)
            if start_ts and end_ts:
                key_expr &= Key("Timestamp").between(start_ts, end_ts)
            elif start_ts:
                key_expr &= Key("Timestamp").gte(start_ts)
            elif end_ts:
                key_expr &= Key("Timestamp").lte(end_ts)
            query_params["KeyConditionExpression"] = key_expr
        else:
            query_params["FilterExpression"] = (
                Attr("Timestamp").between(start_ts, end_ts)
                if start_ts and end_ts
                else None
            )

        if keyword:
            words = keyword.lower().split()
            filters = [
                Attr("UserMessageSearch").contains(w)
                | Attr("BotResponseSearch").contains(w)
                for w in words
            ]
            combined = filters[0]
            for f in filters[1:]:
                combined &= f
            query_params["FilterExpression"] = (
                query_params.get("FilterExpression", combined) & combined
            )

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

        grouped = defaultdict(dict)
        seen = set()
        for item in response["Items"]:
            date_str = (
                datetime.fromisoformat(item["Timestamp"]).date().isoformat()
            )
            sid = item["SessionId"]
            if sid in seen:
                continue
            grouped[date_str][sid] = {
                "UserMessage": item["UserMessage"],
                "Timestamp": item["Timestamp"],
                "SessionId": sid,
                "UserId": item["UserId"],
            }
            seen.add(sid)
        return {date: dict(sess) for date, sess in grouped.items()}
    except Exception as e:
        logger.info(f"Error in chat search: {e}")
        return generate_technical_error_message(
            msg_id="",
            transaction_count=0,
            user_query="",
            session_id="",
            exc=e,
        )


def view_chat_by_session(session_id: str):
    """Return all messages for a given session ID, sorted by timestamp."""
    try:
        response = table.query(
            IndexName="SessionId-index",
            KeyConditionExpression=Key("SessionId").eq(session_id),
        )
        return {
            session_id: sorted(response["Items"], key=lambda x: x["Timestamp"])
        }
    except Exception as e:
        logger.info(f"Error in chat search: {e}")
        return generate_technical_error_message(
            msg_id="",
            transaction_count=0,
            user_query="",
            session_id=session_id,
            exc=e,
        )


def download_chat(request: ChatHistorySearchRequest):
    """Generate and upload an Excel file of chat history, return a presigned download URL."""
    try:
        data = search_chat(request)
        file_path = f"/tmp/{request.userId}_chat_history.xlsx"
        pd.DataFrame(data).to_excel(file_path, index=False)
        s3_key = f"{request.userId}_chat_history.xlsx"
        s3_client.upload_file(file_path, BUCKET_CONTAINER, s3_key)
        return {
            "status": "success",
            "downloadUrl": generate_presigned_url(
                f"s3://{BUCKET_CONTAINER}/{s3_key}", page_number=1
            ),
        }
    except Exception as e:
        logger.info(f"Error in downloading chat: {e}")
        return generate_technical_error_message(
            msg_id="",
            transaction_count=0,
            user_query="",
            session_id="",
            exc=e,
        )


def update_feedback(feedback: FeedbackRequest):
    """Update user feedback for a specific chat message, using MessageId to locate it."""
    try:
        response = table.query(
            IndexName="MessageId-index",
            KeyConditionExpression=Key("MessageId").eq(feedback.messageId),
        )
        if not response["Items"]:
            return {"status": "error"}

        item = response["Items"][0]
        key = {"UserId": item["UserId"], "Timestamp": item["Timestamp"]}
        update_expr = "SET IsFeedbackPositive = :fb"
        # The line below always ensures a valid value is written
        expr_vals = {
            ":fb": (
                feedback.IsFeedbackPositive
                if feedback.IsFeedbackPositive is not None
                else "no_feedback"
            )
        }

        if feedback.feedbackComment is not None:
            update_expr += ", FeedbackComment = :fc"
            expr_vals[":fc"] = feedback.feedbackComment

        table.update_item(
            Key=key,
            UpdateExpression=update_expr,
            ExpressionAttributeValues=expr_vals,
            ReturnValues="UPDATED_NEW",
        )
        return {"status": "success"}
    except Exception as e:
        logger.info(f"Error updating feedback: {e}")
        return generate_technical_error_message(
            feedback.messageId, 0, "", feedback.sessionId, exc=e
        )


def get_latest_active_sessions(user_id: str):
    """Return up to 3 active sessions (QnA flow) with their first message and KbType."""
    try:
        response = []
        seen_session_ids = set()
        last_key = None
        while len(response) < 3:
            query_params = {
                "KeyConditionExpression": Key("UserId").eq(user_id),
                "FilterExpression": Attr("SessionStatus").eq("Active")
                & Attr("ChatMetadata.FlowName").eq("QnA"),
                "ScanIndexForward": False,
                "Limit": 10,
            }
            if last_key:
                query_params["ExclusiveStartKey"] = last_key

            output = table.query(**query_params)
            items_in_batch = output.get("Items", [])

            if not items_in_batch and not output.get("LastEvaluatedKey"):
                break

            for item in items_in_batch:
                sid = item["SessionId"]

                if sid in seen_session_ids:
                    continue

                msg_resp = table.query(
                    IndexName="SessionId-Timestamp-index",
                    KeyConditionExpression=Key("SessionId").eq(sid),
                    ScanIndexForward=True,
                    Limit=1,
                )
                if msg_resp.get("Items"):
                    first_message_item = msg_resp["Items"][0]
                    response.append(
                        {
                            "SessionId": sid,
                            "Message": first_message_item.get("UserMessage"),
                            "KbType": first_message_item.get(
                                "ChatMetadata", {}
                            ).get("KbType"),
                        }
                    )
                    seen_session_ids.add(sid)
                    if len(response) >= 3:
                        break
            if len(response) >= 3:
                break

            last_key = output.get("LastEvaluatedKey")
            if not last_key:
                break
        return response
    except Exception as e:
        logger.info(f"Error retrieving latest active sessions: {e}")
        raise HTTPException(
            status_code=500, detail="Error retrieving latest active sessions"
        )
