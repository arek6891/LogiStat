# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Local development
pip install -r requirements.txt
python app.py                        # → http://127.0.0.1:5001
HOST=0.0.0.0 python app.py           # dev reachable from the LAN (loopback by default)

# Tests
pip install -r requirements-dev.txt
pytest                               # 178 tests
LOGISTAT_TEST_DATABASE_URL=postgresql+psycopg2://u:p@host:5432/db pytest   # same suite on Postgres

# Docker (production-like)
docker compose up --build -d         # → http://localhost:5001
docker compose down

# Database reset (required after model changes — no migrations for existing columns)
rm instance/logistat.db
python app.py                        # re-creates + seeds
```

Default admin credentials after seed: `admin` / `admin123` — override with the `ADMIN_PASSWORD` env var **before the first start** (see `docs/DEPLOY.md`).

## Architecture

**Everything is in `app.py`** — models, routes, API endpoints, seed data (~3200 lines). There are no separate modules.

**Tests:** `tests/` (pytest). `conftest.py` sets `DATABASE_URL` to a temp SQLite file **before importing `app`** (the module runs `init_db()` at import time) and gives every test a fresh schema + seed. Coverage is deliberately concentrated on the money-affecting paths — import aggregation, `recompute_general_stat`, double rate, cost math — plus permissions, day boundaries, validation and a page smoke test. `IsolatedClient` clears `g._login_user` / `g._rates_cache` per request: the fixture holds one app context per test and Flask reuses it, so without that two clients in one test would share the cached login.

**Database:** SQLite at `instance/logistat.db` by default; **`DATABASE_URL` overrides it** (test env on `.31` runs `postgresql+psycopg2://…@db:5432/logistat`). Flask-SQLAlchemy ORM. No Flask-Migrate. The schema always comes from `db.create_all()` on both engines — **not** from `docs/postgres_schema.sql`, which is superseded: its `JSONB` columns would break `get_category_data()`'s `json.loads`, and its `DEFAULT NOW()` would write server-local time into columns everything reads as naive UTC.
- New **tables**: `db.create_all()` at module level handles them automatically on startup.
- New **columns** on existing tables: add an entry to `migrate_columns()` — uses `ALTER TABLE` with try/except to skip if already present.
- `migrate_columns()`'s ALTER block is **SQLite-only** (`db.engine.dialect.name`); on Postgres `create_all()` already produces the current schema. Its index block runs on both.
- **`func.date()` returns `str` on SQLite but `datetime.date` on Postgres** — avoid it for day grouping entirely; `api_stats_user` now groups in Python via `local_day_bounds()` (see the timezone note below).

**Auth:** Flask-Login with three roles enforced by `@leader_required` / `@admin_required` decorators:
- `operator` — scanned in at shift start, no login
- `leader` — password login, runs scanner/assignment/data-entry/time-tracking screens
- `admin` — everything + admin panel, CSV import, country/cost mappings

`/api/users` is `@leader_required` (leaders create operators) but carries its own role guards: only an **admin** may create/edit/deactivate a `leader` or `admin` account, change any role, or set a password (403 otherwise) — see `ROLES` / `PRIVILEGED_ROLES` / `acting_as_admin()`. Degrading or deactivating the **last active admin** is refused (400). `login()` and `load_user()` both check `is_active_user`, so a soft-delete also kills a session already in progress.

**Frontend:** Vanilla HTML/JS + Jinja2 templates. No JS framework. Chart.js for stats graphs. All templates extend `base.html` (dark theme, sidebar navigation).

## Core data flows

**Shift attendance:**
Leader scans operator barcodes → `ShiftAttendance` records created per `Shift`

**Activity assignment:**
Leader drags operators to activities → `ActivityAssignment` records saved

**Daily stats:**
Leader enters quantities per person → `DailyStat` records with audit trail

**Package scanning — two separate modules:**
- `/scan-package` ("Skan paczek"): **read-only lookup**. Scan a package barcode → `GET /api/package-lookup` returns status (scanned / by whom / finished) + basic data. `scanned = processed_by OR scan_start_at`; `finished = scan_end_at`; "kto" = `processed_by_name` else `scan_start_by_name`. Does NOT mutate anything.
- `/scan-paczki` ("Czasy paczek"): time tracking. Tabs Start / Koniec → `POST /api/package-time/start|end` set `scan_start_at`/`scan_end_at` (+ `_by`). `processing_seconds()` = end − start. **Ownership lock:** a package in progress belongs to the worker who started it — another worker starting → 409, ending → 403; same worker re-start keeps the original timestamp. A **finished** package is locked: re-start → 409, re-end → 409 (no re-processing).

