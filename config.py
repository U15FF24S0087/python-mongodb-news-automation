"""Read application settings from environment variables."""

import os
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().with_name(".env"))


def _read_int(name: str, default: int) -> int:
    """Read an integer setting and give a clear error for invalid values."""
    value = os.getenv(name, str(default)).strip()
    try:
        return int(value)
    except ValueError:
        raise ValueError(f"{name} must be an integer") from None


MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017").strip()
MONGODB_DATABASE = os.getenv("MONGODB_DATABASE", "tech_news").strip()

NEWS_API_KEY = os.getenv("NEWS_API_KEY", "").strip()
NEWS_API_URL = os.getenv(
    "NEWS_API_URL",
    "https://newsapi.org/v2/everything",
).strip()
NEWS_API_QUERY = os.getenv(
    "NEWS_API_QUERY",
    "technology OR AI OR cybersecurity OR quantum OR cloud computing OR software OR startup",
).strip()
NEWS_REQUEST_TIMEOUT_SECONDS = _read_int("NEWS_REQUEST_TIMEOUT_SECONDS", 15)

NEWS_SCHEDULE_HOUR = _read_int("NEWS_SCHEDULE_HOUR", 6)
NEWS_SCHEDULE_MINUTE = _read_int("NEWS_SCHEDULE_MINUTE", 0)

if not 0 <= NEWS_SCHEDULE_HOUR <= 23:
    raise ValueError("NEWS_SCHEDULE_HOUR must be between 0 and 23")
if not 0 <= NEWS_SCHEDULE_MINUTE <= 59:
    raise ValueError("NEWS_SCHEDULE_MINUTE must be between 0 and 59")
if NEWS_REQUEST_TIMEOUT_SECONDS <= 0:
    raise ValueError("NEWS_REQUEST_TIMEOUT_SECONDS must be greater than 0")


def get_news_api_provider() -> str:
    """Identify the supported API from its configured endpoint host."""
    host = urlsplit(NEWS_API_URL).hostname
    if host == "newsapi.org" or (host and host.endswith(".newsapi.org")):
        return "newsapi"
    if host == "gnews.io" or (host and host.endswith(".gnews.io")):
        return "gnews"
    raise ValueError("NEWS_API_URL must use a supported NewsAPI or GNews endpoint")
