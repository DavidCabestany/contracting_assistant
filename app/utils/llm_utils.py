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

from .constants import HAIKU, MODEL_ID, SONNET_V1

logger = logging.getLogger(__name__)

# Lightweight model for fast classification and keyword extraction
_KEYWORD_LLM: Final = ChatBedrock(
    model_id=HAIKU,
    model_kwargs={"temperature": 0},
)


REFUSAL_REGEX = re.compile(
    r"(i'?m sorry|i apologise|i apologize|i can(\'|’)t help you with (this )?request)",
    re.IGNORECASE,
)


def is_refusal(answer: str) -> bool:
    """Detect if the answer is a refusal or generic non-answer."""
    return bool(REFUSAL_REGEX.search(answer))


# Prompt to classify the user query intent
_CLASSIFY_PROMPT: Final = """
You are a routing agent of AstraZeneca Policies.

    Return exactly one word:
    IRRELEVANT - If the user chit chats or asks about pizza, sports, weather, jokes, or anything unrelated to business contracts.
    QUESTION - Only if the user asks something related to the domain, clauses, templates, comparisons etc. and what about this country?
    SUMMARY  - if they merely pasted text or explicitly ask "summarise".

    Now classify:
    {query}
    """

# TODO(@kvcn639): Move prompt strings to a central templates/prompts module

cleaner_llm = ChatBedrock(
    model_id=SONNET_V1,
    model_kwargs={"temperature": 0},
)

# System prompt containing software engineering principles and patterns
style_cleaner_instruction = """
You are an Answer Sanitizer. Your job is to take any answer provided in the `ans` field of a JSON payload and remove:
  • Any apologies or “I'm sorry” language
  • Repetition disclaimers (e.g., “As I mentioned,” “To clarify one last time,” etc.)
  • Open-ended invites or offers for more questions (e.g., “feel free to ask,” “let me know if,” etc.)
  • Any passive-aggressive or irrelevant filler

If the answer is just "Sorry, I am unable to assist you with this request." just return it.

Leave the factual content and explanations exactly as-is. the lists and details as-is. Do not rephrase it, do not add anything, and do not return any JSON—just output the cleaned answer text.
"""


def get_claude_response(query: str) -> str:
    """Sanitize LLM-style answer using Claude to remove filler and irrelevant content."""
    prompt = f"""<system>\n{style_cleaner_instruction}\n</system>\n\nAnswer: {query}"""

    try:
        response = cleaner_llm.invoke(prompt)
        return response.content.strip()
    except Exception:
        logger.exception("Error in getting sanitized response from Claude")
        return query


def response_sanitizer(answer: str) -> str:
    """Sanitize an LLM-generated answer using Claude to strip apologies and filler."""
    try:
        if not answer.strip():
            return answer
        cleaned = get_claude_response(answer)
        return cleaned.strip()
    except Exception as e:
        logger.warning(f"Failed to sanitize answer: {e}")
        return answer


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
        return resp.content.strip().upper()
    except Exception as exc:
        logger.warning(
            "LLM classification failed, defaulting to QUESTION: %r",
            exc,
        )
        return "QUESTION"


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
