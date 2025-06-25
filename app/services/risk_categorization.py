"""Risk matrix."""

from __future__ import annotations

import json
import logging
import re
from typing import Optional, Union

# import gzip
# import io
import boto3
from config import get_secret
from fastapi import HTTPException
from langchain_aws import ChatBedrock
from models import (
    AdditionalRisk,
    RiskAssessmentAnswer,
    RiskAssessmentResponse,
    RiskCategory,
    RiskDetail,
)
from prompts import RISK_MATRIX_ALL_RISKS_PROMPT2, RISK_MATRIX_CATEGORY
from pydantic import ValidationError
from utils import (
    generate_prompt_risk,
    generate_prompt_risk_test,
    generate_prompt_summary,
    get_additional_risk,
    get_risk_matrix_details,
    store_contract_risk_to_s3,
)

# from botocore.exceptions import BotoCoreError, ClientError


s3 = boto3.client("s3")
BUCKET_CONTAINER = get_secret("BUCKET_CONTAINER")
MODEL_ID = get_secret("MODEL_ID")
# Logger and configuration constants.
logger = logging.getLogger(__name__)


# to get all the clauses again under same session
def get_all_clauses_froms3(payload_json2: dict):
    """Returns all clauses found in an S3-stored JSON structure.

    Validates and parses the provided dictionary (`payload_json2`) using the
    `RiskAssessmentAnswer` model. Extracts and formats the answer, contractual risks,
    AZ standard risks, additional potential risks, and similarity/difference information
    into a cleaned output dictionary.

    Args:
        payload_json2 (dict): Dictionary parsed from S3 JSON, expected to
            match the `RiskAssessmentAnswer` structure.

    Returns:
        dict: A cleaned dictionary containing the answer and all major clause groupings
            if parsing is successful.
        None: If parsing/validation fails or the structure is invalid.
    """
    try:
        assessment_answer = RiskAssessmentAnswer.model_validate(payload_json2)
        answer = {
            "ans": assessment_answer.ans,
            "ContractualRisks": build_clean_risk_category_dict(
                assessment_answer.ContractualRisks
            ),
            "StandardAZRisks": build_clean_risk_category_dict(
                assessment_answer.StandardAZRisks
            ),
            "AdditionalPotentialRisks": [
                # The AdditionalRisk model is already clean, so a simple dump is fine here
                ar.model_dump()
                for ar in assessment_answer.AdditionalPotentialRisks
            ],
            "similarities": assessment_answer.similarities,
            "differences": assessment_answer.differences,
        }
        return answer
    except Exception as e:
        logger.info(
            f"[Error] No file found, returning none: {str(e)}",
        )
        return None


# to get the specific clauses asked in a query
def get_risks_from_query(clauses_identified: str, payload_json2: str):
    """Returns all clauses from the query.

    Args:
        clauses_identified (str):clauses_identified
        payload_json2 (str): all the risks in contract

    Returns:
        str: A filtered answer.
        None: If parsing/validation fails or the structure is invalid.
    """
    try:
        query_risks = _extract_json_list(clauses_identified)
        target_clause_names = {item["clause_name"] for item in query_risks}
        assessment_answer = RiskAssessmentAnswer.model_validate(payload_json2)

        # matched_clauses = {}
        filtered_assessment = RiskAssessmentAnswer(
            ans=f"Details for the following requested clauses: {', '.join(target_clause_names)}"
        )
        all_risks_from_source = (
            assessment_answer.ContractualRisks.HighRisksClauses
            + assessment_answer.ContractualRisks.MediumRisksClauses
            + assessment_answer.ContractualRisks.LowRisksClauses
            + assessment_answer.StandardAZRisks.HighRisksClauses
            + assessment_answer.StandardAZRisks.MediumRisksClauses
            + assessment_answer.StandardAZRisks.LowRisksClauses
        )

        for risk_detail in all_risks_from_source:
            if risk_detail.title in target_clause_names:
                # Add the risk to the correct category in the new object
                if risk_detail.clause_type == "Contractual":
                    filtered_assessment.ContractualRisks.add_risk(risk_detail)
                elif risk_detail.clause_type == "StandardAZ":
                    filtered_assessment.StandardAZRisks.add_risk(risk_detail)

        for additional_risk in assessment_answer.AdditionalPotentialRisks:
            if additional_risk.title in target_clause_names:
                filtered_assessment.AdditionalPotentialRisks.append(
                    additional_risk
                )

        response_data = {
            "ans": filtered_assessment.ans,
            "ContractualRisks": build_clean_risk_category_dict(
                filtered_assessment.ContractualRisks
            ),
            "StandardAZRisks": build_clean_risk_category_dict(
                filtered_assessment.StandardAZRisks
            ),
            "AdditionalPotentialRisks": [
                # The AdditionalRisk model is already clean, so a simple dump is fine here
                ar.model_dump()
                for ar in filtered_assessment.AdditionalPotentialRisks
            ],
            "similarities": filtered_assessment.similarities,
            "differences": filtered_assessment.differences,
        }
        return response_data
    except Exception as exc:
        print(exc)
        return None


