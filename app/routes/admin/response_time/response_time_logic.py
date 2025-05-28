"""This module defines the ResponseTimeLogic class which offers functionality to compute date ranges and filter data for calculating average response times based on specified timeframes.

Import classes and methods:
- calendar: Provides calendar-related functions and classes for date manipulation.
- datetime, timedelta: Used for handling dates and time calculation.
- pandas: Used for data manipulation via DataFrame.
- SingletonLogger: Custom logger for handling log operations.

Classes:
- ResponseTimeLogic: Contains methods to calculate date ranges and filter data.
"""

import calendar
from datetime import datetime, timedelta

import pandas as pd
from logger import SingletonLogger

logger = SingletonLogger().get_logger()


class ResponseTimeLogic:
    """A class to calculate date ranges and filter data based on timeframes for response times.

    This class provides methods to calculate date ranges based on predefined timeframes and filter data to calculate
    average response times. The timeframes it supports include 'last30days', 'lastQuarter', and 'lastYear'.

    Methods:
    --------
    calculate_date_range(timeframe: str) -> tuple[datetime.date, datetime.date]
        Calculate the start and end dates based on the specified timeframe.

    filter_and_calculate(df: pandas.DataFrame, timeframe: str) -> List[dict]
        Filters records based on the timeframe and calculates the average response time.
    """

    @staticmethod
    def calculate_date_range(
        timeframe: str,
    ) -> tuple[datetime.date, datetime.date]:
        """Calculate the start and end dates based on the specified timeframe.

        Args:
            timeframe (str): One of 'last30days', 'lastQuarter', 'lastYear'.

        Returns:
            tuple[datetime.date, datetime.date]: A tuple containing start_date and end_date.

        Raises:
            ValueError: If the timeframe is not one of the allowed values.
        """
        now = datetime.now()
        if timeframe == "last30days":
            end_date = now.date()
            start_date = end_date - timedelta(days=30)
            return start_date, end_date

        elif timeframe == "lastQuarter":
            current_year = now.year
            current_month = now.month

            if current_month in [1, 2, 3]:
                last_quarter = "Q4"
                quarter_year = current_year - 1
                start_month, end_month = 10, 12
            elif current_month in [4, 5, 6]:
                last_quarter = "Q1"
                quarter_year = current_year
                start_month, end_month = 1, 3
            elif current_month in [7, 8, 9]:
                last_quarter = "Q2"
                quarter_year = current_year
                start_month, end_month = 4, 6
            else:
                last_quarter = "Q3"
                quarter_year = current_year
                start_month, end_month = 7, 9

            start_date = datetime(quarter_year, start_month, 1).date()
            end_date = datetime(
                quarter_year,
                end_month,
                calendar.monthrange(quarter_year, end_month)[1],
            ).date()

            logger.info(
                f"Processing {last_quarter} ({start_date} to {end_date})"
            )
            return start_date, end_date

        elif timeframe == "lastYear":
            end_date = (
                datetime(now.year, now.month, 1) - timedelta(days=1)
            ).date()
            start_date = end_date.replace(year=end_date.year - 1)
            logger.info(f"Calculating from {start_date} to {end_date}")
            return start_date, end_date

        else:
            raise ValueError(
                f"Invalid timeframe: {timeframe}. Allowed values: last30days, lastQuarter, lastYear"
            )

    @staticmethod
    def filter_and_calculate(df, timeframe):
        """Filters records based on the timeframe and calculates the average response time.

        Args:
            df (pandas.DataFrame): DataFrame containing timestamps and durations.
            timeframe (str): One of 'last30days', 'lastQuarter', 'lastYear'.

        Returns:
            List[dict]: A list of dictionaries with 'label' and 'value' keys.

        Note:
            - For 'last30days', it returns the average duration per day.
            - For 'lastQuarter', the average per month in the quarter.
            - For 'lastYear', monthly averages over the year.
        """
        now = datetime.now()
        logger.info(f"current time is: {now}")

        if df is None:
            logger.info(f"No data available for timeframe: {timeframe}")
            return []

        if timeframe == "last30days":
            df["date"] = df["timestamp"].dt.date
            logger.info(f"unique date: {len(df['date'].unique())}")
            avg_per_day = df.groupby("date")["duration_s"].mean().reset_index()
            return [
                {
                    "label": str(row["date"]),
                    "value": round(row["duration_s"], 2),
                }
                for _, row in avg_per_day.iterrows()
            ]

        elif timeframe == "lastQuarter":
            current_year = now.year
            current_month = now.month

            if current_month in [1, 2, 3]:
                last_quarter = "Q4"
                quarter_year = current_year - 1
                start_month, end_month = 10, 12
            elif current_month in [4, 5, 6]:
                last_quarter = "Q1"
                quarter_year = current_year
                start_month, end_month = 1, 3
            elif current_month in [7, 8, 9]:
                last_quarter = "Q2"
                quarter_year = current_year
                start_month, end_month = 4, 6
            else:
                last_quarter = "Q3"
                quarter_year = current_year
                start_month, end_month = 7, 9

            month_names = {
                10: "Oct",
                11: "Nov",
                12: "Dec",
                1: "Jan",
                2: "Feb",
                3: "Mar",
                4: "Apr",
                5: "May",
                6: "Jun",
                7: "Jul",
                8: "Aug",
                9: "Sep",
            }
            quarter_averages = []

            for month in range(start_month, end_month + 1):
                month_start = datetime(quarter_year, month, 1)
                month_end = datetime(
                    quarter_year,
                    month,
                    calendar.monthrange(quarter_year, month)[1],
                )

                month_df = df[
                    (df["timestamp"] >= month_start)
                    & (df["timestamp"] <= month_end)
                ]

                avg_duration = (
                    month_df["duration_s"].mean() if not month_df.empty else 0
                )

                quarter_averages.append(
                    {
                        "label": f"{month_names[month]} - {last_quarter} {quarter_year}",
                        "value": round(avg_duration, 2),
                    }
                )

            return quarter_averages

        elif timeframe == "lastYear":
            logger.info(f"Filtered dataframe for last 12 months: {df}")

            df["month"] = df["timestamp"].dt.strftime("%b %Y")

            end_date = (
                datetime(now.year, now.month, 1) - timedelta(days=1)
            ).date()
            start_date = end_date.replace(year=end_date.year - 1)
            expected_months = (
                pd.date_range(start=start_date, end=end_date, freq="MS")
                .strftime("%b %Y")
                .tolist()
            )

            avg_per_month = (
                df.groupby("month")["duration_s"].mean().reset_index()
            )

            all_months_df = pd.DataFrame({"month": expected_months})
            final_df = all_months_df.merge(
                avg_per_month, on="month", how="left"
            ).fillna(0)

            last_year_avg = [
                {"label": row["month"], "value": round(row["duration_s"], 2)}
                for _, row in final_df.iterrows()
            ]

            return last_year_avg
