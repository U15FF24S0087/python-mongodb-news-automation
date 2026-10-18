# Daily Global Tech News Scheduler

A beginner-friendly Python project that will collect technology news, store it
in MongoDB, and generate a daily briefing. The application is being built in
small learning stages; follow each stage in order.

## Technologies

- Python
- MongoDB and PyMongo
- Requests and JSON
- Flask for the REST API
- APScheduler for the daily job

For a detailed explanation of the scheduler, missed runs, URL-based duplicate
prevention, and the complete external API → Python → MongoDB → REST/Postman
data flow, see [PROJECT_FLOW.md](./PROJECT_FLOW.md).

## Run the project (Windows PowerShell)

Follow these steps from the project folder, `C:\python-mongodb-news-automation`.
Use Python 3.10 or newer.

### 1. Create a virtual environment and install packages

```powershell
py --version
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

If PowerShell does not allow activating the environment, you can run the
environment's Python directly instead:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

In that case, replace `python` in the commands below with
`.\.venv\Scripts\python.exe`.

### 2. Configure your API key and MongoDB

Create a local environment file from the safe template:

```powershell
Copy-Item .env.example .env
```

Open `.env` in VS Code and set `NEWS_API_KEY` to a key issued by the provider
selected in `NEWS_API_URL`. The default endpoint is NewsAPI:
`https://newsapi.org/v2/everything`. The fetcher also supports GNews with
`NEWS_API_URL=https://gnews.io/api/v4/search`; use a GNews-issued key for that
endpoint. A key from one provider cannot authenticate to the other. Keep
`.env` private; Git ignores it. Existing Windows environment variables take
precedence over `.env`, and settings are read when Python starts; after edits,
restart the app.

Start your local MongoDB server before proceeding. On Windows, MongoDB
Community Server is commonly installed as a Windows service; check Windows
Services for the MongoDB service and start it if it is stopped. If you use
MongoDB Atlas instead, replace `MONGODB_URI` in `.env` with your Atlas
connection string and make sure your computer is permitted in the Atlas
network access settings. Connect to the same URI in MongoDB Compass.

The default schedule in `.env` is 6:00 AM local time. Change
`NEWS_SCHEDULE_HOUR` and `NEWS_SCHEDULE_MINUTE` if you want to test at a
different time.

### 3. Check the MongoDB connection

```powershell
python -c "from database import connect_to_mongodb; client, db = connect_to_mongodb(); print('Connected to', db.name); client.close()"
```

Expected output includes `Connected to tech_news`.

### 4. Run collection and briefing once immediately

The scheduler waits for the configured time; it does not run the job
immediately when it starts. To fetch articles and generate today's briefing
now, run:

```powershell
python -c "from scheduler import run_daily_news_job; run_daily_news_job()"
```

This requires a valid API key and a working internet connection. Then inspect
the `news` and `daily_briefings` collections in MongoDB Compass.

### 5. Start the API, dashboard, and scheduler service

```powershell
python main.py
```

Leave this PowerShell window open. The API runs at
`http://127.0.0.1:5000`; open that address in a browser to use the responsive
SignalDesk dashboard. It includes dark/light themes, live collection stats,
the scheduler control panel and activity, saved-article category/search
filters, paginated article cards, recent briefings, and backend-reported
service health. Use the theme button to switch themes; the selection is saved
in this browser.
The scheduler service starts once with periodic collection stopped. Choose an
interval, click **Apply Schedule**, then **Start Scheduler**. The supported
intervals are 1 minute, 5 minutes, 1 hour, and 1 day. A one-day interval
repeats every 24 hours. The initial selected interval uses the existing
`NEWS_SCHEDULE_HOUR` and `NEWS_SCHEDULE_MINUTE` settings (6:00 AM by default)
until another interval is applied.

The dashboard refreshes saved news every 15 seconds and checks scheduler
status every 5 seconds. Browser polling only reads Flask/MongoDB; it never
calls the news provider. Polling pauses while the browser tab is hidden and
refreshes when it becomes visible again. **Refresh Now** queues one immediate collection.
**Stop Scheduler** pauses the periodic job but does not cancel a collection
already running; Refresh Now remains available. Schedule choices reset when
the Python process restarts. The API binds to localhost and scheduler controls
are intended for local learning use. Do not expose control endpoints publicly
without adding authentication.