def get_category4(msg_id, full_prompt):
    """Processes a prompt using an LLM to extract structured risk assessment data.

    Invokes an LLM with the provided `full_prompt` and logs the process/result.
    Parses the raw textual answer into a JSON object and then into a structured risk assessment
    Pydantic object using `parse_llm_output_to_assessment`. Logs all LLM interactions.

    Args:
        msg_id (str): Unique identifier to label logs and trace this prompt/response.
        full_prompt (str): The complete prompt string to send to the LLM.

    Returns:
        tuple (str, RiskAssessmentAnswer or RiskAssessmentResponse):
            - raw_answer: The raw string output from the LLM.
            - payload: Parsed, structured risk assessment object (or None if parsing failed).

    Raises:
        HTTPException: If invocation of the LLM fails.
    """
    try:
        llm_resp = ChatBedrock(model_id=MODEL_ID, max_tokens=4000).invoke(
            full_prompt
        )
        raw_answer = llm_resp.content.strip()
        logger.info(f"[{msg_id}] LLM responded successfully")
        logger.debug(
            f"[{msg_id}] Raw LLM response (truncated): {raw_answer[:1000]}"
        )
    except Exception as exc:
        logger.exception(f"[{msg_id}] LLM call failed")
        raise HTTPException(500, f"Error invoking LLM: {exc}") from exc

        # Step 7: Normalize response
    payload_json = _extract_json(raw_answer)
    payload = parse_llm_output_to_assessment(
        payload_json, msg_id, raw_llm_text_for_fallback=raw_answer
    )

    logger.debug(f"[{msg_id}] Primary JSON parsed: {payload is not None}")

    return raw_answer, payload


