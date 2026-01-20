"""Unit tests for the chat history router endpoints."""

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.services.llm_metrics import put_llm_metrics


def main():
    put_llm_metrics(
        message_id="test-message-001",
        call_type="test",
        payload={"test_field": "test_value"},
        user_id="test-user",
        session_id="test-session",
        model_id="test-model",
        kb_id="test-kb",
        kb_path="/test/path",
        latency_ms=123,
        input_tokens=10,
        output_tokens=5,
        price_per_input_token=0.00001,
        price_per_output_token=0.00002,
        status="success",
        error_message=None,
    )
    print("Test metric written successfully!")


if __name__ == "__main__":
    main()
