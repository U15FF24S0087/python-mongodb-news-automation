# Daily Global Tech News Scheduler: Complete Project Flow

This guide explains how news moves through the project, what APScheduler does,
how scheduled Python functions are triggered, what happens if the application
is stopped at the scheduled time, and how MongoDB prevents duplicate articles.

## 1. Project at a glance

The project has two different kinds of work:

1. **Collection work** contacts the configured external news provider, cleans
   and categorizes the returned articles, writes them to MongoDB, and generates
   a daily briefing. APScheduler or the dashboard's **Run Now** button starts
   this work.
2. **Read/display work** reads the articles and briefings already stored in
   MongoDB and returns them through Flask REST endpoints. The dashboard and
   Postman do this. Reading or polling the API does **not** contact the news
   provider or start collection.

```text
                         collection path
APScheduler / Run Now -> scheduler.run_daily_news_job()
                      -> news_service.fetch_technology_news()
                      -> external NewsAPI or GNews
                      <- JSON response
                      -> validate, normalize, categorize
                      -> database.save_news_articles()
                      -> MongoDB tech_news.news
                      -> briefing_service.generate_daily_briefing()
                      -> MongoDB tech_news.daily_briefings

                         read path
Browser dashboard / Postman -> Flask routes in api.py
                            -> MongoDB queries
                            <- JSON response
                            -> render articles / briefing in the client
```

## 2. Main files and responsibilities

| File | Responsibility |
| --- | --- |
| `main.py` | Opens the application's MongoDB connection, creates one APScheduler instance, creates the Flask app, and runs the local web server. It shuts down the scheduler and closes its MongoDB client when the server exits. |
| `config.py` | Loads `.env` settings such as MongoDB URI, provider URL/key/query, timeout, and default schedule hour/minute. It removes surrounding whitespace from values and validates numeric settings. |
| `scheduler.py` | Registers the recurring job, handles start/stop/change-interval actions, prevents overlapping collections, tracks in-process status/activity, and runs the collection/briefing workflow. |
| `news_service.py` | Sends an HTTP request to NewsAPI or GNews, checks the response, normalizes provider-specific JSON fields, and assigns a category using keyword rules. |
| `database.py` | Connects to MongoDB, creates unique indexes, and saves articles while counting duplicate URLs. |
| `briefing_service.py` | Selects recent articles using a simple importance score, creates the briefing text and metadata, and upserts the briefing for its date. |
| `api.py` | Defines Flask routes for health, saved news, search/category filters, briefings, and scheduler controls. |
| `templates/index.html`, `static/app.js`, `static/style.css` | Implement the browser dashboard, controls, polling, filters, article cards, and theme styling. |

The local `.env` file contains private settings. Do not put API keys or
MongoDB credentials in Postman responses, source code, screenshots, or chat.

## 3. Why use a scheduler?

Without a scheduler, a Python function runs only when something explicitly
calls it—for example, when you start a script or click **Run Now**. That would
require a person or another program to remember to collect news.

APScheduler keeps track of a configured trigger and calls a Python function
when that trigger becomes due. In this project the scheduled function is
`run_daily_news_job()` in `scheduler.py`. The scheduler makes the collection
repeat automatically while the Python application process is running.

The schedule is useful because it:

- automates repeated news collection;
- avoids asking a user to run a command each time;
- lets the dashboard show the next scheduled run and collection results;
- keeps browser polling separate from the more expensive news-provider call.

APScheduler is not a separate server or operating-system service here. It runs
inside the same Python application process as Flask.

## 4. How APScheduler triggers the Python function

The startup sequence in `main.py` is:

1. Call `connect_to_mongodb()` so the web application has its MongoDB database
   connection.
2. Call `start_scheduler()` once to create a `BackgroundScheduler`.
3. Register `run_daily_news_job` as one APScheduler job with the stable ID
   `daily_technology_news`.
4. Start the scheduler engine, while keeping its collection job initially
   paused.
