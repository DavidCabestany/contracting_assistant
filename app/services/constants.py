"""Centralised configuration and constant values for QnA services.

This module defines:
- Dynamic values fetched at runtime from AWS Secrets Manager via `get_secret`
- Static constants used for tuning (e.g., temperature, max tokens)
- Prompt mapping file locations
- Logging and AWS client setup
- Priority query definitions
"""

import logging

from config import get_secret

# ─────── Dynamic config values (loaded at runtime) ───────
REGION_ID: str = get_secret("REGION_ID")
MODEL_ARN: str = get_secret("MODEL_ARN")
EMBEDDING_MODEL_ID: str = get_secret("EMBEDDING_MODEL_ID")
MODEL_ID: str = get_secret("MODEL_ID")
BUCKET_CONTAINER: str = get_secret("BUCKET_CONTAINER")
QNA_FLOW_NAME: str = get_secret("QNA_FLOW_NAME")
SUMMARY_FLOW_NAME: str = get_secret("SUMMARY_FLOW_NAME")
GEN_ENQ_KB_ID: str = get_secret("GEN_ENQ_KB_ID")
SESSION_STATUS: str = get_secret("SESSION_STATUS_ACTIVE")
IRRELEVANT: str = get_secret("IRRELEVANT_KEYWORD")
QNA_SEARCH_TYPE: str = get_secret("QNA_SEARCH_TYPE")
GUARDRAIL_ID: str = get_secret("GUARDRAIL_ID")
GUARDRAIL_VERSION_ID: str = get_secret("GUARDRAIL_VERSION_ID")
QNA_MAX_TOKENS_VALUE: int = 4000
PRIOR_DOC: str = get_secret("PRIOR_DOC")

# ─────── Static tuning knobs ───────
QNA_MAX_TOKENS: int = 4096
QNA_TEMPERATURE: float = 0.1
QNA_TOP_P: float = 0.7

# ─────── Prompt mapping file location ───────
EXCEL_FILE_PATH: str = "mappings/prompt_map.xlsx"
AZ_MAPPING_SHEET_NAME: str = "Sheet1"

# ─────── Logger setup ───────
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ─────── High-priority queries ───────
HIGH_PRIORITY_QUERIES = {
    "General Queries": {
        "what are az standard payment terms?",
        "what are AZ standard payment terms for Vendors located in France?",
        "what are AZ standard payment terms for France",
        "what minimum audit rights do we require in a contract?",
        "the supplier doesn't want to accept out standard payment terms, what can i do?",
        "who decides on the liability cap?",
        "What payment terms should be used in France",
        "What payment terms should be used in Germany",
    },
    "Privacy": {
        "what are the mandatory incident reporting timeframes depending on jurisdiction?",
        "when should i add swiss or uk addendum to privacy terms?",
        "i have technological measures listed already in data privacy appendix. can i refer to them in sccs or i should copy them explicitly?",
        "i do not see list of affiliates covered by data privacy terms and sccs in the documents. where should relevant controllers (affiliates) be listed?",
        "Can the liability for a cyber security incydent be capped?",
        "What to do in case of an cyber security incident?",
        "Im in procurement, can I decide on the liability cap?",
    },
    "Alexion": {
        "what are the thresholds for legal review of contracts at alexion?",
        "what is the process for creating and approving a contract in icertis at alexion?",
        "who are the local legal contacts for different countries in alexion's procurement process?",
        "what is the role of 3prm (third-party risk management) in alexion's vendor onboarding process?",
    },
}

