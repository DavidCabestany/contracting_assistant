"""Loads configuration values and initializes constants for QnA services."""

import logging

import boto3
from config import get_secret

logger = logging.getLogger(__name__)


s3_client = boto3.client("s3")
BUCKET_CONTAINER = get_secret("BUCKET_CONTAINER")
QNA_FLOW_NAME = get_secret("QNA_FLOW_NAME")
MODEL_ID = get_secret("MODEL_ID")
REGION_ID = get_secret("REGION_ID")
SESSION_STATUS = get_secret("SESSION_STATUS_ACTIVE")
IRRELEVANT = get_secret("IRRELEVANT_KEYWORD")
GEN_ENQ_KB_ID = get_secret("GEN_ENQ_KB_ID")
SUMMARY_FLOW_NAME = get_secret("SUMMARY_FLOW_NAME")
PRIOR_DOC = "CAN HANDBOOK 4.0.pdf"

HIGH_PRIORITY_QUERIES = {
    "General Queries": {
        "what are az standard payment terms?",
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
