"""This module provides API endpoints for tracking feedback trends and statistics."""

import calendar
import logging
from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException
from models import (
    FeedbackDataItem,
    FeedbackDataRequest,
    FeedbackDataResponse,
    FeedbackTrendRequest,
    FeedbackTrendResponse,
    PctData,
    TrendData,
)
from routes.admin.utils.feedback_utils import (
    fetch_feedback_items_in_timewindow,  # <-- Use this for unified filtering!
)
from routes.admin.utils.feedback_utils import (
    calculate_timeframe,
    feedback_class,
    parse_date_flexible,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
feedback_data_router = APIRouter()


def get_week_label_and_year(dt: datetime) -> (str, int, int, int):  # type: ignore
    """Returns the week label (e.g., W1 Jan), year, month, and week index (1-4) for a given datetime."""
    day = dt.day
    month = dt.month
    year = dt.year
    month_abbr = dt.strftime("%b")
    if 1 <= day <= 7:
        week_idx = 1
    elif 8 <= day <= 14:
        week_idx = 2
    elif 15 <= day <= 21:
        week_idx = 3
    else:
        week_idx = 4
    label = f"W{week_idx} {month_abbr}"
    return label, year, month, week_idx


def get_month_label(dt: datetime) -> str:
    """Returns the month label (e.g., Jan 2024) for a given datetime."""
    return dt.strftime("%b %Y")


def get_quarter_label(dt: datetime) -> str:
    """Returns the quarter label (e.g., Q1 2024) for a given datetime."""
    quarter = (dt.month - 1) // 3 + 1
    return f"Q{quarter} {dt.year}"


def week_sortkey(label: str) -> tuple:
    """Returns a sort key tuple for week labels (e.g., W2 Feb) to enable chronological sorting."""
    week, month_abbr = label.split()
    today = datetime.now()
    year = (
        today.year
        if (month_abbr != "Dec" or today.month >= 12)
        else today.year - 1
    )
    try:
        month = list(calendar.month_abbr).index(month_abbr)
    except Exception:
        month = 1
    if today.month < month:
        year -= 1
    week_index = int(week[1])
    return (year, month, week_index)


def month_sortkey(label: str) -> tuple:
    """Returns a sort key tuple for month labels (e.g., Jan 2024)."""
    month_abbr, year = label.split()
    month = list(calendar.month_abbr).index(month_abbr)
    year = int(year)
    return (year, month)


def quarter_sortkey(label: str) -> tuple:
    """Returns a sort key tuple for quarter labels (e.g., Q2 2023)."""
    quarter, year = label.split()
    quarter = int(quarter[1])
    year = int(year)
    return (year, quarter)


def aggregate_stats(items):
    """Aggregate all feedback stats over filtered items.Returns the counts of positive, negative, and no feedback items."""
    pos, neg, nofb = 0, 0, 0
    for item in items:
        val = item.get("IsFeedbackPositive")
        label = feedback_class(val)
        if label == "positive":
            pos += 1
        elif label == "negative":
            neg += 1
        else:
            nofb += 1
    return pos, neg, nofb


def aggregate_trend(items, timeframe, start_dt, end_dt):
    """Aggregate feedback items into appropriate time buckets, both positive and negative.Fills all buckets in the range, even if zero."""
    # 1. Group
    buckets = defaultdict(lambda: {"positive": 0, "negative": 0})
    for item in items:
        dt = parse_date_flexible(item["Timestamp"])
        val = item.get("IsFeedbackPositive")
        label = feedback_class(val)
        # Per-timeframe key
        if timeframe == "last7days":
            bucket = dt.date()
        elif timeframe == "last30days":
            # Bucket by *Monday* of each week by day, make key a date
            week_start = (dt - timedelta(days=dt.weekday())).date()
            bucket = week_start
        elif timeframe == "last90days":
            # Bucket by month
            bucket = datetime(dt.year, dt.month, 1)
        elif timeframe == "last365days":
            # Bucket by quarter
            q_start_month = (((dt.month - 1) // 3) * 3) + 1
            bucket = datetime(dt.year, q_start_month, 1)
        else:
            bucket = dt.date()
        if label == "positive":
            buckets[bucket]["positive"] += 1
        elif label == "negative":
            buckets[bucket]["negative"] += 1
        # 'no_feedback' is not counted in trend

    # 2. Fill missing buckets for full period
    out = []
    if timeframe == "last7days":
        cur = start_dt.date()
        end_date = end_dt.date()
        while cur <= end_date:
            data = buckets.get(cur, {"positive": 0, "negative": 0})
            formatted_date = cur.strftime("%d-%b")
            out.append(
                {
                    "label": formatted_date,
                    "value": formatted_date,
                    "positive": data["positive"],
                    "negative": data["negative"],
                }
            )
            cur += timedelta(days=1)
        return out

    elif timeframe == "last30days":
        # Fill by Monday date for each week in window
        cur = (start_dt - timedelta(days=start_dt.weekday())).date()
        endw = (end_dt - timedelta(days=end_dt.weekday())).date()
        while cur <= endw:
            label, *_ = get_week_label_and_year(
                datetime.combine(cur, datetime.min.time())
            )
            data = buckets.get(cur, {"positive": 0, "negative": 0})
            out.append(
                {
                    "label": label,
                    "value": label,
                    "positive": data["positive"],
                    "negative": data["negative"],
                }
            )
            cur += timedelta(days=7)
        return out

    elif timeframe == "last90days":
        cur = datetime(start_dt.year, start_dt.month, 1)
        end_month = datetime(end_dt.year, end_dt.month, 1)
        while cur <= end_month:
            label = get_month_label(cur)
            data = buckets.get(cur, {"positive": 0, "negative": 0})
            out.append(
                {
                    "label": label,
                    "value": label,
                    "positive": data["positive"],
                    "negative": data["negative"],
                }
            )
            # Next month
            if cur.month == 12:
                cur = cur.replace(year=cur.year + 1, month=1)
            else:
                cur = cur.replace(month=cur.month + 1)
        return out

    elif timeframe == "last365days":

        def quarter_start(dt):
            m = (((dt.month - 1) // 3) * 3) + 1
            return datetime(dt.year, m, 1)

        cur = quarter_start(start_dt)
        endq = quarter_start(end_dt)
        while cur <= endq:
            label = get_quarter_label(cur)
            data = buckets.get(cur, {"positive": 0, "negative": 0})
            out.append(
                {
                    "label": label,
                    "value": label,
                    "positive": data["positive"],
                    "negative": data["negative"],
                }
            )
            # Next quarter
            if cur.month >= 10:
                cur = cur.replace(year=cur.year + 1, month=1)
            else:
                cur = cur.replace(month=cur.month + 3)
        return out

    else:
        # fallback: daily
        cur = start_dt.date()
        end_date = end_dt.date()
        while cur <= end_date:
            data = buckets.get(cur, {"positive": 0, "negative": 0})
            out.append(
                {
                    "label": cur.strftime("%Y-%m-%d"),
                    "value": cur.strftime("%Y-%m-%d"),
                    "positive": data["positive"],
                    "negative": data["negative"],
                }
            )
            cur += timedelta(days=1)
        return out


@feedback_data_router.post(
    "/getFeedbackTrend", response_model=FeedbackTrendResponse
)
async def get_feedback_trend(request: FeedbackTrendRequest):
    """Fetch feedback trend data grouped for visualization."""
    try:
        current_time = datetime.now()
        start_time, end_time, _, _ = calculate_timeframe(
            request.timeframe, current_time, include_previous=False
        )
        # Unified fetch!
        items = fetch_feedback_items_in_timewindow(start_time, end_time)
        logger.info(
            f"Fetched feedback items for trend ({request.timeframe}): {items}"
        )
        trend_data = aggregate_trend(
            items, request.timeframe, start_time, end_time
        )
        logger.info(
            f"Feedback trend data fetched for {request.timeframe}: {len(trend_data)} items "
            f"(sum positive={sum(x['positive'] for x in trend_data)}, "
            f"sum negative={sum(x['negative'] for x in trend_data)})"
        )
        return FeedbackTrendResponse(
            data=[TrendData(**item) for item in trend_data]
        )
    except Exception as e:
        logger.error(f"Error fetching feedback trend: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch feedback trend: {str(e)}"
        )


@feedback_data_router.post(
    "/getFeedbackData", response_model=FeedbackDataResponse
)
async def get_feedback_data(request: FeedbackDataRequest):
    """Fetch aggregated feedback statistics (counts, percentages, changes)."""
    try:
        current_time = datetime.now()
        start_time, end_time, prev_start, prev_end = calculate_timeframe(
            request.timeframe, current_time, include_previous=True
        )

        items = fetch_feedback_items_in_timewindow(start_time, end_time)
        pos, neg, nofb = aggregate_stats(items)
        prev_items = fetch_feedback_items_in_timewindow(prev_start, prev_end)
        ppos, pneg, pnofb = aggregate_stats(prev_items)
        logger.info(
            f"Aggregated stats: positive={pos}, negative={neg}, no_feedback={nofb}; previous window: pos={ppos}, neg={pneg}, nofb={pnofb}"
        )

        total = pos + neg + nofb

        def pct(val, base):
            return round((val / base * 100), 2) if base else 0.0

        def pct_change(curr, prev):
            if prev == 0:
                return 100 if curr > 0 else 0
            return round(((curr - prev) / prev) * 100)

        data_items = [
            FeedbackDataItem(name="positive", value=pct(pos, total)),
            FeedbackDataItem(name="negative", value=pct(neg, total)),
            FeedbackDataItem(name="no_feedback", value=pct(nofb, total)),
        ]
        pct_data = PctData(
            positiveCountFeedback=pos,
            negativeCountFeedback=neg,
            noCountFeedback=nofb,
            positiveCountFeedback_pct=pct(pos, total),
            negativeCountFeedback_pct=pct(neg, total),
            noCountFeedback_pct=pct(nofb, total),
            positive_pct_change=pct_change(pos, ppos),
            negative_pct_change=pct_change(neg, pneg),
            no_feedback_pct_change=pct_change(nofb, pnofb),
        )
        return FeedbackDataResponse(data=data_items, pct_data=pct_data)

    except Exception as e:
        logger.error(f"Error fetching feedback data: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch feedback data: {str(e)}"
        )
