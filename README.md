# Globe News Atlas

An interactive 3D atlas of world events, bilateral relationships, and multi-perspective media coverage. News is ingested from live public sources, normalized into a Parquet data lake, clustered into events, and served to a React + WebGL globe.

There is no synthetic event data and no random fallback geocoding. When a story cannot be tied to a real place, it is not plotted. When the pipeline has not produced data yet, the UI says so.

## Features

- **3D globe and list view** — globe.gl / Three.js with category filters, time windows, spectrum filtering, search, hover cards, and an accessible table fallback.
- **Detailed political map** — state/province divisions for every country, higher-resolution country borders, and neutral disputed-area tints with dashed claim boundaries.
- **Scale-aware globe** — numbered markers group stories at the same location and stay a constant screen size at every zoom; country names sit at Natural Earth cartographic label points and are limited to the current view focus with collision culling; state/province names lazy-load and spread in only after deeper regional zoom; bilateral arcs recede at regional scale; high-resolution NASA day/night imagery sits under the boundary layer. The dock reports shown events against the true window total instead of implying each window contains only the display cap.
- **Country desk** — click any country label to open a ranked briefing for the active time window. **Latest** shows the country's top 10 across all topics; **Briefing**, **Protest**, **Conflict**, and **Technology** narrow the desk to the focused categories. Rows open the full event dossier, and closing the dossier returns to the desk without losing the selected country.
- **Watchline, Storylines, Thin File and Rewind** — signed-in readers can pin up to eight countries and followed storylines, get a return brief of what moved since their last visit, and share a read-only desk link. Storylines expose recurring bilateral relations; the Thin File collects dispatches resting on one outlet, one side of the rated press, or a rewritten summary; Atlas Rewind plays back the archived 24h snapshots and ranks events whose coverage is thickening. Public dossiers add APA/BibTeX citations, canonical links, per-event share metadata and frameable embed cards.
- **Reader accounts and security** — optional first-party email/password accounts with Argon2id hashing, signed sessions, email confirmation, password recovery, two-factor authenticator codes with recovery codes, active-session review, a security activity ledger, Google OpenID Connect sign-in, and account closure. Reading the atlas never requires an account..
- **Real multi-source ingestion** — GDELT 2.0 events and GDELT DOC articles, curated RSS, Google News RSS (including targeted Bangladesh, Saudi Arabia, South Asia and human-rights searches), Reddit, Bluesky, USGS earthquakes, ReliefWeb, NewsAPI, and ACLED. Nationality adjectives such as "Bangladeshi" and "Indian" are mapped to their countries. GDELT coded records remain in the lake for relations and analysis but are excluded from public news snapshots.
- **Bounded article crawler + full-text index** — visits article pages belonging to configured outlets (including news sitemaps), honours robots.txt and per-host pacing, skips paywalled publishers, and caps each run at 120 URLs / 180 seconds. Extracted text improves clustering, classification, summaries and search. A SQLite FTS5 index powers body-text search; the UI returns summaries and source links, never article bodies..
- **Medallion data lake** — bronze (raw), silver (deduplicated/enriched), and gold (clustered/scored) layers stored as date-partitioned Parquet, mirrored to a Hugging Face bucket or dataset repo.
- **Honest provenance** — outlet counts, single-source and coverage-gap flags, per-alignment coverage columns, cited source links, and extractive summaries when no LLM key is configured.
- **Read-only serving API** — FastAPI reads the latest gold JSON artifacts with mtime-aware caching and server-sent update notifications.

## Architecture

```
Sources ──► Bronze Parquet ──► Silver Parquet ──► Gold Parquet
(GDELT, RSS, Reddit,          (normalize,          (cluster, classify,
 Bluesky, USGS, ...)           dedupe, geocode)     score, summarize)
                                                          │
                                   data/gold/serving/*.json (and HF repo)
                                                          │
                                             FastAPI /v1 ──► React globe
                                                          │
                       reader accounts: SQLite locally, TiDB/MySQL in production
```

The Hugging Face dataset repo mirrors the local lake at the same paths:

