"""This class fetches and aggregates feedback data."""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from boto3 import resource
from config import get_secret

from .dynamodb_utils import scan_table

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)  # Ensure debug logging level is set

REGION_ID = get_secret("REGION_ID")
CHAT_TABLE = get_secret("CHAT_TABLE")

dynamodb = resource("dynamodb", region_name=REGION_ID)
table = dynamodb.Table(CHAT_TABLE)


def parse_date_flexible(ts: str) -> Optional[datetime]:
    """Robustly parse a date string supporting ISO and 'DD-MM-YYYY' formats.Returns datetime or None if parsing fails."""
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        pass
    try:
        return datetime.strptime(ts, "%d-%m-%Y")
    except Exception:
        pass
    return None  # Give up


def feedback_class(val):
    """Normalize the DynamoDB IsFeedbackPositive value."""
    if isinstance(val, bool):
        return "positive" if val else "negative"
    if isinstance(val, (int, float)):
        return "positive" if val else "negative"
    if isinstance(val, str):
        v = val.strip().lower()
        if v in ("true", "yes", "positive", "1"):
            return "positive"
        elif v in ("false", "no", "negative", "0"):
            return "negative"
        elif v == "no_feedback":
            return "no_feedback"
    return None


def calculate_timeframe(
    timeframe: str, current_time: datetime, include_previous: bool = False
) -> Tuple[datetime, datetime, Optional[datetime], Optional[datetime]]:
    """Calculate the start and end times for a given timeframe, optionally including the previous period."""
    if timeframe == "last7days":
        start_time = current_time - timedelta(days=7)
        end_time = current_time
        prev_start_time = start_time - timedelta(days=7)
        prev_end_time = start_time
    elif timeframe == "last30days":
        start_time = current_time - timedelta(days=30)
        end_time = current_time
        prev_start_time = start_time - timedelta(days=30)
        prev_end_time = start_time
    elif timeframe == "last90days":
        start_time = current_time - timedelta(days=90)
        end_time = current_time
        prev_start_time = start_time - timedelta(days=90)
        prev_end_time = start_time
    elif timeframe == "last365days":
        start_time = current_time - timedelta(days=365)
        end_time = current_time
        prev_start_time = start_time - timedelta(days=365)
        prev_end_time = start_time
    else:
        raise ValueError("Invalid timeframe")
    logger.info(
        f"Calculated timeframe for {timeframe}: start={start_time}, end={end_time}"
    )
    return start_time, end_time, prev_start_time, prev_end_time


def fetch_feedback_items_in_timewindow(start_time, end_time) -> List[dict]:
    """Fetch all feedback items in the given time window, with robust timestamp parsing.Returns list of dicts."""
    items = scan_table(
        table=table,
        projection_expression="#ts, IsFeedbackPositive",
        expression_attribute_names={"#ts": "Timestamp"},
        error_handling="return_empty",
    )
    filtered = []
    for item in items:
        raw_ts = item.get("Timestamp", "")
        if not raw_ts:
            continue
        dt = parse_date_flexible(raw_ts)
        if not dt:
            continue
        if not (start_time <= dt <= end_time):
            continue
        filtered.append(
            {
                "Timestamp": raw_ts,
                "IsFeedbackPositive": item.get("IsFeedbackPositive"),
            }
        )
    logger.info(
        f"Filtered DB items for [{start_time} - {end_time}]: {filtered}"
    )
    return filtered


def fetch_feedback_data_extended(start_time, end_time):
    """Fetch and aggregate feedback data for positive, negative, and no_feedback."""
    items = fetch_feedback_items_in_timewindow(start_time, end_time)

    positive = 0
    negative = 0
    no_feedback = 0
    for item in items:
        val = item.get("IsFeedbackPositive", None)
        label = feedback_class(val)
        if label == "positive":
            positive += 1
        elif label == "negative":
            negative += 1
        elif label == "no_feedback":
            no_feedback += 1

    return (
        positive,
        negative,
        no_feedback,
        {
            "positive": positive,
            "negative": negative,
            "no_feedback": no_feedback,
        },
    )


def fetch_feedback_trends_data(
    start_time: datetime, end_time: datetime, timeframe: str
) -> Dict[datetime, Dict[str, int]]:
    """Fetch and aggregate feedback trends from DynamoDB based on a timeframe.

    Returns:
        Dict mapping datetime (bucket) to {"positive": int, "negative": int}
    """
    items = fetch_feedback_items_in_timewindow(start_time, end_time)
    logger.info(
        f"Items returned for trend aggregation in [{start_time} - {end_time}]: {items}"
    )
    trend_data = {}

    for item in items:
        raw_ts = item.get("Timestamp", "")
        feedback_positive = item.get("IsFeedbackPositive")
        dt = parse_date_flexible(raw_ts)
        if not dt:
            continue

        fb_type = feedback_class(feedback_positive)
        if fb_type not in ("positive", "negative"):
            continue  # skip "no_feedback" or missing

        # Decide on grouping key
        if timeframe == "last7days":
            key = dt.date()
        elif timeframe == "last30days":
            key = (dt - timedelta(days=dt.weekday())).date()
        elif timeframe == "last90days":
            key = datetime(dt.year, dt.month, 1)
        elif timeframe == "last365days":
            quarter = (dt.month - 1) // 3 + 1
            month_start = (quarter - 1) * 3 + 1
            key = datetime(dt.year, month_start, 1)
        else:
            key = dt.date()

        if key not in trend_data:
            trend_data[key] = {"positive": 0, "negative": 0}

        if fb_type == "positive":
            trend_data[key]["positive"] += 1
        elif fb_type == "negative":
            trend_data[key]["negative"] += 1

    logger.info(f"Feedback trend aggregation result / buckets: {trend_data}")
    return trend_data
