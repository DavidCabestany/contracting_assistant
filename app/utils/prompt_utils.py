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
from prompts import (
    ADDITIONAL_RISKS,
    BUSINESS_UNIT_PROMPT,
    CATEGORY_PROMPT,
    RISKS_SUMMARY,
    USER_QUERY_RISKS,
)

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


def generate_prompt_risk_test(
    template: str,
    identified_clauses: str,
    risk_rules: list,
) -> str:
    """Generate a prompt tailored for contract risk analysis.

    Args:
        identified_clauses : clauses identified in contract
        template (str): Prompt template.
        risk_rules(json): risk template

    Returns:
        str: Formatted prompt string.
    """
    return PromptTemplate(
        input_variables=["identified_clauses", "risk_rules"],
        template=template,
    ).format(
        identified_clauses=identified_clauses,
        risk_rules=risk_rules,
    )


def generate_prompt_summary(
    contract_clauses: str,
    additional_clauses: str,
) -> str:
    """Generate a contract risks summary.

    Args:
        contract_clauses(str) : risk rules clauses identified in contract
        additional_clauses (str): additional clauses if any

    Returns:
        summary: a short summary of clauses
    """
    return PromptTemplate(
        input_variables=["contract_clauses", "additional_clauses"],
        template=RISKS_SUMMARY,
    ).format(
        contract_clauses=contract_clauses,
        additional_clauses=additional_clauses,
    )


def generate_prompt_risk(
    contract: str,
    template: str,
) -> str:
    """Generates a formatted LLM prompt string for contract risk analysis.

    This function fills a prompt template with the given contract text so
    it can be used directly for risk assessment by an LLM.

    Args:
        contract (str): The full contract text to be analyzed for risk.
        template (str): The template string or object for prompt construction.

    Returns:
        str: A formatted prompt with the contract text inserted, suitable for LLM use.
    """
    return PromptTemplate(
        input_variables=["contract"],
        template=template,
    ).format(Contract=contract)


def get_additional_risk(content: str, clauses: str) -> str:
    """Creates a prompt to identify and extract additional risks from a contract.

    Formats the ADDITIONAL_RISKS prompt template with both the contract content and
    a list of already-identified clauses, so an LLM can detect further risks.

    Args:
        content (str): The full contract content for analysis.
        clauses (str): Existing clause details as a string.

    Returns:
        str: JSON-style prompt to be sent to the LLM, for additional risk extraction.
    """
    return PromptTemplate(
        input_variables=["content", "clauses"],
        template=ADDITIONAL_RISKS,
    ).format(contract=content, clauses=clauses)


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


def get_clauses(query: str, clauses: list) -> str:
    """To find the clauses asked in user query.

    Args:
        query (str): The user's query text.
        clauses (list): Clauses

    Returns:
        list: risks in user query
    """
    try:
        return PromptTemplate(
            input_variables=["query", "clauses"],
            template=USER_QUERY_RISKS,
        ).format(Query=query, Clauses=clauses)
    except Exception as exc:
        print(exc)
