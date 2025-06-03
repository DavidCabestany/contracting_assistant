"""Risk matrix"""

from __future__ import annotations

import re
import logging
from typing import Any, List,Optional, Union
from pydantic import BaseModel, Field
from fastapi import HTTPException
import json
from langchain_aws import ChatBedrock
from models import RiskAssessmentResponse
from pydantic import ValidationError

from utils import (
    extract_keywords_from_query,
    extract_pdf_contents,
    extract_text_from_word,
    generate_prompt,
    generate_prompt_risk,
    generate_prompt_risk_test,
    get_file_type,
    get_risk_matrix_details,
    prompt_query_cat,
)
from config import get_secret
#from routes.summary import _extract_json,parse_llm_output_to_assessment

MODEL_ID = get_secret("MODEL_ID")
# Logger and configuration constants.
logger = logging.getLogger(__name__)

class RiskDetail(BaseModel):
    """Details of a specific risk identified in a clause."""
    clause_name: str
    risk_content: str
    risk_score: int
    risk_level: str
    clause_type: str 
    risk_importance: str

class RiskCategory(BaseModel):
    """Categorizes risks by their severity level for a specific type (e.g., Contractual)."""
    High: List[RiskDetail] = Field(default_factory=list)
    Medium: List[RiskDetail] = Field(default_factory=list)
    Low: List[RiskDetail] = Field(default_factory=list)
    
    total_risks: int = 0
    high_risk_count: int = 0
    medium_risk_count: int = 0
    low_risk_count: int = 0

    def add_risk(self, risk_detail: RiskDetail):
        """Adds a risk detail to the appropriate list and updates counts."""
        if risk_detail.risk_level == "High":
            self.High.append(risk_detail)
            self.high_risk_count += 1
        elif risk_detail.risk_level == "Medium":
            self.Medium.append(risk_detail)
            self.medium_risk_count += 1
        elif risk_detail.risk_level == "Low":
            self.Low.append(risk_detail)
            self.low_risk_count += 1
        else:
            # Handle unknown risk_level if necessary, or assume it's pre-validated
            print(f"Warning: RiskDetail for '{risk_detail.clause_name}' has unhandled risk_level: '{risk_detail.risk_level}'. Not added to H/M/L lists.")
            return # Don't increment total_risks if not categorized H/M/L

        self.total_risks += 1

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




RISK_MATRIX_ALL_RISKS_PROMPT2 = """Kindly provide details related to the clauses mentioned below in the format below -
If nothing is present for particular clause provide "NA" in details.
```json
{{
  "Termination Clause"(Clause related to the conditions and penalties for terminating a contract.)              : "Provide the details in contract"
  "Liability Clause"(Clause outlining the extent and limitations of liability in the contract.)                 : "Provide the details in contract"
  "Compliance Requirements"(Clause addressing adherence to relevant laws, regulations, and industry standards)  : "Provide the details in contract"
  "Sustainability Terms"(Clause related to environmental, social, and governance (ESG) considerations.)         : "Provide the details in contract"
  "Spend Under Contract"(Clause pertaining to budget management, spending limits, and financial thresholds.)    : "Provide the details in contract"
  "Payment Terms"(Clause governing the methods, timing, and conditions of payment with AZ standard)             : "Provide the details in contract"
  "Performance Metrics"(Clause defining how the contract's success will be measured and assessed.)              : "Provide the details in contract"
  "Confidentiality Clause"(Clause protecting sensitive information shared during the contract.)                 : "Provide the details in contract"
  "Dispute Resolution"(Clause outlining procedures for resolving disagreements or conflicts.)                   : "Provide the details in contract"
  "Force Majeure Clause"(Clause excusing parties from obligations due to unforeseen events.)                    : "Provide the details in contract"
  "Renewal Terms"(Clause outlining the conditions and procedures for extending a contract.)                     : "Provide the details in contract"
}} ```

Document Content:
{Contract}
"""


