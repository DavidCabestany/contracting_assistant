"""Risk matrix"""

from __future__ import annotations

import re
import logging
# import gzip
# import io
import boto3
from typing import Any, List,Optional, Union
from pydantic import BaseModel, Field
from fastapi import HTTPException
import json
from langchain_aws import ChatBedrock
from pydantic import ValidationError
#from botocore.exceptions import BotoCoreError, ClientError

from utils import (
    generate_prompt_risk,
    generate_prompt_risk_test,
    get_risk_matrix_details,
    get_additional_risk,
    generate_prompt_summary,
    store_contract_risk_to_s3
    )

from models import (
    AdditionalRisk,
    RiskAssessmentAnswer,
    RiskAssessmentResponse,
    RiskDetail,
    RiskCategory
)

from config import get_secret
from prompts import RISK_MATRIX_ALL_RISKS_PROMPT2,RISK_MATRIX_CATEGORY

s3 = boto3.client("s3")
BUCKET_CONTAINER = get_secret("BUCKET_CONTAINER")
MODEL_ID = get_secret("MODEL_ID")
# Logger and configuration constants.
logger = logging.getLogger(__name__)

#will be moved to risk.py under models folder
# class RiskDetail(BaseModel):
#     """Details of a specific risk identified in a clause."""
#     clause_name: str
#     risk_content: str
#     risk_score: int
#     risk_level: str
#     clause_type: str 
#     risk_importance: str

#     def model_dump(self, **kwargs: Any) -> dict[str, Any]:
#         """Exclude fields when serializing for the API response."""
       
#         exclude_set = {
#             "risk_score",
#             "risk_level",
#             "clause_type",
#             "risk_importance",
#         }
#         kwargs.setdefault("exclude", set()).update(exclude_set)
#         print(f"kwargs in RiskDetail.model_dump: {kwargs}") 
#         return super().model_dump(**kwargs)


# class RiskCategory(BaseModel):
#     """Categorizes risks by their severity level for a specific type (e.g., Contractual)."""
#     HighRisksClauses: List[RiskDetail] = Field(default_factory=list)
#     MediumRisksClauses: List[RiskDetail] = Field(default_factory=list)
#     LowRisksClauses: List[RiskDetail] = Field(default_factory=list)
    
#     total_risks: int = 0
#     high_risk_count: int = 0
#     medium_risk_count: int = 0
#     low_risk_count: int = 0

#     def add_risk(self, risk_detail: RiskDetail):
#         """Adds a risk detail to the appropriate list and updates counts."""
#         if risk_detail.risk_level == "HighRisksClauses":
#             self.HighRisksClauses.append(risk_detail)
#             self.high_risk_count += 1
#         elif risk_detail.risk_level == "MediumRisksClauses":
#             self.MediumRisksClauses.append(risk_detail)
#             self.medium_risk_count += 1
#         elif risk_detail.risk_level == "LowRisksClauses":
#             self.LowRisksClauses.append(risk_detail)
#             self.low_risk_count += 1
#         else:
#             print(f"Warning: RiskDetail for '{risk_detail.clause_name}' has unhandled risk_level: '{risk_detail.risk_level}'. Not added to H/M/L lists.")
#             return 

#         self.total_risks += 1


#     def model_dump(self, **kwargs: Any) -> dict[str, Any]:
#         """Exclude count fields when serializing for the API response."""
#         exclude_set = {
#             "total_risks",
#             "high_risk_count",
#             "medium_risk_count",
#             "low_risk_count",
#         }
#         kwargs.setdefault("exclude", set()).update(exclude_set)
#         return super().model_dump(**kwargs)

# class AdditionalRisk(BaseModel):
#     """Represents additional risks identified in a contract or document.

#     Attributes:
#         title (str): Short title or category of the risk clause.
#         description (str): Full explanation of the risk clause.
#     """

#     title: str = ""
#     description: str = ""


# class RiskAssessmentAnswer(BaseModel):
#     """Structured response detailing the findings of a risk assessment query."""

#     ans: str
#     ContractualRisks: RiskCategory = Field(default_factory=RiskCategory)
#     StandardAZRisks: RiskCategory = Field(default_factory=RiskCategory)
#     AdditionalPotentialRisks: List[AdditionalRisk] = Field(
#         default_factory=list
#     )
#     similarities: List[Any] = Field(default_factory=list)
#     differences: List[Any] = Field(default_factory=list)




