"""Data models for representing chat metadata, interactions, and search requests."""

from __future__ import annotations

from typing import Any, List

from pydantic import BaseModel, Field


class RiskClause(BaseModel):
    """Represents a single risk clause identified in a contract or document.

    Attributes:
        title (str): Short title or category of the risk clause.
        description (str): Full explanation of the risk clause.
    """

    title: str
    description: str


class RiskCategory(BaseModel):
    """Represents a HighRisksClauses,MediumRisksClauses and LowRisksClauses identified in a contract or document.

    Attributes:
       HighRisksClauses
       MediumRisksClauses
       LowRisksClauses
    """

    HighRisksClauses: List[RiskClause] = Field(default_factory=list)
    MediumRisksClauses: List[RiskClause] = Field(default_factory=list)
    LowRisksClauses: List[RiskClause] = Field(default_factory=list)


class AdditionalRisk(BaseModel):
    """Represents additional risks identified in a contract or document.

    Attributes:
        title (str): Short title or category of the risk clause.
        description (str): Full explanation of the risk clause.
    """

    title: str = ""
    description: str = ""


class RiskAssessmentAnswer(BaseModel):
    """Structured response detailing the findings of a risk assessment query."""

    ans: str
    ContractualRisks: RiskCategory = Field(default_factory=RiskCategory)
    StandardAZRisks: RiskCategory = Field(default_factory=RiskCategory)
    AdditionalPotentialRisks: List[AdditionalRisk] = Field(
        default_factory=list
    )
    similarities: List[Any] = Field(default_factory=list)
    differences: List[Any] = Field(default_factory=list)


class RiskAssessmentResponse(BaseModel):
    """Wrapper model for returning a full risk assessment answer.

    Attributes:
        answer (RiskAssessmentAnswer): Structured answer including clause breakdown and analysis.
    """

    answer: RiskAssessmentAnswer