### Test the scheduler controls in PowerShell

Run the automated tests first; they use mocked news-provider responses and do
not make an external request:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Start the application in one PowerShell window:

```powershell
.\.venv\Scripts\python.exe main.py
```

With the server running, use a second PowerShell window:

```powershell
$base = "http://127.0.0.1:5000"
Invoke-RestMethod "$base/scheduler/status"
Invoke-RestMethod -Method Put -Uri "$base/scheduler/interval" -ContentType "application/json" -Body '{"interval":"1_minute"}'
Invoke-RestMethod -Method Post -Uri "$base/scheduler/start"
```

Wait a little over one minute and check `last_run` and MongoDB Compass:
`tech_news.news`. To replace the active interval, apply the new interval
without restarting Flask:

```powershell
Invoke-RestMethod -Method Put -Uri "$base/scheduler/interval" -ContentType "application/json" -Body '{"interval":"5_minutes"}'
Invoke-RestMethod -Method Post -Uri "$base/scheduler/run-now"
Invoke-RestMethod "$base/news?limit=100"
Invoke-RestMethod -Method Post -Uri "$base/scheduler/stop"
```

Other supported interval strings are `1_hour` and `1_day`. The one-day interval
is exactly 86,400 seconds after each scheduled run. Use the status endpoint
after changes to confirm the selected interval, running state, timestamps,
and next run. Do not wait an hour or a day just to test those options; update
each one and check its `interval_seconds` response:

```powershell
Invoke-RestMethod -Method Put -Uri "$base/scheduler/interval" -ContentType "application/json" -Body '{"interval":"1_hour"}'
Invoke-RestMethod "$base/scheduler/status"
Invoke-RestMethod -Method Put -Uri "$base/scheduler/interval" -ContentType "application/json" -Body '{"interval":"1_day"}'
Invoke-RestMethod "$base/scheduler/status"
Invoke-RestMethod -Method Post -Uri "$base/scheduler/stop"
```

To test server-side validation, send an unsupported value and expect HTTP 400:

```powershell
Invoke-RestMethod -Method Put -Uri "$base/scheduler/interval" -ContentType "application/json" -Body '{"interval":"2_minutes"}'
```

The unit tests also simulate an invalid API key (401), provider rate limit
(429), timeout, invalid JSON, an empty successful response, and MongoDB
connection failure. These tests verify error handling only; they do not prove
that your live API key works or that the provider currently has news available.
For a live invalid-key check, temporarily replace the key in `.env` with an
invalid placeholder, restart the app, and click **Refresh Now**. The
dashboard should display a safe authentication error. Restore your real key
afterward; never put it in chat or a command that may be saved in shell
history. A real 429 response depends on provider quota and cannot be forced
reliably.

### 6. Test in Postman

Create GET requests to:

```text
http://127.0.0.1:5000/health
http://127.0.0.1:5000/news
http://127.0.0.1:5000/news/search?keyword=python
http://127.0.0.1:5000/news/category/AI
http://127.0.0.1:5000/briefings
```

To test one article or briefing, copy a returned MongoDB `_id` or date and use
`http://127.0.0.1:5000/news/<id>` or
`http://127.0.0.1:5000/briefings/YYYY-MM-DD`.
For example, replace `<id>` with the actual `_id` returned by `/news`.
Use `Ctrl+C` in the PowerShell window to stop the application.

### Common startup problems

- **MongoDB connection refused or times out:** Start MongoDB and check
  `MONGODB_URI`. For Atlas, check the username/password and network access.
- **`NEWS_API_KEY is not configured`:** Put a valid key in `.env`, then restart
  the command so Python reloads the setting.
- **News API request failed:** Check that your computer has internet access
  and can reach the host in `NEWS_API_URL` over HTTPS (port 443). If the app reports an
  HTTP status, `401` usually means the API key is missing or invalid, `429`
  means the provider quota/rate limit was reached, and other `4xx` codes
  usually mean the endpoint or request parameters need checking. The provider
  and key must match: NewsAPI endpoint with a NewsAPI-issued key, or GNews
  endpoint with a GNews-issued key. NewsAPI receives its key in the
  `X-Api-Key` request header; GNews expects `apikey` as a request parameter.
  Never paste your API key into chat or share a screenshot of `.env`.
