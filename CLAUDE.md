# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Everything runs on PostgreSQL — there is no SQLite mode any more.
cp .env.example .env                 # then put a real SECRET_KEY in it
docker compose up --build -d         # app + db → http://localhost:5001
docker compose down

# Tests — need a Postgres; the compose file below provides one (port 55432, tmpfs)
docker compose -f docker-compose.test.yml up -d
pip install -r requirements-dev.txt
pytest                               # 324 tests
docker compose -f docker-compose.test.yml down
LOGISTAT_TEST_DATABASE_URL=postgresql+psycopg2://u:p@host:5432/db pytest   # another DB

# Local run without Docker (needs a reachable Postgres)
DATABASE_URL=postgresql+psycopg2://logistat:pass@127.0.0.1:5432/logistat \
  SECRET_KEY=$(python3 -c 'import secrets;print(secrets.token_hex(32))') python app.py

# Database reset (drops all data)
docker compose down -v && docker compose up -d      # re-creates + seeds
```

Default admin credentials after seed: `admin` / `admin123` — override with the `ADMIN_PASSWORD` env var **before the first start** (see `docs/DEPLOY.md`).

## Architecture

**Everything is in `app.py`** — models, routes, API endpoints, seed data (~4000 lines). There are no separate modules.

**Tests:** `tests/` (pytest). `conftest.py` sets `DATABASE_URL` **before importing `app`** (the module runs `init_db()` at import time) — it points at the Postgres from `docker-compose.test.yml` (`…@127.0.0.1:55432/logistat_test`), overridable with `LOGISTAT_TEST_DATABASE_URL`; if the DB is unreachable the import raises with the command that starts it and gives every test a fresh schema + seed. Coverage is deliberately concentrated on the money-affecting paths — import aggregation, `recompute_general_stat`, double rate, cost math — plus permissions, day boundaries, validation and a page smoke test. `IsolatedClient` clears `g._login_user` / `g._rates_cache` per request: the fixture holds one app context per test and Flask reuses it, so without that two clients in one test would share the cached login.

**Database: PostgreSQL only** (since 2026-09 — SQLite support was removed, not merely discouraged). `DATABASE_URL` is **mandatory**: `resolve_database_url()` raises at import if it is missing *or* points at SQLite, instead of silently writing to a file nobody backs up. `docker-compose.yml` ships the `db` service; `.31` overrides it in `docker-compose.override.yml`. Flask-SQLAlchemy ORM. No Flask-Migrate. **The ORM is the single source of truth for the schema** — `db.create_all()` builds it. There is no hand-written DDL file; `docs/postgres_schema.sql` used to exist and was deleted in 2026-09 because it had drifted into something actively harmful (its `JSONB` columns broke `get_category_data()`'s `json.loads`, and its `DEFAULT NOW()` wrote server-local time into columns everything reads as naive UTC). Don't reintroduce one — change the models.
- New **tables**: `db.create_all()` at module level handles them automatically on startup.
- New **columns** on existing tables: add an entry to `migrate_columns()` — uses `ALTER TABLE` with try/except to skip if already present.
- `migrate_columns()` uses `ALTER TABLE … ADD COLUMN IF NOT EXISTS`. This is the **only** way a new column reaches a live database: `create_all()` adds missing *tables* but **never a column to an existing table**, so forgetting it means every query on that model dies with `UndefinedColumn` after deploy. Ordinary tests cannot catch that — conftest does `drop_all()` + `create_all()`, so their schema is always fresh and the bug exists only on a database that already lives. **`tests/test_migracje.py` covers it** by dropping a column and asserting it comes back; add a case there with every new column.
- **Avoid `func.date()` for day grouping** — `api_stats_user` groups in Python via `local_day_bounds()` (see the timezone note below), which keeps one definition of "day" across the app.

**Auth:** Flask-Login with three roles enforced by `@leader_required` / `@admin_required` decorators:
- `operator` — scanned in at shift start, no login
- `leader` — password login, runs scanner/assignment/data-entry/time-tracking screens + **CSV/Excel import** (`/import-csv`, `POST /api/import-csv`, `POST /api/import/excel`)
- `admin` — everything + admin panel, General Stats, country/cost mappings

`/api/users` is `@leader_required` (leaders create operators) but carries its own role guards: only an **admin** may create/edit/deactivate a `leader` or `admin` account, change any role, or set a password (403 otherwise) — see `ROLES` / `PRIVILEGED_ROLES` / `acting_as_admin()`. Degrading or deactivating the **last active admin** is refused (400). `login()` and `load_user()` both check `is_active_user`, so a soft-delete also kills a session already in progress.

**Sidebar** is grouped by **who operates the screen**, not by permission (the two can disagree — `Czasy paczek` sits under Pracownik but is still `@leader_required`, being a station screen): **👷 Pracownik** (Skaner zmian, Czas pracy, Czasy paczek, Paczki inspektor) · **🧑‍💼 Lider** (Dashboard, Forecast, Przydzielanie, Wpis ilości, Statystyki, Paczki (dane), Czasy pracowników, Import danych, Użytkownicy) · **🛡️ Admin** (Statystyki ogólne, Czynności, Panel Admina). Each group header lives **inside** the same role conditional as its items — otherwise a leader sees an empty "Admin" heading.

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
- `/scan-paczki` ("Czasy paczek"): time tracking **+ ilości per kategoria**. Tabs Start / Koniec → `POST /api/package-time/start|end` set `scan_start_at`/`scan_end_at` (+ `_by`). `processing_seconds()` = end − start. Both steps are **skan loginu → skan paczki**. On **Koniec** the package barcode opens a third step: `GET /api/package-lookup` shows the package's `stueckzahl` and the worker types quantities per category, sent as `categories` in the end call and stored on `ImportedCarton.scan_category_data` (JSON, accessors `get_/set_scan_categories()`). The sum is **not** validated against `stueckzahl` — a discrepancy is normal and must not block work. Omitting `categories` keeps the old behaviour (time only). **Ownership lock:** a package in progress belongs to the worker who started it — another worker starting → 409, ending → 403; same worker re-start keeps the original timestamp. A **finished** package is locked: re-start → 409, re-end → 409 (no re-processing).

**Unlocking a stuck package:** a package in progress belongs to whoever started it, so if that worker never returns it is locked forever (another worker: 409 on start, 403 on end). `POST /api/packages/<id>/unlock-scan` (leader+, "🔓 Odblokuj" in `/paczki`) clears `scan_start_at`/`scan_start_by` — the package goes back to "not started" and anyone can scan it. A **finished** package cannot be unlocked (409); an unstarted one → 400.

**`/paczki` filters:** `date_from`/`date_to`/`date_typ`/`barcode`/`land`/`osoba`/`double_rate=1`/`pokaz_zrobione=1`/`bledy=1`. **The default view shows only unfinished packages** (`scan_end_at IS NULL`, the same `finished` definition as `/scan-package`); "pokaż zrobione" adds the rest, but **only together with a date range** — bare `pokaz_zrobione=1` used to pull the whole history, so it is now ignored and the page says why (a Jinja page, so no `abort()`; the form's JS blocks it first, this catches hand-made URLs). `date_typ` picks **which** date column the range applies to, via `PACZKI_POLA_DAT`: `ziel` (default, `ziel_datum`, a `db.Date` compared directly), `import` (`imported_at`), `start` (`scan_start_at`), `koniec` (`scan_end_at`). The last three are naive-UTC `DateTime`, so their bounds go through `local_day_bounds()` with a **half-open** upper bound (`<` the next local midnight) — `<=` would drag in the next day's first packages. An unknown `date_typ` falls back to `ziel`. **`date_typ=koniec` with a date lifts the unfinished-only default**, for the same reason the error filter ignores it: `scan_end_at BETWEEN …` AND `scan_end_at IS NULL` is the empty set, so the screen would always look broken. **`date_typ=start` deliberately does not lift it** — without `pokaz_zrobione` it means "started in this range *and still open*", which is the useful reading on a screen whose job is unfinished work; add `pokaz_zrobione=1` (plus the date it now requires) to see the ones that were also finished. `osoba` reuses the existing "kto" notion (`processed_by` / `scan_start_by` / `scan_end_by`) rather than inventing a fourth. The **error filter** (`bledy_paczki()`) = started-but-never-finished **or** a category quantity exceeding `stueckzahl` by more than 10% (`TOLERANCJA_ILOSCI`); it ignores the unfinished-only default, because a quantity error lives on an already-finished package. That comparison **cannot be SQL** — scan quantities are JSON in a `db.Text` column (JSONB is banned, see the DB section) — so it runs in Python and pagination goes through `StroniceLista`, an in-memory stand-in exposing the `Pagination` surface the template uses.

`ImportedCarton.processed_by` + `processed_at` are set only via reassignment on `/paczki` (leader+). The old alternating employee→package assignment scan (`POST /api/scan-package`) and `POST /api/scan-employee` were removed in the 2026-09 cleanup.

**Double rate (per-package):**
`ImportedCarton.double_rate` checkbox in `/paczki`. In General Stats, any line with double-rate cartons gets a second **yellow** row: Amounts = auto sum of double-rate `stueckzahl` (`double_rate_amount_map()`), categories entered manually into `GeneralStat.double_rate_category_data`. Both lines bill ×1 — doubling is emergent (packages counted twice). The legacy per-line `GeneralStat.double_rate` ×2 multiplier is gone — the column, its `to_dict()` key and its only writer (`PUT /api/packages/uebergabe-double-rate`) were removed in the 2026-09 cleanup. Existing DB columns are simply left untouched.

**Dashboard (`/dashboard`):**
Three tabs — Podsumowanie / Per pracownik (both from `GET /api/dashboard`, today-only, 30s auto-refresh) and **Per zmiana** (`GET /api/dashboard/shifts?date=`, any date). DailyStat is already shift-tagged (`shift_id`) so it aggregates per shift directly; packages have no shift, so they're attributed **by attendance** — a package counts toward the single shift its `scan_end_by` worker was scanned into (`ShiftAttendance`) that day. Workers with no attendance or in both shifts → `unattributed` bucket (each package counted exactly once).

**Time tracking:**
Worker scans barcode on `/time-tracking` to toggle break (`break_start`/`break_end`), toggle **„Inne"** (`other_start`/`other_end` — time off the station that is not a break, e.g. a trip to HR) or record `work_end`. Tabs map to `mode` in `POST /api/time/scan`: `break` | `other` | `work_end`.
All events stored in `WorkerTimeEvent`; state derived from `count(*_start) - count(*_end)` — no flag on User.
**„Inne" subtracts from work time exactly like a break** but is reported separately (`other_minutes`, `others[]`, `on_other`) because operations settle the two differently. A break and an „Inne" **cannot overlap** (409 either way) — otherwise the same minutes would be subtracted twice. `work_end` auto-closes **both** open periods. The scan enforces that, but a **manual correction** on `/worker-times` can still create overlapping periods, so `_compute_worker_times` subtracts the **union** of the intervals (`suma_zlaczonych_okresow()`), not the sum of their lengths — `break_minutes` / `other_minutes` keep reporting the raw totals.
`/worker-times` has a **per-worker filter** and a **„⚠️ Tylko błędy" filter** (work over `max_work_minutes`, no break, break under `min_break_minutes`). Both run in the browser over what `/api/worker-times` already returns — no API change, one definition. **No-break / short-break only count once `work_ended`** — a shift still in progress legitimately has no break yet, and flagging it would make the filter look broken.

**CSV / Excel import flow:**
Raw rows → `ImportedCarton` (deduplicated by `barcode`) → aggregated into `GeneralStat` (grouped by `uebergabe_nr` + `land` + `ziel_datum`). Cost calculation uses `CostMapping` (per year/month rates in `rates_data` JSON). Cost = category amount × rate (×1); see Double rate above for the yellow-row billing.
Both `POST /api/import-csv` (`;`-delimited CSV) and `POST /api/import/excel` (`.xlsx` via openpyxl) feed the **same** helper `process_import_rows(rows)` — same dedup + aggregation + response shape. The helper is **type-aware** (`_cell_to_barcode/_int/_date/_str`): CSV yields strings, openpyxl yields native `datetime`/`int`/`float`/`None`. Excel is read with `load_workbook(..., data_only=True, read_only=True)`; headers pass through the same `normalize_header`. Expected columns (same as CSV): `Barcode`, `Land`, `Stückzahl`, `Kategorie`, `Ziel-Datum`, `Übergabe Nr.`. **Caveat:** numeric barcode columns in Excel are stored as float64 — long SSCC/EAN >2^53 loses precision and leading zeros vanish at the source; format the barcode column as text. The `/import-csv` page accepts both extensions and routes by extension.
**Manual add:** `POST /api/packages` (leader+, "➕ Dodaj paczkę" button in `/paczki`) creates a single `ImportedCarton` for packages missing from CSV. It feeds the **same** `process_import_rows([row])` so it dedups + aggregates + bills identically to an import. Required fields: `barcode`, `stueckzahl` (>0), `land`, `ziel_datum`, `uebergabe_nr`; optional: `kategorie`, `double_rate`. Duplicate barcode → 409 (pre-check + `IntegrityError` fallback for the concurrent-write race); the row carries optional `double_rate` / `added_manually` keys that `process_import_rows` now reads (absent in CSV/Excel rows → False). Land is a dropdown of `CountryMapping` (option value = `innenauftrag`, label = country). `imported_by` (set for both import and manual) is shown per row as the **login** ("👤 username") + a "ręczna" badge when `added_manually`.

**Manual edit:** `PUT /api/packages/<id>` (leader+, "✎ Edytuj" button) — editable **only** for `added_manually` packages (imported ones → 403). Same validation as create; changed barcode collision → 409. Changing a group field (`uebergabe_nr`/`land`/`ziel_datum`) moves the carton between GeneralStat groups: `recompute_general_stat()` rewrites the affected line(s) as `SUM(stueckzahl)` over the group — **recompute-from-sum, not delta** (exact even when manual + imported cartons share a line; the invariant is that `amounts` is written only by carton aggregation). An emptied group's line is kept at `amounts=0` (preserves `category_data`). Sets `modified_by`/`modified_at` (shown per row). Editing a scanned package (has `scan_start_at`/`scan_end_at`) is allowed but the UI confirms first.

**Scan quantities → billing (`GeneralStat.category_source`):**
Quantities entered at package end are the **source of truth for `category_data`**, i.e. for cost (`cost = amount × rate`). `recompute_general_stat(..., from_scan=True)` rewrites `category_data` as `SUM` of the group's cartons' `scan_category_data` — same recompute-from-sum invariant as `amounts`, via `scan_category_totals()`.
- **`category_source`** on `GeneralStat` splits two worlds: `'manual'` (entered by hand, pre-dating scanning) is **never touched by recompute**; `'scan'` is a carton aggregate and its manual field is **rejected by `PUT /api/general-stats/<id>` (400)**. Without this guard a recompute would silently zero out hand-entered billing — the expensive, invisible bug. The flip to `'scan'` happens **only** when scan quantities arrive, never as a side effect of an import.
- **A line that already holds non-zero manual quantities does not flip** (`ma_reczne_ilosci()`): otherwise the first scanned carton would replace e.g. 120 pieces with 6, silently. The scan still stores its quantities **on the carton**, so nothing is lost, and the line shows `⚠ ręczne · skany 3/50` with a **→ użyj skanów** button → `POST /api/general-stats/<id>/use-scan` (admin), which performs the swap deliberately. A freshly imported line has empty categories, so its first scan flips automatically.
- **Correcting a typo:** `PUT /api/packages/<id>/categories` (leader+, "✎ Ilości" in `/paczki`) edits quantities on **any** carton — imported ones included, unlike `PUT /api/packages/<id>` which is manual-only. Since scan quantities bill, a worker's typo had to be fixable; it sets `modified_by`/`modified_at` and recomputes.
- **Coverage:** `scan_coverage_map()` → `scanned/total` cartons per line, shown in General Stats (`🔒 3/50`) and in `GET /api/general-stats`. A line legitimately reads low mid-shift; the counter stops anyone exporting a half-scanned line as final.
- The **yellow double-rate row** (`double_rate_category_data`) stays **manual** — unaffected.
- `carton_labeling` was **removed** from `STAT_CATEGORIES` (2026-09); labels are now `Labelling one/twice/triple`. `GeneralStat.to_dict()` iterates `STAT_CATEGORIES`, not the stored keys, so a removed category can never bill from legacy JSON.
- **`Total Amount` = `TOTAL_AMOUNT_CATEGORY` (`labelling_on`) only**, never the sum of all categories (2026-09-18): one piece passes through several activities, so summing counted the same goods repeatedly and could exceed `Amounts`. Three places must agree — the Jinja row in `general_stats.html`, the JS recompute after an inline edit, and `write_data_row()` in the Excel export. The **yellow double-rate row deliberately still sums everything** (`write_data_row(..., is_double_rate=True)`) — pending a decision with operations, see `docs/TODO.md`. Costs are unaffected: `cost = amount × rate` per category as before.
- **Two label maps:** `STAT_CATEGORY_LABELS` (English, used by the **Excel export headers** — an external billing artifact, keep it English) and `STAT_CATEGORY_LABELS_PL`. Screens use `etykieta_kategorii()` / `etykiety_kategorii()`, which join both (`Labelling one — Etykietowanie pojedyncze`).

**AI suggestions** (`/api/assignment/suggestions`): greedy algorithm using 30-day average `DailyStat.quantity` per user per activity.

## Key implementation details

- **Port 5001** (not 5000 — occupied by Jewelry-Tracker on the same server)
- **Barcode scanner:** EAN-128 via USB HID. 300ms timeout buffers keystrokes. Increase to 500ms if scanner is slow.
- **Drag & drop:** Native HTML5 API. Multi-select via click, drag moves all selected.
- **`GeneralStat.category_data`** and **`CostMapping.rates_data`** store JSON as `db.Text`. Always use `get_category_data()` / `get_rates_data()` accessors.
- **User soft-delete:** `DELETE /api/users/<id>` sets `is_active_user=False`.
- **"Today" is always the Warsaw day, never the server's.** `local_today()` and `local_day_bounds(d)` (→ naive-UTC `[start, end)`, DST-correct via ZoneInfo) are the single definition, used by `api_dashboard`, `api_dashboard_shifts` and `api_stats_user`. Never build a day boundary from `date.today()` — with two shifts working through midnight it puts work on the wrong day, and it used to disagree with the stats screen's `func.date()` (UTC). `api_stats_user` groups packages by local day **in Python**, so `local_day_bounds()` stays the single definition of a day.
- **All timestamps stored in UTC (naive `datetime.utcnow()`); displayed in Europe/Warsaw.** Two display paths, both DST-correct: (1) API JSON serializes datetimes via `iso_z()` which appends **`Z`** so the browser's `new Date(iso)` parses them as UTC and `toLocaleTimeString('pl')` converts to local — **datetime fields only, never date-only** columns (`ziel_datum`, `loading_date`, `Shift.date` stay bare `isoformat()`); (2) server-rendered Jinja timestamps use the **`| localdt('%fmt')`** filter (naive-UTC → `Europe/Warsaw`). Manual worker-time edits round-trip cleanly: the browser sends `new Date(local).toISOString().slice(0,19)` (naive UTC) and `fromisoformat` stores it as-is. Never render a stored datetime with bare `strftime` (shows UTC) or feed a Z-less ISO to `new Date()` (parsed as local → 2h off in PL summer).
- **Time-tracking thresholds** are **configurable** by admin at `/admin/settings` (`PUT /api/settings`): `break_threshold_minutes` (30, red ⚠️ on a too-long break), `max_work_minutes` (660 = 11 h) and `min_break_minutes` (15) — the last two drive the error filter on `/worker-times`. Stored in the generic `AppSetting` key/value table — read via `get_setting_int()`, defaults in `SETTING_DEFAULTS`. The route passes them to the template and JS uses `BREAK_THRESHOLD` / `MAX_WORK_MINUTES` / `MIN_BREAK_MINUTES`.
- **First start is serialized with `pg_advisory_lock`.** Gunicorn imports `app.py` once per worker, so on an empty database the workers race inside `db.create_all()` and the loser dies with a `UniqueViolation` on `pg_class` → `Worker failed to boot`, and gunicorn shuts the whole container down — non-deterministically, so it looks like a flaky deploy. The race is between the existence check and the create, and each `CREATE TABLE` is its own committed transaction, so no ordinary lock covers it. `tests/test_init_race.py` starts four workers against a freshly created database (its `pusta_baza` fixture does `CREATE DATABASE`, since the shared test DB is already initialised).
- **Backups: `pg_dump`.** The old SQLite WAL caveat is gone with SQLite itself.
- **Config / env vars** (full table in `docs/DEPLOY.md`): `SECRET_KEY` is **always mandatory** — `resolve_secret_key()` raises at import rather than silently falling back to the dev key (bypass: `LOGISTAT_ALLOW_DEV_SECRET=1`). It is read from `.env` (gitignored; see `.env.example`) by Compose. **Careful with Compose interpolation:** `${VAR:?msg}` is resolved per-file *before* `docker-compose.override.yml` is merged, so requiring a variable in `docker-compose.yml` breaks `.31`, which has no `.env` and supplies the value in its override — that is why the base file uses plain defaults and the app itself refuses to start instead. `MAX_UPLOAD_MB` (default 32) caps imports; over the limit → `413` as JSON. `SESSION_COOKIE_SAMESITE=Lax` is always on (closes CSRF on the multipart `/api/import-csv`; JSON endpoints were already protected by the preflight requirement); `SESSION_COOKIE_SECURE` is opt-in via env because `.31` is also reached over plain HTTP from the LAN.
- **Errors on `/api/` paths return JSON**, not HTML — one `@app.errorhandler(HTTPException)`. Use `abort(400, 'komunikat')` freely; the front reads `data.error`. Request helpers: `json_body()`, `parse_date()`, `parse_shift_number()`, `require_int()`.
- **Static assets:** `{{ static_v('style.css') }}` appends the file's mtime — no manual `?v=` bump.
- **`escapeHtml()` in `base.html`** — everything interpolated into `innerHTML` from the DB (display names, activity names, barcodes, countries) goes through it. Barcodes arrive from CSV imports, so the risk is *stored* XSS.

## Pending work (from TODO.md)

- Password change screen for leaders/admins
- Touch/tablet support for drag & drop
- Excel export for worker times
