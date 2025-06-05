"""This module defines data models using Pydantic for handling various user analytics features,such as query statistics, feedback data, site usage, and filter options. These models help validate and structure the payloads and responses for related API requests and responses."""

from __future__ import annotations

from typing import List, Literal

from pydantic import BaseModel

from .site import Language


class UserQueryStatsPayload(BaseModel):
    """Model for user query statistics payload.

    Attributes:
        sites (str): The site or sites for which the statistics are requested.
    """

    sites: str


class TimeframePayload(BaseModel):
    """Model for timeframe payload.

    Attributes:
        timeframe (str): The timeframe identifier.
    """

    timeframe: str


class CurrentResponseTime(BaseModel):
    """Model representing current response time.

    Attributes:
        current_response_time (int): The response time for current queries in milliseconds.
    """

    current_response_time: int


class QueryCountPayload(BaseModel):
    """Model for query count payload.

    Attributes:
        managers (List[str]): List of manager identifiers.
        sites (List[str]): List of site identifiers.
        timeframe (Literal): Specifies the timeframe for the query count - 'weekly', 'monthly', 'quarterly', or 'yearly'.
    """

    managers: List[str]
    sites: List[str]
    timeframe: Literal["weekly", "monthly", "quarterly", "yearly"]


class FeedbackDataRequest(BaseModel):
    """Model for feedback data request.

    Attributes:
        isPositive (bool): Indicates if the feedback type filter is positive (legacy field, not used in new logic).
        timeframe (str): The timeframe for the feedback data ('last7days', 'last30days', etc.).
    """

    timeframe: str


class FeedbackDataItem(BaseModel):
    """Represents an individual feedback type and its percentage.

    Attributes:
        name (str): Type of feedback ("positive", "negative", "no_feedback").
        value (float): Percentage of this feedback type in the total.
    """

    name: str
    value: float


class PctData(BaseModel):
    """Provides detailed feedback count and percentage data across all feedback types.

    Attributes:
        positiveCountFeedback (int): Total positive feedback count.
        negativeCountFeedback (int): Total negative feedback count.
        noCountFeedback (int): Total count of 'no feedback'.
        positiveCountFeedback_pct (float): Percentage of positive feedback.
        negativeCountFeedback_pct (float): Percentage of negative feedback.
        noCountFeedback_pct (float): Percentage of 'no feedback'.
        positive_pct_change (int): Change in positive feedback vs previous period (%).
        negative_pct_change (int): Change in negative feedback vs previous period (%).
        no_feedback_pct_change (int): Change in 'no feedback' vs previous period (%).
    """

    positiveCountFeedback: int
    negativeCountFeedback: int
    noCountFeedback: int
    positiveCountFeedback_pct: float
    negativeCountFeedback_pct: float
    noCountFeedback_pct: float
    positive_pct_change: int
    negative_pct_change: int
    no_feedback_pct_change: int


class FeedbackDataResponse(BaseModel):
    """The API response model for feedback data.

    Attributes:
        data (List[FeedbackDataItem]): List of feedback percentages per type.
        pct_data (PctData): Summarized count, percentage, and period-over-period changes.
        isPositive (bool): Indicates if positive filter was requested (for compatibility).
    """

    data: List[FeedbackDataItem]
    pct_data: PctData


class FeedbackDetailDropdown(BaseModel):
    """Model for feedback detail dropdown options.

    Attributes:
        label (str): Label for the dropdown option.
        value (str): Value of the dropdown option.
    """

    label: str
    value: str


class FeedbackFiltersResponse(BaseModel):
    """Model for feedback filters response.

    Attributes:
        feedbackDetailDropdownPositive (List[FeedbackDetailDropdown]): Options for positive feedback detail dropdown.
        feedbackDetailDropdownNegative (List[FeedbackDetailDropdown]): Options for negative feedback detail dropdown.
        feedbackTimeframeDropdown (List[FeedbackDetailDropdown]): Options for feedback timeframe dropdown.
        trendTimeframeDropdown (List[FeedbackDetailDropdown]): Options for trend timeframe dropdown.
    """

    feedbackDetailDropdownPositive: List[FeedbackDetailDropdown]
    feedbackDetailDropdownNegative: List[FeedbackDetailDropdown]
    feedbackTimeframeDropdown: List[FeedbackDetailDropdown]
    trendTimeframeDropdown: List[FeedbackDetailDropdown]


class FeedbackTrendRequest(BaseModel):
    """Model for feedback trend request.

    Attributes:
        timeframe (Literal): The timeframe for the feedback trend - 'lastYear', 'last30days', or 'lastQuarter'.
    """

    timeframe: Literal["last7days", "last30days", "last90days", "last365days"]


class TrendData(BaseModel):
    """Model for trend data.

    Attributes:
        label (str): Label for the trend data.
        value (str): Value of the trend data.
        negative (int): Number of negative entries.
        positive (int): Number of positive entries.
    """

    label: str
    value: str
    negative: int
    positive: int


class FeedbackTrendResponse(BaseModel):
    """Model for feedback trend response.

    Attributes:
        data (List[TrendData]): List of trend data items.
    """

    data: List[TrendData]


class SiteUsageRequest(BaseModel):
    """Model for site usage request.

    Attributes:
        timeframe (Literal): The requested timeframe for site usage - 'monthly', 'quarterly', 'yearly', or 'weekly'.
    """

    timeframe: Literal["monthly", "quarterly", "yearly", "weekly"]


class SiteUsageData(BaseModel):
    """Model for site usage data.

    Attributes:
        label (str): Label for the site usage data.
        queries (int): Number of queries for the site.
    """

    label: str
    queries: int


class SiteUsageResponse(BaseModel):
    """Model for site usage response.

    Attributes:
        data (List[SiteUsageData]): List of site usage data items.
    """

    data: List[SiteUsageData]


class FilterOptionsRequest(BaseModel):
    """Model for filter options request.

    Attributes:
        language (Language): The language for the filter options.
    """

    language: Language
