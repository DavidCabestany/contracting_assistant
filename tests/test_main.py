"""Unit tests for the main FastAPI application."""

import unittest

from fastapi.testclient import TestClient

from app.main import app


class TestMainApp(unittest.TestCase):
    """Test suite for the FastAPI main application."""

    def setUp(self):
        """Set up test client before each test."""
        self.client = TestClient(app)

    def test_alive_endpoint(self):
        """Test the root health check endpoint returns the welcome message."""
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"message": "Welcome to the Contracting Assistant API!"},
        )

    def test_docs_available(self):
        """Test that Swagger documentation is available at /docs."""
        response = self.client.get("/docs")
        self.assertEqual(response.status_code, 200)

    def test_openapi_available(self):
        """Test that OpenAPI schema is available at /openapi.json."""
        response = self.client.get("/openapi.json")
        self.assertEqual(response.status_code, 200)
        self.assertIn("info", response.json())


if __name__ == "__main__":
    unittest.main()
