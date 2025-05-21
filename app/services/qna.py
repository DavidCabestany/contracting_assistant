# services/qna.py
"""High-level Bedrock Q&A helpers.

This module handles prompt formatting, configuration building, and calls to
Bedrock's retrieve-and-generate APIs with optional guardrails and source filtering.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence

import boto3
from utils import extract_file_locations

from .clients import bedrock_agent_runtime, bedrock_client
from .config import (
    BUCKET_CONTAINER,
    GUARDRAIL_ID,
    GUARDRAIL_VERSION_ID,
    MODEL_ARN,
    MODEL_ID,
    QNA_MAX_TOKENS_VALUE,
    QNA_SEARCH_TYPE,
)
from .storage import add_prefix
from .templates import retrieve_template

EXCEL_FILE_PATH = "mappings/prompt_map.xlsx"
AZ_MAPPING_SHEET_NAME = "Sheet1"
logger = logging.getLogger(__name__)

s3 = boto3.client("s3")

QNA_MAX_RESULTS = 3


def generate_answer_with_context(formatted_prompt: str) -> dict:
    """Perform a basic prompt completion call using Bedrock's chat model.

    Args:
        formatted_prompt (str): The prompt text to send to the model.

    Returns:
        dict: Parsed JSON result from Bedrock's model invocation.
    """
    logger.info(
        "[Checkpoint] Step 1: Building request body for Bedrock model..."
    )

    style_prompt = """
        When generating your response, maintain a clear, professional, and direct tone. Strictly avoid the comenting.

        • Don't apologise. Don't comment about user. don't greet. don't praise.
        • avoid any kind of disclaimers (e.g., "As previously mentioned", "To clarify again", etc.)
        • Don't make open-ended invitations or offers for further questions (e.g., "Let me know if you need more", "Feel free to ask", etc.)
        • avoid irrelevant fillers — stick to concise and informative language.

        JUST GIVE THE REQUESTED INFO.

        Only provide the information requested. Do not include unnecessary commentary or emotional framing.
        The question: """
    body = json.dumps(
        {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": QNA_MAX_TOKENS_VALUE,
            "messages": [
                {"role": "user", "content": style_prompt + formatted_prompt}
            ],
        },
    )
    logger.info("[Checkpoint] Step 2: Invoking Bedrock model...")
    try:
        response = bedrock_client.invoke_model(
            body=body,
            modelId=MODEL_ID,
            accept="application/json",
            contentType="application/json",
            guardrailIdentifier=GUARDRAIL_ID,
            guardrailVersion=GUARDRAIL_VERSION_ID,
        )
        logger.info("[Checkpoint] Bedrock model invoked successfully.")
    except Exception as e:
        logger.info(
            f"[Error] Failed to invoke Bedrock model: {str(e)}",
        )
        raise

    logger.info("[Checkpoint] Step 3: Reading and decoding response...")
    try:
        raw_response = response["body"].read().decode()

        result = json.loads(raw_response)
        logger.info("[Checkpoint] JSON parsed successfully.")
        return result
    except Exception as e:
        logger.info(
            f"[Error] Failed to decode or parse response: {str(e)}",
        )
        raise


def _render_prompt(user_query: str, base_prompt: str | None = None) -> str:
    """Render a complete prompt string using a base template and user input.

    Args:
        user_query (str): The original user question.
        base_prompt (Optional[str]): A custom template, if provided.

    Returns:
        str: A complete prompt ready for LLM ingestion.
    """
    tmpl = (
        base_prompt
        if base_prompt is not None
        else retrieve_template(user_query)
    )
    tmpl = str(tmpl)
    tmpl += "\n\n%ADDITIONAL INSTRUCTIONS%:\nPlease treat suppliers and vendors as aliases in the chunks."
    tmpl += f"\n\n%USER QUERY:\n{user_query}\n"
    return tmpl


def _build_gen_cfg() -> dict:
    """Build the generation configuration including temperature, top-p, and guardrails.

    Returns:
        dict: Configuration block for generation.
    """
    return {
        "guardrailConfiguration": {
            "guardrailId": GUARDRAIL_ID,
            "guardrailVersion": GUARDRAIL_VERSION_ID,
        },
        "inferenceConfig": {
            "textInferenceConfig": {
                "maxTokens": QNA_MAX_TOKENS_VALUE,
                "temperature": 0,
                "topP": 1.0,
            },
        },
    }


def retrieve_file_chunks(
    kb_id: str,
    documents: list[str],
    kb_path: str,
    query: str,
) -> dict[str, str]:
    """Retrieve text specific documents.

    Args:
        kb_id (str): The Bedrock KB ID.
        documents (list[str]): List of filenames in S3.
        kb_path (str): Folder where the docs are stored.
        query (str): Initial user question for context.

    Returns:
        dict[str, str]: filename → extracted full text from matched chunks.
    """
    from .config import BUCKET_CONTAINER, MODEL_ARN

    file_contents = {}
    logger.info("starting the retrieval")
    logger.info("✅ query: %s", query)
    for doc in documents:
        s3_uri = f"s3://{BUCKET_CONTAINER}/{kb_path}/{doc}"
        logger.info("▶ Retrieving content from: %s", s3_uri)

        request_body = {
            "input": {"text": query},
            "retrieveAndGenerateConfiguration": {
                "knowledgeBaseConfiguration": {
                    "knowledgeBaseId": kb_id,
                    "modelArn": MODEL_ARN,
                    "retrievalConfiguration": {
                        "vectorSearchConfiguration": {
                            "overrideSearchType": QNA_SEARCH_TYPE,
                            "numberOfResults": QNA_MAX_RESULTS,
                            "filter": {
                                "equals": {
                                    "key": "x-amz-bedrock-kb-source-uri",
                                    "value": s3_uri,
                                }
                            },
                        }
                    },
                    "generationConfiguration": _build_gen_cfg(),
                },
                "type": "KNOWLEDGE_BASE",
            },
        }
        try:
            response = bedrock_agent_runtime.retrieve_and_generate(
                **request_body
            )
            chunks = response.get("citations", [])
            file_text = "\n\n".join(
                c["generatedResponsePart"]["textResponsePart"]["text"]
                for c in chunks
                if "generatedResponsePart" in c
                and "textResponsePart" in c["generatedResponsePart"]
            )
            file_contents[doc] = file_text.strip()
            logger.info("✅ File contents: %s", file_contents)
            logger.info("✅ File retrieved: %s", doc)
        except Exception as e:
            logger.warning("❌ Failed to retrieve %s: %s", doc, e)
            file_contents[doc] = f"[Error: {e}]"

    return file_contents


def retrieve_and_generate(
    query: str,
    kb_id: str,
    *,
    document: str | None = None,
    session_id: str | None = None,
    kb_path: str | None = None,
):
    """Run Bedrock's retrieve-and-generate pipeline using the general KB."""
    logger.info("ENTER ▶ retrieve_and_generate")

    prompt_text = _render_prompt(query)
    logger.debug("Prompt: %.200s", prompt_text.replace("\n", " "))
    logger.debug(
        "KB ID: %s | kb_path: %s | document: %s | session_id: %s",
        kb_id,
        kb_path,
        document,
        session_id,
    )

    filter_config = {}
    if document and kb_path:
        s3_uri = f"s3://{BUCKET_CONTAINER}/{kb_path}/{document}"
        filter_config = {
            "equals": {
                "key": "x-amz-bedrock-kb-source-uri",
                "value": s3_uri,
            }
        }
        logger.info("Applying document filter on: %s", s3_uri)
    else:
        logger.info("No specific document filter applied — full KB search")

    request_body = {
        "input": {"text": prompt_text},
        "retrieveAndGenerateConfiguration": {
            "knowledgeBaseConfiguration": {
                "knowledgeBaseId": kb_id,
                "modelArn": MODEL_ARN,
                "retrievalConfiguration": {
                    "vectorSearchConfiguration": {
                        "overrideSearchType": QNA_SEARCH_TYPE,
                        "numberOfResults": QNA_MAX_RESULTS,
                        **({"filter": filter_config} if filter_config else {}),
                    },
                },
                "generationConfiguration": _build_gen_cfg(),
            },
            "type": "KNOWLEDGE_BASE",
        },
        **({"sessionId": session_id} if session_id else {}),
    }

    logger.debug("Request payload: %s", json.dumps(request_body, indent=2))

    try:
        response = bedrock_agent_runtime.retrieve_and_generate(**request_body)
        logger.info("EXIT ▶ retrieve_and_generate — success")
        logger.debug("Bedrock response: %s", json.dumps(response, indent=2))
        return response
    except Exception:
        logger.exception("Bedrock retrieve_and_generate FAILED")
        raise