| Layer | Path | Contents |
| --- | --- | --- |
| Bronze | `bronze/raw_articles/`, `bronze/raw_social/` | Records exactly as retrieved |
| Silver | `silver/articles/`, `silver/article_content/` | Cleaned metadata and entities; crawled article text is kept separately for 14 days and is private by default |
| Gold | `gold/events/`, `gold/event_details/`, `gold/arcs/`, `gold/snapshots/` | Events, detail payloads, relation arcs, snapshot history |
| Serving | `gold/serving/world_{1h,24h,7d,30d}.json`, `event_details.json`, `manifest.json`, `search_index.sqlite3` | Small JSON files and the private full-text index the API reads |

Every Parquet table is partitioned as `dt=YYYY-MM-DD/part-<run_id>.parquet`. Nested values such as entities, coverage, and sources are stored as JSON strings inside Parquet.

## Quick start

Prerequisites: Python 3.12+, Node 20+.

```bash
python -m venv .venv
source .venv/Scripts/activate      # Windows Git Bash; use .venv\Scripts\activate on cmd
pip install -r backend/requirements.txt -r pipeline/requirements.txt

# Create .env locally (it is gitignored), then set HF_TOKEN and HF_DATASET_REPO (and HF_STORAGE_TYPE=bucket for a bucket). Add optional API keys as desired.

cd frontend && npm ci && cd ..

# Generate the first real snapshot (fetches live sources)
python -m pipeline.orchestration.flows

# Build the frontend once, then serve API + UI on http://127.0.0.1:8000
cd frontend && npm run build && cd ..
python run.py
```

For frontend development with hot reload:

```bash
python run.py --dev          # backend on :8000, Vite on :5173
```

`run.py` runs the pipeline once if no serving artifacts exist, serves the API and built frontend, and can refresh data on an interval (`--refresh-mins`, default 15). Use `--no-scheduler` to disable refreshes.

### Reader accounts

Auth works out of the box in development. Open `http://127.0.0.1:8000/signup`; with no mail provider configured, the browser shows the local confirmation link, and the same message is written to the `app.auth.email.dev` log. Accounts are stored in `data/auth/` by default; set `AUTH_DB_BACKEND=mysql` to use TiDB/MySQL for a persistent Render Free deployment.

