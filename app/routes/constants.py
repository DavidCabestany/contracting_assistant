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
