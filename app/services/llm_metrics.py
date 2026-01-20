"""DynamoDB metrics logging utilities for LLM calls."""

import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import boto3
from botocore.exceptions import ClientError

METRICS_TABLE = os.getenv("LLM_METRICS_TABLE", "azcdi-us-ops-procure-llm-metrics-env")

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(METRICS_TABLE)

_lock = threading.Lock()
_last_ts: datetime | None = None


def _next_timestamp_iso() -> str:
    """Return a UTC ISO-8601 timestamp to calculate latency."""
    global _last_ts
    with _lock:
        now = datetime.now(timezone.utc)
        if _last_ts is not None and now <= _last_ts:
            now = _last_ts + timedelta(microseconds=1)
        _last_ts = now
        return now.isoformat()


def _to_dynamo(value: Any) -> Any:
    """Convert values to DynamoDB-safe types (floats -> Decimal) recursively."""
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: _to_dynamo(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_to_dynamo(v) for v in value if v is not None]
    return value


def put_llm_metrics(
    *,
    message_id: str,
    call_type: str,
    payload: dict[str, Any],
    user_id: str | None = None,
    session_id: str | None = None,
    model_id: str | None = None,
    kb_id: str | None = None,
    kb_path: str | None = None,
    latency_ms: int | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    price_per_input_token: float | None = None,
    price_per_output_token: float | None = None,
    status: str = "success",
    error_message: str | None = None,
) -> None:
    """Write one LLM metrics record to DynamoDB."""
    safe_payload = dict(payload)
    safe_payload.pop("MessageId", None)
    safe_payload.pop("Timestamp", None)

    span_id = safe_payload.get("SpanId") or str(uuid.uuid4())

    in_tok = int(input_tokens or 0)
    out_tok = int(output_tokens or 0)
    tokens_available = input_tokens is not None or output_tokens is not None

    total_cost: float | None = None
    if price_per_input_token is not None or price_per_output_token is not None:
        pit = float(price_per_input_token or 0.0)
        pot = float(price_per_output_token or 0.0)
        total_cost = (in_tok * pit) + (out_tok * pot)

    base_item: dict[str, Any] = {
        "MessageId": message_id,
        "CallType": call_type,
        "SpanId": span_id,
        "UserId": user_id,
        "SessionId": session_id,
        "ModelId": model_id,
        "KbId": kb_id,
        "KbPath": kb_path,
        "LatencyMs": latency_ms,
        "InputTokenCount": in_tok,
        "OutputTokenCount": out_tok,
        "TotalTokenCount": in_tok + out_tok,
        "TokenCountsAvailable": bool(tokens_available),
        "PricePerInputToken": price_per_input_token,
        "PricePerOutputToken": price_per_output_token,
        "TotalCost": total_cost,
        "Status": status,
        "ErrorMessage": error_message[:1500] if error_message else None,
    }

    # Retry on rare PK/SK collision across processes.
    for _ in range(2):
        ts = _next_timestamp_iso()
        item = {**base_item, "Timestamp": ts, **safe_payload}
        cleaned = _to_dynamo({k: v for k, v in item.items() if v is not None})

        try:
            table.put_item(
                Item=cleaned,
                ConditionExpression="attribute_not_exists(#pk) AND attribute_not_exists(#sk)",
                ExpressionAttributeNames={"#pk": "MessageId", "#sk": "Timestamp"},
            )
            return
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise

    raise RuntimeError("Failed to write metrics due to repeated PK/SK collision.")
