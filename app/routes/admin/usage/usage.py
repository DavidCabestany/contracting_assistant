"""This class get total usage by period for dashboard graph."""

import logging

from fastapi import APIRouter, HTTPException
from models import QueryCountPayload
from routes.admin.usage.usage_logic import UsageLogic

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

usage_router = APIRouter()


@usage_router.post("/getUsageByTimePeriod")
async def get_usage_by_time_period(payload: QueryCountPayload):
    """API endpoint to get total usage by period for dashboard graph."""
    if payload:
        timeframe = payload.timeframe
        try:
            result = UsageLogic.fetch_usage_by_time_period(timeframe)
            return {"data": result}
        except HTTPException as e:
            raise e
        except Exception as e:
            logger.exception(f"Error processing request: {e}")
            raise HTTPException(
                status_code=500, detail=f"Internal Server Error: {e}"
            )
