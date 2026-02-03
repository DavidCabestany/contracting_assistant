"""This class fetches feedbackdetails."""

import json
import logging
from datetime import datetime, timezone
from typing import List, Optional

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
from routes.admin.utils.feedback_utils import (
    calculate_timeframe,
    fetch_feedbackdetails_items_in_timewindow,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

REGION_ID = get_secret("REGION_ID")
CHAT_TABLE = get_secret("CHAT_TABLE")
dynamodb = resource("dynamodb", region_name=REGION_ID)
table = dynamodb.Table(CHAT_TABLE)

feedbackdetails_router = APIRouter()


def parse_kbtype(item) -> str:
    """Extract and normalize KbType (category) from ChatMetadata."""
    meta = item.get("ChatMetadata")
    kbtype_val = ""

    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            try:
                meta = eval(meta)
            except Exception:
                return ""
    if not isinstance(meta, dict):
        return ""

    kb = meta.get("KbType")
    if isinstance(kb, dict):
        kbtype_val = kb.get("S", "")
    elif isinstance(kb, str):
        kbtype_val = kb
    return str(kbtype_val).strip().lower()


def parse_all_citations(item) -> Optional[List[RetrievedCitationModel]]:
    """Extract all (fileName, pageNumber) citations from ChatMetadata if present."""
    meta = item.get("ChatMetadata")
    if not meta:
        return None

    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            try:
                meta = eval(meta)
            except Exception:
                return None
    if not isinstance(meta, dict):
        return None

    fileName_data = meta.get("FileName")
    citations = []
    if isinstance(fileName_data, dict) and "L" in fileName_data:
        file_entries = fileName_data["L"]
        for fentry in file_entries:
            if not isinstance(fentry, dict) or "M" not in fentry:
                continue
            meta_map = fentry["M"]
            file_name_obj = meta_map.get("fileName")
            page_obj = meta_map.get("pageNumber")
            if (
                isinstance(file_name_obj, dict)
                and "S" in file_name_obj
                and isinstance(page_obj, dict)
                and "N" in page_obj
            ):
                fname = file_name_obj["S"]
                try:
                    page_num = int(page_obj["N"])
                except Exception:
                    page_num = None
                if fname and page_num is not None:
                    citations.append(RetrievedCitationModel(document=fname, page=page_num))
    elif isinstance(fileName_data, list):
        for fentry in fileName_data:
            if isinstance(fentry, dict):
                fname = fentry.get("fileName")
                page_num = fentry.get("pageNumber")
                if fname and (page_num is not None):
                    try:
                        citations.append(RetrievedCitationModel(document=fname, page=int(page_num)))
                    except Exception:
                        continue
    # logger.info(f"parse_all_citations: citations={citations}")
    return citations or None


@feedbackdetails_router.post("/getFeedbackDetails", response_model=FeedbackDetailsResponse)
async def get_feedback_details(request: FeedbackDetailsRequest):
    """Admin endpoint for feedback details. Filters by feedbackType, timeframe (including custom), queryType (KbType), and UserId (prid). Returns all document/page citations as a list."""
    # === CHANGED LOGIC: ADD "ALL" FILTER OPTION ===
    ft = request.feedbackType.strip().lower()
    if ft == "positive feedback":
        is_positive = True
        filter_on_feedback = True
    elif ft == "negative feedback":
        is_positive = False
        filter_on_feedback = True
    elif ft == "no feedback":
        is_no_feedback = True
        filter_on_feedback = True
    elif ft == "all":
        filter_on_feedback = False
    else:
        raise HTTPException(
            400,
            "Invalid feedbackType. Use 'Positive Feedback', 'Negative Feedback', 'No Feedback', or 'All'.",
        )

    query_type_filter = (request.queryType or "").strip().lower()
    allow_all_types = query_type_filter in ("", "all")
    prid_filter = (request.prid or "").strip().lower()
    allow_all_prids = prid_filter in ("", "all")

    # --- Custom timeframe support ---
    if request.timeframe.strip().lower() == "custom":
        try:
            if not request.start_date or not request.end_date:
                raise ValueError("start_date and end_date must be provided for custom timeframe.")
            # Accept both with/without Z by parsing
            start_dt = datetime.fromisoformat(request.start_date.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(request.end_date.replace("Z", "+00:00"))

            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=timezone.utc)
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=timezone.utc)
            # Expand end_dt to include full ending day
            end_dt = end_dt.replace(hour=23, minute=59, second=59, microsecond=999999)
        except Exception as ex:
            raise HTTPException(400, f"Invalid custom date: {ex}")
    else:
        current_time = datetime.now(timezone.utc)
        try:
            start_dt, end_dt, *_ = calculate_timeframe(request.timeframe, current_time)
            # Fix: adjust boundaries to full days
            start_dt = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
            end_dt = end_dt.replace(hour=23, minute=59, second=59, microsecond=999999)
        except Exception:
            raise HTTPException(
                400,
                "Invalid timeframe: use last7days, last30days, last90days, last365days, or custom.",
            )

    db_items = fetch_feedbackdetails_items_in_timewindow(start_dt, end_dt)

    # --------- Apply W1–W4 week bucket filtering for last30days ---------
    def week_bucket_ranges_for_30day_window(start_dt, end_dt):
        import calendar
        from datetime import datetime, timezone

        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)
        buckets = []
        months = []
        m = start_dt.replace(day=1)
        while m <= end_dt:
            months.append((m.year, m.month))
            if m.month == 12:
                m = m.replace(year=m.year + 1, month=1)
            else:
                m = m.replace(month=m.month + 1)
        for year, month in months:
            days_in_month = calendar.monthrange(year, month)[1]
            for widx, (low, high) in enumerate([(1, 7), (8, 14), (15, 21), (22, days_in_month)], 1):
                wk_start = datetime(year, month, low, tzinfo=timezone.utc)
                wk_end = datetime(year, month, high, tzinfo=timezone.utc)
                if wk_end < start_dt or wk_start > end_dt:
                    continue
                buckets.append((wk_start, wk_end))
        return buckets

    if request.timeframe.strip().lower() == "last30days":
        week_buckets = week_bucket_ranges_for_30day_window(start_dt, end_dt)
        filtered_items = []
        for item in db_items:
            try:
                dt = datetime.fromisoformat(item.get("Timestamp"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
            except Exception:
                continue
            for wk_start, wk_end in week_buckets:
                if wk_start <= dt <= wk_end:
                    filtered_items.append(item)
                    break
        db_items = filtered_items

    for idx, item in enumerate(db_items):
        # logger.info(
        #    "Record [%d]: UserId(PRID)=%r | Timestamp=%r | IsFeedbackPositive=%r",
        #    idx + 1,
        #    item.get("UserId"),
        #    item.get("Timestamp"),
        #    item.get("IsFeedbackPositive"),
        # )

        # ----------- Order Change: capture rows with timestamps and sort -----------
        rows_with_time = []
    for item in db_items:
        feedback_raw = item.get("IsFeedbackPositive")
        val = str(feedback_raw).strip().lower()
        if val in ("true", "1", "yes", "y", "t"):
            item_positive = True
            item_no_feedback = False
        elif val in ("false", "0", "no", "n", "f"):
            item_positive = False
            item_no_feedback = False
        elif val == "no_feedback":
            item_no_feedback = True
            item_positive = None
        else:
            continue

        # Only filter if not "All"
        if filter_on_feedback:
            if ft == "no feedback" and not item_no_feedback:
                continue
            elif ft == "positive feedback" and not item_positive:
                continue
            elif ft == "negative feedback" and (item_positive or item_no_feedback):
                continue

        # ---- Filter by queryType/KbType
        kbtype = parse_kbtype(item)
        if not allow_all_types:
            if kbtype == "":
                continue
            if kbtype != query_type_filter:
                continue

        # ---- Filter by UserId (prid)
        prid = item.get("UserId", "")
        if not allow_all_prids:
            if prid.strip().lower() != prid_filter:
                continue

        user_message = item.get("UserMessage", "") or item.get("UserMessageSearch", "")
        citations = parse_all_citations(item)
        # logger.info("User %s citations: %s", prid, citations)
        feedback_comment = item.get("FeedbackComment", "")

        # === ADD FEEDBACK RESPONSE after query ===
        feedback_response = item.get("BotResponse", "")

        # Get timestamp for sorting; fallback to epoch if not present
        timestamp_str = item.get("Timestamp")
        try:
            timestamp_val = datetime.fromisoformat(timestamp_str) if timestamp_str else datetime.min
            if timestamp_val.tzinfo is None:
                timestamp_val = timestamp_val.replace(tzinfo=timezone.utc)
        except Exception:
            timestamp_val = datetime.min

        row_obj = FeedbackDetailsRow(
            prid=prid,
            query=user_message,
            feedbackResponse=feedback_response,  # <-- added field!
            retrievedCitations=citations,
            feedbackComment=feedback_comment,
            date=timestamp_val.strftime("%Y-%m-%d %H:%M:%S"),
        )
        rows_with_time.append((timestamp_val, row_obj))

    # ----------- Sort: most recent first -----------
    rows_with_time.sort(key=lambda tup: tup[0], reverse=True)
    rows = [row for _, row in rows_with_time]

    filters = FeedbackDetailsFilters(
        feedbackType=request.feedbackType,
        category=request.queryType,
        prid=request.prid,
        timeframe=request.timeframe,
    )
    return FeedbackDetailsResponse(feedbackDetails=rows, filters=filters)