## Documentation Topics for detect_prior_doc_from_query
DOCUMENT_TOPICS = [
    {
        "file": [
            "Playbook_Data Protection Appendix - AZ Controller to Supplier Processor.pdf"
        ],
        "keywords": ["data protection appendix", "controller", "processor"],
    },
    {
        "file": [
            "Playbook_Data Protection Appendix – Controller to Dual Role Processor.pdf"
        ],
        "keywords": ["supplier", "controller", "processor"],
    },
    {
        "file": [
            "Playbook_Data Protection Appendix – receiving Anonymised Data.pdf",
            "Playbook_Data Protection Appendix – sharing Anonymised Data.pdf",
            "Data Protection Terms Decision Tree.pdf",
        ],
        "keywords": ["dpa", "anonymized"],
    },
    {
        "file": [
            "Playbook_Data Protection Appendix - AZ Controller to Supplier Processor.pdf",
        ],
        "keywords": ["dpa"],
    },
    {
        "file": [
            "Playbook_Data Protection Appendix – receiving Anonymised Data.pdf",
            "Playbook_Data Protection Appendix – sharing Anonymised Data.pdf",
            "Data Protection Terms Decision Tree.pdf",
        ],
        "keywords": ["data protection appendix", "anonymised"],
    },
    {
        "file": [
            "Playbook_Data Protection Appendix – receiving Anonymised Data.pdf",
            "Playbook_Data Protection Appendix – sharing Anonymised Data.pdf",
            "Data Protection Terms Decision Tree.pdf",
        ],
        "keywords": ["data protection appendix", "anonymized"],
    },
    {
        "file": [
            "Data Protection Appendix - Sharing Anonymised Data.pdf",
            "Playbook_Data Protection Appendix – receiving Anonymised Data.pdf",
            "Data Protection Appendix – Receiving Anonymised Data.pdf",
            "Playbook_Data Protection Appendix – sharing Anonymised Data.pdf",
        ],
        "keywords": ["anonymized"],
    },
    {
        "file": [
            "Data Protection Appendix - Sharing Anonymised Data.pdf",
            "Playbook_Data Protection Appendix – receiving Anonymised Data.pdf",
            "Data Protection Appendix – Receiving Anonymised Data.pdf",
            "Playbook_Data Protection Appendix – sharing Anonymised Data.pdf",
        ],
        "keywords": ["anonymised"],
    },
    {
        "file": [
            "Playbook_Data Protection Appendix – Controller to Controller - sharing Personal Data .pdf",
            "Playbook_Data Protection Appendix – Controller to Controller - receiving Personal Data .pdf",
        ],
        "keywords": ["data protection appendix", "personal", "personal data"],
    },
    {
        "file": [
            "Playbook_Data Protection Appendix – Controller to Controller - sharing Personal Data .pdf",
            "Playbook_Data Protection Appendix – Controller to Controller - receiving Personal Data .pdf",
        ],
        "keywords": ["liability"],
    },
    {
        "file": [
            "SCCs_Module_1_C2C+_Exhibit_Y_+_Addendums.pdf",
            "SCCs_Module_2_C2P+_Exhibit_Y_+_Addendums.pdf",
            "SCCs_Module_4_P2C+_Exhibit_Y_+_Addendums.pdf",
        ],
        "keywords": ["addendum", "uk", "swiss"],
    },
    {
        "file": [
            "California Consumer Privacy Act Addendum to DPA.pdf",
        ],
        "keywords": ["california", "ccpa"],
    },
]

# TIA Clarification Constants

## TIA Clarification ───────
FINAL_RESPONSE_REQUIRED = "FINAL_RESPONSE_REQUIRED"

# 1. TIA Clarification Questions
TIA_INITIAL_FIXED_QUESTIONS = [
    "What type of data is being processed?",
    "What is the direction of the data flow (are we sharing data with the vendor or are we receiving data from the vendor)?",
    "If we share data, will the vendor process it on our behalf or for its own purposes?",
    "If we receive data, do we receive it for our own purposes?",
]

# 2. TIA Keyword Mapping
TIA_FOLLOWUP_KEYWORDS = {
    "type of data": [
        "patient",
        "patients",
        "clinical",
        "trial",
        "clinical trial",
        "participant",
        "sample",
        "subject",
        "sensitive data",
        "sensitive information",
        "health",
        "health info",
        "biological",
        "medical data",
        "anonymized",
        "anonymised",
        "pseudonymized",
        "pseudo",
        "raw data",
        "de-identified",
        "dataset",
    ],
    "data flow": [
        "share",
        "shared",
        "sharing",
        "send",
        "sent",
        "sending",
        "transfer",
        "transferred",
        "transferring",
        "receive",
        "receiving",
        "received",
        "from vendor",
        "to vendor",
        "from institution",
        "to institution",
        "vendor to az",
        "az to vendor",
        "institution to az",
        "az to institution",
        "send to",
        "sent by",
        "received by",
        "received from",
    ],
    "share data details": [
        "on our behalf",
        "their own purposes",
        "for its own use",
        "process data",
        "controller",
        "processor",
        "acting as a processor",
        "acting as a controller",
        "sub-processor",
        "uses data",
        "handling on behalf of",
        "owner",
    ],
    "receive data details": [
        "for our own purposes",
        "internal use",
        "for our benefit",
        "own use",
        "research purpose",
        "regulatory",
        "analysis",
        "presenting",
        "az use only",
        "az's purposes",
    ],
    "vendor identity": [
        "vendor",
        "institution",
        "supplier",
        "third party",
        "site",
        "provider",
        "partner",
        "consultant",
        "research org",
        "affiliate",
    ],
    "location": [
        "uk",
        "eu",
        "europe",
        "outside uk",
        "outside eu",
        "international",
        "cross-border",
        "within eu",
        "within uk",
        "not leaving uk",
        "not leaving eu",
        "not transferred",
        "not moving outside",
    ],
}

# 3. TIA Field-to-Question Map
QUESTION_MAP = {
    "type of data": TIA_INITIAL_FIXED_QUESTIONS[0],
    "data flow": TIA_INITIAL_FIXED_QUESTIONS[1],
    "share data details": TIA_INITIAL_FIXED_QUESTIONS[2],
    "receive data details": TIA_INITIAL_FIXED_QUESTIONS[3],
}
