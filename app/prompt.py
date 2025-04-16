from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import boto3
import openpyxl
import pandas as pd
import numpy as np

# TODO: remove duplicates
from sklearn.metrics.pairwise import cosine_similarity
import json
import warnings
from sklearn.metrics.pairwise import cosine_similarity
import json
from datetime import datetime
from botocore.config import Config

# TODO: change the way we import the config functions

from config import get_config_value

# TODO: Clean the unused imports

from data import (
    QueryRequest,
    QnaAnswer,
    AnswerRequest,
    User,
    Query,
    RequestQuery,
    Citation,
    QuickReply,
    Result,
    QueryResponse,
    FeedbackDisplayOptions,
    Feedback,
    ChatInteraction,
    ChatMetadata,
    ChatHistorySearchRequest,
    FeedbackRequest,
)

# TODO: remove unwantef f string format


REGION_ID = get_config_value("REGION_ID")
TABLE_NAME = get_config_value("TABLE_NAME")
MODEL_ARN = get_config_value("MODEL_ARN")
EMBEDDING_MODEL_ID = get_config_value("EMBEDDING_MODEL_ID")
BUCKET_NAME = get_config_value("BUCKET_NAME")
QNA_SEARCH_TYPE = get_config_value("QNA_SEARCH_TYPE")
GUARDRAIL_ID = get_config_value("GUARDRAIL_ID")
GUARDRAIL_VERSION_ID = get_config_value("GUARDRAIL_VERSION_ID")
QNA_MAX_TOKENS_VALUE = get_config_value("QNA_MAX_TOKENS_VALUE")
QNA_TEMPRATURE_VALUE = get_config_value("QNA_TEMPRATURE_VALUE")
QNA_TOP_P_VALUE = get_config_value("QNA_TOP_P_VALUE")
MODEL_ID = get_config_value("MODEL_ID")

EXCEL_FILE_PATH = f"mappings/prompt_map.xlsx"
AZ_MAPPING_SHEET_NAME = "Sheet1"

# Initialize an empty dictionary to store embeddings
embeddings_map = {}

# Create a custom configuration with increased max connections
boto_config = Config(retries={"max_attempts": 3}, max_pool_connections=50)
bedrock_agent_runtime = boto3.client(
    service_name="bedrock-agent-runtime", config=boto_config
)
bedrock_client = boto3.client(
    "bedrock-runtime", region_name=REGION_ID, config=boto_config
)
s3_client = boto3.client("s3", config=boto_config)


def get_embeddings(text):
    payload = {"inputText": f"""{text}\""""}
    response = bedrock_client.invoke_model(
        modelId=EMBEDDING_MODEL_ID,
        contentType="application/json",
        accept="*/*",
        body=json.dumps(payload).encode("utf-8"),
    )
    response_body = json.loads(response["body"].read().decode("utf-8"))
    return response_body["embedding"]


def compare_similarity(input_embeddings: str, prompt_template_question: str):
    global embeddings_map  # Declare the global variable
    try:
        # Check if the embedding for prompt_template_question is already calculated and stored
        if prompt_template_question not in embeddings_map:
            prompt_question_embedding = get_embeddings(prompt_template_question)
            embeddings_map[prompt_template_question] = prompt_question_embedding
        else:
            prompt_question_embedding = embeddings_map[prompt_template_question]
        # Calculate cosine similarity
        similarity_score = cosine_similarity(
            [input_embeddings], [prompt_question_embedding]
        )[0][0]
        return similarity_score
    except Exception as e:
        print(f"ERROR: Can't invoke '{EMBEDDING_MODEL_ID}'. Reason: {e}")
        raise Exception(f"Error in compare similarity: {e}")


warnings.filterwarnings("ignore", message="Passing bytes to 'read_excel' is deprecated")


