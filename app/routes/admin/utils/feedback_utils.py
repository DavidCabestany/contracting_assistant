"""This class Fetch and aggregate feedback data."""

import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

from boto3 import resource
from config import get_secret

from .dynamodb_utils import scan_table

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)  # Ensure debug logging level is set

REGION_ID = get_secret("REGION_ID")
CHAT_TABLE = get_secret("CHAT_TABLE")

dynamodb = resource("dynamodb", region_name=REGION_ID)
table = dynamodb.Table(CHAT_TABLE)


def fetch_feedback_data(
    start_time: datetime, end_time: datetime, is_positive: bool
) -> Tuple[Dict[str, int], int, int]:
    """Fetch and aggregate feedback data from DynamoDB within a specified timeframe."""
    items = scan_table(
        table=table,
        projection_expression="#ts, IsFeedbackPositive",
        expression_attribute_names={"#ts": "Timestamp"},
        error_handling="return_empty",
    )

    feedback_data = {"positive": 0, "negative": 0}
    total_positive = 0
    total_negative = 0

    for item in items:
        timestamp_str = item.get("Timestamp", "")
        feedback_positive = item.get("IsFeedbackPositive")

        if feedback_positive in (None, "None"):
            continue

        if not timestamp_str:
            logger.error(f"Missing timestamp in item: {item}")
            continue

        try:
            feedback_timestamp = datetime.fromisoformat(timestamp_str)
            logger.debug(
                f"Parsed timestamp (should be datetime): {feedback_timestamp} of type {type(feedback_timestamp)}"
            )

            if start_time <= feedback_timestamp <= end_time:
                if feedback_positive:
                    feedback_data["positive"] += 1
                    total_positive += 1
                else:
                    feedback_data["negative"] += 1
                    total_negative += 1
        except Exception as e:
            logger.error(
                f"Error parsing timestamp {timestamp_str} in item: {item}: {e}"
            )

    total_selected = total_positive if is_positive else total_negative
    logger.info(
        f"Total feedback selected ({'positive' if is_positive else 'negative'}): {total_selected}"
    )
    return feedback_data, total_selected, total_positive + total_negative


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


def fetch_feedback_trends_data(
    start_time: datetime, end_time: datetime, timeframe: str
) -> Dict[datetime, Dict[str, int]]:
    """Fetch and aggregate feedback trends from DynamoDB based on a timeframe."""
    items = scan_table(
        table=table,
        projection_expression="#ts, IsFeedbackPositive",
        expression_attribute_names={"#ts": "Timestamp"},
        error_handling="return_empty",
    )

    trend_data = {}
    for item in items:
        timestamp_str = item.get("Timestamp", "")
        feedback_positive = item.get("IsFeedbackPositive")

        if feedback_positive in (None, "None"):
            continue

        if not timestamp_str:
            logger.error(f"Missing timestamp in item: {item}")
            continue

        try:
            feedback_timestamp = datetime.fromisoformat(timestamp_str)
            logger.debug(
                f"Evaluating timestamp: {feedback_timestamp}, Type: {type(feedback_timestamp)}"
            )

            if start_time <= feedback_timestamp <= end_time:
                key = None
                if timeframe == "last7days":
                    key = feedback_timestamp.date()
                elif timeframe == "last30days":
                    key = (
                        feedback_timestamp
                        - timedelta(days=feedback_timestamp.weekday())
                    ).date()
                elif timeframe == "last90days":
                    key = datetime(
                        feedback_timestamp.year, feedback_timestamp.month, 1
                    )
                elif timeframe == "last365days":
                    logger.debug(
                        f"Preparing to generate quarter key using: {feedback_timestamp}"
                    )
                    quarter = (feedback_timestamp.month - 1) // 3 + 1
                    month_start = (quarter - 1) * 3 + 1
                    key = datetime(feedback_timestamp.year, month_start, 1)

                logger.debug(f"Generated key: {key} of type {type(key)}")

                if key not in trend_data:
                    trend_data[key] = {"positive": 0, "negative": 0}

                if feedback_positive:
                    trend_data[key]["positive"] += 1
                else:
                    trend_data[key]["negative"] += 1
        except Exception as e:
            logger.error(
                f"Error parsing timestamp {timestamp_str} in item: {item}: {e}"
            )

    logger.info(f"Feedback trend data fetched: {trend_data}")
    return trend_data


def fetch_feedback_data_extended(start_time, end_time):
    """Fetch and aggregate feedback data for positive, negative, and no_feedback.

    Returns:
        - positive_count (int): positive feedbacks
        - negative_count (int): negative feedbacks
        - no_feedback_count (int): 'no_feedback' responses
        - details (dict): category counts
    """
    from boto3 import resource
    from config import get_secret
    from routes.admin.utils.dynamodb_utils import scan_table

    REGION_ID = get_secret("REGION_ID")
    CHAT_TABLE = get_secret("CHAT_TABLE")
    dynamodb = resource("dynamodb", region_name=REGION_ID)
    table = dynamodb.Table(CHAT_TABLE)

    items = scan_table(
        table=table,
        projection_expression="#ts, IsFeedbackPositive",
        expression_attribute_names={"#ts": "Timestamp"},
        error_handling="return_empty",
    )

    positive = 0
    negative = 0
    no_feedback = 0
    for item in items:
        ts = item.get("Timestamp", "")
        val = item.get("IsFeedbackPositive", None)
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(ts)
        except Exception:
            continue
        if not (start_time <= dt <= end_time):
            continue

        if val is True:
            positive += 1
        elif val is False:
            negative += 1
        elif str(val).lower() == "no_feedback":
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