- **An old provider URL is still being used:** Stop Python, set
  `NEWS_API_URL` in `.env` to the endpoint for the provider that issued your
  key, then start Python again. The app loads `.env` at process startup.
- **No news fetched:** Check the API query, provider quota, and whether the
  provider returned an empty list. An empty article list is not a connection
  error.
- **Postman cannot connect:** Keep `python main.py` running and use port `5000`.
- **No briefing appears at startup:** This is expected. Run the immediate job
  command above, or leave the scheduler running until its configured time.

## Stage 2: configuration setup

1. Install Python and MongoDB Community Server, or use a MongoDB Atlas cluster.
2. Create and activate a virtual environment:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

3. Install the project dependencies:

   ```powershell
   pip install -r requirements.txt
   ```

4. Copy `.env.example` to `.env` and add your news API key. The example uses
   NewsAPI Everything endpoint by default. Obtain a key from the provider
   selected in `NEWS_API_URL`. Do not commit `.env`.
5. Start MongoDB locally, or set `MONGODB_URI` to your Atlas connection string.

## Configuration

| Variable | Purpose | Default |
| --- | --- | --- |
| `MONGODB_URI` | MongoDB connection string | `mongodb://localhost:27017` |
| `MONGODB_DATABASE` | Database name | `tech_news` |
| `NEWS_API_KEY` | News provider API key | Empty; set in `.env` |
| `NEWS_API_URL` | News API endpoint | NewsAPI Everything endpoint |
| `NEWS_API_QUERY` | Search terms sent to the provider | Broad technology search |
| `NEWS_REQUEST_TIMEOUT_SECONDS` | Maximum wait for an API response | `15` |
| `NEWS_SCHEDULE_HOUR` | Daily run hour, 24-hour clock | `6` |
| `NEWS_SCHEDULE_MINUTE` | Daily run minute | `0` |

The schedule is interpreted in the machine's local time. Schedule values must
be valid 24-hour clock values; the application reports invalid settings rather
than silently adjusting them.

## Stage 3: MongoDB connection

`database.py` uses PyMongo to connect to the configured MongoDB server, sends a
`ping` command to verify the connection, and creates a unique index on
`news.url`. MongoDB creates the database and collection when the first
document is inserted. The index prevents two articles with the same URL from
being stored; article insertion and duplicate handling will be added in a later
stage.

Start MongoDB before testing the connection. For a local MongoDB Community
Server, the default URI is `mongodb://localhost:27017`. In MongoDB Compass,
connect using the same URI. For Atlas, copy the cluster connection string into
`MONGODB_URI` in your local `.env` file.

After installing dependencies, a quick connection check is:

```powershell
python -c "from database import connect_to_mongodb; client, db = connect_to_mongodb(); print(db.name); client.close()"
```

The expected output is `tech_news`. A connection failure raises a PyMongo
error instead of returning a fake successful connection. The eventual API
health endpoint will turn service status into a safe HTTP response.

## Stage 4: fetching and categorizing news

`news_service.py` requests recent English-language articles from the configured
NewsAPI or GNews endpoint. It selects the correct parameter names for each
provider and checks for missing keys, network and timeout failures,
invalid JSON, provider errors, and unexpected response shapes. An empty
`articles` list is a valid result and returns an empty Python list. Articles
without a title or URL are skipped because those fields are needed to identify
and describe a story.

The service normalizes each result to `title`, `description`, `source`,
`author`, `published_at`, `url`, `category`, and `collected_at`. Keyword rules
in `CATEGORY_KEYWORDS` are intentionally editable. They return the first
matching category; more specific rules such as Agentic AI are checked before
the broader AI category. Articles that do not match a keyword are categorized
as `Other Technology`.

Once dependencies are installed and `.env` contains a valid API key, run a
small fetch check:

```powershell
python -c "from news_service import fetch_technology_news; articles = fetch_technology_news(); print(f'Fetched {len(articles)} articles'); print(articles[0] if articles else 'No articles found')"
```

To check categorization without making a network request:

```powershell
python -c "from news_service import categorize_article; print(categorize_article('New quantum chip announced', 'Researchers test qubits'))"
```

