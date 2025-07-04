"""This class for Response time graph."""

import calendar
import logging
from datetime import datetime, timedelta

import pandas as pd

logger = logging.getLogger(__name__)


class ResponseTimeLogic:
    """Logic for calculating date ranges and aggregating response time data for generating response time graphs over various timeframes: 7 days, 30 days, 90 days, and 365 days."""

    @staticmethod
    def calculate_date_range(timeframe: str) -> tuple:
        """Calculate the start and end dates based on the selected timeframe."""
        now = datetime.now()
        if timeframe == "last7days":
            end_date = now.date()
            start_date = end_date - timedelta(days=6)
            return start_date, end_date
        elif timeframe == "last30days":
            end_date = now.date()
            start_date = end_date - timedelta(days=29)
            return start_date, end_date
        elif timeframe == "last90days":
            end_date = now.date()
            start_date = end_date - timedelta(days=89)
            return start_date, end_date
        elif timeframe == "last365days":
            end_date = now.date()
            start_date = end_date - timedelta(days=364)
            return start_date, end_date
        else:
            raise ValueError(f"Invalid timeframe: {timeframe}")

    @staticmethod
    def filter_and_calculate(df: pd.DataFrame, timeframe: str) -> list:
        """Aggregate and calculate average response durations for the specified timeframe, using /getFeedbackTrend-like time buckets."""
        if df is None or df.empty:
            logger.info(f"No data available for timeframe: {timeframe}")
            now = datetime.now()
            if timeframe == "last7days":
                days = [
                    now.date() - timedelta(days=i) for i in reversed(range(7))
                ]
                return [
                    {"label": d.strftime("%d-%b"), "value": 0} for d in days
                ]
            elif timeframe == "last30days":
                labels = ResponseTimeLogic._trend_week_labels(now)
                return [{"label": lbl, "value": 0} for lbl in labels]
            elif timeframe == "last90days":
                labels = ResponseTimeLogic._trend_month_labels(now)
                return [{"label": lbl, "value": 0} for lbl in labels]
            elif timeframe == "last365days":
                labels = ResponseTimeLogic._trend_quarter_labels(now)
                return [{"label": lbl, "value": 0} for lbl in labels]
            else:
                return []

        now = datetime.now()

        if timeframe == "last7days":
            df = df.copy()
            df["date"] = df["timestamp"].dt.date
            # Oldest (today-7) to newest (today-1), left to right
            date_range = [
                (now.date() - timedelta(days=i)) for i in range(7, 0, -1)
            ]
            res = (
                df.groupby("date")["duration_s"]
                .mean()
                .reset_index()
                .sort_values("date", ascending=True)
            )
            avg_map = {
                row["date"]: row["duration_s"] for _, row in res.iterrows()
            }
            return [
                {
                    "label": d.strftime("%d-%b"),
                    "value": (
                        round(avg_map[d], 2)
                        if d in avg_map and pd.notnull(avg_map[d])
                        else 0
                    ),
                }
                for d in date_range
            ]

        elif timeframe == "last30days":
            now_ = now
            start = now_ - timedelta(days=29)
            df = df.copy()
            df = df[
                (df["timestamp"].dt.date >= start.date())
                & (df["timestamp"].dt.date <= now_.date())
            ]

            # Assign week label
            def assign_week_label(date):
                day = date.day
                month = calendar.month_abbr[date.month]
                if 1 <= day <= 7:
                    return f"W1 {month}"
                elif 8 <= day <= 14:
                    return f"W2 {month}"
                elif 15 <= day <= 21:
                    return f"W3 {month}"
                else:
                    return f"W4 {month}"

            df["week_label"] = df["timestamp"].dt.date.apply(
                lambda dt: assign_week_label(dt)
            )
            avg_per_week = (
                df.groupby("week_label")["duration_s"].mean().reset_index()
            )
            week_labels = ResponseTimeLogic._trend_week_labels(now_)
            avg_map = {
                row["week_label"]: row["duration_s"]
                for _, row in avg_per_week.iterrows()
            }
            return [
                {
                    "label": label,
                    "value": (
                        round(avg_map[label], 2)
                        if label in avg_map and pd.notnull(avg_map[label])
                        else 0
                    ),
                }
                for label in week_labels
            ]

        elif timeframe == "last90days":
            now_ = now
            start = now_ - timedelta(days=89)
            df = df.copy()
            df = df[
                (df["timestamp"].dt.date >= start.date())
                & (df["timestamp"].dt.date <= now_.date())
            ]
            df["month_label"] = df["timestamp"].dt.strftime("%b %Y")
            avg_per_month = (
                df.groupby("month_label")["duration_s"].mean().reset_index()
            )
            month_labels = ResponseTimeLogic._trend_month_labels(now_)
            avg_map = {
                row["month_label"]: row["duration_s"]
                for _, row in avg_per_month.iterrows()
            }
            return [
                {
                    "label": label,
                    "value": (
                        round(avg_map[label], 2)
                        if label in avg_map and pd.notnull(avg_map[label])
                        else 0
                    ),
                }
                for label in month_labels
            ]

        elif timeframe == "last365days":
            now_ = now
            start = now_ - timedelta(days=364)
            df = df.copy()
            df = df[
                (df["timestamp"].dt.date >= start.date())
                & (df["timestamp"].dt.date <= now_.date())
            ]

            # Quarter as "Qn YYYY"
            def quarter_label(dt):
                q = ((dt.month - 1) // 3) + 1
                return f"Q{q} {dt.year}"

            df["quarter_label"] = df["timestamp"].dt.date.apply(
                lambda d: quarter_label(d)
            )
            avg_per_quarter = (
                df.groupby("quarter_label")["duration_s"].mean().reset_index()
            )
            quarter_labels = ResponseTimeLogic._trend_quarter_labels(now_)
            avg_map = {
                row["quarter_label"]: row["duration_s"]
                for _, row in avg_per_quarter.iterrows()
            }
            return [
                {
                    "label": label,
                    "value": (
                        round(avg_map[label], 2)
                        if label in avg_map and pd.notnull(avg_map[label])
                        else 0
                    ),
                }
                for label in quarter_labels
            ]

        else:
            logger.error(f"Unsupported timeframe: {timeframe}")
            return []

    @staticmethod
    def _trend_week_labels(now):
        # Compute all week-in-month ("Wn Mon") that have any overlap with the last 30 days
        start = now - timedelta(days=29)
        end = now
        months = []
        m = start.replace(day=1)
        while m <= end:
            months.append((m.year, m.month))
            if m.month == 12:
                m = m.replace(year=m.year + 1, month=1)
            else:
                m = m.replace(month=m.month + 1)
        week_labels = []
        for year, month in months:
            days_in_month = calendar.monthrange(year, month)[1]
            for widx, (low, high) in enumerate(
                [(1, 7), (8, 14), (15, 21), (22, days_in_month)], 1
            ):
                wk_start = datetime(year, month, low)
                wk_end = datetime(year, month, high)
                if (
                    wk_end.date() < start.date()
                    or wk_start.date() > end.date()
                ):
                    continue
                label = f"W{widx} {calendar.month_abbr[month]}"
                week_labels.append(label)
        # Remove dups, preserve order
        week_labels = list(dict.fromkeys(week_labels))
        return week_labels

    @staticmethod
    def _trend_month_labels(now):
        start = now - timedelta(days=89)
        end = now
        months = []
        m = start.replace(day=1)
        while m <= end:
            months.append(f"{calendar.month_abbr[m.month]} {m.year}")
            if m.month == 12:
                m = m.replace(year=m.year + 1, month=1)
            else:
                m = m.replace(month=m.month + 1)
        return months

    @staticmethod
    def _trend_quarter_labels(now):
        start = now - timedelta(days=364)
        end = now
        quarters = []
        # Start from the first overlapping quarter
        m = datetime(start.year, ((start.month - 1) // 3) * 3 + 1, 1)
        while m <= end:
            q = ((m.month - 1) // 3) + 1
            quarters.append(f"Q{q} {m.year}")
            # advance by 3 months
            if m.month >= 10:
                m = m.replace(year=m.year + 1, month=1)
            else:
                m = m.replace(month=m.month + 3)
        return quarters
