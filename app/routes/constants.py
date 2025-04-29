# services/config.py
import logging

import boto3
from config import get_config_value

logger = logging.getLogger(__name__)


S3 = boto3.client("s3")
BUCKET_CONTAINER = get_config_value("BUCKET_CONTAINER")
QNA_FLOW_NAME = get_config_value("QNA_FLOW_NAME")
MODEL_ID = get_config_value("MODEL_ID")
REGION_ID = get_config_value("REGION_ID")
SESSION_STATUS = get_config_value("SESSION_STATUS_ACTIVE")
IRRELEVANT = get_config_value("IRRELEVANT_KEYWORD")
GEN_ENQ_KB_ID = get_config_value("GEN_ENQ_KB_ID")
SUMMARY_FLOW_NAME = get_config_value("SUMMARY_FLOW_NAME")
PRIOR_DOC = "CAN HANDBOOK Third Edition.pdf"
