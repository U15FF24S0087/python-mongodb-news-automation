"""Insert clearly labeled fictional demo articles into MongoDB."""

from datetime import datetime, timedelta, timezone

from pymongo.database import Database
from pymongo.errors import DuplicateKeyError, PyMongoError

from database import connect_to_mongodb


DEMO_STORIES = (
    (
        "AI",
        "Small Language Model Learns to Organize a Fictional Library",
        "DEMO DATA: In this fictional story, a research team tests a compact "
        "language model that sorts a sample library catalog. No real study "
        "or product is being reported.",
        "Demo AI Desk",
    ),
    (
        "Cybersecurity",
        "Security Exercise Finds a Training Lab Configuration Bug",
        "DEMO DATA: A fictional security team discovers a pretend configuration "
        "issue in an isolated training lab and documents a safe patching exercise.",
        "Demo Security Desk",
    ),
    (
        "Cloud",
        "Cloud Provider Opens a Simulated Student Practice Region",
        "DEMO DATA: This fictional cloud provider announces a mock environment "
        "for students to practice deployment and monitoring without real services.",
        "Demo Cloud Desk",
    ),
    (
        "Programming",
        "DEMO Python Tool Helps Beginners Visualize List Operations",
        "DEMO DATA: A fictional Python learning tool displays how append, sort, "
        "and remove operations change a sample list.",
        "Demo Developer Desk",
    ),
    (
        "Software Development",
        "DEMO Software Team Publishes a Beginner-Friendly Testing Checklist",
        "DEMO DATA: A fictional development team shares a simple checklist for "
        "writing and running tests in a classroom project.",
        "Demo Software Desk",
    ),
    (
        "Data Analytics",
        "DEMO Analytics Exercise Turns Sample Weather Rows into a Chart",
        "DEMO DATA: This fictional classroom exercise uses made-up weather data "
        "to demonstrate filtering, averages, and a basic chart.",
        "Demo Data Desk",
    ),
    (
        "Startups",
        "DEMO Student Startup Pitches a Fictional Campus Repair App",
        "DEMO DATA: A made-up student startup presents a concept for coordinating "
        "campus device repairs; no real company or funding is involved.",
        "Demo Startup Desk",
    ),
    (
        "Developer Tools",
        "DEMO Code Editor Adds a Practice Mode for Reading Error Messages",
        "DEMO DATA: A fictional editor feature gives learners sample Python "
        "errors and hints for understanding them.",
        "Demo Tools Desk",
    ),
    (
        "Quantum Computing",
        "DEMO Quantum Simulator Adds a Toy Qubit Visualization",
        "DEMO DATA: This fictional educational simulator visualizes a toy qubit "
        "state for classroom demonstrations; it is not a real research result.",
        "Demo Science Desk",
    ),
    (
        "Agentic AI",
        "DEMO Agent Exercise Plans Tasks in a Fictional Study Planner",
        "DEMO DATA: A fictional agent prototype organizes a sample study plan "
        "and asks a student to approve each suggested step.",
        "Demo AI Desk",
    ),
)


def build_demo_articles(now: datetime | None = None) -> list[dict[str, object]]:
    """Build ten visibly fictional records with recent, sortable UTC dates."""
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    current_time = current_time.astimezone(timezone.utc)
    collected_at = current_time.isoformat()
    articles = []

    for number, (category, title, description, source) in enumerate(
        DEMO_STORIES,
        start=1,
    ):
        published_at = (current_time - timedelta(hours=number - 1)).isoformat()
        articles.append(
            {
                "title": f"[DEMO] {title}",
                "description": description,
                "url": f"https://example.com/demo/article-{number}",
                "source": source,
                "author": "Demo Author",
                "category": category,
                "published_at": published_at,
                "collected_at": collected_at,
                "created_at": current_time,
                "is_demo": True,
            }
        )

    return articles


def seed_demo_articles(database: Database) -> tuple[int, int]:
    """Upsert only this script's demo URLs and return inserted/updated counts."""
    collection = database["news"]
    inserted_count = 0
    updated_count = 0

    for article in build_demo_articles():
        try:
            result = collection.update_one(
                {"url": article["url"], "is_demo": True},
                {
                    "$set": {
                        key: value
                        for key, value in article.items()
                        if key != "created_at"
                    },
                    "$setOnInsert": {"created_at": article["created_at"]},
                },
                upsert=True,
            )
        except DuplicateKeyError:
            raise ValueError(
                f"Refusing to replace a non-demo article at {article['url']}."
            ) from None
        if result.upserted_id is not None:
            inserted_count += 1
        elif result.matched_count:
            updated_count += 1

    return inserted_count, updated_count


def main() -> None:
    client = None
    try:
        client, database = connect_to_mongodb()
        inserted_count, updated_count = seed_demo_articles(database)
        print(
            "Demo seeding complete: "
            f"inserted={inserted_count}, updated={updated_count}, "
            f"total={inserted_count + updated_count}."
        )
    except PyMongoError:
        print(
            "Could not seed demo articles because MongoDB operation failed. "
            "Check that MongoDB is running and the configured URI is accessible."
        )
        raise SystemExit(1) from None
    except ValueError as error:
        print(f"Could not seed demo articles: {error}")
        raise SystemExit(1) from None
    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    main()
