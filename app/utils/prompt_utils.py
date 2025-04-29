"""Prompt-building helpers and KB routing logic."""

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
    """Map human-friendly name → Bedrock KB ID."""
    lowered = name.lower()
    if lowered == "privacy":
        return PRIVACY_KB_ID
    if lowered == "alexion":
        return ALEXION_ID
    return GEN_ENQ_KB_ID


def get_knowledge_base_folder(name: str) -> str:
    """Return the sub-folder name used in S3 for this KB."""
    lowered = name.lower()
    return lowered if lowered in {"privacy", "alexion"} else "general"


# ───────────────────────── prompt generators ──────────────────────────── #
def business_unit_prompt(query: str) -> str:
    """Formatted prompt for classifying *query* into a business unit."""
    return PromptTemplate(
        input_variables=["Query"],
        template=BUSINESS_UNIT_PROMPT,
    ).format(Query=query)


def get_risk_matrix_details() -> dict:
    """Load and cache the JSON risk-matrix rules."""
    try:
        return json.loads(_RISK_RULES_PATH.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Unable to load risk rules from %s – %r", _RISK_RULES_PATH, exc
        )
        raise


def generate_prompt(content: str, query: str, template: str) -> str:
    """Fill *template* with arbitrary *content* plus the user *query*."""
    return PromptTemplate(
        input_variables=["content", "Query"],
        template=template,
    ).format(content=content, Query=query)


def generate_prompt_risk(
    contract: str, risk_rules: str, query: str, template: str
) -> str:
    """Specialised prompt to ask the LLM about contract risks."""
    return PromptTemplate(
        input_variables=["contract", "risk_rules", "Query"],
        template=template,
    ).format(Contract=contract, risk_rules=risk_rules, Query=query)


def prompt_query_cat(query: str) -> str:
    """Prompt that classifies *query* into a high-level category."""
    return PromptTemplate(
        input_variables=["Query"],
        template=CATEGORY_PROMPT,
    ).format(Query=query)
