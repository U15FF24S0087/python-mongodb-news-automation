"""REST endpoints and dashboard for saved news and scheduler controls."""

import logging
import re
from datetime import date, datetime
from typing import Any

from bson import ObjectId
from flask import Flask, jsonify, render_template, request
from apscheduler.schedulers.background import BackgroundScheduler
from pymongo.database import Database
from pymongo.errors import PyMongoError

import config
from scheduler import (
    NEWS_SCHEDULE_INTERVALS,
    get_scheduler_status,
    request_immediate_collection,
    set_news_schedule,
    start_news_schedule,
    stop_news_schedule,
)


VALID_CATEGORIES = {
    "AI",
    "Agentic AI",
    "Quantum Computing",
    "Cloud",
    "Cybersecurity",
    "Programming",
    "Software Development",
    "Data Analytics",
    "Developer Tools",
    "Startups",
    "Technology Companies",
    "Other Technology",
}
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
logger = logging.getLogger(__name__)


def _to_json_value(value: Any) -> Any:
    """Convert MongoDB-specific values to ordinary JSON-compatible values."""
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _to_json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_to_json_value(item) for item in value]
    return value


def _page_size() -> int:
    """Read and validate the optional response limit."""
    raw_limit = request.args.get("limit", str(DEFAULT_PAGE_SIZE))
    try:
        limit = int(raw_limit)
    except ValueError:
        raise ValueError("limit must be an integer.") from None
    if not 1 <= limit <= MAX_PAGE_SIZE:
        raise ValueError(f"limit must be between 1 and {MAX_PAGE_SIZE}.")
    return limit


def _page_offset() -> int:
    """Read and validate the optional zero-based pagination offset."""
    raw_offset = request.args.get("skip", "0")
    try:
        offset = int(raw_offset)
    except ValueError:
        raise ValueError("skip must be a non-negative integer.") from None
    if offset < 0:
        raise ValueError("skip must be a non-negative integer.")
    return offset


