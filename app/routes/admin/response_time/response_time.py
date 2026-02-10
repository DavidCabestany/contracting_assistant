"""This class calculates the response time over a given timeframe."""

import logging

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
        "yearly",
    ]:
        logger.error(f"Invalid timeframe: {timeframe}")
        raise HTTPException(
            status_code=400,
            detail="Invalid timeframe. Allowed values: last7days, last30days, last90days, last365days, yearly",
        )

    start_date, end_date = ResponseTimeLogic.calculate_date_range(timeframe)
    # logger.info(
    #     f"Fetching records between {start_date} and {end_date} for {timeframe}"
    # )

    records = AggregatedResponse.get_instance().get_by_date_range(start_date, end_date)
    result = ResponseTimeLogic.filter_and_calculate(records, timeframe)

    # logger.info(f"Response result for {timeframe}: {result}")

    # Always return data as a list, never null
    return {"data": result if result is not None else []}


@responseTime_router.get("/getCurrentResponseTime")
async def get_current_response_time():
    """Get the current average response time."""
    df = AggregatedResponse.get_instance().get_latest_non_zero(limit=7)
    if df is None or df.empty:
        logger.info("No recent non-zero records found")
        return {"data": []}

    # logger.info(f"Latest records: {df}")

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

    # logger.info(f"Current response: {response}")
    return response
