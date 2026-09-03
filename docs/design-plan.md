# Poultrix Central Data Warehouse — Design Plan

Goal: one database on the server that centralizes **all farms, current + historical**,
with (1) DB build, (2) initial backfill, (3) ongoing maintenance, (4) an external API.

## 0. Hard constraints (from the pilot)
- Poultrix has **no official API** and sits behind **Cloudflare** → the only ingestion
  path is an **authenticated browser session** (proven end-to-end in the pilot).
- Known surface: 36 farms (ids known via `lstFarms`), each with flocks (מדגרים),
  buildings (מבנים / coops), and the daily grid on `DailyFollowUpV1.aspx` (22 columns:
  תאריך, מבנה, גיל, ס.אכלוס, תמותה, פסילה, משקל, מים, מנת מזון, PH, סה"כ תמותה,
  %תמותה, תמותה מצט', משקל תקן, ...).
- Internal JSON handler `/ws/GeneralHandler.ashx` gives auxiliary data
  (`GetMidgarimForFarm`, `GetHenHousesForFarm`, `GetFoodConsumptionForDay`) but the raw
  daily rows come from scraping the grid DOM.
- Already built: auto-login bot, 5-min keep-alive, collector (HTTP→files), git deploy pipeline.

## 1. Database (build)
- **Engine:** PostgreSQL (matches the existing lulimdb stack).
- **Location:** decision needed — dedicated `poultrix` DB on the masasa server, or reuse
  the existing lulim PG instance. Recommend a separate `poultrixdb` for isolation.
- **Schema (normalized + raw):**
  - `farms(farm_id PK, name, poultrix_id UNIQUE, active, first_seen, last_seen)`
  - `flocks(flock_id PK, farm_id FK, midgar_text, start_date, end_date, breed, status)`
    — `UNIQUE(farm_id, midgar_text)`
  - `buildings(building_id PK, farm_id FK, number, name)` — `UNIQUE(farm_id, number)`
  - `daily_records(id PK, farm_id, flock_id, building_id, record_date, age_text,
    gender, mortality INT, culls INT, weight NUMERIC, water NUMERIC, feed NUMERIC,
    total_mortality INT, cum_mortality INT, std_weight NUMERIC, notes TEXT,
    row_hash TEXT, scraped_at TIMESTAMPTZ)`
    — `UNIQUE(flock_id, building_id, record_date, gender)` for idempotent upserts
  - `raw_snapshots(id PK, farm_id, flock_id, captured_at, payload JSONB)` — keep every
    raw scrape so we can reprocess if the parser changes.
  - `ingest_log(id PK, run_at, mode, farm_id, flock_id, rows, inserted, updated, errors, notes)`
- **Indexes:** `(farm_id, record_date)`, `(flock_id, record_date)`, GIN on `raw_snapshots.payload`.
- **Upsert:** `INSERT … ON CONFLICT (…) DO UPDATE` keyed on the unique tuple; `row_hash`
  decides insert-vs-update-vs-skip so re-runs are cheap and change-detecting.

## 2. Initial extraction (backfill)
Scope: **all 36 farms × all flocks (incl. closed/historical) × all buildings × all dates.**
- **Mechanism (browser-driven crawler — the only Cloudflare-safe path):**
  1. Enumerate farms from `lstFarms` (name → poultrix_id).
  2. For each farm: select it, read its flocks (`cbMidgar` / `GetMidgarimForFarm`).
  3. For each flock: set the date range to the flock's full span, load the grid, scrape
     all rows, POST `{farm, flock, rows}` to the collector.
  4. Collector **upserts into PostgreSQL** and stores the raw snapshot.
- **Driver:** a "backfill mode" in the userscript (or a controlled automation loop) that
  walks the farm/flock matrix with pacing (a few seconds between loads) to respect the
  session and the Poultrix server. Keep-alive keeps auth alive throughout.
- **Resumability:** `ingest_log` records each (farm, flock) done → restart-safe; a crash
  resumes where it left off.
- **Volume:** ~36 farms × a handful of flocks/yr × a few years × ~6 buildings × ~50 days
  ≈ tens of thousands of rows — trivial for PG.
- **Selecting closed flocks:** historical flocks show "מדגר סגור" but are still selectable
  and scrapeable.

## 3. Ongoing maintenance
- **Incremental:** hourly (or daily), iterate **active** flocks per farm, scrape a rolling
  recent window (e.g. last 7 days) and upsert — this also catches late edits to past days.
- **Change detection:** `row_hash` per row → only genuine new/changed rows are logged as changes.
- **Session health:** auto-login bot + keep-alive + watchdog (already built); failures land
  in `ingest_log` with an optional alert.
- **Deploys:** through the git pipeline already live (push → server auto-deploys in ~60s).
- **Data quality:** validate mortality ≥ 0, dates within the flock span, dedupe gender rows,
  reconcile `cum_mortality` against summed daily mortality.

## 4. External API
- **Stack:** FastAPI (matches the user's stack), behind a reverse proxy with HTTPS.
- **Auth:** per-consumer API keys (header token); read-only.
- **Endpoints (first cut):**
  - `GET /farms`, `GET /farms/{id}/flocks`
  - `GET /flocks/{id}/daily`, `GET /daily?farm=&from=&to=&building=`
  - `GET /summary?farm=&flock=` → derived KPIs (mortality %, FCR, EPEF, avg weight)
  - pagination, filtering, JSON; OpenAPI/Swagger docs auto-generated.
- **Serving:** uvicorn under a service (Task Scheduler / NSSM) or containerized; reads from
  the warehouse (optionally a read replica / materialized views for heavy queries).

## 5. Data flow
```
authed browser (keep-alive)
   -> scraper (userscript: backfill + incremental)
   -> collector (HTTP 127.0.0.1)
   -> PostgreSQL warehouse (farms/flocks/buildings/daily_records + raw_snapshots)
   -> FastAPI (API keys, read-only)
   -> external consumers
```

## 6. Risks & mitigations
- **Cloudflare / session fragility** → keep-alive, auto-login, retries, watchdog.
- **Scraping Poultrix** → it is the user's own account/own data; pace requests, off-peak backfill.
- **Schema drift** (Poultrix changes the grid) → `raw_snapshots` + a versioned column map
  let us reparse without re-scraping.
- **Weighings sparse / possibly on a separate שקילות screen** → confirm the weighing source
  before relying on `weight`.
- **Single browser dependency** → the whole ingest hinges on one logged-in Edge; document
  recovery, consider a second session.

## 7. Phased delivery
- **Phase 1 — DB + collector→PG.** Create `poultrixdb` + schema; extend the collector to
  upsert into PG (keep file output as a fallback). Verify with the current Kfar Harif feed.
- **Phase 2 — Backfill crawler.** Farm/flock matrix walk for all history; resumable; load
  every farm once.
- **Phase 3 — Incremental maintenance + monitoring.** Rolling-window daily upserts, ingest_log
  dashboards/alerts.
- **Phase 4 — External API.** FastAPI + keys + docs + deployment.

## 8. Open decisions (need your call)
1. **DB location:** separate `poultrixdb` on masasa, or reuse the existing lulim PG?
2. **API consumers & auth:** who calls it, and API-key vs OAuth?
3. **Weighings source:** confirm whether weighings live in the daily grid's משקל column or a
   separate שקילות screen.
4. **Backfill depth:** how far back (all available history, or since a cutoff year)?
5. **Refresh cadence:** hourly vs daily for the incremental job.