def retrieve_and_generate_prioritized_doc(
    query: str,
    kb_id: str,
    knowledge_base_folder: str,
    files: Sequence[str],
    *,
    session_id: str | None = None,
):
    """Same as retrieve_and_generate, but limits the search to specific files only.

    Args:
        query (str): The user question.
        kb_id (str): The knowledge base ID.
        knowledge_base_folder (str): S3 prefix path for the documents.
        files (Sequence[str]): List of file names to filter retrieval on.
        session_id (Optional[str]): Optional session identifier.

    Returns:
        dict: Retrieved and generated output limited to selected files.
    """
    logger.info("ENTER ▶ retrieve_and_generate_prioritized_doc")
    logger.info("Step 1 ▶ Building prompt for query: %.100s", query)
    prompt_text = _render_prompt(query)
    logger.info(
        "Step 2 ▶ Prompt built (length=%d): %.200s",
        len(prompt_text),
        prompt_text.replace("\n", " "),
    )

    logger.info(
        "Step 3 ▶ Resolving allowed file paths from input files: %s", files
    )
    allowed_paths = add_prefix(files, BUCKET_CONTAINER, knowledge_base_folder)
    logger.info("Step 4 ▶ Allowed S3 paths: %s", allowed_paths)

    request_body = {
        "input": {"text": prompt_text},
        "retrieveAndGenerateConfiguration": {
            "knowledgeBaseConfiguration": {
                "knowledgeBaseId": kb_id,
                "modelArn": MODEL_ARN,
                "retrievalConfiguration": {
                    "vectorSearchConfiguration": {
                        "overrideSearchType": QNA_SEARCH_TYPE,
                        "filter": {
                            "in": {
                                "key": "x-amz-bedrock-kb-source-uri",
                                "value": allowed_paths,
                            },
                        },
                        "numberOfResults": QNA_MAX_RESULTS,
                    },
                },
                "generationConfiguration": _build_gen_cfg(),
            },
            "type": "KNOWLEDGE_BASE",
        },
    }

    if session_id:
        request_body["sessionId"] = session_id
        logger.info("Step 5 ▶ Using existing session_id: %s", session_id)
    else:
        logger.info("Step 5 ▶ No session_id provided — starting new session")

    logger.info("Step 6 ▶ Final request payload ready for Bedrock call.")
    try:
        response = bedrock_agent_runtime.retrieve_and_generate(**request_body)
        logger.info(
            "EXIT  ◀ retrieve_and_generate_prioritized_doc — SUCCESSFUL call"
        )
        return response
    except Exception as e:
        logger.error(
            "EXIT  ◀ retrieve_and_generate_prioritized_doc — FAILED call: %s",
            str(e),
        )
        raise


