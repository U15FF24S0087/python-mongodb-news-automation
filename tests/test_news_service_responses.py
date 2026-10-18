"""Test safe handling of news-provider response errors."""

import unittest
from unittest.mock import patch

import requests

import news_service
from news_service import NewsApiError


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class NewsServiceResponseTests(unittest.TestCase):
    def setUp(self):
        self.config_patches = (
            patch.object(news_service.config, "NEWS_API_KEY", "test-key-not-a-secret"),
            patch.object(news_service.config, "NEWS_API_QUERY", "test query"),
            patch.object(news_service.config, "get_news_api_provider", return_value="newsapi"),
        )
        for config_patch in self.config_patches:
            config_patch.start()
            self.addCleanup(config_patch.stop)

    def test_empty_response_is_not_reported_as_an_error(self):
        with patch.object(
            news_service.requests,
            "get",
            return_value=FakeResponse({"status": "ok", "articles": []}),
        ):
            self.assertEqual(news_service.fetch_technology_news(), [])

    def test_invalid_key_and_rate_limit_errors_are_safe(self):
        for status_code, expected_message in (
            (401, "rejected the key"),
            (429, "request limit"),
        ):
            with self.subTest(status_code=status_code):
                response = requests.Response()
                response.status_code = status_code
                error = requests.HTTPError(response=response)
                with patch.object(
                    news_service.requests,
                    "get",
                    side_effect=error,
                ):
                    with self.assertRaises(NewsApiError) as raised:
                        news_service.fetch_technology_news()

                self.assertIn(expected_message, str(raised.exception).lower())
                self.assertNotIn("test-key-not-a-secret", str(raised.exception))

    def test_invalid_json_is_reported_clearly(self):
        with patch.object(
            news_service.requests,
            "get",
            return_value=FakeResponse(ValueError("invalid")),
        ):
            with self.assertRaisesRegex(NewsApiError, "invalid JSON"):
                news_service.fetch_technology_news()

    def test_timeout_is_reported_clearly(self):
        with patch.object(
            news_service.requests,
            "get",
            side_effect=requests.Timeout,
        ):
            with self.assertRaisesRegex(NewsApiError, "timed out"):
                news_service.fetch_technology_news()


if __name__ == "__main__":
    unittest.main()
