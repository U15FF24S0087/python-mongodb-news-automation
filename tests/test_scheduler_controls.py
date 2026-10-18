"""Tests for interval selection and scheduler-control API endpoints."""

import threading
import unittest
from typing import Any
from unittest.mock import patch

from pymongo.errors import ServerSelectionTimeoutError

from api import create_app
import scheduler


class EmptyCursor:
    def __init__(self):
        self.sort_options: tuple[Any, ...] = ()
        self.limit_size: int | None = None
        self.skip_size: int | None = None

    def sort(self, *_args):
        self.sort_options = _args
        return self

    def skip(self, size):
        self.skip_size = size
        return self

    def limit(self, _size):
        self.limit_size = _size
        return self

    def __iter__(self):
        return iter(())


class EmptyCollection:
    def __init__(self):
        self.last_query: dict[str, Any] | None = None
        self.last_cursor: EmptyCursor | None = None
        self.count_queries: list[dict[str, Any]] = []

    def find(self, _query):
        self.last_query = _query
        self.last_cursor = EmptyCursor()
        return self.last_cursor

    def count_documents(self, _query):
        assert isinstance(_query, dict)
        self.count_queries.append(_query)
        return 0


class EmptyDatabase:
    def __init__(self):
        self.collections = {}

    def __getitem__(self, _name):
        if _name in {"news", "daily_briefings"}:
            if _name not in self.collections:
                self.collections[_name] = EmptyCollection()
            return self.collections[_name]
        raise KeyError(_name)

    def command(self, _name):
        if _name != "ping":
            raise ValueError(f"Unexpected database command: {_name}")
        return {"ok": 1}


class SchedulerControlsTests(unittest.TestCase):
    def setUp(self):
        self.collection_started = threading.Event()
        self.collection_patch = patch(
            "scheduler.run_daily_news_job",
            self.collection_started.set,
        )
        self.collection_patch.start()
        self.scheduler = scheduler.start_scheduler()
        self.database = EmptyDatabase()
        self.client = create_app(self.database, self.scheduler).test_client()

    def tearDown(self):
        self.scheduler.shutdown(wait=True)
        self.collection_patch.stop()

    def test_supported_intervals_reschedule_the_existing_job(self):
        expected_seconds = {
            "1_minute": 60,
            "5_minutes": 300,
            "1_hour": 3600,
            "1_day": 86400,
        }

        for interval, seconds in expected_seconds.items():
            with self.subTest(interval=interval):
                response = self.client.put(
                    "/scheduler/interval",
                    json={"interval": interval},
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json["interval_seconds"], seconds)
                self.assertEqual(len(self.scheduler.get_jobs()), 1)

    def test_start_stop_and_manual_collection(self):
        self.client.put("/scheduler/interval", json={"interval": "1_minute"})

        started = self.client.post("/scheduler/start")
        self.assertEqual(started.status_code, 200)
        self.assertTrue(started.json["running"])
        self.assertIsNotNone(started.json["next_run"])

        stopped = self.client.post("/scheduler/stop")
        self.assertEqual(stopped.status_code, 200)
        self.assertFalse(stopped.json["running"])
        self.assertIsNone(stopped.json["next_run"])

        queued = self.client.post("/scheduler/run-now")
        self.assertEqual(queued.status_code, 202)
        self.assertTrue(self.collection_started.wait(timeout=2))

    def test_invalid_intervals_and_duplicate_collection_are_rejected(self):
        self.assertEqual(
            self.client.put(
                "/scheduler/interval",
                json={"interval": "2_minutes"},
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.put(
                "/scheduler/interval",
                json={"interval": ["1_minute"]},
            ).status_code,
            400,
        )

        scheduler._collection_lock.acquire()
        try:
            response = self.client.post("/scheduler/run-now")
            self.assertEqual(response.status_code, 409)
        finally:
            scheduler._collection_lock.release()

    def test_dashboard_assets_and_news_endpoints_are_available(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        for path in ("/static/app.js", "/static/style.css"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                response.close()
        self.assertEqual(self.client.get("/news").json, [])
        self.assertEqual(self.client.get("/news/search?keyword=python").json, [])
        self.assertEqual(self.client.get("/news/category/AI").json, [])
        self.assertEqual(self.client.get("/health").status_code, 200)

    def test_news_endpoint_supports_combined_filters_and_pagination(self):
        response = self.client.get(
            "/news?limit=2&skip=3&category=AI&keyword=python"
        )

        self.assertEqual(response.status_code, 200)
        news_collection = self.database["news"]
        self.assertEqual(news_collection.last_cursor.skip_size, 3)
        self.assertEqual(news_collection.last_cursor.limit_size, 2)
        self.assertEqual(
            news_collection.last_query,
            {
                "$and": [
                    {"category": "AI"},
                    {
                        "$or": [
                            {"title": {"$regex": "python", "$options": "i"}},
                            {"description": {"$regex": "python", "$options": "i"}},
                            {"category": {"$regex": "python", "$options": "i"}},
                        ]
                    },
                ]
            },
        )

    def test_invalid_news_pagination_is_rejected(self):
        self.assertEqual(self.client.get("/news?skip=-1").status_code, 400)
        self.assertEqual(self.client.get("/news?skip=nope").status_code, 400)
        self.assertEqual(self.client.get("/news?category=not-a-category").status_code, 400)

    def test_status_contains_article_stats_and_recent_activity(self):
        status = self.client.get("/scheduler/status").json

        self.assertIn("today_articles", status)
        self.assertEqual(status["today_articles"], 0)
        self.assertIsInstance(status["activity"], list)
        today_filter = self.database["news"].count_queries[-1]
        self.assertIn("$regex", today_filter["collected_at"])
        self.assertEqual(today_filter["is_demo"], {"$ne": True})


class CollectionStatusTests(unittest.TestCase):
    def setUp(self):
        with scheduler._status_lock:
            self.original_status = dict(scheduler._collection_status)
            scheduler._collection_status.update(
                {
                    "last_run": None,
                    "last_successful_run": None,
                    "last_error": None,
                    "collecting": False,
                    "inserted_articles": 0,
                    "duplicate_articles": 0,
                }
            )

    def tearDown(self):
        with scheduler._status_lock:
            scheduler._collection_status.clear()
            scheduler._collection_status.update(self.original_status)

    def test_empty_provider_response_is_a_successful_collection(self):
        class FakeClient:
            closed = False

            def close(self):
                self.closed = True

        client = FakeClient()
        with (
            patch("scheduler.connect_to_mongodb", return_value=(client, EmptyDatabase())),
            patch("scheduler.fetch_technology_news", return_value=[]),
            patch("scheduler.save_news_articles", return_value=(0, 0)),
            patch("scheduler.generate_daily_briefing", return_value={}),
            patch("scheduler.print_briefing"),
        ):
            scheduler.run_daily_news_job()

        with scheduler._status_lock:
            status = dict(scheduler._collection_status)
        self.assertTrue(client.closed)
        self.assertIsNotNone(status["last_successful_run"])
        self.assertEqual(status["inserted_articles"], 0)
        self.assertIsNone(status["last_error"])

    def test_mongodb_connection_failure_is_reported_safely(self):
        with (
            patch(
                "scheduler.connect_to_mongodb",
                side_effect=ServerSelectionTimeoutError("private connection detail"),
            ),
        ):
            scheduler.run_daily_news_job()

        with scheduler._status_lock:
            status = dict(scheduler._collection_status)
        self.assertIn("MongoDB operation failed", status["last_error"])
        self.assertNotIn("private connection detail", status["last_error"])


if __name__ == "__main__":
    unittest.main()
