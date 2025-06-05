"""Performs a paginated table scan on a DynamoDB table."""

import logging

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException

logger = logging.getLogger(__name__)


def scan_table(
    table,
    projection_expression=None,
    filter_expression=None,
    expression_attribute_names=None,
    expression_attribute_values=None,
    error_handling="return_none",
):
    """Performs a paginated table scan on a DynamoDB table.

    Args:
        table: boto3 DynamoDB Table resource
        projection_expression (str): Attributes to retrieve (e.g., "workerData")
        filter_expression (str): Filter condition for scan (e.g., "#dt BETWEEN :start AND :end")
        expression_attribute_names (dict): Aliases for reserved keywords (e.g., {"#dt": "Date"})
        expression_attribute_values (dict): Values for filter expression (e.g., {":start": "2025-01-01"})
        error_handling (str): "return_none", "raise_exception", or "return_empty"

    Returns:
        List of items, or None/empty list based on error_handling

    Raises:
        HTTPException: If error_handling="raise_exception" and a DynamoDB error occurs
    """
    items = []
    scan_kwargs = {}

    if projection_expression:
        scan_kwargs["ProjectionExpression"] = projection_expression
    if filter_expression:
        scan_kwargs["FilterExpression"] = filter_expression
    if expression_attribute_names:
        scan_kwargs["ExpressionAttributeNames"] = expression_attribute_names
    if expression_attribute_values:
        scan_kwargs["ExpressionAttributeValues"] = expression_attribute_values

    try:
        response = table.scan(**scan_kwargs)
        items.extend(response.get("Items", []))

        while "LastEvaluatedKey" in response:
            scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
            response = table.scan(**scan_kwargs)
            items.extend(response.get("Items", []))

        return items

    except (BotoCoreError, ClientError) as e:
        logger.error(f"Error scanning table {table.name}: {e}")
        if error_handling == "return_none":
            return None
        elif error_handling == "raise_exception":
            raise HTTPException(
                status_code=500, detail=f"Failed to scan table: {e}"
            )
        else:  # return_empty
            return []
