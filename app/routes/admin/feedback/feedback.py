"""This is a feedback graph class providing feedback trend and statistics APIs."""

import calendar
import logging
from datetime import date, datetime

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
    calculate_timeframe,
    fetch_feedback_data_extended,
    fetch_feedback_trends_data,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

feedback_data_router = APIRouter()


def get_week_label(dt: datetime) -> str:
    """Return the week label (W1-W4) and month abbreviation for a date."""
    day = dt.day
    month = dt.strftime("%b")
    if 1 <= day <= 7:
        return f"W1 {month}"
    elif 8 <= day <= 14:
        return f"W2 {month}"
    elif 15 <= day <= 21:
        return f"W3 {month}"
    else:
        return f"W4 {month}"


def get_month_label(dt: datetime) -> str:
    """Return the label as 'Mon YYYY'."""
    return dt.strftime("%b %Y")


def get_quarter_label(dt: datetime) -> str:
    """Return the label as 'Qx YYYY' based on the month."""
    quarter = (dt.month - 1) // 3 + 1
    return f"Q{quarter} {dt.year}"


def week_sortkey(label: str) -> tuple:
    """Sort key for week labels."""
    # Example: 'W1 May'
    week, month_abbr = label.split()
    # Get current year from context if info available, otherwise use the most recent
    today = datetime.now()
    year = (
        today.year
        if month_abbr != "Dec" or today.month >= 12
        else today.year - 1
    )
    # Try to infer correct year from existing month sequence
    try:
        month = list(calendar.month_abbr).index(month_abbr)
    except:  # noqa: E722
        month = 1
    # Correction if week sequence passes new year
    if today.month < month:
        year -= 1
    week_index = int(week[1])
    return (year, month, week_index)


def month_sortkey(label: str) -> tuple:
    """Sort key for month labels like 'May 2025'."""
    month_abbr, year = label.split()
    month = list(calendar.month_abbr).index(month_abbr)
    year = int(year)
    return (year, month)


def quarter_sortkey(label: str) -> tuple:
    """Sort key for quarter labels like 'Q2 2025'."""
    quarter, year = label.split()
    quarter = int(quarter[1])
    year = int(year)
    return (year, quarter)


def construct_trend_data(aggregated_data, timeframe) -> list:
    """Construct trend data for the expected UI grouping/labeling rules.

    Args:
        aggregated_data: Dict of grouped data from DB.
        timeframe: 'last30days', 'last90days', or 'last365days'.

    Returns:
        List[Dict]: Sorted trend elements with appropriate labels/values.
    """
    trend_dict = {}

    if timeframe == "last30days":
        # aggregate by (label, year, month, week)
        buckets = {}
        for dt, data in aggregated_data.items():
            # dt can be datetime.date or datetime
            if isinstance(dt, date) and not isinstance(dt, datetime):
                dt = datetime.combine(dt, datetime.min.time())
            label, year, month, week_idx = get_week_label_and_year(dt)
            key = (year, month, week_idx, label)
            if key not in buckets:
                buckets[key] = {"positive": 0, "negative": 0}
            buckets[key]["positive"] += data.get("positive", 0)
            buckets[key]["negative"] += data.get("negative", 0)
        # sort by year, month, week_idx
        sorted_keys = sorted(buckets.keys())
        trend_data = [
            {
                "label": label,
                "value": label,
                "negative": buckets[key]["negative"],
                "positive": buckets[key]["positive"],
            }
            for (year, month, week_idx, label) in sorted_keys
        ]
        return trend_data

    elif timeframe == "last90days":
        # Group by month, format "May 2025"
        for dt, data in aggregated_data.items():
            label = get_month_label(dt)
            if label not in trend_dict:
                trend_dict[label] = {"negative": 0, "positive": 0}
            trend_dict[label]["negative"] += data.get("negative", 0)
            trend_dict[label]["positive"] += data.get("positive", 0)
        # Chronological sort by year, month
        sorted_labels = sorted(trend_dict.keys(), key=month_sortkey)
        trend_data = [
            {
                "label": label,
                "value": label,
                "negative": trend_dict[label]["negative"],
                "positive": trend_dict[label]["positive"],
            }
            for label in sorted_labels
        ]

    elif timeframe == "last365days":
        # Group by quarter, format "Q2 2025"
        for dt, data in aggregated_data.items():
            label = get_quarter_label(dt)
            if label not in trend_dict:
                trend_dict[label] = {"negative": 0, "positive": 0}
            trend_dict[label]["negative"] += data.get("negative", 0)
            trend_dict[label]["positive"] += data.get("positive", 0)
        # Chronological sort by year then quarter
        sorted_labels = sorted(trend_dict.keys(), key=quarter_sortkey)
        trend_data = [
            {
                "label": label,
                "value": label,
                "negative": trend_dict[label]["negative"],
                "positive": trend_dict[label]["positive"],
            }
            for label in sorted_labels
        ]
    else:
        # Fallback to default: raw dates, as before.
        trend_data = []
        for dt, data in aggregated_data.items():
            time_label = dt.strftime("%Y-%m-%d")
            trend_data.append(
                {
                    "label": time_label,
                    "value": time_label,
                    "negative": data.get("negative", 0),
                    "positive": data.get("positive", 0),
                }
            )

    return trend_data