def get_mapping_list():
    try:
        response = s3_client.get_object(Bucket=BUCKET_NAME, Key=EXCEL_FILE_PATH)
        excel_file_content = response["Body"].read()
        df_mapping = pd.read_excel(excel_file_content, sheet_name=AZ_MAPPING_SHEET_NAME)
        question_category_ls = df_mapping["Question"].tolist()
        map_prompt_ls = df_mapping["Prompt"].tolist()
    except Exception as e:
        print(f"ERROR: Error in retrieving template. Reason: {e}")
        raise Exception(f"Error in retrieving template: {e}")
    return {"question_ls": question_category_ls, "prompt_ls": map_prompt_ls}


def retrieve_template(user_query: str):
    row_index = 10000
    prompt_template = ""
    prompts = []
    try:
        # Retrieve question and prompt lists from the S3 file
        result = get_mapping_list()
        list_question = result["question_ls"]
        input_embeddings = get_embeddings(user_query)
        # Find the index of the most similar question to the user query
        similarity_scores = np.array(
            [
                compare_similarity(input_embeddings, question)
                for question in list_question
            ]
        )
        row_index = np.argmax(similarity_scores)
        # Extract the corresponding prompt template
        if similarity_scores[row_index] > 0.6:
            prompts = result["prompt_ls"]
            prompt_template = str(prompts[row_index])
    except Exception as e:
        raise Exception(f"Error in retrieving template: {e}")
    return prompt_template


def retrieve_and_generate(
    query: str, kb_id: str, model_id: str, region_id: str, session_id: str
):
    try:
        prompt_template = retrieve_template(query)
        prompt_template += """\n\n%ADDITIONAL INSTRUCTIONS%:\n Please treat suppliers and vendors as alias in the chunks."""
        prompt_template += f"\n\n%USER QUERY:\n{query}\n"
        return bedrock_agent_runtime.retrieve_and_generate(
            input={"text": prompt_template},
            retrieveAndGenerateConfiguration={
                "knowledgeBaseConfiguration": {
                    "knowledgeBaseId": kb_id,
                    "modelArn": MODEL_ARN,
                    "retrievalConfiguration": {
                        "vectorSearchConfiguration": {
                            "overrideSearchType": QNA_SEARCH_TYPE,
                            "numberOfResults": 3,
                        }
                    },
                    "generationConfiguration": {
                        "guardrailConfiguration": {
                            "guardrailId": GUARDRAIL_ID,
                            "guardrailVersion": GUARDRAIL_VERSION_ID,
                        },
                        "inferenceConfig": {
                            "textInferenceConfig": {
                                "maxTokens": int(QNA_MAX_TOKENS_VALUE),
                                "temperature": float(QNA_TEMPRATURE_VALUE),
                                "topP": float(QNA_TOP_P_VALUE),
                            }
                        },
                    },
                },
                "type": "KNOWLEDGE_BASE",
            },
            **({"sessionId": session_id} if session_id else {}),  # Conditionally add
        )
    except Exception as e:
        raise Exception(f"Error in retrieving q&a answer: {e}")


# TODO: move the prompting to a separate file

follow_up_prompt = """You are an AI assistant helping to understand the flow of conversation in a technical troubleshooting scenario. Your job is to determine if a new question is related to a previous question and its answer
Here's how to analyze the relationship:
* **Follow-up:** If the second question is seeking more information,clarification or a specific step related to the first question and its answer, its a FOLLOW-UP.
* **New Question:** If the second question introduces a different problem, requests information unrelated to the first question,or could be asked independently, its a NEW QUESTION.
Analyze the relationship between these queries:
Query 1:{}
Query 2:{}

Respond with only one label:follow-up or New Question. """


def generate_answer_with_context(formatted_prompt):
    try:
        body = json.dumps(
            {
                "anthropic_version": "bedrock-2023-05-31",  # or "bedrock-2024-05-31", check the docs.
                "max_tokens": int(QNA_MAX_TOKENS_VALUE),
                "messages": [{"role": "user", "content": formatted_prompt}],
            }
        )

        response = bedrock_client.invoke_model(
            body=body,
            modelId=MODEL_ID,
            accept="application/json",
            contentType="application/json",
            guardrailIdentifier=GUARDRAIL_ID,
            guardrailVersion=GUARDRAIL_VERSION_ID,
        )

        response_body = json.loads(response["body"].read().decode("utf-8"))

        return response_body

    except Exception as e:
        raise Exception(f"Error during answer generation: {e}")