# RISK_MATRIX_ALL_RISKS_PROMPT2 = """Kindly provide details related to the clauses mentioned below in the format below -
# If nothing is present for particular clause provide "NA" in details.Do not infer or invent details based on the context or description—these are provided only to help you understand what to look for.
# ```json
# {{
#   "Termination Clause"(It addresses the conditions and procedures under which a contract may be ended before its agreed expiration. It outlines who can terminate, on what grounds (such as convenience or breach), the notice periods required, and what happens after termination, including handover, transition, and settlement of outstanding obligations. This ensures both parties understand their rights and responsibilities if the contract ends early.)                                                                                                                                                                                                                                                                                                                  : "Provide the details in contract"
#   "Liability Clause"(It addresses the extent to which each party is responsible for losses, damages, or claims arising from the contract. It sets any financial limits (caps) on liability, details any exceptions (such as for personal injury or breaches of confidentiality), and outlines what types of losses are included or excluded. The clause clarifies the parties’ obligations in the event of a problem and helps allocate risks and responsibilities clearly under the contract.)                                                                                                                                                                                                                                                                                      : "Provide the details in contract"
#   "Compliance Requirements"(It addresses adherence to relevant laws, regulations, and industry standards as set out in the contract. It covers subjects such as liability for breaches (including data protection, intellectual property, and cybersecurity); requirements for sustainability commitments; obligations regarding audit rights and flow-down clauses; and compliance with anti-bribery, anti-corruption, modern slavery, data protection, and diversity-related obligations.)                                                                                                                                                                                                                                                                                         : "Provide the details in contract"
#   "Sustainability Terms"(It relates to environmental, social, and governance (ESG) considerations. It covers requirements such as alignment with sustainability frameworks (e.g., CDP, SBTi), commitments to reduce environmental impact, verified greenhouse gas reduction targets, renewable energy sourcing, compliance with AstraZeneca’s Supplier Expectations or Code of Ethics, provision of ESG data, diversity measures, and acceptance of audits and traceability.)                                                                                                                                                                                                                                                                                                        : "Provide the details in contract"
#   "Payment Terms"(The Payment Terms clause governs the methods, timing, and conditions for payments between the parties. It specifies AstraZeneca’s standard payment periods—75 days from receipt of a correct and undisputed invoice for most regions, 60 days within the United Kingdom and the European Union, and 45 days within France and for recurring invoices. The clause also addresses requirements such as payments being linked to receipt (not just the invoice date), adherence to the “No PO, No Pay” rule, proper documentation and approval of any deviations, controls over pass-through costs, and compliance with electronic transaction platforms. This ensures clear expectations and compliance with both AZ policies and regional regulations.)             : "Provide the details in contract"
#   "Performance Metrics"(It defines how the contract’s success will be measured and assessed. It sets out specific metrics, such as service levels, operational efficiency indicators, or compliance targets, and describes the consequences for meeting or missing those metrics. These may include informational or developmental measures, moderate metrics affecting efficiency and satisfaction, or strict, auditable metrics with remedies or penalties for non-compliance—especially when performance impacts regulatory, financial, or reputational matters for AstraZeneca. The clause ensures clear expectations for performance and accountability under the contract.)                                                                                                    : "Provide the details in contract"
#   "Confidentiality Clause"(It protects sensitive information shared during the contract. It defines the obligations of each party to safeguard confidential data—such as clinical, patient, or proprietary research data—against unauthorized disclosure or use. The clause sets out restrictions on sharing information with subcontractors or third parties, specifies how breaches are handled, and may include conditions on liability, enforcement, and the duration of confidentiality commitments. This ensures confidential information is handled appropriately and in line with agreed contract terms.)                                                                                                                                                                    : "Provide the details in contract"
#   "Dispute Resolution"(It outlines the procedures for resolving disagreements or conflicts arising under the contract. It defines the steps parties must follow, which may include structured escalation, good faith negotiation, optional mediation, and—if needed—arbitration or litigation. The clause may specify preferred jurisdictions, require ongoing contract performance during disputes, and ensure the process is fair, balanced, and clearly defined for both parties)                                                                                                                                                                                                                                                                                                 : "Provide the details in contract"
#   "Force Majeure Clause"(The Force Majeure Clause excuses parties from their contractual obligations when unforeseen events beyond their control occur. Key aspects may include requirements to notify and mitigate, clear definitions of qualifying events, exclusion of relief for events caused by a party’s own fault or foreseeable issues, continuation of unaffected services, no price increases due to force majeure, and the ability for parties to terminate or engage alternatives after prolonged disruption. Well-defined clauses ensure fairness and protect against misuse or supplier exploitation.)                                                                                                                                                                : "Provide the details in contract"
#   "Renewal Terms"(It defines the conditions and procedures for extending a contract. It typically covers whether renewal is automatic or requires explicit written agreement, specifies notification periods for renewal, and ensures renewal terms are transparent and subject to review. Well-drafted clauses prevent unintended or perpetual renewals, prohibit automatic renewals without the right to opt out, require all renewals to be documented, and ensure no additional obligations or costs are imposed without clear approval. This promotes clarity, compliance, and control over contract continuations)                                                                                                                                                             : "Provide the details in contract"
# }} ```
# Document Content:
# {Contract}
# """


