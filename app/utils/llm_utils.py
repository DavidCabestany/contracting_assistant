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
from pathlib import Path
from typing import Final

from langchain_aws import ChatBedrock
from models import RiskAssessmentResponse
from prompts import CLASSIFY_PROMPT, STYLE_PROMPT, TOPIC_CHECKER
from pydantic import ValidationError

from .constants import DOCS_DIR, HAIKU, MODEL_ID, SONNET_V1

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


TOPICS_FILE: Final[Path] = DOCS_DIR / "topics.json"
with TOPICS_FILE.open(encoding="utf-8") as f:
    TOPICS_JSON = json.load(f)


# Prompt to classify the user query intent

cleaner_llm = ChatBedrock(
    model_id=SONNET_V1,
    model_kwargs={"temperature": 0},
)


def get_claude_response(query: str) -> str:
    """Sanitize LLM-style answer using Claude to remove filler and irrelevant content."""
    prompt = f"""<system>\n{STYLE_PROMPT}\n</system>\n\nAnswer: {query}"""

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
            CLASSIFY_PROMPT.format(query=query.strip()),
        )
        return resp.content.strip().upper()
    except Exception as exc:
        logger.warning(
            "LLM classification failed, defaulting to QUESTION: %r",
            exc,
        )
        return "QUESTION"


async def db_tab_checker(query: str) -> tuple[str, str]:
    """Classifies a query into a tab and topic using LLM."""
    prompt = TOPIC_CHECKER.format(
        topics_json=json.dumps(TOPICS_JSON, ensure_ascii=False, indent=2),
        query=query.strip(),
    )
    try:
        resp = await ChatBedrock(model_id=MODEL_ID).ainvoke(prompt)
        result = json.loads(resp.content)
        tab = result["tab"].lower()
        topic = result["topic"]
        if tab not in TOPICS_JSON:
            logger.warning(
                f"Tab '{tab}' not in allowed tabs, defaulting to 'general'."
            )
            return "general", topic
        return tab, topic
    except Exception as exc:
        logger.warning(
            "Tab classification failed, defaulting to 'general': %r", exc
        )
        return "general", "Unknown"


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