5. Create the Flask application and start the server on
   `http://127.0.0.1:5000`.
6. When the user presses **Start Scheduler**, Flask calls
   `start_news_schedule()`, which resumes that existing job. It does not add a
   second copy.

Conceptually:

```text
main.py
  ├─ start_scheduler()
  │    └─ APScheduler registers a trigger -> run_daily_news_job
  └─ Flask serves API and dashboard
       └─ POST /scheduler/start -> resume the registered job
```

When the trigger's time arrives, APScheduler's background scheduler dispatches
`run_daily_news_job()` to execute in the application process. The job obtains
a non-blocking collection lock, then fetches, stores, and briefs the news. If
another collection already owns the lock, the overlapping attempt is skipped
instead of running concurrently. APScheduler also sets `max_instances=1` for
the scheduled job.

The available interval triggers are:

| Dashboard selection | Interval |
| --- | ---: |
| 1 Minute | 60 seconds |
| 5 Minutes | 300 seconds |
| 1 Hour | 3,600 seconds |
| 1 Day | 86,400 seconds |

The scheduler initially registers the `.env` default as a local wall-clock
schedule using `NEWS_SCHEDULE_HOUR` and `NEWS_SCHEDULE_MINUTE` (6:00 AM by
default). The application starts with this job paused. Selecting another
interval and pressing **Apply Schedule** replaces the trigger on the same job;
pressing **Start Scheduler** resumes it. A one-day interval is an interval of
24 hours, not necessarily a fixed 6:00 AM daily clock time.

`main.py` uses `use_reloader=False` so Flask's development reloader does not
accidentally create a second scheduler instance. This learning application
must run as one Python process/one web worker. Multiple server workers or
replicas would each own their own in-process scheduler and could collect twice.

## 5. What if the server is stopped at the scheduled time?

The scheduler only runs while the Python process is alive. If the computer is
off, the terminal running `main.py` is closed, the process crashes, or the
server is stopped at the due time, the job cannot execute then.

This project uses an in-process scheduler and does not persist a queue of
missed executions. Therefore:

- A run missed while the app is stopped is **not replayed automatically**.
- Starting the app after the scheduled time does not make it collect the
  missed news immediately.
- With the default 6:00 AM clock schedule, if the server was off at 6:00 AM
  and starts at 7:00 AM, that 6:00 AM run has been missed. After enabling the
  scheduler, the next clock-triggered run is the next time the configured
  daily clock schedule is due.
- If you have applied an interval such as one hour, the selected interval is
  held in process memory and is reset when the app restarts. Startup restores
  the `.env` default, initially paused.
- Collection timestamps, recent activity, and scheduler status are held in
  process memory as well. MongoDB articles and briefings remain stored.

To collect immediately after starting the app, use **Run Now** in the
dashboard or `POST /scheduler/run-now`. To keep the default schedule operating,
start the server and click **Start Scheduler**. For a production system that
must recover missed jobs, use a durable external process/service and a
persistent job store or explicitly implement a catch-up policy; that is not
part of this beginner project.

## 6. How duplicate articles are prevented

The project's article deduplication uses the article URL:

1. When `connect_to_mongodb()` runs, it creates a **unique index** on
   `tech_news.news.url`.
2. `save_news_articles()` tries to insert each normalized article as a
   MongoDB document.
3. If an article URL is already present, MongoDB rejects the insert with a
   duplicate-key error because of the unique index.
4. The save function catches that specific duplicate-key error, increments its
   duplicate count, and continues with other articles.
5. The collection job records inserted and duplicate counts in scheduler
   status/activity.

The important part is the MongoDB unique index. Checking for a URL in Python
before inserting would not be sufficient on its own: two collection attempts
could both check at the same time and then both try to insert. The unique
database constraint is enforced at insert time.