# RISK_MATRIX_ALL_RISKS_PROMPT3 = """Kindly fill in the risk_score in the json and return it, depending upon the risk_rules.scenario_description as per below scale
# category : risk_score
# High : 8-10
# Medium : 5-7
# Low : 1-4
# identified_clauses : {identified_clauses}
# risk_rules :{risk_rules}
# Output Json :
# ```json
# {{
#   "Termination Clause" {{"details": "details in contract", "risk_score": "risk_score_value","reason":"reason why you chose this score"}},
#   // ... more clauses
# }}```
# """


#to get all the clauses again under same session
def get_all_clauses_froms3(payload_json2:dict):
    """to return back all the clauses found on s3
    Args:
        dict: dictionary with all the clauses/

    Returns:
        A dictionary if a JSON object is found and parsed successfully, otherwise None.
    """
    try:
        assessment_answer=RiskAssessmentAnswer.model_validate(payload_json2)
        answer = {
        "ans": assessment_answer.ans,
        "ContractualRisks": build_clean_risk_category_dict(assessment_answer.ContractualRisks),
        "StandardAZRisks": build_clean_risk_category_dict(assessment_answer.StandardAZRisks),
        "AdditionalPotentialRisks": [
            # The AdditionalRisk model is already clean, so a simple dump is fine here
            ar.model_dump() for ar in assessment_answer.AdditionalPotentialRisks
        ],
        "similarities": assessment_answer.similarities,
        "differences": assessment_answer.differences
    }     
        return answer
    except:
        return None 

# to get the specific clauses asked in a query
def get_risks_from_query(clauses_identified:str,payload_json2:str):
    try:
        query_risks = _extract_json_list(clauses_identified)
        target_clause_names = {item['clause_name'] for item in query_risks}
        assessment_answer=RiskAssessmentAnswer.model_validate(payload_json2)

        #matched_clauses = {}
        filtered_assessment = RiskAssessmentAnswer(
        ans=f"Details for the following requested clauses: {', '.join(target_clause_names)}")
        all_risks_from_source = (
        assessment_answer.ContractualRisks.HighRisksClauses +
        assessment_answer.ContractualRisks.MediumRisksClauses +
        assessment_answer.ContractualRisks.LowRisksClauses +
        assessment_answer.StandardAZRisks.HighRisksClauses +
        assessment_answer.StandardAZRisks.MediumRisksClauses +
        assessment_answer.StandardAZRisks.LowRisksClauses)

        for risk_detail in all_risks_from_source:
            if risk_detail.clause_name in target_clause_names:
                # Add the risk to the correct category in the new object
                if risk_detail.clause_type == 'Contractual':
                    filtered_assessment.ContractualRisks.add_risk(risk_detail)
                elif risk_detail.clause_type == 'StandardAZ':
                    filtered_assessment.StandardAZRisks.add_risk(risk_detail)
        
        for additional_risk in assessment_answer.AdditionalPotentialRisks:
            if additional_risk.title in target_clause_names:
                filtered_assessment.AdditionalPotentialRisks.append(additional_risk)

        response_data = {
        "ans": filtered_assessment.ans,
        "ContractualRisks": build_clean_risk_category_dict(filtered_assessment.ContractualRisks),
        "StandardAZRisks": build_clean_risk_category_dict(filtered_assessment.StandardAZRisks),
        "AdditionalPotentialRisks": [
            # The AdditionalRisk model is already clean, so a simple dump is fine here
            ar.model_dump() for ar in filtered_assessment.AdditionalPotentialRisks
        ],
        "similarities": filtered_assessment.similarities,
        "differences": filtered_assessment.differences}
        return response_data
    except Exception as exc:
        print(exc)
        return None
    
