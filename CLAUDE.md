# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Local development
pip install -r requirements.txt
python app.py                        # → http://localhost:5001

# Docker (production-like)
docker compose up --build -d         # → http://localhost:5001
docker compose down

# Database reset (required after model changes — no migrations for existing columns)
rm instance/logistat.db
python app.py                        # re-creates + seeds
```

Default admin credentials after seed: `admin` / `admin123`

## Architecture

**Everything is in `app.py`** — models, routes, API endpoints, seed data (~2000 lines). There are no separate modules.

**Database:** SQLite at `instance/logistat.db`. Flask-SQLAlchemy ORM. No Flask-Migrate.
- New **tables**: `db.create_all()` at module level handles them automatically on startup.
- New **columns** on existing tables: add an entry to `migrate_columns()` — uses `ALTER TABLE` with try/except to skip if already present.

**Auth:** Flask-Login with three roles enforced by `@leader_required` / `@admin_required` decorators:
- `operator` — scanned in at shift start, no login
- `leader` — password login, runs scanner/assignment/data-entry/time-tracking screens
- `admin` — everything + admin panel, CSV import, country/cost mappings

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
- `/scan-paczki` ("Czasy paczek"): time tracking. Tabs Start / Koniec → `POST /api/package-time/start|end` set `scan_start_at`/`scan_end_at` (+ `_by`). `processing_seconds()` = end − start. No dedup guard (re-scan overwrites).

`ImportedCarton.processed_by` + `processed_at` are set only via reassignment on `/paczki` (leader+) now. The old alternating employee→package assignment scan (`/api/scan-package` POST, 409 on duplicate) is retired dead code.

**Double rate (per-package):**
`ImportedCarton.double_rate` checkbox in `/paczki`. In General Stats, any line with double-rate cartons gets a second **yellow** row: Amounts = auto sum of double-rate `stueckzahl` (`double_rate_amount_map()`), categories entered manually into `GeneralStat.double_rate_category_data`. Both lines bill ×1 — doubling is emergent (packages counted twice). The legacy per-line `GeneralStat.double_rate` ×2 multiplier is removed (column kept as dead back-compat).

**Time tracking:**
Worker scans barcode on `/time-tracking` to toggle break (`break_start`/`break_end`) or record `work_end`.
All events stored in `WorkerTimeEvent`. Break state derived from `count(break_start) - count(break_end)` — no flag on User.
Auto-closes open break when `work_end` is scanned.

**CSV import flow:**
Raw rows → `ImportedCarton` (deduplicated by `barcode`) → aggregated into `GeneralStat` (grouped by `uebergabe_nr` + `land` + `ziel_datum`). Cost calculation uses `CostMapping` (per year/month rates in `rates_data` JSON). Cost = category amount × rate (×1); see Double rate above for the yellow-row billing.

**AI suggestions** (`/api/assignment/suggestions`): greedy algorithm using 30-day average `DailyStat.quantity` per user per activity.

## Key implementation details

- **Port 5001** (not 5000 — occupied by Jewelry-Tracker on the same server)
- **Barcode scanner:** EAN-128 via USB HID. 300ms timeout buffers keystrokes. Increase to 500ms if scanner is slow.
- **Drag & drop:** Native HTML5 API. Multi-select via click, drag moves all selected.
- **`GeneralStat.category_data`** and **`CostMapping.rates_data`** store JSON as `db.Text`. Always use `get_category_data()` / `get_rates_data()` accessors.
- **User soft-delete:** `DELETE /api/users/<id>` sets `is_active_user=False`.
- **All timestamps in UTC.** Frontend converts to local time via `new Date(iso).toLocaleTimeString('pl')`.
- **Break >30 min** highlighted red in `/worker-times` — threshold hardcoded in `worker_times.html`.
- **SECRET_KEY:** Set via `SECRET_KEY` env var in production.

## Pending work (from TODO.md)

- Excel import endpoint (`/api/import/excel`) — reserved but not implemented (`openpyxl` already in requirements)
- Password change screen for leaders/admins
- Touch/tablet support for drag & drop
- Excel export for worker times
