"""This class for Response time graph."""

import calendar
import logging
from datetime import datetime, timedelta

import pandas as pd

logger = logging.getLogger(__name__)


class ResponseTimeLogic:
    """Logic for calculating date ranges and aggregating response time datafor generating response time graphs over various timeframes:7 days, 30 days, 90 days, and 365 days."""

    @staticmethod
    def calculate_date_range(timeframe: str) -> tuple:
        """Calculate the start and end dates based on the selected timeframe.

        Args:
            timeframe (str): Time period for aggregation
                ('last7days', 'last30days', 'last90days', 'last365days').

        Returns:
            tuple: (start_date, end_date) as datetime.date objects.

        Raises:
            ValueError: If an invalid timeframe is provided.
        """
        now = datetime.now()
        if timeframe == "last7days":
            end_date = now.date()
            start_date = end_date - timedelta(
                days=6
            )  # include today and 6 days back
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
        """Aggregate and calculate average response durations for the specified timeframe.

        Args:
            df (pd.DataFrame): DataFrame with 'timestamp' and 'duration_s' columns.
            timeframe (str): Time period to aggregate ('last7days', 'last30days', 'last90days', 'last365days').

        Returns:
            list: List of dict results for plotting graphs. Each dict contains:
                'label': str (x-axis label for the graph)
                'value': float or None (aggregated value for the period)
        """
        if df is None or df.empty:
            logger.info(f"No data available for timeframe: {timeframe}")
            return []

        logger.info(
            f"Filtering and calculating average response time for timeframe: {timeframe}, DF size: {df.shape}"
        )

        if timeframe == "last7days":
            # Group by each day (ensure no missing days)
            df["date"] = df["timestamp"].dt.date
            # Remove days with invalid duration or nan, but keep duration zero for valid calculations
            res = (
                df.groupby("date")["duration_s"]
                .mean()
                .reset_index()
                .sort_values("date", ascending=True)
            )
            # Ensure all 7 days are represented
            start_date = df["date"].min()
            end_date = df["date"].max()
            all_days = pd.date_range(start=start_date, end=end_date, freq="D")
            res = (
                res.set_index("date")
                .reindex(all_days, fill_value=float("nan"))
                .reset_index()
            )
            res.columns = ["date", "duration_s"]
            # Only last 7 days
            last_7 = res.tail(7)
            logger.info("Daily averages for last 7 days:\n%s", last_7)
            return [
                {
                    "label": row["date"].strftime("%d-%b"),
                    "value": (
                        round(row["duration_s"], 2)
                        if pd.notnull(row["duration_s"])
                        else None
                    ),
                }
                for _, row in last_7.iterrows()
            ]

        elif timeframe == "last30days":
            current_date = datetime.now()
            start_date = current_date - timedelta(days=29)
            df = df[
                (df["timestamp"].dt.date >= start_date.date())
                & (df["timestamp"].dt.date <= current_date.date())
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
            avg_per_week["month"] = avg_per_week["week_label"].apply(
                lambda x: datetime.strptime(x.split()[1], "%b").month
            )
            avg_per_week["week_number"] = avg_per_week["week_label"].apply(
                lambda x: int(x.split()[0][1])
            )
            avg_per_week.sort_values(by=["month", "week_number"], inplace=True)
            for week_label, dates in df.groupby("week_label")["timestamp"]:
                week_dates = dates.dt.date.unique()
                logger.info(
                    f"{week_label} -> Dates: {', '.join(map(str, week_dates))}"
                )
            return [
                {
                    "label": row["week_label"],
                    "value": round(row["duration_s"], 2),
                }
                for _, row in avg_per_week.iterrows()
            ]

        elif timeframe == "last90days":
            df["month_year"] = df["timestamp"].dt.strftime("%b %Y")
            avg_per_month = (
                df.groupby("month_year")["duration_s"].mean().reset_index()
            )
            avg_per_month["month"] = avg_per_month["month_year"].apply(
                lambda x: datetime.strptime(x, "%b %Y").month
            )
            avg_per_month["year"] = avg_per_month["month_year"].apply(
                lambda x: datetime.strptime(x, "%b %Y").year
            )
            avg_per_month.sort_values(by=["year", "month"], inplace=True)
            unique_months = df["month_year"].unique()
            for month in unique_months:
                month_dates = df[df["month_year"] == month][
                    "timestamp"
                ].dt.date.unique()
                logger.info(
                    f"{month} -> Dates: {', '.join(map(str, month_dates))}"
                )
            return [
                {
                    "label": row["month_year"],
                    "value": round(row["duration_s"], 2),
                }
                for _, row in avg_per_month.iterrows()
            ]

        elif timeframe == "last365days":
            df["quarter"] = df["timestamp"].dt.to_period("Q")
            df["quarter_label"] = df["quarter"].apply(
                lambda x: f"Q{x.quarter} {x.year}"
            )
            avg_per_quarter = (
                df.groupby("quarter_label")["duration_s"].mean().reset_index()
            )
            avg_per_quarter["year"] = avg_per_quarter["quarter_label"].apply(
                lambda x: int(x.split()[1])
            )
            avg_per_quarter["quarter"] = avg_per_quarter[
                "quarter_label"
            ].apply(lambda x: int(x[1]))
            avg_per_quarter.sort_values(by=["year", "quarter"], inplace=True)
            unique_quarters = df["quarter_label"].unique()
            for quarter in unique_quarters:
                quarter_dates = df[df["quarter_label"] == quarter][
                    "timestamp"
                ].dt.date.unique()
                logger.info(
                    f"{quarter} -> Dates: {', '.join(map(str, quarter_dates))}"
                )
            return [
                {
                    "label": row["quarter_label"],
                    "value": round(row["duration_s"], 2),
                }
                for _, row in avg_per_quarter.iterrows()
            ]
        else:
            logger.error(f"Unsupported timeframe: {timeframe}")
            return []