Expected output: `Quantum Computing`. The news API returns JSON, which
`response.json()` converts into Python dictionaries and lists. Each article
dictionary is normalized before later stages store it in MongoDB. This stage
does not write articles to the database yet.

## Stage 5: storing articles and handling duplicates

`save_news_articles(database, articles)` inserts each normalized article into
the MongoDB `news` collection. The unique index on `url`, created by
`connect_to_mongodb()`, is the database-level safeguard against duplicate
stories. If an article URL already exists, the helper counts it as a duplicate
and continues. Other MongoDB errors are not hidden.

The helper returns a tuple: `(inserted_count, duplicate_count)`. It rejects
articles without a non-empty URL instead of trying to save records that cannot
be reliably deduplicated.

After setting up `.env`, starting MongoDB, and installing dependencies, you
can fetch and save one batch from PowerShell:

```powershell
python -c "from database import connect_to_mongodb, save_news_articles; from news_service import fetch_technology_news; client, db = connect_to_mongodb(); articles = fetch_technology_news(); print('Inserted, duplicates:', save_news_articles(db, articles)); client.close()"
```

In MongoDB Compass, connect using the URI in `.env`, open the `tech_news`
database and then the `news` collection. If this is the first insert, the
database and collection become visible after MongoDB receives the documents.
Each document includes the normalized article fields, including category and
collection time. Running the fetch-and-save command again should increase the
duplicate count for URLs MongoDB has already seen.

**Data flow:** fetched article dictionaries → `save_news_articles()` →
`news.insert_one()` → URL unique-index check → inserted or counted duplicate.
This stage introduces MongoDB inserts and unique indexes; later stages will
add reading/filtering for the API and briefing.

## Stage 6: generating the daily briefing

`briefing_service.py` loads saved articles, chooses recent stories, builds
concise briefing sections, and saves the result in `daily_briefings`.
`connect_to_mongodb()` also creates a unique index on `briefing_date`, and
`update_one(..., upsert=True)` replaces the current date's briefing when run
again instead of creating a second copy.

### Simple importance score

Each article starts with a category score: Agentic AI and Quantum Computing
score 6; AI and Cybersecurity score 5; Cloud scores 4; Programming, Developer
Tools, Startups, and Technology Companies score 3; Other Technology scores 1.
Each matching phrase in `IMPORTANT_PHRASES`—such as “breakthrough” or
“vulnerability”—adds 2 points. Only stories from the latest 36 hours are
considered. Exact repeated titles are grouped, keeping the higher-scored
version. Results are sorted by score, then publication time, and limited to 12.
This transparent rule is an educational starting point, not a measure of
objective importance.

### Briefing contents

The saved document contains its date, generation time, article count,
category counts, selected headlines with summaries, reasons they matter,
sources, URLs, scores, a learning suggestion, and a career-skills suggestion.
It also includes `briefing_text`, a terminal-friendly rendering. Descriptions
from the source are used as summaries; when absent, the headline is used.
Nothing in this stage generates or verifies facts beyond the source article.

After articles have been saved and MongoDB is running, generate and print the
briefing:

```powershell
python -c "from database import connect_to_mongodb; from briefing_service import generate_daily_briefing, print_briefing; client, db = connect_to_mongodb(); briefing = generate_daily_briefing(db); print_briefing(briefing); client.close()"
```

Check `tech_news` → `daily_briefings` in MongoDB Compass. If there are no recent
articles, a briefing is still saved with an empty `top_news` list and a message
that no recent stories were available. `total_news` is the number of article
documents read from MongoDB, while `categories` counts the selected stories.
The scheduler stage below connects fetching, saving, and briefing generation
into one daily job.
The briefing date uses the machine's local calendar date; `generated_at` is
stored in UTC.

## Stage 7: daily scheduler

`scheduler.py` connects the existing services into one job: connect to MongoDB,
fetch API articles, insert new articles, generate the briefing, and print it.
It reports expected API and MongoDB failures without printing credentials or
raw database error details, and always closes the MongoDB client after a run.
An empty API article list is valid and still results in a briefing based on
recently stored articles.

`BackgroundScheduler` runs the job every day at `NEWS_SCHEDULE_HOUR` and
`NEWS_SCHEDULE_MINUTE` when the default schedule is active. These settings
default to 6:00 AM local system time. `main.py` creates one background
scheduler, initially paused for collection, while the API server runs:

