"""A class to fetch and total usage statistics."""

import calendar
import logging
from datetime import datetime, timedelta
from typing import Dict, List

import pandas as pd
from boto3 import resource
from config import get_secret
from routes.admin.utils.dynamodb_utils import scan_table

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

REGION_ID = get_secret("REGION_ID")
CHAT_TABLE = get_secret("CHAT_TABLE")

dynamodb = resource("dynamodb", region_name=REGION_ID)
table = dynamodb.Table(CHAT_TABLE)


class UsageLogic:
    """A class to fetch and aggregate usage statistics over time periods for dashboard analytics.

    Provides methods for bucketing usage (chat) data by:
      - Day (last 7 days)
      - Week (W1–W4 per calendar month, last 30 days)
      - Month (last 90 days)
      - Quarter (last 365 days)

    Time periods and bucket definitions match business requirements exactly.
    All API returns are in the format:
        { "label": "BucketLabel", "value": NumberOfEvents }
    """

    @staticmethod
    def fetch_usage_by_time_period(timeframe: str) -> List[Dict]:
        """Aggregate and return usage statistics for a specified timeframe.

        Args:
            timeframe (str): One of "last7days", "last30days", "last90days", "last365days".

        Returns:
            List[Dict]: List of dictionaries, each with keys 'label' and 'value', sorted chronologically.
        """
        items = scan_table(table)
        if not items:
            # Return empty data if no records
            return []

        df = pd.DataFrame(items)
        df["Timestamp"] = pd.to_datetime(df["Timestamp"], errors="coerce")
        df = df.dropna(subset=["Timestamp"])

        now = datetime.utcnow()
        now_date = now.date()

        if timeframe.lower() == "last7days":
            return UsageLogic._agg_last7days(df, now_date)
        elif timeframe.lower() == "last30days":
            return UsageLogic._agg_last30days(df, now)
        elif timeframe.lower() == "last90days":
            return UsageLogic._agg_last90days(df, now)
        elif timeframe.lower() == "last365days":
            return UsageLogic._agg_last365days(df, now)
        else:
            raise ValueError("Unknown timeframe requested.")

    @staticmethod
    def _agg_last7days(
        df: pd.DataFrame, now_date: datetime.date
    ) -> List[Dict]:
        """Buckets usage per day for the past 7 days."""
        label_fmt = "%Y-%m-%d"
        days = [
            (now_date - timedelta(days=i)).strftime(label_fmt)
            for i in range(6, -1, -1)
        ]
        df["label"] = df["Timestamp"].dt.strftime(label_fmt)
        start = pd.Timestamp(now_date - timedelta(days=6))
        df = df[df["Timestamp"] >= start]
        usage = df.groupby("label").size().reindex(days, fill_value=0)
        return [
            {"label": day, "value": int(usage.get(day, 0))} for day in days
        ]

    @staticmethod
    def _agg_last30days(df: pd.DataFrame, now: datetime) -> List[Dict]:
        """Buckets usage by week-in-month (W1-W4) for last 30 days.- W1: days 1–7, W2: 8–14, W3: 15–21, W4: 22–end.Label: 'Wk Month' (e.g., 'W2 May')Always returns the most recent 4 buckets spanning up to 2 months."""
        # Date range: last 30 days including today
        start = (now - timedelta(days=29)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
        mask = (df["Timestamp"] >= start) & (df["Timestamp"] <= end)
        df = df[mask].copy()
        # Add week bucket per business logic
        df["Day"] = df["Timestamp"].dt.day
        df["Month"] = df["Timestamp"].dt.month
        df["Year"] = df["Timestamp"].dt.year
        df["WEEK"] = pd.cut(
            df["Day"],
            bins=[0, 7, 14, 21, 31],
            labels=["W1", "W2", "W3", "W4"],
            right=True,
            include_lowest=True,
        )
        df["label"] = (
            df["WEEK"].astype(str) + " " + df["Timestamp"].dt.strftime("%b")
        )
        if df.empty:
            labels = UsageLogic._get_calendar_week_labels(start, end)
            return [{"label": label, "value": 0} for label in labels]
        all_labels = UsageLogic._get_calendar_week_labels(start, end)
        usage = df.groupby("label").size().reindex(all_labels, fill_value=0)
        return [
            {"label": label, "value": int(usage[label])}
            for label in all_labels
        ]

    @staticmethod
    def _get_calendar_week_labels(start: datetime, end: datetime) -> List[str]:
        """Returns the 4 week labels (e.g., 'W2 May') covering the timespan between start and end.Includes only week buckets whose date range overlaps with start-end window."""
        buckets = []
        iter_months = []
        # Gather year, month pairs across span
        m = start.replace(day=1)
        while m <= end:
            iter_months.append((m.year, m.month))
            if m.month == 12:
                m = m.replace(year=m.year + 1, month=1)
            else:
                m = m.replace(month=m.month + 1)
        for year, month in iter_months:
            days_in_month = calendar.monthrange(year, month)[1]
            for week_idx, (bin_min, bin_max) in enumerate(
                [(1, 7), (8, 14), (15, 21), (22, days_in_month)], start=1
            ):
                bin_start = datetime(year, month, bin_min)
                bin_end = datetime(year, month, bin_max)
                # Overlap with period
                if bin_end < start or bin_start > end:
                    continue
                week_label = f"W{week_idx} {calendar.month_abbr[month]}"
                buckets.append(week_label)
        # Always return only the last four buckets
        return buckets[-4:]

    @staticmethod
    def _agg_last90days(df: pd.DataFrame, now: datetime) -> List[Dict]:
        """Buckets usage for last 90 days into calendar months.Label: 'Apr 2025', 'May 2025', etc.Returns: list of {label, value} sorted chronologically."""
        start = now - timedelta(days=89)
        end = now
        mask = (df["Timestamp"] >= start) & (df["Timestamp"] <= end)
        df = df[mask].copy()
        months = []
        for i in reversed(range(3)):
            month_dt = now - pd.DateOffset(months=i)
            label = month_dt.strftime("%b %Y")
            key = month_dt.strftime("%Y-%m")
            months.append({"label": label, "key": key})
        df["yearmonth"] = df["Timestamp"].dt.strftime("%Y-%m")
        usage = df.groupby("yearmonth").size()
        result = []
        for m in months:
            value = int(usage.get(m["key"], 0))
            result.append({"label": m["label"], "value": value})
        return result

    @staticmethod
    def _agg_last365days(df: pd.DataFrame, now: datetime) -> List[Dict]:
        """Buckets usage for last 365 days into calendar quarters."""
        quarter_labels, quarter_lookup = UsageLogic._get_last4quarters_labels(
            now
        )
        df["yearquarter"] = df["Timestamp"].apply(
            lambda d: f"{(d.year)}-Q{((d.month - 1)//3)+1}"
        )
        df["label"] = df["yearquarter"].map(quarter_lookup)
        start = now - timedelta(days=364)
        df = df[df["Timestamp"] >= start]
        usage = (
            df.groupby("label").size().reindex(quarter_labels, fill_value=0)
        )
        return [
            {"label": label, "value": int(usage.get(label, 0))}
            for label in quarter_labels
        ]

    @staticmethod
    def _get_last4quarters_labels(now: datetime):
        """Helper for last365days."""
        labels = []
        lookup = {}
        dt = now
        for i in reversed(range(4)):
            offset = i * 3
            q_dt = dt - pd.DateOffset(months=offset)
            quarter = ((q_dt.month - 1) // 3) + 1
            year = q_dt.year
            label = f"Q{quarter} {year}"
            key = f"{year}-Q{quarter}"
            labels.append(label)
            lookup[key] = label
        return labels, lookup