##main function for identifying risks
def risk_categorization_fn(content, queryText, msg_id, userId, session_id):
    """Performs contract risk assessment and categorization using LLMs and risk rules.

    This function processes contract content and user query text to identify, categorize,
    and summarize contractual risks. It generates multiple LLM prompts, parses and rates
    clauses, associates risk levels, attaches additional potential risks, builds a summary,
    and prepares a fully structured assessment output. It also logs and stores results in S3.

    Args:
        content (str): Full contract or clause text to be analyzed.
        queryText (str): Original query regarding risks or required clauses.
        msg_id (str): Unique message identifier for log traceability.
        userId (str): User or owner ID for risk file association.
        session_id (str): Chat or workflow session identifier.

    Returns:
        dict: A cleaned, summary dictionary with:
            - "ans": Short descriptive summary of the identified risks.
            - "ContractualRisks": All found contractual risk clauses by level.
            - "StandardAZRisks": Found AZ standard risk clauses by level.
            - "AdditionalPotentialRisks": Additional risks (if any).
            - "similarities": Risks similar across contractual and standard clauses.
            - "differences": Risks unique to contract or standard clauses.

    Raises:
        HTTPException: If LLM invocation fails for any required prompt.
    """
    risk_rules = get_risk_matrix_details()
    ##Step 1 Fetch 10 risks details
    body_prompt2 = generate_prompt_risk(content, RISK_MATRIX_ALL_RISKS_PROMPT2)

    try:
        llm_resp = ChatBedrock(model_id=MODEL_ID, max_tokens=4000).invoke(
            body_prompt2
        )
        clauses = llm_resp.content.strip()
        logger.info(f"[{msg_id}] LLM responded successfully")
        logger.debug(
            f"[{msg_id}] Raw LLM response (truncated): {clauses[:1000]}"
        )
    except Exception as exc:
        logger.exception(f"[{msg_id}] LLM call failed")
        raise HTTPException(500, f"Error invoking LLM: {exc}") from exc

    # payload_json = _extract_json(clauses)

    ##Step 2 Mark the risk level
    body_prompt3 = generate_prompt_risk_test(
        RISK_MATRIX_CATEGORY, clauses, risk_rules
    )
    try:
        llm_resp = ChatBedrock(model_id=MODEL_ID, max_tokens=4000).invoke(
            body_prompt3
        )
        raw_answer = llm_resp.content.strip()
        logger.info(f"[{msg_id}] LLM responded successfully")
        logger.debug(
            f"[{msg_id}] Raw LLM response (truncated): {raw_answer[:1000]}"
        )
    except Exception as exc:
        logger.exception(f"[{msg_id}] LLM call failed")
        raise HTTPException(500, f"Error invoking LLM: {exc}") from exc

    payload_json2 = _extract_json(raw_answer)

    ##Step 3 Mark High/medium/low and contractual,standard risk
    for clause_title, clause_data in payload_json2.items():
        risk_score = int(clause_data["risk_score"])
        if 8 <= risk_score <= 10:
            clause_data["risk_level"] = "HighRisksClauses"
        elif 5 <= risk_score <= 7:
            clause_data["risk_level"] = "MediumRisksClauses"
        elif 1 <= risk_score <= 4:
            clause_data["risk_level"] = "LowRisksClauses"
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
                re.match(r"^(na|n/a)\b", text_content_lower)
                or text_content_lower == "na"
                or text_content_lower == "n/a"
                or text_content_lower == "" 
                in text_content_lower
            ):
                clause_data["clause_type"] = "StandardAZ"
                clause_data["details"] = clause_data["reason"]
            else:
                clause_data["clause_type"] = "Contractual"
                clause_data["details"] = (
                    clause_data["details"] + clause_data["reason"]
                )
        else:
            # If 'text' field is missing or not a string, default clause_type
            print(
                f"Warning: 'text' field missing or not a string for '{clause_title}'. 'clause_type' set to 'Unknown'."
            )
            clause_data["clause_type"] = "Unknown"

    ##Step 4 Identify the importance of risk
    clause_risk_levels = {
        clause["name"]: clause["details"]["clause_inherent_risk_level"]
        for clause in risk_rules["clauses"]
    }

    # Iterate through the payload and add the clause_inherent_risk_level
    for clause_name, clause_data in payload_json2.items():
        if isinstance(clause_data, dict):
            if clause_name in clause_risk_levels:
                clause_data["risk_importance"] = clause_risk_levels[
                    clause_name
                ]
            else:
                clause_data["risk_importance"] = "Unknown"
        else:
            print(
                f"Warning: Clause data for '{clause_name}' is not a dictionary. Skipping."
            )

    # contract_risks=get_contract_risk_from_s3(userId,session_id,BUCKET_CONTAINER)

    ##Step 5 Get additional risks if any and add to the final structure
    body_prompt3 = get_additional_risk(content, clauses)

    llm_resp = ChatBedrock(model_id=MODEL_ID, max_tokens=4000).invoke(
        body_prompt3
    )
    add_clauses = llm_resp.content.strip()
    add_clauses_v1 = _extract_json_list(add_clauses)

    assessment_answer = RiskAssessmentAnswer(ans="")
    if isinstance(add_clauses_v1, list):
        for item_data in add_clauses_v1:
            try:
                if isinstance(item_data, dict):
                    title = str(
                        item_data.get("title", "Untitled Additional Risk")
                    )
                    description = str(
                        item_data.get(
                            "description", "No description provided."
                        )
                    )
                    assessment_answer.AdditionalPotentialRisks.append(
                        AdditionalRisk(title=title, description=description)
                    )
                else:
                    logger.warning(
                        f"[{msg_id}] Skipping non-dict item in additional risks data: {item_data}"
                    )
            except ValidationError as e:
                logger.warning(
                    f"[{msg_id}] Validation error for AdditionalRisk item {item_data}: {e}"
                )
    elif add_clauses_v1 is not None:
        logger.warning(
            f"[{msg_id}] Expected a list for additional risks, but got {type(add_clauses_v1)}. Data: {add_clauses_v1}"
        )

    ##Step 6 Generating short summary
    risk_summary = generate_prompt_summary(clauses, add_clauses_v1)
    try:
        llm_resp_summary = ChatBedrock(
            model_id=MODEL_ID, max_tokens=500
        ).invoke(risk_summary)
        summary_text = llm_resp_summary.content.strip()
        assessment_answer.ans = summary_text
        logger.info(
            f"[{msg_id}] LLM (overall summary) responded successfully."
        )
        logger.debug(f"[{msg_id}] Generated summary: {summary_text[:200]}")
    except Exception:
        logger.exception(f"[{msg_id}] LLM call for overall summary failed")
        assessment_answer.ans = ""  # Fallback summary

    ##Step 7 Semi - Final output creation
    for clause_name, details in payload_json2.items():
        risk_detail = RiskDetail(
            title=clause_name,
            description=str(details["details"]),
            risk_score=details["risk_score"],
            risk_level=details["risk_level"],
            clause_type=details["clause_type"],
            risk_importance=details["risk_importance"],
        )

        if details["clause_type"] == "Contractual":
            assessment_answer.ContractualRisks.add_risk(risk_detail)
        elif details["clause_type"] == "StandardAZ":
            assessment_answer.StandardAZRisks.add_risk(risk_detail)
        else:
            print(
                f"Warning: Unknown clause type '{details['clause_type']}' for clause '{clause_name}'"
            )

    response_data = assessment_answer.model_dump()
    ##Step 8 Storing the risk file on S3
    store_contract_risk_to_s3(
        userId, session_id, response_data, BUCKET_CONTAINER, compress=True
    )

    ##Step 9 Final output creation
    response_data = {
        "ans": assessment_answer.ans,
        "ContractualRisks": build_clean_risk_category_dict(
            assessment_answer.ContractualRisks
        ),
        "StandardAZRisks": build_clean_risk_category_dict(
            assessment_answer.StandardAZRisks
        ),
        "AdditionalPotentialRisks": [
            # The AdditionalRisk model is already clean, so a simple dump is fine here
            ar.model_dump()
            for ar in assessment_answer.AdditionalPotentialRisks
        ],
        "similarities": assessment_answer.similarities,
        "differences": assessment_answer.differences,
    }

    return response_data


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