`ImportedCarton.processed_by` + `processed_at` are set only via reassignment on `/paczki` (leader+). The old alternating employee→package assignment scan (`POST /api/scan-package`) and `POST /api/scan-employee` were removed in the 2026-09 cleanup.

**Double rate (per-package):**
`ImportedCarton.double_rate` checkbox in `/paczki`. In General Stats, any line with double-rate cartons gets a second **yellow** row: Amounts = auto sum of double-rate `stueckzahl` (`double_rate_amount_map()`), categories entered manually into `GeneralStat.double_rate_category_data`. Both lines bill ×1 — doubling is emergent (packages counted twice). The legacy per-line `GeneralStat.double_rate` ×2 multiplier is gone — the column, its `to_dict()` key and its only writer (`PUT /api/packages/uebergabe-double-rate`) were removed in the 2026-09 cleanup. Existing DB columns are simply left untouched.

**Dashboard (`/dashboard`):**
Three tabs — Podsumowanie / Per pracownik (both from `GET /api/dashboard`, today-only, 30s auto-refresh) and **Per zmiana** (`GET /api/dashboard/shifts?date=`, any date). DailyStat is already shift-tagged (`shift_id`) so it aggregates per shift directly; packages have no shift, so they're attributed **by attendance** — a package counts toward the single shift its `scan_end_by` worker was scanned into (`ShiftAttendance`) that day. Workers with no attendance or in both shifts → `unattributed` bucket (each package counted exactly once).

**Time tracking:**
Worker scans barcode on `/time-tracking` to toggle break (`break_start`/`break_end`) or record `work_end`.
All events stored in `WorkerTimeEvent`. Break state derived from `count(break_start) - count(break_end)` — no flag on User.
Auto-closes open break when `work_end` is scanned.

**CSV / Excel import flow:**
Raw rows → `ImportedCarton` (deduplicated by `barcode`) → aggregated into `GeneralStat` (grouped by `uebergabe_nr` + `land` + `ziel_datum`). Cost calculation uses `CostMapping` (per year/month rates in `rates_data` JSON). Cost = category amount × rate (×1); see Double rate above for the yellow-row billing.
Both `POST /api/import-csv` (`;`-delimited CSV) and `POST /api/import/excel` (`.xlsx` via openpyxl) feed the **same** helper `process_import_rows(rows)` — same dedup + aggregation + response shape. The helper is **type-aware** (`_cell_to_barcode/_int/_date/_str`): CSV yields strings, openpyxl yields native `datetime`/`int`/`float`/`None`. Excel is read with `load_workbook(..., data_only=True, read_only=True)`; headers pass through the same `normalize_header`. Expected columns (same as CSV): `Barcode`, `Land`, `Stückzahl`, `Kategorie`, `Ziel-Datum`, `Übergabe Nr.`. **Caveat:** numeric barcode columns in Excel are stored as float64 — long SSCC/EAN >2^53 loses precision and leading zeros vanish at the source; format the barcode column as text. The `/import-csv` page accepts both extensions and routes by extension.
**Manual add:** `POST /api/packages` (leader+, "➕ Dodaj paczkę" button in `/paczki`) creates a single `ImportedCarton` for packages missing from CSV. It feeds the **same** `process_import_rows([row])` so it dedups + aggregates + bills identically to an import. Required fields: `barcode`, `stueckzahl` (>0), `land`, `ziel_datum`, `uebergabe_nr`; optional: `kategorie`, `double_rate`. Duplicate barcode → 409 (pre-check + `IntegrityError` fallback for the concurrent-write race); the row carries optional `double_rate` / `added_manually` keys that `process_import_rows` now reads (absent in CSV/Excel rows → False). Land is a dropdown of `CountryMapping` (option value = `innenauftrag`, label = country). `imported_by` (set for both import and manual) is shown per row as the **login** ("👤 username") + a "ręczna" badge when `added_manually`.

**Manual edit:** `PUT /api/packages/<id>` (leader+, "✎ Edytuj" button) — editable **only** for `added_manually` packages (imported ones → 403). Same validation as create; changed barcode collision → 409. Changing a group field (`uebergabe_nr`/`land`/`ziel_datum`) moves the carton between GeneralStat groups: `recompute_general_stat()` rewrites the affected line(s) as `SUM(stueckzahl)` over the group — **recompute-from-sum, not delta** (exact even when manual + imported cartons share a line; the invariant is that `amounts` is written only by carton aggregation). An emptied group's line is kept at `amounts=0` (preserves `category_data`). Sets `modified_by`/`modified_at` (shown per row). Editing a scanned package (has `scan_start_at`/`scan_end_at`) is allowed but the UI confirms first.

