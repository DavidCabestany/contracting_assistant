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
            return UsageLogic._agg_last365days_monthly(df, now)
        elif timeframe.lower() == "yearly":
            return UsageLogic._agg_yearly(df, now)
        else:
            raise ValueError("Unknown timeframe requested.")

    @staticmethod
    def _agg_last7days(df: pd.DataFrame, now_date: datetime.date) -> List[Dict]:
        """Buckets usage per day for the past 7 days. Label as 'DD-MMM'."""
        iso_fmt = "%Y-%m-%d"
        display_fmt = "%d-%b"

        days = [(now_date - timedelta(days=i)) for i in range(6, -1, -1)]
        iso_days = [d.strftime(iso_fmt) for d in days]
        display_days = [d.strftime(display_fmt) for d in days]

        # Group by iso format (YYYY-MM-DD, as before)
        df["group_label"] = df["Timestamp"].dt.strftime(iso_fmt)
        start = pd.Timestamp(now_date - timedelta(days=6))
        df = df[df["Timestamp"] >= start]
        usage = df.groupby("group_label").size().reindex(iso_days, fill_value=0)

        # Output using display_fmt in 'label'
        return [{"label": display_days[i], "value": int(usage.get(iso_days[i], 0))} for i in range(7)]

    @staticmethod
    def _agg_last30days(df: pd.DataFrame, now: datetime) -> List[Dict]:
        """Bucket usage by week-in-month (W1-W4 per calendar month, e.g., 'W2 Jun')for all week-buckets that overlap the last 30 days.This matches the revised /getFeedbackTrend grouping logic."""
        start = (now - timedelta(days=29)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
        mask = (df["Timestamp"] >= start) & (df["Timestamp"] <= end)
        df = df[mask].copy()
        if df.empty:
            # Create label list below and just return zeros for each bucket
            months = []
            m = start.replace(day=1)
            while m <= end:
                months.append((m.year, m.month))
                if m.month == 12:
                    m = m.replace(year=m.year + 1, month=1)
                else:
                    m = m.replace(month=m.month + 1)
            labels = []
            for year, month in months:
                days_in_month = calendar.monthrange(year, month)[1]
                for widx, (low, high) in enumerate([(1, 7), (8, 14), (15, 21), (22, days_in_month)], 1):
                    wk_start = datetime(year, month, low, tzinfo=start.tzinfo)
                    wk_end = datetime(year, month, high, tzinfo=start.tzinfo)
                    if wk_end < start or wk_start > end:
                        continue
                    label = f"W{widx} {calendar.month_abbr[month]}"
                    labels.append(label)
            labels = sorted(set(labels), key=lambda x: (x.split()[1], int(x[1])))
            return [{"label": label, "value": 0} for label in labels]

        # Compute week bucket for each row
        def week_label_from_row(ts):
            day = ts.day
            month_abbr = ts.strftime("%b")
            if 1 <= day <= 7:
                week_idx = 1
            elif 8 <= day <= 14:
                week_idx = 2
            elif 15 <= day <= 21:
                week_idx = 3
            else:
                week_idx = 4
            return f"W{week_idx} {month_abbr}"

        df["label"] = df["Timestamp"].apply(week_label_from_row)

        # Get all relevant week-buckets (see which overlap window)
        months = []
        m = start.replace(day=1)
        while m <= end:
            months.append((m.year, m.month))
            if m.month == 12:
                m = m.replace(year=m.year + 1, month=1)
            else:
                m = m.replace(month=m.month + 1)
        week_buckets = []
        for year, month in months:
            days_in_month = calendar.monthrange(year, month)[1]
            for widx, (low, high) in enumerate([(1, 7), (8, 14), (15, 21), (22, days_in_month)], 1):
                wk_start = datetime(year, month, low, tzinfo=start.tzinfo)
                wk_end = datetime(year, month, high, tzinfo=start.tzinfo)
                if wk_end < start or wk_start > end:
                    continue
                label = f"W{widx} {calendar.month_abbr[month]}"
                week_buckets.append(label)
        # Remove duplicates, keep correct order
        week_buckets = list(dict.fromkeys(week_buckets))

        usage = df.groupby("label").size().reindex(week_buckets, fill_value=0)
        return [{"label": label, "value": int(usage[label])} for label in week_buckets]

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
            for week_idx, (bin_min, bin_max) in enumerate([(1, 7), (8, 14), (15, 21), (22, days_in_month)], start=1):
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
        """Bucket usage for last 90 days into calendar months (e.g., 'Apr 2025', 'May 2025'),including all calendar months overlapped by the window, even partial."""
        start = (now - timedelta(days=89)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
        mask = (df["Timestamp"] >= start) & (df["Timestamp"] <= end)
        df = df[mask].copy()

        # Find all months overlapped by the window
        months = []
        m = start.replace(day=1)
        while m <= end:
            months.append((m.year, m.month))
            if m.month == 12:
                m = m.replace(year=m.year + 1, month=1)
            else:
                m = m.replace(month=m.month + 1)
        month_labels = [f"{calendar.month_abbr[month]} {year}" for (year, month) in months]

        def month_label_from_ts(ts):
            return f"{ts.strftime('%b')} {ts.year}"

        if not df.empty:
            df["label"] = df["Timestamp"].apply(month_label_from_ts)
            usage = df.groupby("label").size().reindex(month_labels, fill_value=0)
        else:
            usage = pd.Series([0] * len(month_labels), index=month_labels)
        return [{"label": label, "value": int(usage[label])} for label in month_labels]

    @staticmethod
    def _agg_last365days(df: pd.DataFrame, now: datetime) -> List[Dict]:
        """Bucket usage for last 365 days into calendar quarters (e.g., 'Q2 2025'),including any quarter that overlaps with the window."""
        start = (now - timedelta(days=364)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
        mask = (df["Timestamp"] >= start) & (df["Timestamp"] <= end)
        df = df[mask].copy()

        # Find all quarters overlapping with the window.
        quarters = []
        q_start = datetime(start.year, ((start.month - 1) // 3) * 3 + 1, 1)
        while q_start <= end:
            quarter = ((q_start.month - 1) // 3) + 1
            quarters.append((q_start.year, quarter, q_start.month))
            # advance by 3 months
            if q_start.month >= 10:
                q_start = q_start.replace(year=q_start.year + 1, month=1)
            else:
                q_start = q_start.replace(month=q_start.month + 3)
        quarter_labels = [f"Q{q} {y}" for y, q, _ in quarters]

        def quarter_label_from_ts(ts):
            q = ((ts.month - 1) // 3) + 1
            return f"Q{q} {ts.year}"

        if not df.empty:
            df["label"] = df["Timestamp"].apply(quarter_label_from_ts)
            usage = df.groupby("label").size().reindex(quarter_labels, fill_value=0)
        else:
            usage = pd.Series([0] * len(quarter_labels), index=quarter_labels)
        return [{"label": label, "value": int(usage[label])} for label in quarter_labels]

    @staticmethod
    def _agg_last365days_monthly(df: pd.DataFrame, now: datetime) -> List[Dict]:
        """Bucket usage for last 365 days into calendar months (e.g., 'Apr 2025', 'May 2025')."""
        start = (now - timedelta(days=364)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
        mask = (df["Timestamp"] >= start) & (df["Timestamp"] <= end)
        df = df[mask].copy()

        # Find all months overlapped by the window
        months = []
        m = start.replace(day=1)
        while m <= end:
            months.append((m.year, m.month))
            if m.month == 12:
                m = m.replace(year=m.year + 1, month=1)
            else:
                m = m.replace(month=m.month + 1)
        month_labels = [f"{calendar.month_abbr[month]} {year}" for (year, month) in months]

        def month_label_from_ts(ts):
            return f"{ts.strftime('%b')} {ts.year}"

        if not df.empty:
            df["label"] = df["Timestamp"].apply(month_label_from_ts)
            usage = df.groupby("label").size().reindex(month_labels, fill_value=0)
        else:
            usage = pd.Series([0] * len(month_labels), index=month_labels)
        return [{"label": label, "value": int(usage[label])} for label in month_labels]

    @staticmethod
    def _agg_yearly(df: pd.DataFrame, now: datetime) -> List[Dict]:
        """Bucket usage by year for all years present in the last 365 days window."""
        start = (now - timedelta(days=364)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
        mask = (df["Timestamp"] >= start) & (df["Timestamp"] <= end)
        df = df[mask].copy()

        years = sorted(df["Timestamp"].dt.year.unique())
        if not years:
            # If no data, show current and previous year
            years = [start.year, end.year]
        usage = df.groupby(df["Timestamp"].dt.year).size().reindex(years, fill_value=0)
        return [{"label": str(year), "value": int(usage[year])} for year in years]

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