This implementation **does not update** an existing article when the provider
returns the same URL again; it keeps the first stored document and counts the
later URL as a duplicate. Demo articles are inserted by a separate seeder and
are not added by normal scheduled collection.

Briefings use a different rule: `daily_briefings.briefing_date` has a unique
index and the generator uses an upsert for that date, so generating today's
briefing replaces that date's briefing instead of making a second briefing
document for the same day.

## 7. Detailed news journey: external API to MongoDB

### Step A: A collection is requested

Collection starts either when:

- APScheduler's active job trigger becomes due; or
- a user presses **Run Now**, which calls `POST /scheduler/run-now`.

The manual endpoint queues the same `run_daily_news_job()` function on a
background thread. It returns HTTP `202 Accepted` when the request is queued.
If a collection is already running or queued, it returns HTTP `409 Conflict`.
The manual and scheduled paths share the collection lock.

### Step B: Python reads provider configuration

`config.py` loads settings from the local `.env` file. The news service reads
the provider URL, query, API key, and timeout. The key is passed to the provider
in the provider-specific format:

- NewsAPI: `X-Api-Key` HTTP header.
- GNews: `apikey` query parameter.

The provider host determines which request format to use. The API key is never
printed in normal application logs or returned by REST endpoints.

### Step C: Python sends an HTTP request

`news_service.fetch_technology_news()` uses the `requests` library to send the
configured query and waits no longer than
`NEWS_REQUEST_TIMEOUT_SECONDS`.

The service reports clear errors for conditions such as an invalid key,
provider rate limit (HTTP 429), other HTTP errors, network connection failure,
timeout, invalid JSON, or an unexpected response shape. A failed request is
not converted into fake articles or reported as a successful fetch.

### Step D: Python reads and normalizes JSON

On a successful response, the service expects an article list and extracts
provider fields such as title, description, source, author, publication time,
URL, and an optional image URL. It normalizes these into the project's shared
article fields:

```text
title
description
source
author
published_at
url
image_url
category
collected_at
```

Entries without a usable title or URL are skipped. The category is selected
from editable keyword rules in `news_service.py`; for example, a story
containing “quantum” or “qubit” is categorized as `Quantum Computing`.
Unknown technology topics are assigned `Other Technology`.

### Step E: PyMongo saves articles

`run_daily_news_job()` passes the normalized list to
`database.save_news_articles()`. PyMongo inserts documents into:

```text
Database:   tech_news (or MONGODB_DATABASE)
Collection: news
```

The unique `url` index prevents repeat articles. On success, the job records
the successful collection time, inserted count, duplicate count, and recent
activity. These scheduler fields are in memory; the article documents are
persistent in MongoDB.

### Step F: Python generates a briefing

After saving, `briefing_service.generate_daily_briefing()` reads saved news,
chooses recent articles using category importance and a small set of news
signals, creates summaries and “why it matters” descriptions, and stores the
briefing in `tech_news.daily_briefings`. The briefing document includes its
date, generation time, total article count, category counts, selected stories,
learning topic, career suggestion, and readable briefing text.

If the provider request fails but MongoDB is available, the job can still try
to create a briefing from already stored articles. The collection error remains
visible; using stored articles does not mean the external API fetch succeeded.

## 8. How saved news travels through REST, dashboard, and Postman

The Flask REST API is a reader/control interface. It uses the database opened
by `main.py` and does not call the external news provider for normal read
requests.

For example, when a browser or Postman requests `GET /news`:

1. The HTTP request arrives at Flask.
2. The `/news` route in `api.py` validates optional query parameters and asks
   MongoDB for saved `news` documents, sorted by publication time.
3. Flask converts MongoDB-specific values such as `ObjectId` and `datetime`
   into JSON-compatible values.
4. Flask sends a JSON array in the HTTP response.
5. Postman shows that JSON, or dashboard JavaScript builds article cards from
   it.

The browser dashboard polls saved data separately from collection:

- It requests `/news` about every 15 seconds.
- It requests `/scheduler/status` about every 5 seconds.
- It pauses its polling while the browser tab is hidden, then refreshes when
  the tab becomes visible again.
- Polling reads Flask/MongoDB only. It does not make a new request to NewsAPI
  or GNews.
- New articles become visible after a successful scheduled/manual collection
  has saved them and the dashboard's next read request completes.

Useful Postman requests:

| Method | URL | Purpose |
| --- | --- | --- |
| GET | `http://127.0.0.1:5000/health` | Check Flask and MongoDB health and whether provider settings are present. Settings being present does not verify that the provider key works. |
| GET | `http://127.0.0.1:5000/news` | Read the newest saved article documents. An empty JSON array means the query found no stored articles. |
| GET | `http://127.0.0.1:5000/news?limit=10&skip=0` | Read a page of saved articles. |
| GET | `http://127.0.0.1:5000/news?category=AI&keyword=python` | Combine category and text search. |
| GET | `http://127.0.0.1:5000/news/category/AI` | Read articles in a supported category. |
| GET | `http://127.0.0.1:5000/news/search?keyword=python` | Search saved article title, description, and category. |
| GET | `http://127.0.0.1:5000/briefings` | Read saved briefing documents. |
| GET | `http://127.0.0.1:5000/briefings/YYYY-MM-DD` | Read one briefing by its actual date. |
| GET | `http://127.0.0.1:5000/scheduler/status` | Check running state, interval, next/last run, counts, and errors. |
| PUT | `http://127.0.0.1:5000/scheduler/interval` | Apply an interval; send JSON such as `{"interval":"5_minutes"}`. |
| POST | `http://127.0.0.1:5000/scheduler/start` | Resume automatic collection. |
| POST | `http://127.0.0.1:5000/scheduler/stop` | Pause future scheduled collection. |
| POST | `http://127.0.0.1:5000/scheduler/run-now` | Queue one manual collection. |

For a `PUT` request in Postman, choose **Body → raw → JSON** and send:

```json
{
  "interval": "5_minutes"
}
```

Valid interval values are `1_minute`, `5_minutes`, `1_hour`, and `1_day`.
An unsupported value returns HTTP `400`. A concurrent manual request returns
HTTP `409`. A successfully queued manual request returns HTTP `202`; this
means the collection was accepted for execution, not that the provider call
has already succeeded. Check `/scheduler/status` for completion or failure.

## 9. Checking whether news really reached MongoDB

Do not infer a successful collection just from the Flask server starting or
from `/health` returning HTTP 200. `/health` checks the API/database connection
and whether provider settings are present, not whether the provider has
accepted the credentials.

Verify the journey with:

1. Start MongoDB and the Flask application.
2. Call `POST /scheduler/run-now` or click **Run Now**.
3. Poll `GET /scheduler/status` and inspect `collecting`,
   `last_successful_run`, `inserted_articles`, `duplicate_articles`, and
   `last_error`.
4. Query `GET /news` or inspect `tech_news.news` in MongoDB Compass.
5. If the external provider fails, read the safe `last_error` message. A
   briefing from stored records can still exist, but it does not prove the
   provider returned new articles.

An empty `/news` array can mean that no articles have been collected, the
provider returned no usable articles, or the endpoint is pointed at a
different MongoDB database than expected. Confirm the configured MongoDB URI
and database name without sharing credentials.

## 10. Important operating limits

- The server, APScheduler, and the machine must remain running for scheduled
  collection to occur.
- Missed runs are not caught up automatically.
- Schedule configuration and status/activity are currently held in process
  memory; after restart, the job returns to the `.env` daily schedule and
  starts paused.
- Run one application process/worker. Multiple workers or replicas can run
  duplicate schedulers.
- Keep scheduler-control endpoints on localhost unless authentication and
  deployment safeguards are added.
- The browser dashboard and REST API do not invent news. A successful empty
  provider response can store zero new records; a failed response is reported
  as an error.