def retrieve_citations_from_query(
    query: str,
    kb_id: str,
    kb_path: str = "general",  # default as needed
    files: list[str] | None = None,
    session_id: str | None = None,
) -> list[dict]:
    """Run Bedrock retrieve-and-generate and extract only citations.

    Args:
        query (str): User query string.
        kb_id (str): Knowledge Base ID.
        kb_path (str): Folder/prefix path in S3 for documents.
        files (list[str] | None): Optional list of file names to restrict retrieval.
        session_id (str | None): Optional session identifier.

    Returns:
        list[dict]: List of citations as dicts (filePath, pageNumber, fileName).
    """
    if files:
        resp = retrieve_and_generate_prioritized_doc(
            query=query,
            kb_id=kb_id,
            knowledge_base_folder=kb_path,
            files=files,
            session_id=session_id,
        )
    else:
        resp = retrieve_and_generate(
            query=query,
            kb_id=kb_id,
            session_id=session_id,
            kb_path=kb_path,
        )

    citations = extract_file_locations(resp)
    return citations


########################### OLD PROD CODE ##################################


# def get_embeddings(text):
#     payload = {"inputText": f"""{text}\""""}
#     response = bedrock_client.invoke_model(
#         modelId=EMBEDDING_MODEL_ID,
#         contentType="application/json",
#         accept="*/*",
#         body=json.dumps(payload).encode("utf-8"),
#     )
#     response_body = json.loads(response["body"].read().decode("utf-8"))
#     return response_body["embedding"]


