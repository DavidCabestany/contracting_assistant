"""This class retrieves feedback details with dynamic timeframe, including custom date windows."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Tuple

from boto3 import resource
from config import get_secret
from fastapi import APIRouter, HTTPException
from models.graph import (
    FeedbackDetailsFilters,
    FeedbackDetailsRequest,
    FeedbackDetailsResponse,
    FeedbackDetailsRow,
    RetrievedCitationModel,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

REGION_ID = get_secret("REGION_ID")
CHAT_TABLE = get_secret("CHAT_TABLE")

dynamodb = resource("dynamodb", region_name=REGION_ID)
table = dynamodb.Table(CHAT_TABLE)

feedbackdetails_router = APIRouter()

TIMEFRAME_MAP = {
    "last7days": 7,
    "last30days": 30,
    "last90days": 90,
    "last365days": 365,
}


def get_time_bounds(
    request: FeedbackDetailsRequest,
) -> Tuple[datetime, datetime]:
    """Calculate the (start, end) time window for filter.Supports custom ISO date ranges and preset timeframes.

    Args:
        request (FeedbackDetailsRequest): Incoming request data.

    Returns:
        Tuple[datetime, datetime]: Start and end UTC-aware datetime objects.

    Raises:
        HTTPException: if input dates are invalid or missing for "custom".
    """
    key = request.timeframe
    now = datetime.now(timezone.utc)
    if key.lower() == "custom":
        # Expect request.start_date and request.end_date as ISO strings
        if not hasattr(request, "start_date") or not hasattr(
            request, "end_date"
        ):
            raise HTTPException(
                400,
                "start_date and end_date must be provided for custom timeframe.",
            )
        if not request.start_date or not request.end_date:
            raise HTTPException(
                400,
                "start_date and end_date must be provided for custom timeframe.",
            )
        try:
            start_dt = datetime.fromisoformat(request.start_date)
            end_dt = datetime.fromisoformat(request.end_date)
        except Exception:
            raise HTTPException(
                400,
                "Invalid date format: must be ISO (e.g. '2025-06-01T00:00:00+00:00')",
            )
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)
        if start_dt > end_dt:
            raise HTTPException(400, "start_date must be <= end_date")
        return start_dt, end_dt
    else:
        # Preset window
        preset = key.lower()
        days = TIMEFRAME_MAP.get(preset)
        if not days:
            raise HTTPException(
                400,
                "Invalid timeframe: use last7days, last30days, last90days, last365days, or custom.",
            )
        start_dt = now - timedelta(days=days)
        return start_dt, now


def parse_kbtype(item) -> str:
    """Extract KBType value from ChatMetadata. Handles dict or string JSON.

    Args:
        item (dict): A DynamoDB item.

    Returns:
        str: KBType value or fallback.
    """
    meta = item.get("ChatMetadata")
    try:
        if isinstance(meta, dict):
            kbtype = meta.get("KbType") or {}
            if isinstance(kbtype, dict):
                return kbtype.get("S") or "General Queries"
            elif isinstance(kbtype, str):
                return kbtype
        elif isinstance(meta, str):
            import json

            try:
                meta_dict = json.loads(meta)
            except Exception:
                meta_dict = eval(meta)
            kbtype = meta_dict.get("KbType", {})
            if isinstance(kbtype, dict):
                return kbtype.get("S", "General Queries")
            if isinstance(kbtype, str):
                return kbtype
    except Exception:
        pass
    return "General Queries"


def parse_citation(item) -> RetrievedCitationModel:
    """Extracts citation document and page number from ChatMetadata.Handles both dict and JSON-string for ChatMetadata.

    Args:
        item (dict): A DynamoDB item.

    Returns:
        RetrievedCitationModel: citation information.
    """
    import json

    meta = item.get("ChatMetadata")
    doc_name = "Document.pdf"
    page_num = 1
    # Parse meta if it's a string JSON
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            try:
                meta = eval(meta)
            except Exception:
                meta = {}
    if isinstance(meta, dict):
        # Doc name
        file_field = meta.get("FileName")
        if isinstance(file_field, dict):
            doc_name = file_field.get("S", doc_name)
        elif isinstance(file_field, str):
            doc_name = file_field or doc_name
        # Page
        page_field = meta.get("Page")
        if isinstance(page_field, dict):
            try:
                page_num = int(page_field.get("N", page_num))
            except Exception:
                page_num = 1
        elif isinstance(page_field, (str, int)):
            try:
                page_num = int(page_field)
            except Exception:
                page_num = 1
    return RetrievedCitationModel(document=doc_name, page=page_num)


@feedbackdetails_router.post(
    "/getFeedbackDetails", response_model=FeedbackDetailsResponse
)
async def get_feedback_details(request: FeedbackDetailsRequest):
    """Returns feedback details for the admin UI.Supports window filtered by "last7days", "last30days", "last90days", "last365days", or a custom window.

    Args:
        request (FeedbackDetailsRequest): The request, including timeframe and (if custom) start_date/end_date.

    Returns:
        FeedbackDetailsResponse: List of feedback rows and echoed filters.
    """
    # Feedback type
    if request.feedbackType.lower() == "positive feedback":
        is_positive = True
    elif request.feedbackType.lower() == "negative feedback":
        is_positive = False
    else:
        raise HTTPException(
            400,
            "Invalid feedbackType. Use 'Positive Feedback' or 'Negative Feedback'.",
        )
    category_filter = (
        request.queryType
    )  # NOTE: now using queryType per your input.
    prid_filter = request.prid

    start_dt, end_dt = get_time_bounds(request)
    logger.debug(f"Time window: {start_dt} to {end_dt}")

    # 2. Load from DynamoDB
    try:
        scan_res = table.scan()
        items = scan_res.get("Items", [])
        logger.debug(f"Loaded {len(items)} rows from chat table")
    except Exception as e:
        logger.error("DynamoDB scan failed: %s", str(e))
        raise HTTPException(500, "DynamoDB scan failed")

    rows = []
    for item in items:
        logger.debug(
            f"Raw item: UserId={item.get('UserId')}, "
            f"Timestamp={item.get('Timestamp')}, "
            f"FeedbackComment={item.get('FeedbackComment')}, "
            f"IsFeedbackPositive={item.get('IsFeedbackPositive')}, "
            f"KBType={parse_kbtype(item)}"
        )

        # Date filter
        ts = item.get("Timestamp")
        if not ts:
            continue
        try:
            ts_dt = datetime.fromisoformat(ts)
            if ts_dt.tzinfo is None:
                ts_dt = ts_dt.replace(tzinfo=timezone.utc)
        except Exception:
            logger.debug(f"Skipping: Bad Timestamp {ts}")
            continue
        if not (start_dt <= ts_dt <= end_dt):
            continue

        # Feedback type filter
        IsFeedbackPositive = item.get("IsFeedbackPositive")
        val = str(IsFeedbackPositive).strip().lower()
        if val in ("true", "1"):
            item_positive = True
        elif val in ("false", "0"):
            item_positive = False
        else:
            continue
        if item_positive != is_positive:
            continue

        # KBType/category filter (queryType)
        kbtype = parse_kbtype(item)
        if category_filter != "All" and category_filter != kbtype:
            continue

        # PRID filter
        prid = item.get("UserId")
        if not prid:
            continue
        if (
            prid_filter
            and prid_filter.lower() != "all"
            and prid_filter != prid
        ):
            continue
        if (
            category_filter
            and category_filter.lower() != "all"
            and category_filter != kbtype
        ):
            continue

        # UserMessage
        user_message = (
            item.get("UserMessage") or item.get("UserMessageSearch") or ""
        )

        # Citation info
        retrieved_citation = parse_citation(item)

        # Feedback comment (may be empty, still included)
        feedback_comment = item.get("FeedbackComment", "")

        rows.append(
            FeedbackDetailsRow(
                prid=prid,
                query=user_message,
                retrievedCitation=retrieved_citation,
                feedbackComment=feedback_comment,
            )
        )

    filters = FeedbackDetailsFilters(
        feedbackType=request.feedbackType,
        category=category_filter,
        prid=request.prid,
        timeframe=request.timeframe,
    )
    rows = sorted(rows, key=lambda x: x.prid)
    logger.debug(f"Returning {len(rows)} feedback rows")
    return FeedbackDetailsResponse(feedbackDetails=rows, filters=filters)