For a production deployment set `APP_BASE_URL`, `PUBLIC_BASE_URL`, and `ENVIRONMENT=production`, terminate TLS, and configure Resend or SMTP. To enable **Continue with Google**, create a Web OAuth client with the exact redirect URI `https://your-domain.example/v1/auth/google/callback` and set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` on the server only. Operational setup, cookie model and security details are maintained privately.

### Docker

```bash
# Create .env locally (it is gitignored) first.
docker compose up -d --build
```

This builds the frontend inside the backend image and runs the pipeline in a separate container on an interval. The optional local Ollama service is available under the `ollama` profile:

```bash
docker compose --profile ollama up -d --build
```

## API

| Endpoint | Description |
| --- | --- |
| `GET /v1/snapshot?window=24h` | Events and arcs for `1h`, `24h`, `7d`, or `30d` |
| `GET /v1/events/{id}/card` | Compact hover-card payload |
| `GET /v1/events/{id}` | Full detail: summary, coverage, timeline, sources |
| `GET /v1/countries/brief?name=India&window=24h` | Country-level Latest top 10 plus focused protest, conflict and technology sections |
| `GET /v1/search?q=...&window=30d&limit=20` | Ranked full-text search over event titles, summaries and crawled article text |
| `GET /v1/relations` | Bilateral relation arcs for the 24h window |
| `GET /v1/relations/{id}` | One relation arc |
| `GET /v1/events/{id}/citation` | APA and BibTeX citation plus the canonical dossier URL |
| `GET /v1/storylines?window=24h` | Recurring country relations with their dispatches |
| `GET /v1/lenses/thin?window=24h` | Thinly corroborated dispatches and the reason each qualifies |
| `GET /v1/pulse?window=24h` | Events gaining outlets between archived snapshots |
| `GET /v1/rewind` | Compact replay archive built from pipeline snapshots |
| `/v1/watchline/*` | Account-backed pinned desks, return brief and public share feed |
| `GET /v1/stream` | Server-sent event when serving artifacts change |
| `GET /v1/outlets` | Outlet metadata and alignment ratings |
| `POST /v1/feedback` | Record a correction report to `data/feedback/reports.jsonl` |
| `/v1/auth/*` | Reader accounts: signup, sign-in, sessions, email verification, password recovery, TOTP, Google OIDC and account closure. |
| `GET /health` | Service and latest pipeline status |
| `GET /docs` | OpenAPI documentation |

## Data sources, accounts and keys

No key is required for GDELT, RSS, Google News RSS, USGS, or Bluesky. Reddit now falls back to its keyless RSS feed when OAuth credentials are unavailable; PullPush is the last resort. Reader accounts need no third-party service for email/password; Google sign-in and transactional email are optional.

| Variable | Required | Free tier / notes |
| --- | --- | --- |
| `APP_BASE_URL`, `PUBLIC_BASE_URL` | For account emails/OAuth | Public app and API origins; keep them identical in the single-process deployment |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Optional Google sign-in | Create a Web OAuth client in Google Cloud Console; the secret stays server-side. |
| `RESEND_API_KEY`, `BREVO_API_KEY`, `EMAIL_FROM` | Optional email | Resend or Brevo HTTPS API; alternatively use SMTP variables |
| `AUTH_SECRET` | Recommended | Long random value. If omitted, a key is generated at `data/auth/secret.key` |
| `AUTH_DB_BACKEND` | Optional | `sqlite` locally; `mysql` for TiDB Cloud Starter / MySQL 8 |
| `AUTH_DB_HOST`, `AUTH_DB_PORT`, `AUTH_DB_NAME`, `AUTH_DB_USER`, `AUTH_DB_PASSWORD` | For MySQL auth | TiDB **Connect** values; password stays server-side. |
| `AUTH_DB_SSL_CA`, `AUTH_DB_SSL_CA_PEM` or `AUTH_DB_SSL_CA_PEM_B64` | For MySQL auth | TiDB CA certificate path, PEM contents or base64 PEM; TLS is mandatory |
| `AUTH_DB_POOL_SIZE` | Optional | Connection pool size, default `5` |
| `HF_TOKEN` | For shared persistence | https://huggingface.co/settings/tokens (write token) |
| `HF_DATASET_REPO` | For shared persistence | Bucket or dataset ID such as `username/global_news_bucket` |
| `HF_STORAGE_TYPE` | Optional | `bucket` or `dataset` (default `dataset`) |
| `GROQ_API_KEY` | Optional LLM | https://console.groq.com/keys; free model configured by `GROQ_MODEL` |
| `OPENROUTER_API_KEY` | Optional LLM | https://openrouter.ai/keys; comma-separated `:free` models |
| `GEMINI_API_KEY` | Optional LLM | https://aistudio.google.com/apikey |
| `GEONAMES_USERNAME` | Optional geocoding | https://www.geonames.org/login |
| `NEWSAPI_KEY` | Optional source | https://newsapi.org (free developer tier); budgeted by `NEWSAPI_DAILY_LIMIT` |
| `ACLED_EMAIL`, `ACLED_PASSWORD` | Optional source | myACLED login used only server-side to obtain/refresh OAuth tokens; legacy access keys are no longer used |
| `RELIEFWEB_APPNAME` | Optional source | Must be requested and approved by ReliefWeb |
| `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET` | Optional Reddit OAuth | https://www.reddit.com/prefs/apps |
| `DISCORD_WEBHOOK_URL` | Optional alerts | Discord server webhook |

Without LLM keys the pipeline still produces summaries by extracting publisher sentences and, when a multi-source cluster only has headlines, by adding distinct secondary headlines with attribution. It never invents summary text.

## Deployment and live updates

The app can run in two shapes. Both keep Hugging Face as the durable store and update the browser automatically.

### 1. One long-running service (simplest)

Run `python run.py` on a VM, Docker host, Fly/Render/Railway service, or similar long-lived process. A single process serves the API/frontend and runs the ingestion scheduler every 15 minutes. Each run writes new `gold/serving/*.json` files and pushes them to the HF bucket. The API notices the new file mtimes, the SSE endpoint emits `snapshot_updated`, and the React client refetches. Use **one replica** if the scheduler is enabled so ingestion and free-tier API quotas are not duplicated.

### 2. Web service + scheduled worker (recommended for scale)

The repository includes a scheduled GitHub Actions data platform at
`.github/workflows/pipeline.yml`: it extracts, builds all medallion layers and
pushes Parquet to Hugging Face in one run. The workflow owns the UTC schedule, repository secrets, tier behavior and
the GitHub cron 50-minute limitation.

Run the web process with `python run.py --no-scheduler` and run the pipeline separately on a cron, Cloud Scheduler, or GitHub Actions schedule:

```bash
python -m pipeline.orchestration.flows
```

The scheduled worker pushes serving JSON to Hugging Face. The web service checks the HF serving manifest every `HF_PULL_INTERVAL_SECONDS` (default 120), swaps in newer JSON, and the existing SSE stream tells connected browsers to refetch. This works even if the web and worker containers have no shared disk. On a cold start the web service downloads the serving files from the HF bucket automatically.

If the frontend is hosted separately (for example Vercel/Netlify), build it with `VITE_API_URL=https://your-api.example.com/v1` and set `ENVIRONMENT=production` plus `ALLOWED_ORIGINS` as a JSON array on the backend. If FastAPI serves the built frontend, no extra CORS setup is needed. Reader auth cookies are first-party in the single-origin setup; a separately hosted SPA on another domain also needs `AUTH_COOKIE_SAMESITE=none` and `AUTH_COOKIE_SECURE=true`, and may still be blocked by third-party-cookie privacy settings. Prefer serving the SPA from the API origin. A platform that sleeps idle services will not run the in-process scheduler; use the external scheduled-worker option there.

Reader accounts are separate from pipeline data. SQLite is the local default and needs `data/auth/` on a persistent volume. For Render Free, set `AUTH_DB_BACKEND=mysql` with TiDB Cloud Starter credentials so accounts and watchlines survive restarts without a paid disk. Set `APP_BASE_URL` and `PUBLIC_BASE_URL` to the public origin, use HTTPS, and keep `ENVIRONMENT=production` so session cookies are Secure and development links are disabled. Use one web replica with the in-memory account rate limiter, or move limits/lockout state to shared storage before scaling out..

### Render

The root `Dockerfile` is a Render-ready multi-stage image: Node builds the SPA,
Python serves the API and frontend, `$PORT` is honoured, and the app runs as a
non-root user. `render.yaml` describes the web service and required secrets.
Set the public URL, Google callback and an HTTPS email provider in the service environment.

Freshness depends on the source: RSS/Google News are fetched each run, GDELT is rate-limited upstream, and NewsAPI's free tier is delayed by 24 hours and budgeted to 10 requests/day. The globe itself always reflects the latest successfully published snapshot.

## Free-tier budgets and secrets

The pipeline treats optional APIs as best-effort and never lets an exhausted quota crash ingestion:

- **LLM summaries** use at most `MAX_LLM_SUMMARIES_PER_RUN` (default 8), and only for clusters with substantive material. Groq and OpenRouter stop at 80% of the configured daily caps; counters persist in `data/llm_usage.json` across pipeline processes. The default fallback chain is Groq `qwen/qwen3.8-27b` → configured OpenRouter `:free` models → optional Gemini → optional Ollama → deterministic extraction.
- **NewsAPI** is limited by `NEWSAPI_DAILY_LIMIT` (default 10) in `data/source_usage.json`, well below the 100/day developer allocation.
- **ACLED** uses the current password/refresh-token OAuth flow; access tokens are cached for their 24-hour lifetime. A rejected login is backed off for an hour rather than retried on every run.
- **Hugging Face** uploads only append-only Parquet parts from the current run plus the latest serving JSON; failed uploads are logged and do not stop the local pipeline.

All credentials live in the gitignored `.env` (or environment variables). They are never sent to the browser, embedded in the frontend bundle, or printed in logs. Use a read/write Hugging Face token scoped to the storage bucket or dataset.

## Tests

```bash
PYTHONPATH=backend .venv/Scripts/python.exe -m pytest backend/tests pipeline/tests -q
cd frontend && npm run build
```

## License and attribution

All headlines, excerpts, and linked content remain the property of their publishers. The application links every story back to its original reporting. Data is retrieved from public feeds and APIs; consult the original sources for licensing and reuse terms.

Coastlines and political boundaries come from [Natural Earth](https://www.naturalearthdata.com/) (public domain). Globe imagery comes from NASA Blue Marble Next Generation and Black Marble 2016 (public domain). Newsreader, IBM Plex Sans and IBM Plex Mono are self-hosted under the SIL Open Font License; see `frontend/public/fonts/README.md`.
