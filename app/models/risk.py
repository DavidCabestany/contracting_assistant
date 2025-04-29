from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel


class RiskClause(BaseModel):
    title: str
    description: str


class RiskAssessmentAnswer(BaseModel):
    ans: str
    highRisksClauses: Optional[List[RiskClause]] = []
    mediumRisksClauses: Optional[List[RiskClause]] = []
    lowRisksClauses: Optional[List[RiskClause]] = []
    additionalRisks: Optional[List[RiskClause]] = []
    similarities: Optional[List[str]] = []
    differences: Optional[List[str]] = []


class RiskAssessmentResponse(BaseModel):
    answer: RiskAssessmentAnswer