```powershell
python main.py
```

Keep this process running for scheduled collection. Use the dashboard Start
button to enable the configured daily job, or apply an interval first.
`Ctrl+C` stops the API and scheduler. To verify the workflow immediately from
the command line, call the job directly:

```powershell
python -c "from scheduler import run_daily_news_job; run_daily_news_job()"
```

The same job powers scheduler intervals, the manual `Refresh Now` button, and
the command above. It uses a lock to prevent concurrent collections, reports
last-run/success/error status in memory, and closes its MongoDB client.
The daily job's broad flow is:

`scheduler` → `news_service` → `database.save_news_articles()` →
`briefing_service.generate_daily_briefing()` → print terminal briefing.
APScheduler invokes the initial job at the configured local wall-clock time.
After applying a UI interval, APScheduler uses a single interval trigger,
including a 24-hour interval for one day. The scheduler does not run while the
computer or Python process is stopped.

## Stage 8: REST API and search

`api.py` creates a Flask API for reading MongoDB collections and controlling
the in-process news scheduler.
`main.py` now connects to MongoDB, starts the scheduler in the background, and
serves the API on `http://127.0.0.1:5000`. Start both with:

```powershell
python main.py
```

The API and scheduler use the same MongoDB database. The API keeps its
connection open while serving requests; each collection job opens and closes
its own connection. MongoDB connection failure is reported with a safe message
and prevents the server from starting. Press `Ctrl+C` to stop the server and
scheduler.

### Endpoints

| Method and path | Purpose | Success |
| --- | --- | --- |
| `GET /health` | Check API and MongoDB connectivity | `200` |
| `GET /news` | Get newest articles | `200` |
| `GET /news/<id>` | Get one article by MongoDB ObjectId | `200` |
| `GET /news/category/<category>` | Filter by a supported category | `200` |
| `GET /news/search?keyword=python` | Search title, description, and category | `200` |
| `GET /briefings` | Get previous briefings | `200` |
| `GET /briefings/<date>` | Get a briefing by `YYYY-MM-DD` | `200` |
| `GET /scheduler/status` | Return schedule, collection state, and timestamps | `200` |
| `POST /scheduler/start` | Enable periodic collection | `200` |
| `POST /scheduler/stop` | Pause periodic collection | `200` |
| `PUT /scheduler/interval` | Replace the interval; body `{"interval":"5_minutes"}` | `200` |
| `POST /scheduler/run-now` | Queue one immediate collection | `202` |

List endpoints accept an optional `limit` from 1 to 100 (default 20), for
example `/news?limit=10`. The `/news` endpoint also accepts a non-negative
`skip` offset, a supported `category`, and a `keyword` searched across title,
description, and category. These filters can be combined; for example:
`/news?category=AI&keyword=python&limit=12&skip=12`. The dashboard uses the
same endpoint for its filters and Load More action. Error responses have a simple JSON shape such as
`{"error":"Article not found."}`. Invalid IDs, dates, categories, limits, or
offsets and missing search keywords return `400`; missing articles and briefings return
`404`; an unavailable database returns `503`. MongoDB IDs and dates are
converted to plain strings in JSON.

The scheduler status tracks the most recent attempt, most recent successful
collection, next scheduled run, total saved documents, inserted/duplicate
counts, today's non-demo article count (UTC), a short recent activity list, and
the latest safe error message. `/health` reports whether news-provider settings
are present, not whether the key currently works; only an actual collection
can confirm provider connectivity and authentication. API keys and MongoDB
credentials are never included. Interval choices and collection status live
in the process; restarting the app restores the configured daily schedule in
the stopped state.

This beginner project runs one Flask process and one APScheduler instance.
Do not run it with multiple workers or multiple replicas: each process would
otherwise run its own scheduler.

### Test with Postman

1. Start the server using `python main.py`.
2. Create a `GET` request to `http://127.0.0.1:5000/health` and send it.
3. Try `http://127.0.0.1:5000/news?limit=5`.
4. Copy an article's `_id` string from that JSON and request
   `http://127.0.0.1:5000/news/<id>`.
5. Try a category, for example
   `http://127.0.0.1:5000/news/category/Quantum%20Computing`.
