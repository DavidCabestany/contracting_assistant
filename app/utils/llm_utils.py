"""Bedrock-related helpers and post-processing utilities."""

from __future__ import annotations

import json
import logging
from typing import Final

from langchain_aws import ChatBedrock
from models import RiskAssessmentResponse
from pydantic import ValidationError

from .constants import MODEL_ID

logger = logging.getLogger(__name__)
_KEYWORD_LLM: Final = ChatBedrock(
    model_id="anthropic.claude-3-haiku-20240307-v1:0",
    model_kwargs={"temperature": 0},
)

_CLASSIFY_PROMPT: Final = """
You are a routing agent.

Return exactly one word:
QUESTION - if the user asks anything, requests a comparison, or wants similarities / differences.
SUMMARY  - if they merely pasted text or explicitly ask "summarise".

Now classify:
{query}
"""


def needs_summary(query: str) -> bool:
    """Return *True* if the query should be summarised instead of answered."""
    resp = ChatBedrock(model_id=MODEL_ID).invoke(
        _CLASSIFY_PROMPT.format(query=query.strip())
    )
    return resp.content.strip().upper() == "SUMMARY"


def llm_summarise(text: str) -> str:
    """Generate a one-paragraph summary of *text*."""
    prompt = f"Give a concise summary in one descriptive paragraph:\n\n{text}"
    return ChatBedrock(model_id=MODEL_ID).invoke(prompt).content.strip()


def parse_risk_assessment_output(model_output: str) -> RiskAssessmentResponse:
    """Convert the model’s raw JSON-string into a strongly-typed object."""
    try:
        start, end = model_output.find("{"), model_output.rfind("}") + 1
        parsed = json.loads(model_output[start:end])
        return RiskAssessmentResponse.parse_obj({"answer": parsed})
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ValueError(
            f"Could not parse risk assessment response: {exc}\nRaw:\n{model_output}"
        ) from exc


def extract_keywords_from_query(query: str, *, max_char: int = 2_000) -> str:
    """Return a comma-separated, lowercase keyword list suitable for indexing."""
    if not query.strip():
        return ""

    prompt = f"""
Extract the most meaningful keywords (≤ {max_char} chars) from the user query
to help with document search indexing.

- Use lowercase only, no punctuation or stop-words
- Return a comma-separated list

Query:
{query}
"""
    try:
        response = _KEYWORD_LLM.invoke(prompt)
        return response.content.strip()[:2_040]
    except Exception as exc:  # noqa: BLE001
        logger.warning("[Keyword Extractor] fallback – %r", exc)
        return query[:2_046].lower()