**AI suggestions** (`/api/assignment/suggestions`): greedy algorithm using 30-day average `DailyStat.quantity` per user per activity.

## Key implementation details

- **Port 5001** (not 5000 — occupied by Jewelry-Tracker on the same server)
- **Barcode scanner:** EAN-128 via USB HID. 300ms timeout buffers keystrokes. Increase to 500ms if scanner is slow.
- **Drag & drop:** Native HTML5 API. Multi-select via click, drag moves all selected.
- **`GeneralStat.category_data`** and **`CostMapping.rates_data`** store JSON as `db.Text`. Always use `get_category_data()` / `get_rates_data()` accessors.
- **User soft-delete:** `DELETE /api/users/<id>` sets `is_active_user=False`.
- **"Today" is always the Warsaw day, never the server's.** `local_today()` and `local_day_bounds(d)` (→ naive-UTC `[start, end)`, DST-correct via ZoneInfo) are the single definition, used by `api_dashboard`, `api_dashboard_shifts` and `api_stats_user`. Never build a day boundary from `date.today()` — with two shifts working through midnight it puts work on the wrong day, and it used to disagree with the stats screen's `func.date()` (UTC). `api_stats_user` groups packages by local day **in Python**, because SQLite and Postgres do timezone conversion completely differently.
- **All timestamps stored in UTC (naive `datetime.utcnow()`); displayed in Europe/Warsaw.** Two display paths, both DST-correct: (1) API JSON serializes datetimes via `iso_z()` which appends **`Z`** so the browser's `new Date(iso)` parses them as UTC and `toLocaleTimeString('pl')` converts to local — **datetime fields only, never date-only** columns (`ziel_datum`, `loading_date`, `Shift.date` stay bare `isoformat()`); (2) server-rendered Jinja timestamps use the **`| localdt('%fmt')`** filter (naive-UTC → `Europe/Warsaw`). Manual worker-time edits round-trip cleanly: the browser sends `new Date(local).toISOString().slice(0,19)` (naive UTC) and `fromisoformat` stores it as-is. Never render a stored datetime with bare `strftime` (shows UTC) or feed a Z-less ISO to `new Date()` (parsed as local → 2h off in PL summer).
- **Break threshold** (min) highlighted red in `/worker-times` is **configurable** by admin at `/admin/settings` (`PUT /api/settings`, key `break_threshold_minutes`, default 30). Stored in the generic `AppSetting` key/value table — read via `get_setting_int()`, defaults in `SETTING_DEFAULTS`. The route passes it to the template (`break_threshold`) and JS uses `BREAK_THRESHOLD`.
- **SQLite pragmas:** `_set_sqlite_pragmas` (a SQLAlchemy `Engine` `connect` listener) sets `journal_mode=WAL` + `busy_timeout=5000` on every connection, so concurrent leaders don't hit `database is locked`. WAL adds `logistat.db-wal` / `-shm` next to the DB — **back up with `sqlite3.Connection.backup()` or `VACUUM INTO`, never a bare `cp`** (torn snapshot). The listener no-ops on non-SQLite DBAPI connections, so the Postgres migration stays unaffected.
- **Config / env vars** (full table in `docs/DEPLOY.md`): `SECRET_KEY` is **mandatory whenever `DATABASE_URL` is set** — `resolve_secret_key()` raises at import rather than silently falling back to the dev key (bypass: `LOGISTAT_ALLOW_DEV_SECRET=1`). `MAX_UPLOAD_MB` (default 32) caps imports; over the limit → `413` as JSON. `SESSION_COOKIE_SAMESITE=Lax` is always on (closes CSRF on the multipart `/api/import-csv`; JSON endpoints were already protected by the preflight requirement); `SESSION_COOKIE_SECURE` is opt-in via env because `.31` is also reached over plain HTTP from the LAN.
- **Errors on `/api/` paths return JSON**, not HTML — one `@app.errorhandler(HTTPException)`. Use `abort(400, 'komunikat')` freely; the front reads `data.error`. Request helpers: `json_body()`, `parse_date()`, `parse_shift_number()`, `require_int()`.
- **Static assets:** `{{ static_v('style.css') }}` appends the file's mtime — no manual `?v=` bump.
- **`escapeHtml()` in `base.html`** — everything interpolated into `innerHTML` from the DB (display names, activity names, barcodes, countries) goes through it. Barcodes arrive from CSV imports, so the risk is *stored* XSS.

## Pending work (from TODO.md)

- Password change screen for leaders/admins
- Touch/tablet support for drag & drop
- Excel export for worker times
