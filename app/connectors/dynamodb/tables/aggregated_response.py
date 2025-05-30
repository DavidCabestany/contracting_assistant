"""This module provides functionality for interacting with the aggregated response data stored in DynamoDB. It includes classes and methods for fetching data within a specified date range and retrieving the latest non-zero interaction records.Dependencies include boto3 and pandas."""

from datetime import date, datetime, timedelta
from typing import Optional

import boto3
import pandas as pd
from botocore.config import Config
from connectors.dynamodb import DynamoDB
from logger import SingletonLogger

logger = SingletonLogger().get_logger()
AGGREGATED_RESPONSE_DYNAMODB = "azcdi-us-ops-procure-aggresponsetime-dev"
REGION_ID = "us-east-1"


class AggregatedResponse(DynamoDB):
    """A class to interact with the DynamoDB table containing aggregated response data.This class allows querying the DynamoDB table for records within a specified date range and fetching the latest non-zero interaction records. It extends the functionality of the DynamoDB connector.

    Attributes:
        table_name (str): The name of the DynamoDB table.
        region_name (str): The AWS region name.
    """

    def __init__(
        self,
        table_name: str = AGGREGATED_RESPONSE_DYNAMODB,
        region_name: str = REGION_ID,
    ):
        """Initialize the AggregatedResponse instance with the specified table and region names, setting up the DynamoDB client configuration.

        Args:
            table_name (str): The name of the DynamoDB table to interact with.
            region_name (str): The AWS region where the DynamoDB table is hosted.
        """
        super().__init__(table_name, region_name)
        boto_config = Config(
            retries={"max_attempts": 3}, max_pool_connections=50
        )
        self.dynamodb_client = boto3.client(
            "dynamodb", region_name=region_name, config=boto_config
        )

    def get_by_date_range(
        self, start_date: date, end_date: date
    ) -> Optional[pd.DataFrame]:
        """Fetch records from AGGREGATED_RESPONSE_DYNAMODB for the specified date range.

        Args:
            start_date (date): Start date of the range.
            end_date (date): End date of the range.

        Returns:
            Optional[pd.DataFrame]: DataFrame with 'timestamp' (datetime) and 'duration_s' (float), or None if empty/error.
        """
        try:
            # Generate date keys for the specified range
            date_range = pd.date_range(
                start=start_date, end=end_date, freq="D"
            )
            date_strings = [d.strftime("%Y-%m-%d") for d in date_range]

            # Batch query
            records = []
            batch_size = 100
            for i in range(0, len(date_strings), batch_size):
                batch_dates = date_strings[i : i + batch_size]
                request_items = {
                    self.table_name: {
                        "Keys": [
                            {"Date": {"S": date_str}}
                            for date_str in batch_dates
                        ]
                    }
                }
                response = self.dynamodb_client.batch_get_item(
                    RequestItems=request_items
                )
                items = response.get("Responses", {}).get(self.table_name, [])

                # Process unprocessed keys
                while (
                    "UnprocessedKeys" in response
                    and response["UnprocessedKeys"]
                ):
                    response = self.dynamodb_client.batch_get_item(
                        RequestItems=response["UnprocessedKeys"]
                    )
                    items.extend(
                        response.get("Responses", {}).get(self.table_name, [])
                    )

                # Process items
                for item in items:
                    date_str = item.get("Date", {}).get("S")
                    interactions = int(
                        item.get("Interactions", {}).get("N", "0")
                    )
                    response_time = float(
                        item.get("ResponseTime", {}).get("N", "0")
                    )
                    try:
                        date = datetime.strptime(date_str, "%Y-%m-%d").date()
                        if interactions > 0:
                            avg_response_time = response_time / interactions
                            records.append(
                                {
                                    "timestamp": pd.to_datetime(date),
                                    "duration_s": avg_response_time,
                                }
                            )
                    except (ValueError, ZeroDivisionError) as e:
                        logger.warning(
                            f"Skipping invalid record: {item}, error: {e}"
                        )
                        continue

            # Convert to DataFrame
            df = pd.DataFrame(records)
            if df.empty:
                logger.info(
                    f"No data available for range {start_date} to {end_date}"
                )
                return None

            df = df.sort_values(by="timestamp", ascending=False)
            logger.info(
                f"Fetched {len(df)} records from {start_date} to {end_date}"
            )
            return df

        except Exception as e:
            logger.error(f"Error fetching records: {e}")
            return None

    def get_latest_non_zero(
        self, limit: int = 7, max_days: int = 30
    ) -> Optional[pd.DataFrame]:
        """Fetch the latest records with non-zero interactions, up to limit, within max_days.

        Args:
            limit (int): Maximum number of records to return (default: 7).
            max_days (int): Lookback period in days (default: 30).

        Returns:
            Optional[pd.DataFrame]: DataFrame with 'timestamp' (datetime) and 'duration_s' (float), or None if empty/error.
        """
        try:
            # Date range: yesterday to max_days prior
            end_date = datetime.now().date() - timedelta(days=1)
            start_date = end_date - timedelta(days=max_days - 1)
            date_range = pd.date_range(
                start=start_date, end=end_date, freq="D"
            )
            date_strings = [d.strftime("%Y-%m-%d") for d in date_range][::-1]

            # Batch query
            records = []
            batch_size = 100
            for i in range(0, len(date_strings), batch_size):
                batch_dates = date_strings[i : i + batch_size]
                request_items = {
                    self.table_name: {
                        "Keys": [
                            {"Date": {"S": date_str}}
                            for date_str in batch_dates
                        ]
                    }
                }
                response = self.dynamodb_client.batch_get_item(
                    RequestItems=request_items
                )
                items = response.get("Responses", {}).get(self.table_name, [])

                # Process unprocessed keys
                while (
                    "UnprocessedKeys" in response
                    and response["UnprocessedKeys"]
                ):
                    response = self.dynamodb_client.batch_get_item(
                        RequestItems=response["UnprocessedKeys"]
                    )
                    items.extend(
                        response.get("Responses", {}).get(self.table_name, [])
                    )

                # Sort items by date (latest first)
                items.sort(
                    key=lambda x: x.get("Date", {}).get("S", ""), reverse=True
                )

                # Process items
                for item in items:
                    date_str = item.get("Date", {}).get("S")
                    interactions = int(
                        item.get("Interactions", {}).get("N", "0")
                    )
                    response_time = float(
                        item.get("ResponseTime", {}).get("N", "0")
                    )
                    try:
                        date = datetime.strptime(date_str, "%Y-%m-%d").date()
                        if interactions > 0:
                            avg_response_time = response_time / interactions
                            records.append(
                                {
                                    "timestamp": pd.to_datetime(date),
                                    "duration_s": avg_response_time,
                                }
                            )
                        if len(records) >= limit:
                            break
                    except (ValueError, ZeroDivisionError) as e:
                        logger.warning(
                            f"Skipping invalid record: {item}, error: {e}"
                        )
                        continue
                    if len(records) >= limit:
                        break

            # Convert to DataFrame
            df = pd.DataFrame(records)
            if df.empty:
                logger.info(f"No data available for latest {max_days} days")
                return None

            df = df.sort_values(by="timestamp", ascending=False)
            logger.info(
                f"Fetched {len(df)} records for latest {max_days} days"
            )
            return df

        except Exception as e:
            logger.error(f"Error fetching latest records: {e}")
            return None
