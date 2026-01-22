# services/token_usage.py
from __future__ import annotations

from typing import Any, Tuple


def extract_token_usage(obj: Any) -> Tuple[int | None, int | None]:
    """Best-effort extraction of (input_tokens, output_tokens) from.

    - Bedrock Claude Messages JSON dicts (invoke_model parsed JSON)
    - Bedrock responses that include 'usage' dict
    - LangChain AIMessage objects (ChatBedrock.invoke/ainvoke)
    Returns (None, None) if not available.
    """
    # ---------- Case A: plain dict (Bedrock JSON / response dicts)
    if isinstance(obj, dict):
        usage = obj.get("usage")
        if isinstance(usage, dict):
            it = usage.get("input_tokens")
            ot = usage.get("output_tokens")
            if it is not None or ot is not None:
                return int(it or 0), int(ot or 0)

        # Some libs tuck it under response_metadata/usage
        rm = obj.get("response_metadata")
        if isinstance(rm, dict):
            u2 = rm.get("usage") or rm.get("token_usage")
            if isinstance(u2, dict):
                it = u2.get("input_tokens") or u2.get("prompt_tokens")
                ot = u2.get("output_tokens") or u2.get("completion_tokens")
                if it is not None or ot is not None:
                    return int(it or 0), int(ot or 0)

        return None, None

    # ---------- Case B: LangChain AIMessage-like objects
    # langchain messages often have: .response_metadata, .usage_metadata, .additional_kwargs
    rm = getattr(obj, "response_metadata", None)
    if isinstance(rm, dict):
        u = rm.get("usage") or rm.get("token_usage")
        if isinstance(u, dict):
            it = u.get("input_tokens") or u.get("prompt_tokens")
            ot = u.get("output_tokens") or u.get("completion_tokens")
            if it is not None or ot is not None:
                return int(it or 0), int(ot or 0)

    um = getattr(obj, "usage_metadata", None)
    if isinstance(um, dict):
        it = um.get("input_tokens") or um.get("prompt_tokens")
        ot = um.get("output_tokens") or um.get("completion_tokens")
        if it is not None or ot is not None:
            return int(it or 0), int(ot or 0)

    ak = getattr(obj, "additional_kwargs", None)
    if isinstance(ak, dict):
        u = ak.get("usage") or ak.get("token_usage")
        if isinstance(u, dict):
            it = u.get("input_tokens") or u.get("prompt_tokens")
            ot = u.get("output_tokens") or u.get("completion_tokens")
            if it is not None or ot is not None:
                return int(it or 0), int(ot or 0)

    return None, None
