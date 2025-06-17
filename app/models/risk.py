"""Data models for representing chat metadata, interactions, and search requests."""

from __future__ import annotations

from typing import Any, List

from pydantic import BaseModel, Field


class RiskDetail(BaseModel):
    """Details of a specific risk identified in a clause."""
    title: str
    description: str
    risk_score: int
    risk_level: str
    clause_type: str 
    risk_importance: str

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        """Exclude fields when serializing for the API response."""
       
        exclude_set = {
            "risk_score",
            "risk_level",
            "clause_type",
            "risk_importance",
        }
        kwargs.setdefault("exclude", set()).update(exclude_set)
        print(f"kwargs in RiskDetail.model_dump: {kwargs}") 
        return super().model_dump(**kwargs)
    
class RiskClause(BaseModel):
    """Represents a single risk clause identified in a contract or document.

    Attributes:
        title (str): Short title or category of the risk clause.
        description (str): Full explanation of the risk clause.
    """

    title: str
    description: str


class RiskCategory(BaseModel):
    """Categorizes risks by their severity level for a specific type (e.g., Contractual)."""
    HighRisksClauses: List[RiskDetail] = Field(default_factory=list)
    MediumRisksClauses: List[RiskDetail] = Field(default_factory=list)
    LowRisksClauses: List[RiskDetail] = Field(default_factory=list)
    
    total_risks: int = 0
    high_risk_count: int = 0
    medium_risk_count: int = 0
    low_risk_count: int = 0

    def add_risk(self, risk_detail: RiskDetail):
        """Adds a risk detail to the appropriate list and updates counts."""
        if risk_detail.risk_level == "HighRisksClauses":
            self.HighRisksClauses.append(risk_detail)
            self.high_risk_count += 1
        elif risk_detail.risk_level == "MediumRisksClauses":
            self.MediumRisksClauses.append(risk_detail)
            self.medium_risk_count += 1
        elif risk_detail.risk_level == "LowRisksClauses":
            self.LowRisksClauses.append(risk_detail)
            self.low_risk_count += 1
        else:
            print(f"Warning: RiskDetail for '{risk_detail.clause_name}' has unhandled risk_level: '{risk_detail.risk_level}'. Not added to H/M/L lists.")
            return 

        self.total_risks += 1


    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        """Exclude count fields when serializing for the API response."""
        exclude_set = {
            "total_risks",
            "high_risk_count",
            "medium_risk_count",
            "low_risk_count",
        }
        kwargs.setdefault("exclude", set()).update(exclude_set)
        return super().model_dump(**kwargs)


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
