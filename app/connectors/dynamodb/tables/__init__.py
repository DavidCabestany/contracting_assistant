"""This module provides the AggregatedResponse class.

The AggregatedResponse class is designed to handle the aggregation of responses
from various sources and provide a unified response format.

Classes:
    AggregatedResponse: A class for aggregating and handling responses.

Example usage:
    from .aggregated_response import AggregatedResponse
    response = AggregatedResponse(data)
"""

from .aggregated_response import AggregatedResponse

__all__ = [
    "AggregatedResponse",
]