def _extract_json_list(text: str) -> list[dict] | None:
    """Extract the first JSON list containing dictionaries found in a text.

    This function is specifically designed to extract a JSON list where each element
    in the list is a dictionary. It removes code block markers (```) before attempting
    to parse the JSON.

    Args:
        text: A string potentially containing a JSON list of dictionaries.

    Returns:
        A list of dictionaries if a JSON list is found and parsed successfully, otherwise None.
    """
    cleaned = "\n".join(
        ln for ln in text.splitlines() if not ln.lstrip().startswith("```")
    ).strip()
    match = re.search(r"\[.*\]", cleaned, flags=re.S)
    if not match:
        return None

    try:
        data = json.loads(match.group(0))
        if isinstance(data, list) and all(
            isinstance(item, dict) for item in data
        ):
            return data
        else:
            return None  # Not a list of dictionaries
    except json.JSONDecodeError:
        return None


def build_clean_risk_category_dict(risk_category: RiskCategory) -> dict:
    """Builds and returns a structured dictionary summarizing risk clauses by level.

    For a given `RiskCategory` object, this function groups all risk details as lists of
    dictionaries within the categories "HighRisksClauses", "MediumRisksClauses", and "LowRisksClauses".
    Each inner dictionary contains the clause's title (appended with its importance in parentheses)
    and its description.

    Args:
        risk_category (RiskCategory): A RiskCategory object containing categorized risk details.

    Returns:
        dict: A dictionary with three keys:
            - "HighRisksClauses": List of high-risk clause dictionaries.
            - "MediumRisksClauses": List of medium-risk clause dictionaries.
            - "LowRisksClauses": List of low-risk clause dictionaries.
        Each dictionary inside the lists has:
            - "title": Clause title with importance as a string.
            - "description": Clause risk description/content as a string.
    """
    return {
        "HighRisksClauses": [
            {
                "title": risk_detail.title
                + "("
                + risk_detail.risk_importance
                + ")",
                "description": risk_detail.description,
            }
            for risk_detail in risk_category.HighRisksClauses
        ],
        "MediumRisksClauses": [
            {
                "title": risk_detail.title
                + "("
                + risk_detail.risk_importance
                + ")",
                "description": risk_detail.description,
            }
            for risk_detail in risk_category.MediumRisksClauses
        ],
        "LowRisksClauses": [
            {
                "title": risk_detail.title
                + "("
                + risk_detail.risk_importance
                + ")",
                "description": risk_detail.description,
            }
            for risk_detail in risk_category.LowRisksClauses
        ],
    }
