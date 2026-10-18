"""Fetch and normalize technology articles from the configured news API."""

import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

import requests

import config


CATEGORY_KEYWORDS = {
    "Agentic AI": ("agentic ai", "ai agent", "autonomous agent"),
    "Quantum Computing": ("quantum", "qubit"),
    "Cybersecurity": ("cybersecurity", "cyber attack", "data breach", "ransomware"),
    "Cloud": ("cloud computing", "cloud service", "aws", "azure", "google cloud"),
    "Developer Tools": ("developer tool", "ide", "visual studio code", "github copilot"),
    "Programming": ("programming", "programming language", "python", "javascript"),
    "Startups": ("startup", "venture capital", "funding round"),
    "Technology Companies": ("apple", "google", "microsoft", "meta", "nvidia", "openai"),
    "AI": ("artificial intelligence", "machine learning", "generative ai", "large language model"),
}


class NewsApiError(Exception):
    """Raised when the configured news API cannot return usable data."""


def categorize_article(title: str, description: str) -> str:
    """Assign the first matching category using editable keyword rules."""
    text = f"{title} {description}".casefold()

    for category, keywords in CATEGORY_KEYWORDS.items():
        for keyword in keywords:
            if keyword in text:
                return category

    if re.search(r"\bai\b", text):
        return "AI"

    return "Other Technology"


def _normalize_article(article: dict[str, Any]) -> dict[str, str | None] | None:
    """Convert one API article to the fields used by our application."""
    title = article.get("title")
    url = article.get("url")
    if not isinstance(title, str) or not title.strip():
        return None
    if not isinstance(url, str) or not url.strip():
        return None

    description = article.get("description")
    source = article.get("source")
    author = article.get("author")
    published_at = article.get("publishedAt")
    image_url = article.get("urlToImage") or article.get("image")
    if isinstance(image_url, str):
        parsed_image_url = urlsplit(image_url.strip())
        if parsed_image_url.scheme not in {"http", "https"} or not parsed_image_url.netloc:
            image_url = None
        else:
            image_url = image_url.strip()
    else:
        image_url = None

    if isinstance(source, dict):
        source_name = source.get("name")
    else:
        source_name = source

    return {
        "title": title.strip(),
        "description": description.strip() if isinstance(description, str) else "",
        "source": source_name if isinstance(source_name, str) else "Unknown",
        "author": author.strip() if isinstance(author, str) and author.strip() else None,
        "published_at": published_at if isinstance(published_at, str) else None,
        "url": url.strip(),
        "image_url": image_url,
        "category": categorize_article(
            title,
            description if isinstance(description, str) else "",
        ),
        "collected_at": datetime.now(timezone.utc).isoformat(),
    }


def fetch_technology_news() -> list[dict[str, str | None]]:
    """Fetch recent articles and return them in the project's common format."""
    if not config.NEWS_API_KEY:
        raise NewsApiError("NEWS_API_KEY is not configured.")
    if not config.NEWS_API_QUERY:
        raise NewsApiError("NEWS_API_QUERY is not configured.")

    try:
        provider = config.get_news_api_provider()
    except ValueError as exc:
        raise NewsApiError(str(exc)) from None

    if provider == "gnews":
        params: dict[str, str | int] = {
            "q": config.NEWS_API_QUERY,
            "lang": "en",
            "max": 10,
            "apikey": config.NEWS_API_KEY,
        }
        headers = {}
    else:
        params = {
            "q": config.NEWS_API_QUERY,
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": 100,
        }
        headers = {"X-Api-Key": config.NEWS_API_KEY}

    try:
        response = requests.get(
            config.NEWS_API_URL,
            params=params,
            headers=headers,
            timeout=config.NEWS_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.Timeout:
        raise NewsApiError("The news API request timed out.") from None
    except requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else "unknown"
        if provider == "newsapi" and status_code == 401:
            message = "NewsAPI rejected the key. Verify that it is an active NewsAPI key."
        elif provider == "gnews" and status_code in (401, 403):
            message = "GNews rejected the key or request. Verify the key and account access."
        elif status_code == 429:
            message = "The news API request limit was reached. Check your plan and quota."
        else:
            message = (
                f"The news API returned HTTP {status_code}. "
                "Check the endpoint and request parameters."
            )
        raise NewsApiError(message) from None
    except requests.ConnectionError:
        raise NewsApiError(
            "Could not reach the news API host. Check internet access, DNS, "
            "firewall, or proxy settings."
        ) from None
    except requests.RequestException:
        raise NewsApiError("The news API request failed.") from None

    try:
        payload = response.json()
    except ValueError:
        raise NewsApiError("The news API returned invalid JSON.") from None

    if not isinstance(payload, dict):
        raise NewsApiError("The news API returned an unexpected response.")
    if provider == "newsapi" and payload.get("status") != "ok":
        code = payload.get("code")
        if code == "apiKeyInvalid":
            raise NewsApiError("NewsAPI rejected the key. Verify that it is an active NewsAPI key.")
        if code == "apiKeyExhausted":
            raise NewsApiError("The NewsAPI request quota has been reached.")
        raise NewsApiError("NewsAPI reported that the request failed.")

    articles = payload.get("articles")
    if not isinstance(articles, list):
        raise NewsApiError("The news API response did not contain an article list.")

    normalized_articles = []
    for article in articles:
        if isinstance(article, dict):
            normalized = _normalize_article(article)
            if normalized is not None:
                normalized_articles.append(normalized)

    return normalized_articles