def get_s3_path(bucket_name, folder_name):
    return f"s3://{bucket_name}/{folder_name}/"


def add_s3_prefix_to_files(files, bucket_name, folder_name):
    s3_prefix = get_s3_path(bucket_name, folder_name)
    updated_files = [s3_prefix + file for file in files]
    return updated_files


# TODO: remove unwantef f string format


def retrieve_and_generate_prioritized_doc(
    query: str,
    kb_id: str,
    knowledge_base_folder: str,
    model_id: str,
    region_id: str,
    session_id: str,
    files: list,
):
    try:
        prompt_template = ""
        if str(retrieve_template(query)) != "nan":
            prompt_template = retrieve_template(query)
        GENERAL_QUERIES_DOCUMENT_PATH = add_s3_prefix_to_files(
            files, BUCKET_NAME, knowledge_base_folder
        )
        prompt_template += f"""\n\n%ADDITIONAL INSTRUCTIONS%:\n Please treat suppliers and vendors as alias in the chunks."""
        prompt_template += f"\n\n%USER QUERY:\n{query}\n"
        return bedrock_agent_runtime.retrieve_and_generate(
            input={"text": prompt_template},
            retrieveAndGenerateConfiguration={
                "knowledgeBaseConfiguration": {
                    "knowledgeBaseId": kb_id,
                    "modelArn": MODEL_ARN,
                    "retrievalConfiguration": {
                        "vectorSearchConfiguration": {
                            "overrideSearchType": QNA_SEARCH_TYPE,
                            "filter": {
                                "in": {
                                    "key": "x-amz-bedrock-kb-source-uri",
                                    "value": GENERAL_QUERIES_DOCUMENT_PATH,
                                }
                            },
                            "numberOfResults": 3,
                        }
                    },
                    "generationConfiguration": {
                        "guardrailConfiguration": {
                            "guardrailId": GUARDRAIL_ID,
                            "guardrailVersion": GUARDRAIL_VERSION_ID,
                        },
                        "inferenceConfig": {
                            "textInferenceConfig": {
                                "maxTokens": int(QNA_MAX_TOKENS_VALUE),
                                "temperature": float(QNA_TEMPRATURE_VALUE),
                                "topP": float(QNA_TOP_P_VALUE),
                            }
                        },
                    },
                },
                "type": "KNOWLEDGE_BASE",
            },
            **({"sessionId": session_id} if session_id else {}),  # Conditionally add
        )
    except Exception as e:
        raise Exception(f"Error in retrieving q&a answer: {e}")


def retrieve_documents(
    query: str, kb_id: str, region_id: str, filter_value: str = None
):
    try:
        bedrock_agent_runtime = boto3.client(
            "bedrock-agent-runtime", region_name=region_id
        )

        # Build the retrieval configuration
        retrieval_configuration = {
            "vectorSearchConfiguration": {
                "overrideSearchType": QNA_SEARCH_TYPE,
                "numberOfResults": 3,
            }
        }

        # Conditionally add the filter
        if filter_value:
            retrieval_configuration["vectorSearchConfiguration"]["filter"] = {
                "equals": {"key": "x-amz-bedrock-kb-source-uri", "value": filter_value}
            }

        # Construct the full request
        request = {
            "knowledgeBaseId": kb_id,  # Required at the top level
            "retrievalQuery": {
                "text": query  # Query goes inside 'retrievalQuery' object
            },
            "retrievalConfiguration": retrieval_configuration,  # Not 'retrieveConfiguration'
        }

        # Invoke the API
        response = bedrock_agent_runtime.retrieve(**request)
        return response

    except Exception as e:
        raise Exception(f"Error during document retrieval: {e}")