6. Search with `http://127.0.0.1:5000/news/search?keyword=python`.
7. Check briefing history at `/briefings`, then use a returned date at
   `/briefings/YYYY-MM-DD`.
8. Try invalid inputs such as `/news/not-an-object-id`,
   `/briefings/not-a-date`, `/news/category/Unknown`, or `/news?limit=0` to
   see the corresponding JSON error.

### Sample responses

`GET /health`:

```json
{"status": "ok", "database": "connected"}
```

`GET /news/search?keyword=python`:

```json
[
  {
    "_id": "671234567890abcdef123456",
    "title": "A Python developer tool is released",
    "description": "The release adds a new debugging feature.",
    "source": "Example News",
    "author": null,
    "published_at": "2026-10-18T08:30:00Z",
    "url": "https://example.com/python-tool",
    "category": "Programming",
    "collected_at": "2026-10-18T08:35:00+00:00"
  }
]
```

Search terms are escaped before being used as regular expressions, so users
search for literal text rather than supplying arbitrary regex patterns. The
API returns stored records only; collecting fresh news remains the scheduler's
responsibility.

## Stage 9: final project demonstration

Use this checklist for a class presentation. First, confirm MongoDB is running,
`.env` has a valid `NEWS_API_KEY`, and dependencies are installed:

```powershell
pip install -r requirements.txt
```

### Seed clearly marked demo articles

If the news API is unavailable, seed ten fictional records without starting
the real collection job:

```powershell
.\.venv\Scripts\python.exe seed_demo_data.py
```

The script uses the existing MongoDB connection function and upserts only its
stable `https://example.com/demo/article-*` URLs where `is_demo` is true. Each
record has `[DEMO]` in its title, a description labeled `DEMO DATA`, and a
fictional source. It will not delete records or replace a non-demo article.
The output reports inserted and updated counts. Rerunning the script updates
the same ten demo records rather than adding duplicates.

Refresh `tech_news.news` in MongoDB Compass and confirm the demo URL, `is_demo:
true`, and `[DEMO]` title values. With the Flask app running, verify the HTTP
response:

```powershell
Invoke-RestMethod http://127.0.0.1:5000/news
Invoke-RestMethod "http://127.0.0.1:5000/news/search?keyword=python"
Invoke-RestMethod "http://127.0.0.1:5000/news/category/Data%20Analytics"
```

Demo records are included in briefing selection because their dates are recent.
They remain visibly labeled so the generated briefing cannot present them as
genuine reporting. The seeder is a separate, manual command and does not run
when the Flask server or scheduler starts.

1. Run `python -c "from database import connect_to_mongodb; c, db = connect_to_mongodb(); print(db.name); c.close()"` to demonstrate the MongoDB connection.
2. Run `python -c "from scheduler import run_daily_news_job; run_daily_news_job()"` to fetch news, insert non-duplicates, generate the briefing, and print it.
3. Open MongoDB Compass, connect using `MONGODB_URI`, and show `tech_news.news` and `tech_news.daily_briefings`, including the unique indexes and stored documents.
4. Start the full application with `python main.py`. Show the scheduler startup message and leave the process running.
5. In Postman, request `/health`, `/news`, a specific `/news/<id>`, `/news/category/AI`, `/news/search?keyword=python`, `/briefings`, and one `/briefings/<date>`.
6. Demonstrate validation by requesting an invalid ObjectId, date, category, missing search keyword, and invalid list limit.
7. Explain that the scheduler triggers collection at the configured local time, while API calls only read stored documents.
8. Walk through the complete data flow: environment configuration → API request/JSON → normalized and categorized article → URL unique-index insert → relevance score → daily briefing upsert → API JSON response.

`python main.py` runs both the API and scheduler in one process. The scheduler
does not execute if the application process is stopped. To demonstrate the
automatic schedule without waiting until 6:00 AM, temporarily set
`NEWS_SCHEDULE_HOUR` and `NEWS_SCHEDULE_MINUTE` in `.env` to a near-future local
time, restart the app, observe the run, then restore the intended values.

## Current project status

Environment configuration, dependencies, secret exclusions, MongoDB
connection/index setup, news fetching/categorization, MongoDB article
insertion, briefing generation, daily scheduling, and read-only REST APIs are
in place. Follow the demonstration checklist to verify the complete flow with
a live news API and MongoDB instance.