RISK_MATRIX_ALL_RISKS_PROMPT3 = """Kindly fill in the risk_score in the json and return it, depending upon the risk_rules.scenario_description as per below scale
category : risk_score
High : 8-10
Medium : 5-7
Low : 1-4
risk_json : {risk_json}
risk_rules :{risk_rules}
Output Json :
```json
{{
  "Termination Clause" {{"details": "details in contract", "risk_score": "risk_score_value"}},
  // ... more clauses
}}```
"""

def risk_categorization_fn(content,queryText,msg_id):
    risk_rules = get_risk_matrix_details()
    body_prompt2 = generate_prompt_risk(
                    content,
                    queryText,
                    RISK_MATRIX_ALL_RISKS_PROMPT2,
                    risk_rules,
                    clauses_lst=extract_clause_names_from_risk_rules(risk_rules) )
    
    try:
        llm_resp = ChatBedrock(
            model_id=MODEL_ID, max_tokens=4000
        ).invoke(body_prompt2)
        clauses = llm_resp.content.strip()
        logger.info(f"[{msg_id}] LLM responded successfully")
        logger.debug(
            f"[{msg_id}] Raw LLM response (truncated): {clauses[:1000]}"
        )
    except Exception as exc:
        logger.exception(f"[{msg_id}] LLM call failed")
        raise HTTPException(500, f"Error invoking LLM: {exc}") from exc

    payload_json = _extract_json(clauses)
    body_prompt3 = generate_prompt_risk_test(
        RISK_MATRIX_ALL_RISKS_PROMPT3, clauses, risk_rules
    )
    try:
        llm_resp = ChatBedrock(
            model_id=MODEL_ID, max_tokens=4000
        ).invoke(body_prompt3)
        raw_answer = llm_resp.content.strip()
        logger.info(f"[{msg_id}] LLM responded successfully")
        logger.debug(
            f"[{msg_id}] Raw LLM response (truncated): {raw_answer[:1000]}"
        )
    except Exception as exc:
        logger.exception(f"[{msg_id}] LLM call failed")
        raise HTTPException(500, f"Error invoking LLM: {exc}") from exc

    payload_json2 = _extract_json(raw_answer)

    for clause_title, clause_data in payload_json2.items():
        risk_score = int(clause_data["risk_score"])
        if 8 <= risk_score <= 10:
            clause_data["risk_level"] = "High"
        elif 5 <= risk_score <= 7:
            clause_data["risk_level"] = "Medium"
        elif 1 <= risk_score <= 4:
            clause_data["risk_level"] = "Low"
        else:
            print(
                f"Warning: Risk score {risk_score} for '{clause_title}' is out of defined ranges (1-10). Skipping categorization."
            )
            clause_data["risk_level"] = "Undefined"

        if "details" in clause_data and isinstance(
            clause_data["details"], str
        ):
            # Normalize text for checking "NA" or missing indicators
            text_content_lower = clause_data["details"].strip().lower()
            if (
                text_content_lower == "na"
                or text_content_lower == "n/a"
                or text_content_lower == ""
                # or "not addressed/missing" in text_content_lower
                # or "no provision for this checklist clause found"
                in text_content_lower
            ):
                clause_data["clause_type"] = "StandardAZ"
            else:
                clause_data["clause_type"] = "Contractual"
        else:
            # If 'text' field is missing or not a string, default clause_type
            print(
                f"Warning: 'text' field missing or not a string for '{clause_title}'. 'clause_type' set to 'Unknown'."
            )
            clause_data["clause_type"] = "Unknown"



    clause_risk_levels = {clause["name"]: clause["details"]["clause_inherent_risk_level"] for clause in risk_rules["clauses"]}

    # Iterate through the payload and add the clause_inherent_risk_level
    for clause_name, clause_data in payload_json.items():
        if clause_name in clause_risk_levels:
            clause_data['risk_importance'] = clause_risk_levels[clause_name]
        else:
            clause_data['risk_importance'] = 'Unknown'
        
    

    assessment_answer = RiskAssessmentAnswer(ans="") 
    for clause_name,details in payload_json2.items():
        risk_detail = RiskDetail(
        clause_name=clause_name,
        risk_content=str(details['details']),
        risk_score=details['risk_score'],
        risk_level=details['risk_level'],
        clause_type=details['clause_type'],
        risk_importance=details['risk_importance'])
    
        if details['clause_type'] == 'Contractual':
            assessment_answer.ContractualRisks.add_risk(risk_detail)
        elif details['clause_type'] == 'StandardAZ':
            assessment_answer.StandardAZRisks.add_risk(risk_detail)
        else:
            print(f"Warning: Unknown clause type '{details['clause_type']}' for clause '{clause_name}'")

    return assessment_answer


