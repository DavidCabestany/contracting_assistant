"""DynamoDB metrics logging utilities for LLM calls."""

from __future__ import annotations

import os
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping

import boto3
from botocore.exceptions import ClientError

# TODO(@kvnc639): Consider making the table name required in prod and failing fast if missing.
METRICS_TABLE = os.getenv("LLM_METRICS_TABLE", "azcdi-us-ops-procure-llm-metrics-env")

# TODO(@kvnc639) Keep these reserved so user payload can't clobber your schema.
_RESERVED_KEYS = {
    "MessageId",
    "Timestamp",
    "CallType",
    "SpanId",
    "UserId",
    "SessionId",
    "ModelId",
    "KbId",
    "KbPath",
    "LatencyMs",
    "InputTokenCount",
    "OutputTokenCount",
    "TotalTokenCount",
    "TokenCountsAvailable",
    "PricePerInputToken",
    "PricePerOutputToken",
    "TotalCost",
    "Status",
    "ErrorMessage",
}

_TABLE_LOCK = threading.Lock()
_TABLE = None


def _get_table():
    """Lazily create DynamoDB table resource (better for tests and import side-effects)."""
    global _TABLE
    if _TABLE is None:
        with _TABLE_LOCK:
            if _TABLE is None:
                dynamodb = boto3.resource("dynamodb")
                _TABLE = dynamodb.Table(METRICS_TABLE)
    return _TABLE


def _utc_iso_now() -> str:
    """UTC ISO-8601 timestamp (human-friendly)."""
    return datetime.now(timezone.utc).isoformat()


def _make_sort_key(timestamp_iso: str) -> str:
    """
    Composite sort key: timestamp + random suffix.
    Avoids PK/SK collisions across threads/processes without relying on monotonic clocks.
    """
    return f"{timestamp_iso}#{uuid.uuid4().hex}"


def _truncate(s: str | None, limit: int) -> str | None:
    if not s:
        return None
    return s if len(s) <= limit else s[:limit]


def _to_dynamo(value: Any) -> Any:
    """Convert values to DynamoDB-safe types recursively (floats -> Decimal)."""
    if value is None:
        return None

    # DynamoDB uses Decimal for non-integer numbers
    if isinstance(value, float):
        return Decimal(str(value))

    if isinstance(value, (dict, Mapping)):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if v is None:
                continue
            out[str(k)] = _to_dynamo(v)
        return out

    if isinstance(value, (list, tuple, set)):
        return [_to_dynamo(v) for v in value if v is not None]

    return value


def _clean_extra(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Remove reserved keys so payload can't overwrite the top-level schema."""
    extra: dict[str, Any] = {}
    for k, v in payload.items():
        if k in _RESERVED_KEYS:
            continue
        if v is None:
            continue
        extra[str(k)] = v
    return extra


def _compute_total_cost(
    input_tokens: int,
    output_tokens: int,
    price_per_input_token: float | None,
    price_per_output_token: float | None,
) -> float | None:
    if price_per_input_token is None and price_per_output_token is None:
        return None
    pit = float(price_per_input_token or 0.0)
    pot = float(price_per_output_token or 0.0)
    return (input_tokens * pit) + (output_tokens * pot)


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
    table = _get_table()

    span_id = payload.get("SpanId") or str(uuid.uuid4())

    in_tok = int(input_tokens or 0)
    out_tok = int(output_tokens or 0)
    tokens_available = (input_tokens is not None) or (output_tokens is not None)

    total_cost = _compute_total_cost(in_tok, out_tok, price_per_input_token, price_per_output_token)

    ts_iso = _utc_iso_now()
    sk = _make_sort_key(ts_iso)

    item: dict[str, Any] = {
        "MessageId": message_id,
        "Timestamp": sk,  # sort key: timestamp#random
        "TimestampIso": ts_iso,  # optional: easy to read / filter
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
        "ErrorMessage": _truncate(error_message, 1500),
        "Extra": _clean_extra(payload),
    }

    cleaned = _to_dynamo({k: v for k, v in item.items() if v is not None})

    # Retry transient AWS issues (throttling/network). No need to retry conditionals now.
    # FIXME(@kvnc639): If you have a standard retry helper in the project, use it instead.
    for attempt in range(3):
        try:
            table.put_item(
                Item=cleaned,
                ConditionExpression="attribute_not_exists(#pk) AND attribute_not_exists(#sk)",
                ExpressionAttributeNames={"#pk": "MessageId", "#sk": "Timestamp"},
            )
            return
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code == "ConditionalCheckFailedException":
                # Should be extremely rare now; generate a new SK and try once more quickly.
                ts_iso = _utc_iso_now()
                cleaned["Timestamp"] = _make_sort_key(ts_iso)
                cleaned["TimestampIso"] = ts_iso
                continue

            # Common transient codes
            if code in {"ProvisionedThroughputExceededException", "ThrottlingException", "RequestLimitExceeded"}:
                time.sleep(0.05 * (2**attempt))
                continue

            raise

    raise RuntimeError("Failed to write metrics after retries.")
