"""This Class uses source table and do the metric calculation and update the target table."""

import json
import logging
import traceback
from datetime import datetime, timedelta, timezone
from decimal import Decimal  # Import Decimal to handle DynamoDB number types

import boto3  # noqa: D100
from config import get_secret

REGION_ID = get_secret("REGION_ID")
CHAT_TABLE = get_secret("CHAT_TABLE")
AGGREGATED_RESPONSE_DYNAMODB = get_secret("AGGREGATE_RESPONSETIME_TABLE")

# Configure logging
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class DynamoDBResponseAggregator:  # noqa: D101
    def __init__(
        self, source_table_name, destination_table_name, region_name=REGION_ID
    ):  # noqa: D107
        """This intialize the dynamodb client."""
        self.dynamodb = boto3.resource("dynamodb", region_name=region_name)
        self.source_table = self.dynamodb.Table(source_table_name)
        self.destination_table = self.dynamodb.Table(destination_table_name)
        logger.info(
            f"DynamoDB client initialized for tables: {source_table_name}, {destination_table_name}"
        )

    def query_source_table_for_yesterday(self):
        """Query the DynamoDB table for entries from yesterday."""
        now = datetime.now(timezone.utc)
        start_date_time = (now - timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        end_date_time = start_date_time + timedelta(days=1)

        items = []
        last_evaluated_key = None

        while True:
            scan_kwargs = {
                "FilterExpression": "#ts BETWEEN :start AND :end",
                "ExpressionAttributeNames": {"#ts": "Timestamp"},
                "ExpressionAttributeValues": {
                    ":start": start_date_time.isoformat(),
                    ":end": end_date_time.isoformat(),
                },
            }

            if last_evaluated_key:
                scan_kwargs["ExclusiveStartKey"] = last_evaluated_key

            response = self.source_table.scan(**scan_kwargs)

            items.extend(response.get("Items", []))
            last_evaluated_key = response.get("LastEvaluatedKey")
            if not last_evaluated_key:
                break

        logger.debug(
            f"Fetched {len(items)} items from DynamoDB for yesterday's data."
        )
        return items

    def update_destination_table(self, items):
        """Aggregate response times and interactions, then update the destination table."""
        aggregated_data = {}

        for item in items:
            try:
                start_time = datetime.fromisoformat(item["StartTime"]).replace(
                    tzinfo=timezone.utc
                )
                end_time = datetime.fromisoformat(item["EndTime"]).replace(
                    tzinfo=timezone.utc
                )
                response_time = Decimal(
                    (end_time - start_time).total_seconds()
                )  # Convert float to Decimal

                # Convert Timestamp to YYYY-MM-DD format
                record_key = datetime.fromisoformat(
                    item["Timestamp"]
                ).strftime("%Y-%m-%d")

                if record_key not in aggregated_data:
                    aggregated_data[record_key] = {
                        "ResponseTime": Decimal(0),
                        "interactions": 0,
                    }

                aggregated_data[record_key]["ResponseTime"] += response_time
                aggregated_data[record_key][
                    "interactions"
                ] += 1  # Count occurrences of each record_key

            except KeyError as e:
                logger.warning(f"Missing key {e} in item: {item}")
            except ValueError as e:
                logger.warning(f"Date format error in item {item}: {e}")

        # Update destination table
        for record_key, data in aggregated_data.items():
            update_expression = "SET ResponseTime = :rt, Interactions = :ic"
            expression_values = {
                ":rt": data["ResponseTime"],
                ":ic": Decimal(
                    data["interactions"]
                ),  # Ensures count is stored as Decimal
            }

            self.destination_table.update_item(
                Key={"Date": record_key},  # Using formatted date as the key
                UpdateExpression=update_expression,
                ExpressionAttributeValues=expression_values,
            )

            logger.info(
                f"Updated {record_key} with ResponseTime: {data['ResponseTime']} and Interactions: {data['interactions']}"
            )

    def process_yesterday_data(self):
        """Fetch yesterday's data and update the destination table."""
        items = self.query_source_table_for_yesterday()
        if items:
            self.update_destination_table(items)


def lambda_handler(event, context):
    """AWS Lambda handler function."""
    try:
        aggregator = DynamoDBResponseAggregator(
            CHAT_TABLE, AGGREGATED_RESPONSE_DYNAMODB
        )
        aggregator.process_yesterday_data()

        return {
            "statusCode": 200,
            "body": json.dumps("Procure Response time completed successfully"),
        }
    except Exception as e:
        logger.error(f"Lambda execution failed: {str(e)}")
        error_data = {
            "Error": str(e),
            "Function": "lambda_handler",
            "Timestamp": datetime.utcnow().isoformat(),
            "StackTrace": traceback.format_exc(),
        }
        return {"statusCode": 500, "body": json.dumps(error_data)}
