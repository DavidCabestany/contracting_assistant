"""This module defines API endpoints for calculating average response times.

The module uses FastAPI to create endpoints that handle the logic for:
- Retrieving the average response time over a specified timeframe.
- Retrieving the current average response time based on recent records.

Modules:
    connectors: Provides aggregated responses data.
    fastapi: Utilized to create the API router and manage HTTP exceptions.
    logger: Custom logger for logging information.
    models: Contains payload structures for API requests.
    routes.admin.response_time.response_time_logic: Contains logic for calculating response times.

Classes:
    ResponseTimeRouter: Defines the API endpoints for response time calculations.
"""

import logging

# FastAPI imports
from connectors import AggregatedResponse
from fastapi import APIRouter, HTTPException
from models import TimeframePayload
from routes.admin.response_time.response_time_logic import ResponseTimeLogic

logger = logging.getLogger(__name__)

responseTime_router = APIRouter()


@responseTime_router.post("/getAverageResponseTime")
async def get_average_response_time(payload: TimeframePayload):
    """Calculate the average response time over a given timeframe."""
    timeframe = payload.timeframe

    if timeframe not in [
        "last7days",
        "last30days",
        "last90days",
        "last365days",
    ]:
        logger.error(f"Invalid timeframe: {timeframe}")
        raise HTTPException(
            status_code=400,
            detail="Invalid timeframe. Allowed values: last7days, last30days, last90days, last365days",
        )

    start_date, end_date = ResponseTimeLogic.calculate_date_range(timeframe)
    records = AggregatedResponse.get_instance().get_by_date_range(
        start_date, end_date
    )
    result = ResponseTimeLogic.filter_and_calculate(records, timeframe)

    return {"data": result}


@responseTime_router.get("/getCurrentResponseTime")
async def get_current_response_time():
    """Get the current average response time.

    This endpoint retrieves the most recent seven records with non-zero interactions
    and calculates the average response time for these records.

    Returns:
        dict: A dictionary containing the average response time and visual bound information.
    """
    df = AggregatedResponse.get_instance().get_latest_non_zero(limit=7)
    if df is None or df.empty:
        logger.info("No recent non-zero records found")
        return {"data": []}

    logger.info(f"Latest records: {df}")

    avg_response_time = df["duration_s"].mean()

    response = {
        "data": [
            {
                "value": round(avg_response_time, 2),
                "bounds": [
                    {"value": 33.33, "color": "#C1D300"},
                    {"value": 33.33, "color": "#FBB040"},
                    {"value": 33.33, "color": "#7B234A"},
                ],
            }
        ]
    }

    return response