@feedback_data_router.post(
    "/getFeedbackTrend", response_model=FeedbackTrendResponse
)
async def get_feedback_trend(request: FeedbackTrendRequest):
    """Fetch feedback trend data grouped for visualization.

    - last30days: data grouped into weeks (W1-W4 per month)
    - last90days: grouped by calendar months
    - last365days: grouped by quarter (Q1-Q4 per year)

    Returns:
        FeedbackTrendResponse containing data[] with label/value/positive/negative keys.
    """
    try:
        current_time = datetime.now()
        start_time, end_time, _, _ = calculate_timeframe(
            request.timeframe, current_time, include_previous=False
        )
        aggregated_data = fetch_feedback_trends_data(
            start_time, end_time, request.timeframe
        )

        trend_data = construct_trend_data(aggregated_data, request.timeframe)

        logger.info(
            f"Feedback trend data fetched for {request.timeframe}: {len(trend_data)} items"
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
    """Fetches aggregated feedback statistics (counts, percentages, changes) for positive, negative, and no feedback types.

    Returns:
        FeedbackDataResponse with count/percentage/stats for each type for current and previous periods.
    """
    try:
        current_time = datetime.now()
        start_time, end_time, prev_start, prev_end = calculate_timeframe(
            request.timeframe, current_time, include_previous=True
        )

        # Get counts for selected and previous periods
        pos, neg, nof, _ = fetch_feedback_data_extended(start_time, end_time)
        ppos, pneg, pnof, _ = fetch_feedback_data_extended(
            prev_start, prev_end
        )

        total = pos + neg + nof

        def pct(val, base):
            return round((val / base * 100), 2) if base else 0.0

        def pct_change(curr, prev):
            if prev == 0:
                return 100 if curr > 0 else 0
            return round(((curr - prev) / prev) * 100)

        # Fill the FeedbackDataItem list (percent breakdown)
        data_items = [
            FeedbackDataItem(name="positive", value=pct(pos, total)),
            FeedbackDataItem(name="negative", value=pct(neg, total)),
            FeedbackDataItem(name="no_feedback", value=pct(nof, total)),
        ]

        pct_data = PctData(
            positiveCountFeedback=pos,
            negativeCountFeedback=neg,
            noCountFeedback=nof,
            positiveCountFeedback_pct=pct(pos, total),
            negativeCountFeedback_pct=pct(neg, total),
            noCountFeedback_pct=pct(nof, total),
            positive_pct_change=pct_change(pos, ppos),
            negative_pct_change=pct_change(neg, pneg),
            no_feedback_pct_change=pct_change(nof, pnof),
        )

        return FeedbackDataResponse(data=data_items, pct_data=pct_data)

    except Exception as e:
        logger.error(f"Error fetching feedback data: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch feedback data: {str(e)}"
        )


def calculate_pct_feedback(total_selected: int, total_feedback: int) -> int:
    """Calculate the percentage of selected feedback out of total feedback.

    Returns:
        Rounded integer percentage, or 0 if denominator is zero.
    """
    if total_feedback == 0:
        return 0
    pct_feedback = total_selected / total_feedback * 100
    return round(pct_feedback)


def get_week_label_and_year(dt: datetime) -> (str, int, int, int):
    """Return week label, year, month number, and week index for proper sorting."""
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
