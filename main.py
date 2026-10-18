"""Start the Flask dashboard and its single background scheduler service."""

import logging

from api import create_app
from database import connect_to_mongodb
from scheduler import start_scheduler
from pymongo.errors import PyMongoError


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        client, database = connect_to_mongodb()
    except PyMongoError:
        logging.getLogger(__name__).error(
            "Application could not start because MongoDB is unavailable."
        )
        return

    scheduler = None
    try:
        scheduler = start_scheduler()
        app = create_app(database, scheduler)
        app.run(host="127.0.0.1", port=5000, use_reloader=False)
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=True)
        client.close()


if __name__ == "__main__":
    main()
