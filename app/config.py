import io
import os
import boto3
from fastapi import APIRouter, HTTPException
import json

# This module will hold the loaded configuration values
BUCKET_NAME = None
EMBEDDING_MODEL_ID = None
GEN_ENQ_KB_ID = None
GUARDRAIL_ID = None
GUARDRAIL_VERSION_ID = None
IRRELEVANT_KEYWORD = None
MODEL_ARN = None
MODEL_ID = None
PRIVACY_KB_ID = None
QNA_FLOW_NAME = None
REGION_ID = None
#RND_KB_ID = None
SESSION_STATUS_ACTIVE = None
SUMMARY_FLOW_NAME = None
TABLE_NAME = None
QNA_TEMPRATURE_VALUE = None
QNA_SEARCH_TYPE = None
QNA_TOP_P_VALUE = None
QNA_TOP_K_VALUE = None
QNA_MAX_TOKENS_VALUE = None
QNA_COSINE_SIMILARITY_SCORE = None
API_KEY = None
BASE_URL_API = None
BASE_URL_UI = None
ALEXION_ID=None

config_router = APIRouter()
secret = ""

@config_router.get("/config")
async def load_config():
    try:
        load_values()
        return {"message": "Config loaded successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error in loading config data: {str(e)}")

@config_router.get("/config/{key}")
async def get_value(key: str):
    try:
        value = secret.get(key)        
        if value is None:
            return {"message": "Key is missing"}       
        return {key: value}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error in loading config data: {str(e)}")

def load_values():
    try:
        client = boto3.client(service_name="secretsmanager", region_name="us-east-1")
        # Get environment variables, picks the dev secret manager if os variable is empty 
        secret_name = os.getenv("secret_name", "aig-azcdi-us-ops-procure-ds-secret-dev")
        # Retrieve secret value
        get_secret_value_response = client.get_secret_value(SecretId=secret_name)
        global secret
        secret = json.loads(get_secret_value_response["SecretString"])
        # Extract values from the secret and assign them to the module-level variables
        global BUCKET_NAME, EMBEDDING_MODEL_ID, GEN_ENQ_KB_ID, GUARDRAIL_ID, GUARDRAIL_VERSION_ID
        global IRRELEVANT_KEYWORD, MODEL_ARN, MODEL_ID, PRIVACY_KB_ID, QNA_FLOW_NAME, REGION_ID
        global RND_KB_ID,ALEXION_ID, SESSION_STATUS_ACTIVE, SUMMARY_FLOW_NAME, TABLE_NAME, QNA_TEMPRATURE_VALUE
        global QNA_SEARCH_TYPE, QNA_TOP_P_VALUE, QNA_TOP_K_VALUE, QNA_MAX_TOKENS_VALUE, API_KEY

        BUCKET_NAME = secret.get("BUCKET_NAME")
        EMBEDDING_MODEL_ID = secret.get("EMBEDDING_MODEL_ID")
        GEN_ENQ_KB_ID = secret.get("GEN_ENQ_KB_ID")
        GUARDRAIL_ID = secret.get("GUARDRAIL_ID")
        GUARDRAIL_VERSION_ID = secret.get("GUARDRAIL_VERSION_ID")
        IRRELEVANT_KEYWORD = secret.get("IRRELEVANT_KEYWORD")
        MODEL_ARN = secret.get("MODEL_ARN")
        MODEL_ID = secret.get("MODEL_ID")
        PRIVACY_KB_ID = secret.get("PRIVACY_KB_ID")
        QNA_FLOW_NAME = secret.get("QNA_FLOW_NAME")
        REGION_ID = secret.get("REGION_ID")
        #RND_KB_ID = secret.get("RND_KB_ID")
        ALEXION_ID = secret.get("ALEXION_ID")
        
        SESSION_STATUS_ACTIVE = secret.get("SESSION_STATUS_ACTIVE")
        SUMMARY_FLOW_NAME = secret.get("SUMMARY_FLOW_NAME")
        TABLE_NAME = secret.get("TABLE_NAME")
        QNA_TEMPRATURE_VALUE = secret.get("QNA_TEMPRATURE_VALUE")
        QNA_SEARCH_TYPE = secret.get("QNA_SEARCH_TYPE")
        QNA_TOP_P_VALUE = secret.get("QNA_TOP_P_VALUE")
        QNA_TOP_K_VALUE = secret.get("QNA_TOP_K_VALUE")
        QNA_MAX_TOKENS_VALUE = secret.get("QNA_MAX_TOKENS_VALUE")
        QNA_COSINE_SIMILARITY_SCORE = secret.get("QNA_COSINE_SIMILARITY_SCORE")
        API_KEY = secret.get("API_KEY")
        print("Configuration values loaded successfully")

    except Exception as e:
        raise Exception(f"Error in loading required data: {str(e)}")

load_values()


##Hardcoded Values
PRIORITZE_DOCUMENT = 'CAN HANDBOOK Third Edition.pdf'
