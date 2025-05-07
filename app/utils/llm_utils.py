"""Bedrock-related helpers and post-processing utilities.

Includes:
- LLM-based classification to decide if input is a summary request
- One-paragraph summarisation
- Risk assessment JSON parsing
- Keyword extraction from user queries
"""

from __future__ import annotations

import json
import logging
import re
from typing import Final

from langchain_aws import ChatBedrock
from models import RiskAssessmentResponse
from pydantic import ValidationError

from .constants import MODEL_ID

logger = logging.getLogger(__name__)

# Lightweight model for fast classification and keyword extraction
_KEYWORD_LLM: Final = ChatBedrock(
    model_id="anthropic.claude-3-haiku-20240307-v1:0",
    model_kwargs={"temperature": 0},
)

# Prompt to classify the user query intent
_CLASSIFY_PROMPT: Final = """
You are a routing agent.

Return exactly one word:
QUESTION - if the user asks anything, requests a comparison, or wants similarities / differences.
SUMMARY  - if they merely pasted text or explicitly ask "summarise".

Now classify:
{query}
"""

# TODO(@kvcn639): Move prompt strings to a central templates/prompts module


def needs_summary(query: str) -> bool:
    """Determine if a query should be summarised instead of answered.

    Args:
        query (str): Raw user input.

    Returns:
        bool: True if LLM classifies it as a summary request.
    """
    try:
        resp = ChatBedrock(model_id=MODEL_ID).invoke(
            _CLASSIFY_PROMPT.format(query=query.strip()),
        )
        return resp.content.strip().upper() == "SUMMARY"
    except Exception as exc:
        logger.warning(
            "LLM classification failed, defaulting to QUESTION: %r",
            exc,
        )
        return False


def llm_summarise(text: str) -> str:
    """Generate a concise paragraph summary from raw text.

    Args:
        text (str): Any long user input or extracted document content.

    Returns:
        str: One-paragraph summary.
    """
    prompt = f"Give a concise summary in one descriptive paragraph:\n\n{text}"
    try:
        return ChatBedrock(model_id=MODEL_ID).invoke(prompt).content.strip()
    except Exception as exc:
        logger.error("Summarisation failed: %r", exc)
        return "Summary unavailable."


def parse_risk_assessment_output(model_output: str) -> RiskAssessmentResponse:
    """Parse a stringified JSON block into a structured RiskAssessmentResponse.

    Args:
        model_output (str): Model output string, expected to contain a JSON object.

    Returns:
        RiskAssessmentResponse: Strongly-typed risk data wrapper.

    Raises:
        ValueError: If JSON is malformed or validation fails.
    """
    try:
        start, end = model_output.find("{"), model_output.rfind("}") + 1
        parsed = json.loads(model_output[start:end])
        return RiskAssessmentResponse.parse_obj({"answer": parsed})
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ValueError(
            f"Could not parse risk assessment response: {exc}\nRaw:\n{model_output}",
        ) from exc


def extract_keywords_from_query(query: str, *, max_char: int = 2_000) -> str:
    """Extract a lowercase, comma-separated keyword list from a user query.

    Uses an LLM to pull indexable terms with optional truncation.
    Falls back to a simple regex-based keyword list if the LLM fails.

    Args:
        query (str): User's original input.
        max_char (int): Maximum character length of output keyword string.

    Returns:
        str: Comma-separated keywords.
    """
    if not isinstance(query, str):
        raise TypeError(
            f"extract_keywords_from_query expected str, got {type(query).__name__}"
        )
    if not query:
        return ""

    # Build a clean, dedented prompt
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
        content = (response.content or "").strip().lower()
        # Ensure we never exceed max_char
        return content[:max_char]
    except Exception as exc:
        logger.warning("[Keyword Extractor] LLM fallback – %r", exc)
        # Simple regex fallback: alphanumeric words only, unique, comma-joined
        words: list[str] = re.findall(r"\b[a-z0-9]+\b", query.lower())
        # Dedupe while preserving order
        seen = set()
        keywords = [w for w in words if not (w in seen or seen.add(w))]
        fallback = ",".join(keywords)
        return fallback[:max_char]