def get_category4(msg_id, full_prompt):
    try:
        llm_resp = ChatBedrock(
                    model_id=MODEL_ID, max_tokens=4000
                ).invoke(full_prompt)
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

    logger.debug(
                f"[{msg_id}] Primary JSON parsed: {payload is not None}"
            )
    
    return raw_answer,payload



##main function for identifying risks
def risk_categorization_fn(content,queryText,msg_id,userId,session_id):
    risk_rules = get_risk_matrix_details()
    ##Step 1 Fetch 11 risks details
    body_prompt2 = generate_prompt_risk(
                    content,
                    RISK_MATRIX_ALL_RISKS_PROMPT2)
    
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

    #payload_json = _extract_json(clauses)

    ##Step 2 Mark the risk level
    body_prompt3 = generate_prompt_risk_test(
        RISK_MATRIX_CATEGORY, clauses, risk_rules
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
                text_content_lower == "na"
                or text_content_lower == "n/a"
                or text_content_lower == ""
                # or "not addressed/missing" in text_content_lower
                # or "no provision for this checklist clause found"
                in text_content_lower
            ):
                clause_data["clause_type"] = "StandardAZ"
                clause_data["details"]=clause_data["reason"]
            else:
                clause_data["clause_type"] = "Contractual"
        else:
            # If 'text' field is missing or not a string, default clause_type
            print(
                f"Warning: 'text' field missing or not a string for '{clause_title}'. 'clause_type' set to 'Unknown'."
            )
            clause_data["clause_type"] = "Unknown"


    ##Step 4 Identify the importance of risk
    clause_risk_levels = {clause["name"]: clause["details"]["clause_inherent_risk_level"] for clause in risk_rules["clauses"]}

    # Iterate through the payload and add the clause_inherent_risk_level
    for clause_name, clause_data in payload_json2.items():
        if isinstance(clause_data, dict): 
            if clause_name in clause_risk_levels:
                clause_data['risk_importance'] = clause_risk_levels[clause_name]
            else:
                clause_data['risk_importance'] = 'Unknown'
        else:
            print(f"Warning: Clause data for '{clause_name}' is not a dictionary. Skipping.") 
    
    #contract_risks=get_contract_risk_from_s3(userId,session_id,BUCKET_CONTAINER)
    

    ##Step 5 Get additional risks if any and add to the final structure
    body_prompt3 = get_additional_risk(
                    content,
                    clauses)
    
    llm_resp = ChatBedrock(
            model_id=MODEL_ID, max_tokens=4000
        ).invoke(body_prompt3)
    add_clauses = llm_resp.content.strip()
    add_clauses_v1 = _extract_json_list(add_clauses)

    assessment_answer = RiskAssessmentAnswer(ans='') 
    if isinstance(add_clauses_v1, list):
        for item_data in add_clauses_v1:
            try:
                if isinstance(item_data, dict):
                    title = str(item_data.get("title", "Untitled Additional Risk"))
                    description = str(item_data.get("description", "No description provided."))
                    assessment_answer.AdditionalPotentialRisks.append(
                        AdditionalRisk(title=title, description=description)
                    )
                else:
                    logger.warning(f"[{msg_id}] Skipping non-dict item in additional risks data: {item_data}")
            except ValidationError as e:
                logger.warning(f"[{msg_id}] Validation error for AdditionalRisk item {item_data}: {e}")
    elif add_clauses_v1 is not None: 
         logger.warning(f"[{msg_id}] Expected a list for additional risks, but got {type(add_clauses_v1)}. Data: {add_clauses_v1}")


    ##Step 6 Generating short summary 
    risk_summary=generate_prompt_summary(clauses, add_clauses_v1)
    try:
        llm_resp_summary = ChatBedrock(
            model_id=MODEL_ID, max_tokens=500
        ).invoke(risk_summary)
        summary_text = llm_resp_summary.content.strip()
        assessment_answer.ans = summary_text
        logger.info(f"[{msg_id}] LLM (overall summary) responded successfully.")
        logger.debug(f"[{msg_id}] Generated summary: {summary_text[:200]}")
    except Exception as exc:
        logger.exception(f"[{msg_id}] LLM call for overall summary failed")
        assessment_answer.ans = "" # Fallback summary

    ##Step 7 Semi - Final output creation
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
    
    response_data = assessment_answer.model_dump()
    ##Step 8 Storing the risk file on S3
    store_contract_risk_to_s3(userId,session_id,response_data,BUCKET_CONTAINER,compress=True)

    ##Step 9 Final output creation
    response_data = {
        "ans": assessment_answer.ans,
        "ContractualRisks": build_clean_risk_category_dict(assessment_answer.ContractualRisks),
        "StandardAZRisks": build_clean_risk_category_dict(assessment_answer.StandardAZRisks),
        "AdditionalPotentialRisks": [
            # The AdditionalRisk model is already clean, so a simple dump is fine here
            ar.model_dump() for ar in assessment_answer.AdditionalPotentialRisks
        ],
        "similarities": assessment_answer.similarities,
        "differences": assessment_answer.differences
    }

    return response_data


