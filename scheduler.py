"""Schedule and track technology-news collection in one application process."""

import logging
from datetime import datetime, timedelta, timezone
from threading import Lock, Thread
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from pymongo.database import Database
from pymongo.errors import PyMongoError

import config
from briefing_service import generate_daily_briefing, print_briefing
from database import connect_to_mongodb, save_news_articles
from news_service import NewsApiError, fetch_technology_news


logger = logging.getLogger(__name__)
SCHEDULE_JOB_ID = "daily_technology_news"
NEWS_SCHEDULE_INTERVALS = {
    "1_minute": (60, "Every 1 minute"),
    "5_minutes": (300, "Every 5 minutes"),
    "1_hour": (3600, "Every 1 hour"),
    "1_day": (86400, "Every 1 day"),
}

_collection_lock = Lock()
_manual_lock = Lock()
_status_lock = Lock()
_manual_queued = False
_collection_activity: list[dict[str, str]] = []
_collection_status: dict[str, Any] = {
    "last_run": None,
    "last_successful_run": None,
    "last_error": None,
    "collecting": False,
    "inserted_articles": 0,
    "duplicate_articles": 0,
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _set_status(**updates: Any) -> None:
    with _status_lock:
        _collection_status.update(updates)


def _record_activity(message: str, level: str = "info") -> None:
    with _status_lock:
        _collection_activity.insert(
            0,
            {
                "message": message,
                "level": level,
                "timestamp": _utc_now().isoformat(),
            },
        )
        del _collection_activity[20:]


def _run_manual_news_job() -> None:
    """Run one queued manual collection and clear its pending state."""
    global _manual_queued
    try:
        run_daily_news_job()
    finally:
        with _manual_lock:
            _manual_queued = False


def run_daily_news_job() -> None:
    """Fetch, save, and brief news while preventing overlapping collections."""
    if not _collection_lock.acquire(blocking=False):
        logger.warning("News collection skipped because another collection is running.")
        return

    client = None
    run_started_at = _utc_now()
    _set_status(
        last_run=run_started_at,
        last_error=None,
        collecting=True,
        inserted_articles=0,
        duplicate_articles=0,
    )
    _record_activity("News collection started.")
    try:
        client, database = connect_to_mongodb()
        articles = fetch_technology_news()
        inserted_count, duplicate_count = save_news_articles(database, articles)
        successful_at = _utc_now()
        _set_status(
            last_successful_run=successful_at,
            inserted_articles=inserted_count,
            duplicate_articles=duplicate_count,
            last_error=None,
        )
        _record_activity(
            f"Collection completed: {inserted_count} new, "
            f"{duplicate_count} duplicate, {len(articles)} fetched."
        )

        briefing = generate_daily_briefing(database)
        logger.info(
            "News collection completed: fetched=%d inserted=%d duplicates=%d",
            len(articles),
            inserted_count,
            duplicate_count,
        )
        print_briefing(briefing)
    except NewsApiError as exc:
        _set_status(last_error=str(exc))
        _record_activity(f"Collection failed: {exc}", "error")
        logger.error("News collection failed: %s", exc)
        if client is not None:
            try:
                briefing = generate_daily_briefing(database)
            except PyMongoError as briefing_error:
                _set_status(
                    last_error=(
                        "The news provider failed and MongoDB could not generate "
                        "a briefing from stored articles."
                    )
                )
                logger.error(
                    "Could not generate a briefing from stored news (%s).",
                    type(briefing_error).__name__,
                )
            except ValueError as briefing_error:
                _set_status(
                    last_error=(
                        "The news provider failed and the stored-news briefing "
                        "could not be generated."
                    )
                )
                logger.error(
                    "Could not generate a briefing from stored news (%s).",
                    type(briefing_error).__name__,
                )
            else:
                print_briefing(briefing)
    except PyMongoError as exc:
        _set_status(
            last_error="MongoDB operation failed; collection or briefing may be incomplete."
        )
        _record_activity("Collection failed: MongoDB operation unavailable.", "error")
        logger.error(
            "News collection could not complete because MongoDB is unavailable (%s).",
            type(exc).__name__,
        )
    except ValueError as exc:
        _set_status(last_error=str(exc))
        _record_activity(f"Collection failed: {exc}", "error")
        logger.error("News collection or briefing could not complete: %s", exc)
    finally:
        try:
            if client is not None:
                client.close()
        finally:
            _set_status(collecting=False)
            _collection_lock.release()


def start_scheduler() -> BackgroundScheduler:
    """Create the single scheduler engine, initially with collection stopped."""
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        run_daily_news_job,
        trigger=CronTrigger(
            hour=config.NEWS_SCHEDULE_HOUR,
            minute=config.NEWS_SCHEDULE_MINUTE,
        ),
        id=SCHEDULE_JOB_ID,
        name="Fetch news and generate the daily briefing",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start(paused=True)
    scheduler.pause_job(SCHEDULE_JOB_ID)
    scheduler.resume()
    logger.info(
        "Scheduler service initialized; collection is stopped. "
        "The configured daily schedule is %02d:%02d local time.",
        config.NEWS_SCHEDULE_HOUR,
        config.NEWS_SCHEDULE_MINUTE,
    )
    return scheduler


def _job_interval(scheduler: BackgroundScheduler) -> tuple[str, int, str]:
    job = scheduler.get_job(SCHEDULE_JOB_ID)
    if job is None:
        raise RuntimeError("The news collection job is not registered.")

    if isinstance(job.trigger, IntervalTrigger):
        seconds = int(job.trigger.interval.total_seconds())
        for interval, (interval_seconds, label) in NEWS_SCHEDULE_INTERVALS.items():
            if seconds == interval_seconds:
                return interval, seconds, label
        raise RuntimeError("The news collection job has an unsupported interval.")

    if isinstance(job.trigger, CronTrigger):
        return (
            "1_day",
            86400,
            f"Daily at {config.NEWS_SCHEDULE_HOUR:02d}:"
            f"{config.NEWS_SCHEDULE_MINUTE:02d} local time",
        )
    raise RuntimeError("The news collection job has an unsupported schedule.")


def get_scheduler_status(
    scheduler: BackgroundScheduler,
    database: Database | None = None,
) -> dict[str, Any]:
    """Return scheduler state and the latest collection results."""
    job = scheduler.get_job(SCHEDULE_JOB_ID)
    if job is None:
        raise RuntimeError("The news collection job is not registered.")

    interval, interval_seconds, label = _job_interval(scheduler)
    running = job.next_run_time is not None
    with _status_lock:
        status = dict(_collection_status)
    with _manual_lock:
        manual_queued = _manual_queued

    total_articles = database["news"].count_documents({}) if database is not None else None
    today_articles = None
    if database is not None:
        today_prefix = _utc_now().date().isoformat()
        today_articles = database["news"].count_documents(
            {
                "collected_at": {"$regex": f"^{today_prefix}"},
                "is_demo": {"$ne": True},
            }
        )
    next_run = job.next_run_time
    with _status_lock:
        activity = list(_collection_activity)
    return {
        "running": running,
        "interval": interval,
        "interval_seconds": interval_seconds,
        "schedule_label": label,
        "interval_trigger": isinstance(job.trigger, IntervalTrigger),
        "last_run": status["last_run"].isoformat() if status["last_run"] else None,
        "last_successful_run": (
            status["last_successful_run"].isoformat()
            if status["last_successful_run"]
            else None
        ),
        "next_run": next_run.isoformat() if next_run else None,
        "collecting": status["collecting"],
        "collection_queued": manual_queued,
        "last_error": status["last_error"],
        "inserted_articles": status["inserted_articles"],
        "duplicate_articles": status["duplicate_articles"],
        "total_articles": total_articles,
        "today_articles": today_articles,
        "activity": activity,
        "interval_options": [
            {"interval": key, "label": label, "seconds": seconds}
            for key, (seconds, label) in NEWS_SCHEDULE_INTERVALS.items()
        ],
    }


def set_news_schedule(scheduler: BackgroundScheduler, interval: str) -> None:
    """Replace the existing collection job's trigger with a supported interval."""
    if interval not in NEWS_SCHEDULE_INTERVALS:
        raise ValueError("Choose 1_minute, 5_minutes, 1_hour, or 1_day.")

    job = scheduler.get_job(SCHEDULE_JOB_ID)
    if job is None:
        raise RuntimeError("The news collection job is not registered.")

    seconds, label = NEWS_SCHEDULE_INTERVALS[interval]
    scheduler.modify_job(
        SCHEDULE_JOB_ID,
        trigger=IntervalTrigger(seconds=seconds),
        name=f"Fetch news and generate briefing ({label})",
    )
    _record_activity(f"Schedule applied: {label}.")
    logger.info("News collection schedule changed to %s.", label)


def start_news_schedule(scheduler: BackgroundScheduler) -> None:
    """Enable periodic collection without creating another scheduled job."""
    job = scheduler.get_job(SCHEDULE_JOB_ID)
    if job is None:
        raise RuntimeError("The news collection job is not registered.")
    if job.next_run_time is None:
        scheduler.resume_job(SCHEDULE_JOB_ID)
        interval, _, label = _job_interval(scheduler)
        _record_activity(f"Scheduler started: {label} ({interval}).")
        logger.info("News collection scheduler started: %s (%s).", label, interval)


def stop_news_schedule(scheduler: BackgroundScheduler) -> None:
    """Pause periodic collection while keeping the scheduler available for run-now."""
    job = scheduler.get_job(SCHEDULE_JOB_ID)
    if job is None:
        raise RuntimeError("The news collection job is not registered.")
    if job.next_run_time is not None:
        scheduler.pause_job(SCHEDULE_JOB_ID)
        _record_activity("Scheduler stopped.")
        logger.info("News collection scheduler stopped.")


def request_immediate_collection(scheduler: BackgroundScheduler) -> bool:
    """Queue one manual collection, even when periodic scheduling is stopped."""
    global _manual_queued
    with _manual_lock:
        if scheduler.get_job(SCHEDULE_JOB_ID) is None:
            raise RuntimeError("The news collection job is not registered.")
        if _collection_lock.locked() or _manual_queued:
            return False
        _manual_queued = True
        worker = Thread(
            target=_run_manual_news_job,
            name="manual-news-collection",
        )
        started = False
        try:
            worker.start()
            started = True
        finally:
            if not started:
                _manual_queued = False
    logger.info("Manual news collection was queued.")
    _record_activity("Manual collection requested.")
    return True