# def compare_similarity(input_embeddings: str, prompt_template_question: str):
#     global embeddings_map  # Declare the global variable
#     try:
#         # Check if the embedding for prompt_template_question is already calculated and stored
#         if prompt_template_question not in embeddings_map:
#             prompt_question_embedding = get_embeddings(prompt_template_question)
#             embeddings_map[prompt_template_question] = prompt_question_embedding
#         else:
#             prompt_question_embedding = embeddings_map[prompt_template_question]
#         # Calculate cosine similarity
#         similarity_score = cosine_similarity([input_embeddings], [prompt_question_embedding])[0][0]
#         return similarity_score
#     except Exception as e:
#         print(f"ERROR: Can't invoke '{EMBEDDING_MODEL_ID}'. Reason: {e}")
#         raise Exception(f"Error in compare similarity: {e}")


# def get_mapping_list():
#     try:
#         response = s3.get_object(Bucket=BUCKET_CONTAINER, Key=EXCEL_FILE_PATH)
#         excel_file_content = response["Body"].read()
#         df_mapping = pd.read_excel(excel_file_content, sheet_name=AZ_MAPPING_SHEET_NAME)
#         question_category_ls = df_mapping["Question"].tolist()
#         map_prompt_ls = df_mapping["Prompt"].tolist()
#     except Exception as e:
#         print(f"ERROR: Error in retrieving template. Reason: {e}")
#         raise Exception(f"Error in retrieving template: {e}")
#     return {"question_ls": question_category_ls, "prompt_ls": map_prompt_ls}


# def retrieve_template(user_query: str):
#     row_index = 10000
#     prompt_template = ""
#     prompts = []
#     try:
#         # Retrieve question and prompt lists from the S3 file
#         result = get_mapping_list()
#         list_question = result["question_ls"]
#         input_embeddings = get_embeddings(user_query)
#         # Find the index of the most similar question to the user query
#         similarity_scores = np.array([compare_similarity(input_embeddings, question) for question in list_question])
#         row_index = np.argmax(similarity_scores)
#         # Extract the corresponding prompt template
#         if similarity_scores[row_index] > 0.6:
#             prompts = result["prompt_ls"]
#             prompt_template = str(prompts[row_index])
#     except Exception as e:
#         raise Exception(f"Error in retrieving template: {e}")
#     return prompt_template


# def retrieve_and_generate(query: str, kb_id: str, model_id: str, region_id: str, session_id: str):
#     try:
#         prompt_template = retrieve_template(query)
#         prompt_template += (
#             f"""\n\n%ADDITIONAL INSTRUCTIONS%:\n Please treat suppliers and vendors as alias in the chunks."""
#         )
#         prompt_template += f"\n\n%USER QUERY:\n{query}\n"
#         return bedrock_agent_runtime.retrieve_and_generate(
#             input={"text": prompt_template},
#             retrieveAndGenerateConfiguration={
#                 "knowledgeBaseConfiguration": {
#                     "knowledgeBaseId": kb_id,
#                     "modelArn": MODEL_ARN,
#                     "retrievalConfiguration": {
#                         "vectorSearchConfiguration": {"overrideSearchType": QNA_SEARCH_TYPE, "numberOfResults": 3}
#                     },
#                     "generationConfiguration": {
#                         "guardrailConfiguration": {
#                             "guardrailId": GUARDRAIL_ID,
#                             "guardrailVersion": GUARDRAIL_VERSION_ID,
#                         },
#                         "inferenceConfig": {
#                             "textInferenceConfig": {
#                                 "maxTokens": int(QNA_MAX_TOKENS_VALUE),
#                                 "temperature": float(QNA_TEMPERATURE_VALUE),
#                                 "topP": float(QNA_TOP_P_VALUE),
#                             }
#                         },
#                     },
#                 },
#                 "type": "KNOWLEDGE_BASE",
#             },
#             **({"sessionId": session_id} if session_id else {}),  # Conditionally add
#         )
#     except Exception as e:
#         raise Exception(f"Error in retrieving q&a answer: {e}")


# def generate_answer_with_context(formatted_prompt):
#     try:
#         body = json.dumps(
#             {
#                 "anthropic_version": "bedrock-2023-05-31",  # or "bedrock-2024-05-31", check the docs.
#                 "max_tokens": int(QNA_MAX_TOKENS_VALUE),
#                 "messages": [{"role": "user", "content": formatted_prompt}],
#             }
#         )