# def store_contract_risk_to_s3(userId,session_id,data,compress=True):
#     """
#     Stores a JSON-serializable dictionary in an S3 bucket.

#     Args:
#         data (dict): The dictionary to store.
#         bucket_name (str): The name of the S3 bucket.
#         object_key (str): The key (path) within the bucket where the data will be stored.
#         compress (bool, optional): Whether to compress the data using gzip. Defaults to True.
#     """
#     folder_path = f"contract_risks/{userId}/{session_id}/risk_data.json"
#     try:
#         json_data = json.dumps(data, indent=2) 
#         if compress:
#             buffer = io.BytesIO()
#             with gzip.GzipFile(fileobj=buffer, mode='wb') as gz:
#                 gz.write(json_data.encode('utf-8'))
#             body = buffer.getvalue()
#             content_encoding = 'gzip'
#         else:
#             body = json_data.encode('utf-8')
#             content_encoding = None

#         s3.put_object(
#             Bucket=BUCKET_CONTAINER,
#             Key=folder_path,
#             Body=body,
#             ContentType='application/json',
#             ContentEncoding=content_encoding 
#         )
#         logger.info(
#             f"[{session_id}] Successfully stored risk data to S3: s3://{BUCKET_CONTAINER}/{folder_path}"
#         )
#     except (BotoCoreError, ClientError) as exc:
#         logger.exception(f"[{session_id}] S3 upload failed")
#         raise HTTPException(500, "S3 upload failed") from exc

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
        if isinstance(data, list) and all(isinstance(item, dict) for item in data):  
            return data
        else:
            return None  # Not a list of dictionaries
    except json.JSONDecodeError:
        return None
    

def build_clean_risk_category_dict(risk_category: RiskCategory) -> dict:
        return {
            "HighRisksClauses": [
                {
                    "clause_name": risk_detail.clause_name + "(" + risk_detail.risk_importance + ")",
                    "risk_content": risk_detail.risk_content
                }
                for risk_detail in risk_category.HighRisksClauses
            ],
            "MediumRisksClauses": [
                {
                    "clause_name": risk_detail.clause_name +"(" + risk_detail.risk_importance + ")",
                    "risk_content": risk_detail.risk_content
                }
                for risk_detail in risk_category.MediumRisksClauses
            ],
            "LowRisksClauses": [
                {
                    "clause_name": risk_detail.clause_name +"(" + risk_detail.risk_importance + ")",
                    "risk_content": risk_detail.risk_content
                }
                for risk_detail in risk_category.LowRisksClauses
            ]
        }