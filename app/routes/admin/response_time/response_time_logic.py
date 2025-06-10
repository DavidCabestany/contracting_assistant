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
        """Aggregate and calculate average response durations for the specified timeframe."""
        if df is None or df.empty:
            logger.info(f"No data available for timeframe: {timeframe}")
            # Pad all expected labels with value 0
            if timeframe == "last7days":
                today = datetime.now().date()
                days = [today - timedelta(days=i) for i in reversed(range(7))]
                return [
                    {"label": d.strftime("%d-%b"), "value": 0} for d in days
                ]
            elif timeframe == "last30days":
                now = datetime.now()
                labels = ResponseTimeLogic._get_all_weeks_labels(now)
                return [{"label": lbl, "value": 0} for lbl in labels]
            elif timeframe == "last90days":
                now = datetime.now()
                labels = ResponseTimeLogic._get_all_months_labels(now, 3)
                return [{"label": lbl, "value": 0} for lbl in labels]
            elif timeframe == "last365days":
                now = datetime.now()
                labels = ResponseTimeLogic._get_all_quarters_labels(now)
                return [{"label": lbl, "value": 0} for lbl in labels]
            else:
                return []

        if timeframe == "last7days":
            df = df.copy()
            df["date"] = df["timestamp"].dt.date
            date_range = [
                datetime.now().date() - timedelta(days=i)
                for i in reversed(range(7))
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
            now = datetime.now()
            start_date = now - timedelta(days=29)
            df = df.copy()
            df = df[
                (df["timestamp"].dt.date >= start_date.date())
                & (df["timestamp"].dt.date <= now.date())
            ]

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

            df["week_label"] = df["timestamp"].apply(assign_week_label)
            avg_per_week = (
                df.groupby("week_label")["duration_s"].mean().reset_index()
            )

            week_labels = ResponseTimeLogic._get_all_weeks_labels(now)
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
            now = datetime.now()
            df = df.copy()
            df["month_year"] = df["timestamp"].dt.strftime("%b %Y")
            avg_per_month = (
                df.groupby("month_year")["duration_s"].mean().reset_index()
            )
            month_labels = ResponseTimeLogic._get_all_months_labels(now, 3)
            avg_map = {
                row["month_year"]: row["duration_s"]
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
            now = datetime.now()
            df = df.copy()
            df["quarter"] = df["timestamp"].dt.to_period("Q")
            df["quarter_label"] = df["quarter"].apply(
                lambda x: f"Q{x.quarter} {x.year}"
            )
            avg_per_quarter = (
                df.groupby("quarter_label")["duration_s"].mean().reset_index()
            )
            quarter_labels = ResponseTimeLogic._get_all_quarters_labels(now)
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
    def _get_all_weeks_labels(now):
        labels = []
        # Get the last 4 weeks covering the last 30 days
        current = now
        for i in reversed(range(4)):
            week_start = current - timedelta(days=current.day - 1)
            week_num = i + 1
            labels.append(f"W{week_num} {calendar.month_abbr[current.month]}")
            current = week_start - timedelta(days=1)
        labels.reverse()
        return labels

    @staticmethod
    def _get_all_months_labels(now, num_months):
        labels = []
        for i in reversed(range(num_months)):
            month = (now.month - i - 1) % 12 + 1
            year = now.year if now.month - i > 0 else now.year - 1
            labels.append(f"{calendar.month_abbr[month]} {year}")
        return labels

    @staticmethod
    def _get_all_quarters_labels(now):
        labels = []
        year = now.year
        current_q = (now.month - 1) // 3 + 1
        for i in reversed(range(4)):
            q = current_q - i
            q_year = year
            if q <= 0:
                q += 4
                q_year -= 1
            labels.append(f"Q{q} {q_year}")
        return labels