#         response = bedrock_client.invoke_model(
#             body=body,
#             modelId=MODEL_ID,
#             accept="application/json",
#             contentType="application/json",
#             guardrailIdentifier=GUARDRAIL_ID,
#             guardrailVersion=GUARDRAIL_VERSION_ID,
#         )

#         response_body = json.loads(response["body"].read().decode("utf-8"))

#         return response_body

#     except Exception as e:
#         raise Exception(f"Error during answer generation: {e}")


# def get_s3_path(bucket_name, folder_name):
#     return f"s3://{bucket_name}/{folder_name}/"


# def add_s3_prefix_to_files(files, bucket_name, folder_name):
#     s3_prefix = get_s3_path(bucket_name, folder_name)
#     updated_files = [s3_prefix + file for file in files]
#     return updated_files


# def retrieve_and_generate_prioritized_doc(
#     query: str, kb_id: str, knowledge_base_folder: str, model_id: str, region_id: str, session_id: str, files: list
# ):
#     try:
#         prompt_template = ""
#         if str(retrieve_template(query)) != "nan":
#             prompt_template = retrieve_template(query)
#         GENERAL_QUERIES_DOCUMENT_PATH = add_s3_prefix_to_files(files, BUCKET_CONTAINER, knowledge_base_folder)
#         prompt_template += (
#             f"""\n\n%ADDITIONAL INSTRUCTIONS%:\n Please treat suppliers and vendors as alias in the chunks."""
#         )
#         prompt_template += f"\n\n%USER QUERY:\n{query}\n"
#         return bedrock_agent_runtime.retrieve_and_generate(
#             input={"text": prompt_template},
#             retrieveAndGenerateConfiguration={
#                 "knowledgeBaseConfiguration": {
#                     "knowledgeBaseId": kb_id,
#                     "modelArn": MODEL_ARN,
#                     "retrievalConfiguration": {
#                         "vectorSearchConfiguration": {
#                             "overrideSearchType": QNA_SEARCH_TYPE,
#                             "filter": {
#                                 "in": {"key": "x-amz-bedrock-kb-source-uri", "value": GENERAL_QUERIES_DOCUMENT_PATH}
#                             },
#                             "numberOfResults": 3,
#                         }
#                     },
#                     "generationConfiguration": {
#                         "guardrailConfiguration": {
#                             "guardrailId": GUARDRAIL_ID,
#                             "guardrailVersion": GUARDRAIL_VERSION_ID,
#                         },
#                         "inferenceConfig": {
#                             "textInferenceConfig": {
#                                 "maxTokens": int(QNA_MAX_TOKENS_VALUE),
#                                 "temperature": float(QNA_TEMPERATURE_VALUE),
#                                 "topP": float(QNA_TOP_P_VALUE),
#                             }
#                         },
#                     },
#                 },
#                 "type": "KNOWLEDGE_BASE",
#             },
#             **({"sessionId": session_id} if session_id else {}),  # Conditionally add
#         )
#     except Exception as e:
#         raise Exception(f"Error in retrieving q&a answer: {e}")


# def retrieve_documents(query: str, kb_id: str, region_id: str, filter_value: str = None):
#     try:
#         bedrock_agent_runtime = boto3.client("bedrock-agent-runtime", region_name=region_id)

#         # Build the retrieval configuration
#         retrieval_configuration = {
#             "vectorSearchConfiguration": {
#                 "overrideSearchType": QNA_SEARCH_TYPE,
#                 "numberOfResults": 3,
#             }
#         }

#         # Conditionally add the filter
#         if filter_value:
#             retrieval_configuration["vectorSearchConfiguration"]["filter"] = {
#                 "equals": {"key": "x-amz-bedrock-kb-source-uri", "value": filter_value}
#             }

#         # Construct the full request
#         request = {
#             "knowledgeBaseId": kb_id,  # Required at the top level
#             "retrievalQuery": {
#                 "text": query  # Query goes inside 'retrievalQuery' object
#             },
#             "retrievalConfiguration": retrieval_configuration,  # Not 'retrieveConfiguration'
#         }

#         # Invoke the API
#         response = bedrock_agent_runtime.retrieve(**request)
#         return response

#     except Exception as e:
#         raise Exception(f"Error during document retrieval: {e}")