def create_app(
    database: Database,
    scheduler: BackgroundScheduler | None = None,
) -> Flask:
    """Create the API application using an existing MongoDB database."""
    app = Flask(__name__)

    @app.errorhandler(PyMongoError)
    def handle_database_error(error: PyMongoError) -> tuple[Any, int]:
        logger.error("Database request failed (%s).", type(error).__name__)
        return jsonify({"error": "The database is temporarily unavailable."}), 503

    @app.get("/")
    def index() -> str:
        return render_template("index.html")

    def scheduler_unavailable() -> tuple[Any, int]:
        if scheduler is None:
            return jsonify({"error": "The scheduler is not available."}), 503
        try:
            return jsonify(get_scheduler_status(scheduler, database)), 200
        except RuntimeError as exc:
            return jsonify({"error": str(exc)}), 503

    @app.get("/scheduler/status")
    def scheduler_status() -> tuple[Any, int]:
        return scheduler_unavailable()

    @app.post("/scheduler/start")
    def scheduler_start() -> tuple[Any, int]:
        if scheduler is None:
            return jsonify({"error": "The scheduler is not available."}), 503
        try:
            start_news_schedule(scheduler)
            return jsonify(get_scheduler_status(scheduler, database)), 200
        except RuntimeError as exc:
            return jsonify({"error": str(exc)}), 503

    @app.post("/scheduler/stop")
    def scheduler_stop() -> tuple[Any, int]:
        if scheduler is None:
            return jsonify({"error": "The scheduler is not available."}), 503
        try:
            stop_news_schedule(scheduler)
            return jsonify(get_scheduler_status(scheduler, database)), 200
        except RuntimeError as exc:
            return jsonify({"error": str(exc)}), 503

    @app.put("/scheduler/interval")
    def scheduler_interval() -> tuple[Any, int]:
        if scheduler is None:
            return jsonify({"error": "The scheduler is not available."}), 503
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "A JSON request body is required."}), 400
        interval = payload.get("interval")
        if not isinstance(interval, str):
            return jsonify({"error": "interval must be a supported string value."}), 400
        try:
            set_news_schedule(scheduler, interval)
            return jsonify(get_scheduler_status(scheduler, database)), 200
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except RuntimeError as exc:
            return jsonify({"error": str(exc)}), 503

    @app.post("/scheduler/run-now")
    def scheduler_run_now() -> tuple[Any, int]:
        if scheduler is None:
            return jsonify({"error": "The scheduler is not available."}), 503
        try:
            if not request_immediate_collection(scheduler):
                return jsonify(
                    {"error": "A news collection is already running or queued."}
                ), 409
            return jsonify({"message": "News collection queued."}), 202
        except RuntimeError as exc:
            return jsonify({"error": str(exc)}), 503

    @app.get("/api/scheduler")
    def legacy_scheduler_status() -> tuple[Any, int]:
        return scheduler_unavailable()

    @app.post("/api/scheduler")
    def legacy_scheduler_update() -> tuple[Any, int]:
        if scheduler is None:
            return jsonify({"error": "The scheduler is not available."}), 503
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "A JSON request body is required."}), 400
        interval_minutes = payload.get("interval_minutes")
        interval_by_minutes = {
            seconds // 60: key
            for key, (seconds, _) in NEWS_SCHEDULE_INTERVALS.items()
        }
        if isinstance(interval_minutes, bool) or not isinstance(interval_minutes, int):
            return jsonify({"error": "interval_minutes must be an integer."}), 400
        interval = interval_by_minutes.get(interval_minutes)
        if interval is None:
            return jsonify({"error": "Choose 1, 5, 60, or 1440 minutes."}), 400
        try:
            set_news_schedule(scheduler, interval)
            return jsonify(get_scheduler_status(scheduler, database)), 200
        except RuntimeError as exc:
            return jsonify({"error": str(exc)}), 503

    @app.get("/health")
    def health() -> tuple[Any, int]:
        try:
            database.command("ping")
        except PyMongoError:
            return jsonify(
                {
                    "status": "unavailable",
                    "database": "disconnected",
                    "news_provider_configured": bool(
                        config.NEWS_API_KEY and config.NEWS_API_QUERY and config.NEWS_API_URL
                    ),
                }
            ), 503
        return jsonify(
            {
                "status": "ok",
                "database": "connected",
                "news_provider_configured": bool(
                    config.NEWS_API_KEY and config.NEWS_API_QUERY and config.NEWS_API_URL
                ),
            }
        ), 200

    @app.get("/news")
    def latest_news() -> tuple[Any, int]:
        try:
            limit = _page_size()
            offset = _page_offset()
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        query: dict[str, Any] = {}
        category = request.args.get("category", "").strip()
        if category:
            categories_by_name = {item.casefold(): item for item in VALID_CATEGORIES}
            matched_category = categories_by_name.get(category.casefold())
            if matched_category is None:
                return jsonify({"error": "Unknown news category."}), 400
            query["category"] = matched_category

        keyword = request.args.get("keyword", "").strip()
        if keyword:
            safe_keyword = re.escape(keyword)
            search_filter = {
                "$or": [
                    {"title": {"$regex": safe_keyword, "$options": "i"}},
                    {"description": {"$regex": safe_keyword, "$options": "i"}},
                    {"category": {"$regex": safe_keyword, "$options": "i"}},
                ]
            }
            if query:
                query = {"$and": [query, search_filter]}
            else:
                query = search_filter

        articles = list(
            database["news"]
            .find(query)
            .sort("published_at", -1)
            .skip(offset)
            .limit(limit)
        )
        return jsonify(_to_json_value(articles)), 200

    @app.get("/news/search")
    def search_news() -> tuple[Any, int]:
        keyword = request.args.get("keyword", "").strip()
        if not keyword:
            return jsonify({"error": "keyword is required."}), 400
        try:
            limit = _page_size()
            offset = _page_offset()
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        safe_keyword = re.escape(keyword)
        articles = list(
            database["news"]
            .find(
                {
                    "$or": [
                        {"title": {"$regex": safe_keyword, "$options": "i"}},
                        {"description": {"$regex": safe_keyword, "$options": "i"}},
                        {"category": {"$regex": safe_keyword, "$options": "i"}},
                    ]
                }
            )
            .sort("published_at", -1)
            .skip(offset)
            .limit(limit)
        )
        return jsonify(_to_json_value(articles)), 200

    @app.get("/news/category/<category>")
    def news_by_category(category: str) -> tuple[Any, int]:
        normalized_category = category.casefold()
        categories_by_name = {item.casefold(): item for item in VALID_CATEGORIES}
        matched_category = categories_by_name.get(normalized_category)
        if matched_category is None:
            return jsonify({"error": "Unknown news category."}), 400
        try:
            limit = _page_size()
            offset = _page_offset()
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        articles = list(
            database["news"]
            .find({"category": matched_category})
            .sort("published_at", -1)
            .skip(offset)
            .limit(limit)
        )
        return jsonify(_to_json_value(articles)), 200

    @app.get("/news/<article_id>")
    def get_news_article(article_id: str) -> tuple[Any, int]:
        if not ObjectId.is_valid(article_id):
            return jsonify({"error": "Article ID must be a valid MongoDB ObjectId."}), 400

        article = database["news"].find_one({"_id": ObjectId(article_id)})
        if article is None:
            return jsonify({"error": "Article not found."}), 404
        return jsonify(_to_json_value(article)), 200

    @app.get("/briefings")
    def list_briefings() -> tuple[Any, int]:
        try:
            limit = _page_size()
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        briefings = list(
            database["daily_briefings"]
            .find({})
            .sort("briefing_date", -1)
            .limit(limit)
        )
        return jsonify(_to_json_value(briefings)), 200

    @app.get("/briefings/<briefing_date>")
    def get_briefing(briefing_date: str) -> tuple[Any, int]:
        try:
            parsed_date = date.fromisoformat(briefing_date)
        except ValueError:
            return jsonify({"error": "Date must use YYYY-MM-DD format."}), 400
        if parsed_date.isoformat() != briefing_date:
            return jsonify({"error": "Date must use YYYY-MM-DD format."}), 400

        briefing = database["daily_briefings"].find_one(
            {"briefing_date": parsed_date.isoformat()}
        )
        if briefing is None:
            return jsonify({"error": "Briefing not found."}), 404
        return jsonify(_to_json_value(briefing)), 200

    return app
