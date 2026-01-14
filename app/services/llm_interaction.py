import boto3
from decimal import Decimal
from datetime import datetime

from services.constants import MODEL_ID

TABLE_NAME = "azcdi-us-ops-procure-llm-interaction-dev"
dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)


def log_llm_interaction(
    message_id: str,
    user_id: str,
    session_id: str,
    model_name: str,
    input_token_count: int,
    output_token_count: int,
    price_per_token: float,
    user_message: str,
    bot_response: str,
    start_time: str,
    end_time: str,
):
    latency_ms = int((datetime.fromisoformat(end_time) - datetime.fromisoformat(start_time)).total_seconds() * 1000)
    total_cost = float(input_token_count + output_token_count) * price_per_token
    timestamp = end_time  # Use end_time as the sort key

    item = {
        "MessageId": message_id,
        "Timestamp": timestamp,
        "UserId": user_id,
        "SessionId": session_id,
        "ModelName": MODEL_ID,
        "InputTokenCount": input_token_count,
        "OutputTokenCount": output_token_count,
        "PricePerToken": Decimal(str(price_per_token)),
        "TotalCost": Decimal(str(total_cost)),
        "LatencyMs": latency_ms,
        "StartTime": start_time,
        "EndTime": end_time,
        "UserMessage": user_message,
        "BotResponse": bot_response,
    }
    table.put_item(Item=item)
