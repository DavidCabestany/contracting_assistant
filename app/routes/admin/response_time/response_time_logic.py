"""A class to calculate date ranges and filter data based on timeframes for response times."""

import calendar
from datetime import datetime, timedelta

import pandas as pd
from logger import SingletonLogger

logger = SingletonLogger().get_logger()


class ResponseTimeLogic:
    """A class to calculate date ranges and filter data based on timeframes for response times.

    This class provides methods to calculate date ranges based on predefined timeframes
    and filter data to calculate average response times.
    The timeframes it supports include 'last7days', 'last30days', 'last90days', and 'last365days'.

    Methods:
    -------
    calculate_date_range(timeframe: str) -> tuple[datetime.date, datetime.date]
        Calculate the start and end dates based on the specified timeframe.

    filter_and_calculate(df: pandas.DataFrame, timeframe: str) -> list[dict]
        Filters and aggregates data according to specified timeframes: 'last7days',
        'last30days', 'last90days', and 'last365days' to compute average response times
        periodically. The method supports calculating average response times per day, week,
        month, or quarter depending on the timeframe.
    """

    @staticmethod
    def calculate_date_range(timeframe: str) -> tuple:
        """Calculate the start and end dates based on the specified timeframe."""
        now = datetime.now()

        if timeframe == "last7days":
            end_date = now.date()
            start_date = end_date - timedelta(days=7)
            return start_date, end_date

        elif timeframe == "last30days":
            end_date = now.date()
            start_date = end_date - timedelta(days=30)
            return start_date, end_date

        elif timeframe == "last90days":
            end_date = now.date()
            start_date = end_date - timedelta(days=90)
            return start_date, end_date

        elif timeframe == "last365days":
            end_date = now.date()
            start_date = end_date - timedelta(days=365)
            return start_date, end_date

        else:
            raise ValueError(f"Invalid timeframe: {timeframe}")

    @staticmethod
    def filter_and_calculate(df: pd.DataFrame, timeframe: str) -> list:
        """Filters and aggregates data based on the timeframe to calculate average response times.

        Parameters
        ----------
        df : pandas.DataFrame
            DataFrame containing timestamps and durations.

        timeframe : str
            One of 'last7days', 'last30days', 'last90days', 'last365days'.

        Returns:
        -------
        list
            A list of dictionaries with 'label' and 'value' keys representing
            average durations per day, week, month, or quarter.
        """
        if df is None or df.empty:
            logger.info(f"No data available for timeframe: {timeframe}")
            return []

        if timeframe == "last30days":
            current_date = datetime.now()
            start_date = current_date - timedelta(days=30)

            # Filter records from the last 30 days
            df = df[
                (df["timestamp"].dt.date >= start_date.date())
                & (df["timestamp"].dt.date <= current_date.date())
            ]

            # Assign week labels based on days of the month
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

            # Aggregate and compute average durations per week
            avg_per_week = (
                df.groupby("week_label")["duration_s"].mean().reset_index()
            )

            # Sort the weeks within their respective months
            avg_per_week["month"] = avg_per_week["week_label"].apply(
                lambda x: datetime.strptime(x.split()[1], "%b").month
            )
            avg_per_week["week_number"] = avg_per_week["week_label"].apply(
                lambda x: int(x.split()[0][1])
            )
            avg_per_week.sort_values(by=["month", "week_number"], inplace=True)

            # Log each week's details
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

            # Extract month and year for sorting
            avg_per_month["month"] = avg_per_month["month_year"].apply(
                lambda x: datetime.strptime(x, "%b %Y").month
            )
            avg_per_month["year"] = avg_per_month["month_year"].apply(
                lambda x: datetime.strptime(x, "%b %Y").year
            )

            # Sort months by year and month
            avg_per_month.sort_values(by=["year", "month"], inplace=True)

            # Logging the dates for each month
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

            # Sorting quarters by year and quarter number
            avg_per_quarter["year"] = avg_per_quarter["quarter_label"].apply(
                lambda x: int(x.split()[1])
            )
            avg_per_quarter["quarter"] = avg_per_quarter[
                "quarter_label"
            ].apply(lambda x: int(x[1]))
            avg_per_quarter.sort_values(by=["year", "quarter"], inplace=True)

            # Log each quarter's details
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

        # Add any additional logic you might need for other timeframes
