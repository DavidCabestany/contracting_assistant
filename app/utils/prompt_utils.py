"""Prompt-building helpers and KB routing logic for classification and risk analysis.

This module contains utility functions that:
- Map friendly names to KBs and folders.
- Generate LangChain prompts for classification, category detection, and risk analysis.
- Load risk rule configurations.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Final

from langchain_core.prompts import PromptTemplate
from prompts import BUSINESS_UNIT_PROMPT, CATEGORY_PROMPT

from .constants import ALEXION_ID, DOCS_DIR, GEN_ENQ_KB_ID, PRIVACY_KB_ID

logger = logging.getLogger(__name__)
_RISK_RULES_PATH: Final[Path] = DOCS_DIR / "risk_rules.json"


def get_knowledge_base_id(name: str) -> str:
    """Return the KB ID for a given friendly name.

    Args:
        name (str): A friendly name such as 'privacy', 'alexion', etc.

    Returns:
        str: The corresponding knowledge base ID.
    """
    lowered = name.lower()
    if lowered == "privacy":
        return PRIVACY_KB_ID
    if lowered == "alexion":
        return ALEXION_ID
    return GEN_ENQ_KB_ID


def get_knowledge_base_folder(name: str) -> str:
    """Map a friendly name to an S3 folder name.

    Args:
        name (str): A knowledge base name like 'privacy' or 'alexion'.

    Returns:
        str: The folder name used in S3.
    """
    lowered = name.lower()
    return lowered if lowered in {"privacy", "alexion"} else "general"


def business_unit_prompt(query: str) -> str:
    """Generate a business unit classification prompt.

    Args:
        query (str): User query text.

    Returns:
        str: Rendered prompt string.
    """
    return PromptTemplate(
        input_variables=["Query"],
        template=BUSINESS_UNIT_PROMPT,
    ).format(Query=query)


def get_risk_matrix_details() -> dict:
    """Load risk rules from a local JSON file.

    Returns:
        dict: Parsed JSON content from the risk rules file.

    Raises:
        Exception: If the file cannot be read or parsed.
    """
    try:
        return json.loads(_RISK_RULES_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error(
            "Unable to load risk rules from %s – %r",
            _RISK_RULES_PATH,
            exc,
        )
        raise


def generate_prompt(content: str, query: str, template: str) -> str:
    """Generate a prompt using user content, query, and a given template.

    Args:
        content (str): Document or message content.
        query (str): User query string.
        template (str): Prompt template with placeholders.

    Returns:
        str: Rendered prompt.
    """
    return PromptTemplate(
        input_variables=["content", "Query"],
        template=template,
    ).format(content=content, Query=query)


def generate_prompt_risk(
    contract: str,
    query: str,
    template: str,
    risk_rules: str,
    clauses_lst: list,
) -> str:
    """Generate a prompt tailored for contract risk analysis.

    Args:
        contract (str): Contract text.
        risk_rules (str): JSON string of rules.
        query (str): Risk-related user question.
        template (str): Prompt template.
        clauses_lst(List): clauses

    Returns:
        str: Formatted prompt string.
    """
    return PromptTemplate(
        input_variables=["contract", "risk_rules", "Query"],
        template=template,
    ).format(
        risk_rules=risk_rules,
        Contract=contract,
        Query=query,
        clauses=clauses_lst,
    )


def prompt_query_cat(query: str) -> str:
    """Generate a category classification prompt for a query.

    Args:
        query (str): The user's query text.

    Returns:
        str: Prompt for determining the query category.
    """
    return PromptTemplate(
        input_variables=["Query"],
        template=CATEGORY_PROMPT,
    ).format(Query=query)