def extract_clause_names_from_risk_rules(risk_rules_input) -> list[str]:
    """Extracts the names of all top-level clauses from the risk_rules checklist.

    Args:
        risk_rules_input: Either a JSON string or a Python dictionary
                          representing the risk_rules structure.

    Returns:
        A list of strings, where each string is the name of a clause.
        Returns an empty list if the input is invalid or no clauses are found.
    """
    if isinstance(risk_rules_input, str):
        try:
            data = json.loads(risk_rules_input)
        except json.JSONDecodeError:
            print("Error: Invalid JSON string provided.")
            return []
    elif isinstance(risk_rules_input, dict):
        data = risk_rules_input
    else:
        print("Error: Input must be a JSON string or a Python dictionary.")
        return []

    clause_names = []
    if "clauses" in data and isinstance(data["clauses"], list):
        for clause_item in data["clauses"]:
            if isinstance(clause_item, dict) and "name" in clause_item:
                clause_names.append(clause_item["name"])
            else:
                print(
                    f"Warning: Found an item in 'clauses' list that is not a dict or lacks a 'name' key: {clause_item}"
                )
    else:
        print(
            "Warning: 'clauses' key not found in risk_rules or it's not a list."
        )

    return clause_names



def _extract_json(text: str) -> dict | None:
    """Extract the first JSON object found in a text.

    Args:
        text: A string potentially containing JSON.

    Returns:
        A dictionary if a JSON object is found and parsed successfully, otherwise None.
    """
    cleaned = "\n".join(
        ln for ln in text.splitlines() if not ln.lstrip().startswith("```")
    ).strip()
    match = re.search(r"{.*}", cleaned, flags=re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _wrap_plain(ans: str) -> dict:
    """Wrap plain text answer in structured summary format.

    Args:
        ans: Free-text summary.

    Returns:
        A dictionary with default summary fields.
    """
    return {
        "ans": ans,
        "ContractualRisks": {},
        "StandardAZRisks": {},
        "AdditionalPotentialRisks": [],
        "similarities": [],
        "differences": [],
    }


# ... (imports and other functions like _extract_json, _wrap_plain remain the same) ...


def parse_llm_output_to_assessment(
    raw_json_dict: Optional[dict],
    msg_id: str = "parse",
    raw_llm_text_for_fallback: Optional[str] = None,
) -> Union[RiskAssessmentResponse, RiskAssessmentAnswer]:
    """Parses a pre-extracted JSON dictionary from LLM output into a structured `RiskAssessmentResponse` or `RiskAssessmentAnswer` Pydantic object.

    Args:
        raw_json_dict: Dictionary from initial JSON extraction
            of LLM output, or None if extraction failed.
        msg_id: Logger message ID. Defaults to "parse".
        raw_llm_text_for_fallback: Original raw LLM text,
            used if `raw_json_dict` is None or unparsable.

    Returns:
        A parsed Pydantic object (`RiskAssessmentResponse` or `RiskAssessmentAnswer`).
        This function will always return one of these types, using fallbacks if necessary.
    """
    if not raw_json_dict:
        logger.warning(
            f"[{msg_id}] `raw_json_dict` is None or empty. Using fallback text."
        )
        fallback_text = (
            raw_llm_text_for_fallback
            if raw_llm_text_for_fallback
            else "No input data provided to parse."
        )
        return RiskAssessmentAnswer(**_wrap_plain(fallback_text))

    extracted_data: Optional[dict] = None

    if "answer" in raw_json_dict and isinstance(
        raw_json_dict.get("answer"), dict
    ):
        try:
            response_obj = RiskAssessmentResponse(**raw_json_dict["answer"])
            logger.info(
                f"[{msg_id}] Successfully parsed as RiskAssessmentResponse structure."
            )
            return response_obj
        except ValidationError as e:
            logger.warning(
                f"[{msg_id}] Validation failed for RiskAssessmentResponse structure: {e.errors()}"
            )
            extracted_data = raw_json_dict.get("answer")
        except Exception as e:
            logger.error(
                f"[{msg_id}] Unexpected error parsing as RiskAssessmentResponse: {e}"
            )
            extracted_data = raw_json_dict.get("answer")

    if extracted_data is None:
        extracted_data = raw_json_dict

    if isinstance(extracted_data, dict):
        try:
            parsed_obj = RiskAssessmentAnswer(**extracted_data)
            logger.info(
                f"[{msg_id}] Successfully parsed `extracted_data` as RiskAssessmentAnswer structure."
            )
            return parsed_obj
        except ValidationError as e:
            logger.warning(
                f"[{msg_id}] Validation failed for RiskAssessmentAnswer from `extracted_data`: {e.errors()}"
            )
        except Exception as e:
            logger.error(
                f"[{msg_id}] Unexpected error parsing `extracted_data` as RiskAssessmentAnswer: {e}"
            )

    if (
        isinstance(extracted_data, dict)
        and "response" in extracted_data
        and isinstance(extracted_data["response"], str)
    ):
        text_from_response_field = extracted_data["response"]
        logger.info(
            f"[{msg_id}] Found 'response' field with string content. Attempting to process it."
        )
        nested_json_dict = _extract_json(text_from_response_field)
        if nested_json_dict:
            try:
                parsed_obj = RiskAssessmentAnswer(**nested_json_dict)
                logger.info(
                    f"[{msg_id}] Successfully parsed nested JSON from 'response' field as RiskAssessmentAnswer."
                )
                return parsed_obj
            except ValidationError as e:
                logger.warning(
                    f"[{msg_id}] Validation failed for nested JSON in 'response': {e.errors()}. Using 'response' string as 'ans'."
                )
                return RiskAssessmentAnswer(
                    **_wrap_plain(text_from_response_field)
                )
            except Exception as e:
                logger.error(
                    f"[{msg_id}] Unexpected error parsing nested JSON in 'response': {e}. Using 'response' string as 'ans'."
                )
                return RiskAssessmentAnswer(
                    **_wrap_plain(text_from_response_field)
                )
        else:  # No valid nested JSON
            logger.info(
                f"[{msg_id}] Using plain text from 'response' field as 'ans'."
            )
            return RiskAssessmentAnswer(
                **_wrap_plain(text_from_response_field)
            )

    if (
        isinstance(extracted_data, dict)
        and "ans" in extracted_data
        and isinstance(extracted_data["ans"], str)
    ):
        logger.info(
            f"[{msg_id}] `extracted_data` has 'ans' string. Using it via _wrap_plain."
        )
        return RiskAssessmentAnswer(**_wrap_plain(extracted_data["ans"]))

    # FINAL FALLBACK
    logger.warning(
        f"[{msg_id}] All structured parsing attempts for `raw_json_dict` failed. Using `raw_llm_text_for_fallback` or default."
    )
    fallback_text = (
        raw_llm_text_for_fallback
        if raw_llm_text_for_fallback
        else "Could not interpret LLM output into a structured format."
    )
    return RiskAssessmentAnswer(**_wrap_plain(fallback_text))
