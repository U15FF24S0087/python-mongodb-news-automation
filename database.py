"""Connect to MongoDB and prepare the collections used by the application."""

from pymongo import MongoClient
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError, PyMongoError

import config


def connect_to_mongodb() -> tuple[MongoClient, Database]:
    """Connect to MongoDB and create the unique news URL index."""
    client = MongoClient(
        config.MONGODB_URI,
        serverSelectionTimeoutMS=5000,
    )

    try:
        client.admin.command("ping")
        database = client[config.MONGODB_DATABASE]
        database["news"].create_index("url", unique=True)
        database["daily_briefings"].create_index("briefing_date", unique=True)
    except PyMongoError:
        client.close()
        raise

    return client, database


def save_news_articles(
    database: Database,
    articles: list[dict[str, str | None]],
) -> tuple[int, int]:
    """Insert articles and return counts for inserted and duplicate records."""
    news_collection = database["news"]
    inserted_count = 0
    duplicate_count = 0

    for article in articles:
        url = article.get("url")
        if not isinstance(url, str) or not url.strip():
            raise ValueError("Each article must have a non-empty URL.")

        try:
            news_collection.insert_one(article)
            inserted_count += 1
        except DuplicateKeyError:
            duplicate_count += 1

    return inserted_count, duplicate_count
