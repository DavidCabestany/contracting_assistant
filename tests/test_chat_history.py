"""Unit tests for the chat history router endpoints."""

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app


class TestChatHistoryRouter(unittest.TestCase):
    """Test suite for chat history endpoints."""

    def setUp(self):
        """Initialize test client."""
        self.client = TestClient(app)

    @patch("app.routes.chat_history.store_interaction")
    def test_store_interaction(self, mock_store):
        """Test storing chat interaction returns success message."""
        mock_store.return_value = {
            "message": "User-bot interaction stored successfully"
        }
        payload = {
            "UserId": "user1",
            "SessionId": "abc123",
            "UserMessage": "Hello?",
            "UserMessageSearch": "hello",
            "BotResponse": "Hi there!",
            "BotResponseSearch": "hi",
            "FeedbackComment": "",
            "Timestamp": "2025-05-02T10:00:00",
            "SessionStatus": "Active",
            "MessageId": "msg1",
            "ChatMetadata": {
                "FileName": ["file.txt"],
                "FileLocation": "/path/",
                "FlowName": "QnA",
                "KbType": "general",
            },
        }
        response = self.client.post("/chat/store/", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"message": "User-bot interaction stored successfully"},
        )

    # @patch("app.routes.chat_history.view_chat_by_session")
    # def test_get_session_history(self, mock_view):
    #     """Test fetching session history."""
    #     mock_view.return_value = {
    #         "abc123": [
    #             {
    #                 "UserMessage": "Hi",
    #                 "BotResponse": "Hello!",
    #                 "apiKey": None,
    #                 "FeedbackComment": "",
    #                 "SessionId": "abc123",
    #                 "UserId": "user1",
    #                 "Timestamp": "2025-05-02T10:00:00",
    #                 "MessageId": "msg1",
    #                 "SessionStatus": "Active",
    #                 "ChatMetadata": {},
    #             }
    #         ]
    #     }

    #     response = self.client.post("/chat/session/", json={"session_id": "abc123"})
    #     self.assertEqual(response.status_code, 200)
    #     self.assertEqual(response.json(), {"abc123": [{"UserMessage": "Hi", "BotResponse": "Hello!"}]})

    @patch("app.routes.chat_history.search_chat")
    def test_search_chat(self, mock_search):
        """Test chat search returns grouped sessions."""
        mock_search.return_value = {
            "2025-05-02": {
                "abc123": {
                    "UserMessage": "What is ESG?",
                    "Timestamp": "2025-05-02T12:00:00",
                    "SessionId": "abc123",
                    "UserId": "user1",
                }
            }
        }
        response = self.client.post(
            "/chat/search/", json={"session_id": "abc123", "userId": "user1"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("2025-05-02", response.json())

    # @patch("app.routes.chat_history.download_chat")
    # def test_download_chat(self, mock_download):
    #     """Test chat transcript download."""
    #     mock_download.return_value = {"status": "success", "downloadUrl": "https://mocked-url.com/file.xlsx"}
    #     payload = {"userId": "user1"}
    #     response = self.client.post("/chat/download/", json=payload)
    #     self.assertEqual(response.status_code, 200)
    #     self.assertEqual(response.json()["status"], "success")

    @patch("app.routes.chat_history.update_feedback")
    def test_feedback(self, mock_feedback):
        """Test feedback submission."""
        mock_feedback.return_value = {"status": "success"}
        payload = {
            "session_id": "abc123",
            "messageId": "msg1",
            "IsFeedbackPositive": True,
            "feedbackComment": "Helpful!",
        }
        response = self.client.post("/chat/feedback/", json=payload)
        self.assertEqual(response.json(), {"status": "success"})

    # @patch("app.routes.chat_history.get_latest_active_sessions")
    # def test_recents_success(self, mock_recents):
    #     """Test recent sessions list is returned."""
    #     mock_recents.return_value = [
    #         {"SessionId": "s1", "Message": "Hi", "KbType": "general"},
    #         {"SessionId": "s2", "Message": "Hello", "KbType": "finance"},
    #     ]
    #     response = self.client.post("/chat/recents/", json={"userId": "user1"})
    #     self.assertEqual(response.status_code, 200)
    #     data = response.json()
    #     self.assertEqual(len(data), 2)
    #     self.assertEqual(data[0]["SessionId"], "s1")

    def test_recents_missing_user_id(self):
        """Test recent sessions request without userId returns 400."""
        response = self.client.post("/chat/recents/", json={})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(), {"detail": "Missing userId in request"}
        )


if __name__ == "__main__":
    unittest.main()
