"""Select important recent news and save a daily briefing."""

from collections import Counter
from datetime import date, datetime, timedelta, timezone
from typing import Any

from pymongo.database import Database


CATEGORY_SCORES = {
    "Agentic AI": 6,
    "Quantum Computing": 6,
    "AI": 5,
    "Cybersecurity": 5,
    "Cloud": 4,
    "Programming": 3,
    "Software Development": 3,
    "Data Analytics": 3,
    "Developer Tools": 3,
    "Startups": 3,
    "Technology Companies": 3,
    "Other Technology": 1,
}
IMPORTANT_PHRASES = (
    "announces",
    "announced",
    "breakthrough",
    "breach",
    "launches",
    "launched",
    "open source",
    "vulnerability",
)
MAX_TOP_NEWS = 12
ARTICLE_MAX_AGE = timedelta(hours=36)


def _parse_article_date(article: dict[str, Any]) -> datetime | None:
    """Read an article date, treating timezone-free values as UTC."""
    for field in ("published_at", "collected_at"):
        value = article.get(field)
        if not isinstance(value, str):
            continue
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return None


def score_article(article: dict[str, Any]) -> int:
    """Score articles using topic importance and a few clear news signals."""
    score = CATEGORY_SCORES.get(article.get("category"), 1)
    text = f"{article.get('title', '')} {article.get('description', '')}".casefold()
    score += sum(2 for phrase in IMPORTANT_PHRASES if phrase in text)
    return score


def select_top_news(
    articles: list[dict[str, Any]],
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Return recent, relevant stories in deterministic score order."""
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    current_time = current_time.astimezone(timezone.utc)
    cutoff = current_time - ARTICLE_MAX_AGE

    unique_articles: dict[str, dict[str, Any]] = {}
    for article in articles:
        article_date = _parse_article_date(article)
        if article_date is None or not cutoff <= article_date <= current_time:
            continue

        url = article.get("url")
        title = article.get("title")
        if not isinstance(url, str) or not isinstance(title, str):
            continue

        story_key = " ".join(title.casefold().split())
        existing = unique_articles.get(story_key)
        article_key = (
            score_article(article),
            article_date,
            url,
        )
        existing_date = _parse_article_date(existing) if existing else None
        existing_key = (
            score_article(existing),
            existing_date or datetime.min.replace(tzinfo=timezone.utc),
            existing.get("url", ""),
        ) if existing else None
        if existing_key is None or article_key > existing_key:
            unique_articles[story_key] = article

    return sorted(
        unique_articles.values(),
        key=lambda article: (
            score_article(article),
            _parse_article_date(article) or datetime.min.replace(tzinfo=timezone.utc),
            article["url"],
        ),
        reverse=True,
    )[:MAX_TOP_NEWS]


def _why_it_matters(category: str) -> str:
    explanations = {
        "Agentic AI": "It shows how AI agents may automate multi-step work and change software workflows.",
        "Quantum Computing": "It may affect future computing capabilities and the security of current systems.",
        "AI": "It can influence how people and organizations build and use intelligent software.",
        "Cybersecurity": "It highlights risks and defenses that affect digital services and user data.",
        "Cloud": "It may change the cost, reliability, or capabilities of cloud-based applications.",
        "Programming": "It can influence how developers write, maintain, and learn software.",
        "Developer Tools": "It may improve developer productivity and the way teams build software.",
        "Startups": "It can signal changing investment, competition, and business opportunities.",
        "Technology Companies": "It may affect products, platforms, or decisions across the tech industry.",
    }
    return explanations.get(category, "It is a technology development worth monitoring.")


def _make_summary(article: dict[str, Any]) -> str:
    description = article.get("description")
    if isinstance(description, str) and description.strip():
        summary = description.strip()
    else:
        summary = article.get("title", "")
    if len(summary) > 600:
        return f"{summary[:597].rstrip()}..."
    return summary


def _make_briefing_text(
    briefing_date: date,
    top_news: list[dict[str, Any]],
    learning_topic: str,
    career_opportunity: str,
) -> str:
    lines = [
        "DAILY GLOBAL TECH BRIEFING",
        f"Date: {briefing_date.isoformat()}",
        "",
    ]
    for number, story in enumerate(top_news, start=1):
        lines.extend(
            [
                f"{number}. {story['category']} - {story['title']}",
                f"Summary: {story['summary']}",
                f"Why it matters: {story['why_it_matters']}",
                f"Source: {story['source']}",
                "",
            ]
        )
    lines.extend(
        [
            "LEARNING OF THE DAY",
            learning_topic,
            "",
            "CAREER OPPORTUNITY",
            career_opportunity,
        ]
    )
    return "\n".join(lines)


def generate_daily_briefing(
    database: Database,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build today's briefing from recent MongoDB articles and save it."""
    local_generated_at = now or datetime.now().astimezone()
    briefing_date = local_generated_at.date()
    generated_at = local_generated_at
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=timezone.utc)
    generated_at = generated_at.astimezone(timezone.utc)

    articles = list(database["news"].find({}))
    selected_articles = select_top_news(articles, generated_at)
    top_news = [
        {
            "title": article["title"],
            "summary": _make_summary(article),
            "why_it_matters": _why_it_matters(article.get("category", "Other Technology")),
            "source": article.get("source", "Unknown"),
            "url": article["url"],
            "category": article.get("category", "Other Technology"),
            "score": score_article(article),
        }
        for article in selected_articles
    ]
    categories = dict(Counter(story["category"] for story in top_news))
    learning_topic = (
        f'Explore {top_news[0]["category"]} and build a small example related to '
        f'"{top_news[0]["title"]}".'
        if top_news
        else "Review a technology topic you want to understand better and build a small example."
    )
    career_opportunity = (
        f"Related skills to explore: {', '.join(categories)}. Look for learning "
        "projects and entry-level roles that use these technologies."
        if categories
        else "No recent stories were available to infer skills or roles today."
    )
    briefing = {
        "briefing_date": briefing_date.isoformat(),
        "generated_at": generated_at,
        "total_news": len(articles),
        "categories": categories,
        "top_news": top_news,
        "learning_topic": learning_topic,
        "career_opportunity": career_opportunity,
        "briefing_text": _make_briefing_text(
            briefing_date,
            top_news,
            learning_topic,
            career_opportunity,
        ),
        "created_at": generated_at,
    }

    database["daily_briefings"].update_one(
        {"briefing_date": briefing["briefing_date"]},
        {"$set": briefing},
        upsert=True,
    )
    return briefing


def print_briefing(briefing: dict[str, Any]) -> None:
    """Print the readable text version of a briefing."""
    print(briefing["briefing_text"])
