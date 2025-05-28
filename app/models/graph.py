"""This module defines data models using Pydantic for handling various user analytics features,such as query statistics, feedback data, site usage, and filter options. These models help validate and structure the payloads and responses for related API requests and responses."""

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
        isPositive (bool): Indicates if the feedback is positive.
        timeframe (Literal): The timeframe for the feedback data - 'lastYear', 'last30days', or 'lastQuarter'.
    """

    isPositive: bool
    timeframe: Literal["lastYear", "last30days", "lastQuarter"]


class FeedbackDataItem(BaseModel):
    """Model for individual feedback data item.

    Attributes:
        name (str): Name of the feedback item.
        value (float): Value or score of the feedback item.
    """

    name: str
    value: float


class PctData(BaseModel):
    """Model representing feedback percentage data.

    Attributes:
        countFeedback (int): Number of feedback entries.
        pctFeedback (str): Percentage of feedback.
        feedback_pct_change (int): Change in feedback percentage.
    """

    countFeedback: int
    pctFeedback: str
    feedback_pct_change: int


class FeedbackDataResponse(BaseModel):
    """Model for feedback data response.

    Attributes:
        data (List[FeedbackDataItem]): List of feedback data items.
        pct_data (PctData): Feedback percentage data.
        isPositive (bool): Indicates if the feedback is positive.
    """

    data: List[FeedbackDataItem]
    pct_data: PctData
    isPositive: bool


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

    timeframe: Literal["lastYear", "last30days", "lastQuarter"]


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
