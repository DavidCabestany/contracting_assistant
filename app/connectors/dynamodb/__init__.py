"""This module provides access to the base functionalities of DynamoDB and includes aggregated response handling.

Modules:
- base: Contains the definition for the DynamoDB class.
- tables: Includes data structures like AggregatedResponse.

Exports:
- DynamoDB: The class to interface with DynamoDB.
- AggregatedResponse: Data structure for aggregated responses.
"""

from .base import DynamoDB
from .tables import (
    AggregatedResponse,
)

__all__ = [
    "DynamoDB",
    "AggregatedResponse",
]
