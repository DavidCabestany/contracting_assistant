from __future__ import annotations

from typing import Optional, list

from pydantic import BaseModel


class RiskClause(BaseModel):
    """
    Represents a single risk clause identified in a contract or document.

    Attributes:
        title (str): Short title or category of the risk clause.
        description (str): Full explanation of the risk clause.
    """

    title: str
    description: str


class RiskAssessmentAnswer(BaseModel):
    """
    Detailed structured response for a risk assessment query.

    Attributes:
        ans (str): Main answer or summary.
        highRisksClauses (Optional[list[RiskClause]]): List of high-risk clauses identified.
        mediumRisksClauses (Optional[list[RiskClause]]): List of medium-risk clauses identified.
        lowRisksClauses (Optional[list[RiskClause]]): List of low-risk clauses identified.
        additionalRisks (Optional[list[RiskClause]]): List of additional risk clauses not classified by severity.
        similarities (Optional[list[str]]): Descriptions of similarities between compared documents or clauses.
        differences (Optional[list[str]]): Descriptions of differences between compared documents or clauses.
    """

    ans: str
    highRisksClauses: Optional[list[RiskClause]] = []
    mediumRisksClauses: Optional[list[RiskClause]] = []
    lowRisksClauses: Optional[list[RiskClause]] = []
    additionalRisks: Optional[list[RiskClause]] = []
    similarities: Optional[list[str]] = []
    differences: Optional[list[str]] = []


class RiskAssessmentResponse(BaseModel):
    """
    Wrapper model for returning a full risk assessment answer.

    Attributes:
        answer (RiskAssessmentAnswer): Structured answer including clause breakdown and analysis.
    """

    answer: RiskAssessmentAnswer
