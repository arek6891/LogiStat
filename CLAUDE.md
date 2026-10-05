# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**Rules only.** The *why* behind them — decision history, `.31` incidents, the numbers — lives in **`docs/ARCHITEKTURA.md`**. Read the relevant part there before changing a mechanism described below, especially before "simplifying" it. **When you change a mechanism, update its rule here and its section in `docs/ARCHITEKTURA.md` in the same commit** — a doc that drifts from the code is worse than none (see the deleted DDL file below).

## Commands

```bash
# Everything runs on PostgreSQL — there is no SQLite mode any more.
cp .env.example .env                 # then put a real SECRET_KEY in it
docker compose up --build -d         # app + db → http://localhost:5001
docker compose down

# Tests — need a Postgres; the compose file below provides one (port 55432, tmpfs)
docker compose -f docker-compose.test.yml up -d
pip install -r requirements-dev.txt
pytest                               # 463 tests
docker compose -f docker-compose.test.yml down
LOGISTAT_TEST_DATABASE_URL=postgresql+psycopg2://u:p@host:5432/db pytest   # another DB
# On .32 there is no pytest/venv — use the prebuilt runner image instead:
docker run --rm --network host -v /opt/LogiStat:/app -w /app logistat-testrunner:latest pytest -q

# Static check (npm i -g pyright; basic mode — pyrightconfig.json). The one remaining
# error at the parse_date() call in api_assignment_suggestions is a false positive (abort() in except).
pyright

# Local run without Docker (needs a reachable Postgres)
DATABASE_URL=postgresql+psycopg2://logistat:pass@127.0.0.1:5432/logistat \
  SECRET_KEY=$(python3 -c 'import secrets;print(secrets.token_hex(32))') python app.py

# Database reset (drops all data)
docker compose down -v && docker compose up -d      # re-creates + seeds
```

Default admin after seed: `admin` / `admin123` — override with `ADMIN_PASSWORD` **before the first start** (`docs/DEPLOY.md`).

## Architecture

**Everything is in `app.py`** — models, routes, API, seed data (~4500 lines). No separate modules.

**Tests:** `tests/` (pytest). `conftest.py` sets `DATABASE_URL` **before importing `app`** (it runs `init_db()` at import) → `…@127.0.0.1:55432/logistat_test`, overridable with `LOGISTAT_TEST_DATABASE_URL`; unreachable DB → import raises with the start command. Each test gets a fresh schema + seed. Coverage is concentrated on money paths (import aggregation, `recompute_general_stat`, double rate, cost math) plus permissions, day boundaries, validation, page smoke test. `IsolatedClient` clears `g._login_user` / `g._rates_cache` per request — Flask reuses the test's app context, so two clients would otherwise share the cached login.

**Database: PostgreSQL only.** `DATABASE_URL` is mandatory — `resolve_database_url()` raises at import if missing or SQLite. `.31` overrides the `db` service in `docker-compose.override.yml`. Flask-SQLAlchemy, no Flask-Migrate. **The ORM is the single source of truth for the schema** (`db.create_all()`); never reintroduce a hand-written DDL file (the old one broke `json.loads` with JSONB and wrote local time via `DEFAULT NOW()`).
- New **tables**: `db.create_all()` handles them on startup.
- New **columns**: **must** go into `migrate_columns()` (`ALTER TABLE … ADD COLUMN IF NOT EXISTS`). `create_all()` never adds a column to an existing table → `UndefinedColumn` after deploy, and ordinary tests can't see it (fresh schema). **Add a case to `tests/test_migracje.py`** with every new column.
- The `"user"` table name is a reserved word — quote it in `migrate_columns()`; unquoted, the try/except swallows the syntax error silently.
- **No `func.date()` for day grouping** — group in Python via `local_day_bounds()`.
- JSON lives in `db.Text` (JSONB is banned): `GeneralStat.category_data`, `CostMapping.rates_data`, `ImportedCarton.scan_category_data` — always via `get_…()` / `set_…()` accessors.

**Auth:** Flask-Login, `@leader_required` / `@admin_required`:
- `operator` — scanned in at shift start, no login
- `leader` — password login; scanner/assignment/data-entry/time-tracking + **CSV/Excel import**
- `admin` — everything + admin panel, General Stats, country/cost mappings

`/api/users` is leader+ but only an **admin** may create/edit/deactivate `leader`/`admin` accounts, change roles or set passwords (403) — `ROLES` / `PRIVILEGED_ROLES` / `acting_as_admin()`. Degrading/deactivating the **last active admin** → 400. `login()` and `load_user()` both check `is_active_user`, so soft-delete (`DELETE /api/users/<id>`) kills live sessions.

**Sidebar** is grouped by **who operates the screen**, not by permission — the two can disagree: `Czasy paczek` sits under Pracownik but is still `@leader_required` (a station screen); don't "fix" either side: **👷 Pracownik** (Skaner zmian, Czas pracy, Czasy paczek, Paczki inspektor) · **🧑‍💼 Lider** (Dashboard, Forecast, Przydzielanie, Wpis ilości, Normy, Paczki (dane), Czasy pracowników, Import danych, Użytkownicy) · **🛡️ Admin** (Statystyki ogólne, Czynności, Panel Admina). Each group header sits **inside** the same role conditional as its items.

**Frontend:** Vanilla HTML/JS + Jinja2, no framework, Chart.js. All templates extend `base.html`.

## Core data flows

- **Shift attendance:** leader scans badges → `ShiftAttendance` per `Shift`.
- **Activity assignment:** drag operators to activities → `ActivityAssignment`. `POST /api/assignment/save` **replaces the whole shift** (delete + insert), so: it locks the `Shift` row (`with_for_update()`), and `GET /api/assignment/data` returns `wersja` (`wersja_przydzialu()` — hash of the sorted `(user_id, activity_id)` pairs, no column) which the client sends back; a stale one → **409 + `konflikt: true`**, nothing overwritten (two leaders on one shift). No `wersja` in the body = old behaviour (`tests/test_przydzielanie_wersja.py`). AI suggestions save immediately too, so applying them over a non-empty board asks first.
- **Daily stats:** leader enters quantities → `DailyStat` (audit trail).
- **AI suggestions** (`/api/assignment/suggestions`): greedy, 30-day average `DailyStat.quantity` per user × activity.

**Package scanning — two modules:**
- `/scan-package` („Skan paczek"): **read-only** `GET /api/package-lookup`. `scanned = processed_by OR scan_start_at`; `finished = scan_end_at`; "kto" = `processed_by_name` else `scan_start_by_name`.
- `/scan-paczki` („Czasy paczek"): tabs Start / Koniec → `POST /api/package-time/start|end` (`scan_start_at`/`scan_end_at` + `_by`). Steps: badge scan → package scan; on Koniec a third step takes quantities per category → `categories` → `scan_category_data`. Sum is **not** validated against `stueckzahl` (discrepancy is normal). No `categories` = time only.
  - **Ownership lock:** in-progress package belongs to its starter — other worker start → 409, end → 403; same worker re-start keeps the original timestamp. Finished → re-start/re-end 409.
  - Start/end read the carton **`with_for_update()`** (double Enter / two stations raced; `tests/test_skan_paczek_stanowisko.py`).
  - **Station guards:** step 1 validates the badge at once via `GET /api/employee-lookup`. A badge scanned into the package field → **400 + `kod_pracownika: true`** (`blad_nieznanej_paczki()`, checked only after the carton misses) from lookup/start/end; UI keeps step 1. JS in-flight guard per tab (`zajete`) + disabled field during a request; open quantity panel shows „Paczka NIE jest jeszcze zakończona" and confirms tab switch / leave; quantity ≥ `ILOSC_WYGLADA_NA_KOD` (100 000) refused client-side.
- **Unlock:** `POST /api/packages/<id>/unlock-scan` (leader+, „🔓 Odblokuj") clears `scan_start_at`/`_by`. Finished → 409, unstarted → 400.
- `processed_by`/`processed_at` are set only by reassignment on `/paczki`. Removed in the 2026-09 cleanup — don't reintroduce: `POST /api/scan-package`, `POST /api/scan-employee`, `PUT /api/packages/uebergabe-double-rate` (and the `GeneralStat.double_rate` ×2 multiplier).

**`/paczki` filters:** `date_from`/`date_to`/`date_typ`/`barcode`/`land`/`osoba`/`double_rate=1`/`status`/`bledy=1`.
- `status` (`PACZKI_STATUSY`): `niezrobione` (default, `scan_end_at IS NULL`) · `zrobione` · `wszystkie`. Legacy `pokaz_zrobione=1` → `wszystkie`. `zrobione`/`wszystkie` **require a date range**, else fall back to `niezrobione` with a message (Jinja page — no `abort()`).
- `date_typ` (`PACZKI_POLA_DAT`): `ziel` (default, `db.Date`, direct) · `import` · `start` · `koniec` (naive-UTC → `local_day_bounds()`, **half-open** `<` next midnight). Unknown → `ziel`.
- **`date_typ=koniec` + date turns default `niezrobione` into `zrobione`** (otherwise always empty). **`date_typ=start` deliberately does not** ("started in range and still open").
- `osoba` = existing "kto" (`processed_by` / `scan_start_by` / `scan_end_by`).
- Error filter `bledy_paczki()` = started-not-finished **or** a category > `stueckzahl` + 10 % (`TOLERANCJA_ILOSCI`); ignores `status`. Runs in **Python** (JSON in Text), paginated via `StroniceLista`.

**Double rate (per-package):** `ImportedCarton.double_rate` checkbox in `/paczki`. A line with double-rate cartons gets a second **yellow** row in General Stats: Amounts = auto sum (`double_rate_amount_map()`), categories manual in `double_rate_category_data`. Both rows bill ×1 — doubling comes from counting twice. The old per-line ×2 multiplier is gone; its DB column is left untouched.

**Dashboard:** tabs Podsumowanie / Per pracownik (`GET /api/dashboard`, today, 30 s refresh) and Per zmiana (`GET /api/dashboard/shifts?date=`). Packages have no shift → attributed **by attendance** of the `scan_end_by` worker that day; no attendance or both shifts → `unattributed` (each package once). „Zrobione dziś" / „Pozostało" shown in packages and pieces (`pieces_today`, `remaining_pieces`); „Pozostało" is **all-time** (`scan_end_at IS NULL`).

**Time tracking:** `/time-tracking` scan → `POST /api/time/scan` `mode`: `break` (`break_start`/`break_end`) | `other` („Inne", off-station non-break; `other_start`/`other_end`) | `work_end`. Events in `WorkerTimeEvent`; state = `count(*_start) - count(*_end)`, no flag on User.
- „Inne" subtracts like a break but is reported separately (`other_minutes`, `others[]`, `on_other`). Break and „Inne" **cannot overlap** (409). `work_end` closes both.
- Manual corrections can still overlap → `_compute_worker_times` subtracts the **union** (`suma_zlaczonych_okresow()`); `break_minutes`/`other_minutes` stay raw.
- `/worker-times` per-worker and „⚠️ Tylko błędy" filters run **in the browser** over `/api/worker-times`. No-break / short-break count **only once `work_ended`**.

**CSV / Excel import:** rows → `ImportedCarton` (dedup by `barcode`) → `GeneralStat` grouped by `uebergabe_nr` + `land` + `ziel_datum`. Cost = category amount × rate (`CostMapping.rates_data`, per year/month).
- `POST /api/import-csv` (`;` CSV) and `POST /api/import/excel` (openpyxl, `data_only=True, read_only=True`) share **`process_import_rows(rows)`**, type-aware (`_cell_to_barcode/_int/_date/_str`), headers via `normalize_header`. Columns: `Barcode`, `Land`, `Stückzahl`, `Kategorie`, `Ziel-Datum`, `Übergabe Nr.`. Excel numeric barcodes are float64 (>2^53 loses digits, leading zeros vanish) — format as text.
- **Manual add** `POST /api/packages` (leader+): same `process_import_rows([row])`. Required `barcode`, `stueckzahl` > 0, `land`, `ziel_datum`, `uebergabe_nr`; optional `kategorie`, `double_rate`. Duplicate → 409 (pre-check + `IntegrityError`). Land dropdown = `CountryMapping` (value `innenauftrag`). Row shows `imported_by` login + „ręczna" badge.
- **Manual edit** `PUT /api/packages/<id>`: **only `added_manually`** (else 403). Group-field change moves the carton; `recompute_general_stat()` rewrites lines as `SUM(stueckzahl)` — **recompute-from-sum, never delta**; `amounts` is written only by carton aggregation. Emptied line kept at `amounts=0`. Sets `modified_by`/`modified_at`; UI confirms for scanned packages.

**Scan quantities → billing (`GeneralStat.category_source`):** scan quantities are the source of truth for `category_data`; `recompute_general_stat(..., from_scan=True)` sums `scan_category_data` (`scan_category_totals()`).
- `'manual'` lines are **never touched by recompute**; `'scan'` lines reject manual edits in `PUT /api/general-stats/<id>` (400). Flip to `'scan'` happens **only** when scan quantities arrive, never on import.
- A line with non-zero manual quantities **does not flip** (`ma_reczne_ilosci()`); shows `⚠ ręczne · skany 3/50` + „→ użyj skanów" → `POST /api/general-stats/<id>/use-scan` (admin). Empty (freshly imported) lines flip automatically.
- Typo fix: `PUT /api/packages/<id>/categories` (leader+, „✎ Ilości") works on **any** carton; sets `modified_*`, recomputes.
- Coverage `scan_coverage_map()` → `🔒 scanned/total` in General Stats and `GET /api/general-stats`.
- Yellow double-rate row stays **manual**.
- `GeneralStat.to_dict()` iterates `STAT_CATEGORIES`, not stored keys (`carton_labeling` was removed).
- **`Total Amount` = `TOTAL_AMOUNT_CATEGORY` (`labelling_on`) only**, never the sum. Three places must agree: Jinja row in `general_stats.html`, JS recompute after inline edit, `write_data_row()` in Excel export. The **yellow row still sums everything** (`is_double_rate=True`) — pending, `docs/TODO.md`.
- `STAT_CATEGORY_LABELS` (English — General Stats + Excel export headers, external artifact, keep English, **never admin-editable**) vs `STAT_CATEGORY_LABELS_PL` (**defaults only**). Screens use `etykiety_kategorii()` (one query) / `etykieta_kategorii(kat, nazwy_pl=None)` → **„Polish (English)"**, e.g. „Niesprocesowane (Sorting)" — worker-facing: end-of-package step, „✎ Ilości" on `/paczki`, cost mapping, scan-quantity validation errors. Polish names are admin-edited at `/admin/category-labels` (`PUT /api/category-labels {nazwy: {kat: str}}`, autosave) and stored in `AppSetting` as `kategoria_pl:<kat>` (no column); empty or equal to the default → the row is **deleted**, so a changed default in code still applies. `bledy_paczki()` keeps the English name (called per carton — a label lookup there would be N+1). General Stats shows English + the current Polish name.

**Normy (`/stats`) — overview `GET /api/stats/overview?date_from=&date_to=` (leader+)** — built on **finished packages, not `DailyStat`**.
- Metric = `sum(stueckzahl)` / **union** of the worker's scan intervals (`suma_zlaczonych_okresow()`), i.e. pieces per hour of *scanning* (breaks don't reduce it — label it so).
- Baseline = **team mean for the period** (`srednia_szt_h` = all pieces / all scanning hours), never a stored norm. Includes the „za mało danych" bucket (hour-weighted); cartons without measured time excluded. `proc_sredniej` = vs colleagues, and the UI says so.
- `min_packages_rank` (3) gates **ranking and verdicts only**, not the mean; below it → „za mało danych" (never hidden).
- `AppSetting`: `norm_good_pct` (110, 🟢, `>=`), `norm_weak_pct` (90, 🔴, `<=`), `min_packages_rank` (3) — via `PUT /api/settings`, `/admin/settings`.
- Pieces without measured time → `szt_h: null` (not 0). Nothing divides by zero.
- Soft-deleted workers stay in figures, badged „nieaktywna" (`is_active_user` on the row).
- Range filters `scan_end_at` via `local_day_bounds()`, half-open.
- Target `target_szt_h` (0 = unset → `cel_szt_h: null`, columns hidden) adds `proc_celu` / `ocena_celu` **beside** the mean. Verdict is two-state (`>= 100 %` → `spelnia`), not the mean's bands. `spelnia_cel` is `null` when unset **or ranking empty**.
- `PUT /api/stats/target` is **leader+** (display-only) and accepts **only that key** (`test_endpoint_celu_nie_rusza_innych_ustawien`).
- Per-worker `GET /api/stats/user/<id>`: `paczki_podsumowanie` (`podsumuj_paczki_pracownika()`) — totals + per day/month averages over days/months **with ≥ 1 finished carton**, independent of `activity_id`; none → `null`.
- Per-worker `norma` = **the worker's row from `przeglad_zespolu()`** + `miejsce` / `w_rankingu` / `powod_braku_oceny` (`za_malo_paczek` · `brak_czasu` · `brak_paczek`). Never compute it a second way (`test_ocena_osoby_zgadza_sie_z_przegladem`); clicking a name copies the date range.
- Charts `wykres_dzienny` / `wykres_miesieczny` from finished packages by local day/month of `scan_end_at`: bars = pieces, line = szt./h (`null` without time), dashed = mean and target.
- Dashboard names → `/stats?user=<id>` (`user_id` in `workers_today`, `unattributed.workers`); `stats.html` reads `?user=` (+ dates), name from the API.
- Rows link to `/paczki?osoba=<id>&date_typ=koniec&date_from=&date_to=` (no `status` needed).

## Key implementation details

- **Port 5001** (5000 is Jewelry-Tracker on the same server).
- **Barcode scanner:** EAN-128 via USB HID, 300 ms keystroke buffer (raise to 500 ms if slow).
- **Drag & drop:** native HTML5, click multi-select, drag moves all selected.
- **User options:** `User.worker_type_id` („Rodzaj pracownika") and `User.shift_group_id` („Nazwa zmiany") → `UserOption(kind, name)`, `USER_OPTION_KINDS`. Defaults seeded **once** (marker `user_options_seeded`). Columns in the Normy overview (`worker_type` / `shift_group`, `joinedload`ed). Named `shift_group` because `Shift`/`shift_id` = dated shift 1/2. Admin edits at `/admin/user-options`; `GET /api/user-options` leader+; option in use → delete 409, rename only.
- **"Today" = Warsaw day:** `local_today()` / `local_day_bounds(d)` (→ naive-UTC `[start, end)`, DST-correct) are the single definition. Never `date.today()`.
- **Timestamps: naive UTC (`datetime.utcnow()`), displayed Europe/Warsaw.** API: `iso_z()` appends `Z` — **datetime fields only**, date-only (`ziel_datum`, `loading_date`, `Shift.date`) stay bare `isoformat()`. Jinja: `| localdt('%fmt')`. Browser sends `new Date(local).toISOString().slice(0,19)`. Never bare `strftime` on a stored datetime, never a Z-less ISO into `new Date()`.
- **Time thresholds** (`/admin/settings`, `PUT /api/settings`, `AppSetting`, `get_setting_int()`, `SETTING_DEFAULTS`): `break_threshold_minutes` 30, `max_work_minutes` 660, `min_break_minutes` 15 → JS `BREAK_THRESHOLD` / `MAX_WORK_MINUTES` / `MIN_BREAK_MINUTES`.
- **First start serialized with `pg_advisory_lock`** — gunicorn workers race in `db.create_all()` on an empty DB (`Worker failed to boot`). `tests/test_init_race.py` (`pusta_baza` does `CREATE DATABASE`).
- **Backups:** `pg_dump`.
- **Config** (`docs/DEPLOY.md`): `SECRET_KEY` mandatory — `resolve_secret_key()` raises (bypass `LOGISTAT_ALLOW_DEV_SECRET=1`); from `.env` via Compose. **Never `${VAR:?}` in `docker-compose.yml`** — resolved before the override merges, breaks `.31` (no `.env`). `MAX_UPLOAD_MB` (32) → 413 JSON. `SESSION_COOKIE_SAMESITE=Lax` always; `SESSION_COOKIE_SECURE` opt-in (`.31` also on plain HTTP).
- **`/api/` errors are JSON** (one `@app.errorhandler(HTTPException)`): `abort(400, 'komunikat')`, front reads `data.error`. Helpers: `json_body()`, `parse_date()` (empty → today; for range filters call conditionally), `parse_shift_number()`, `require_int()`.
- **Static:** `{{ static_v('style.css') }}` appends mtime.
- **`escapeHtml()` (`base.html`)** on everything from the DB going into `innerHTML` — barcodes come from imports, risk is *stored* XSS.
- **Autosave, no „Zapisz" button** on the bulk screens — Przydzielanie, Wpis ilości, Forecast, Statystyki ogólne (people forgot the button and lost work). One helper in `base.html`: `autoZapis.zaplanuj(klucz, wyslij, pola)` + `zapiszJson()`. Rules: wire fields with **`autoZapis.poWpisaniu(pole, zapisz)`** — saves **1.2 s after typing stops** *or* on `change` (blur), same value never twice; a field waiting for its pause counts as unsaved (`beforeunload`, „✎ Zapis za chwilę…"), and `przedOpuszczeniem()` pushes it out first — closing a tab with the cursor in a field fires no `change`, so blur-only lost the last number silently. Build the payload (incl. date/shift) **at change time** — pages keep `loadedDate`, not the date field's live value; **one request in flight per key**, then only the newest pending one (key = row / shift); status in `#autoZapisStatus` (Zapisywanie / ✓ Zapisano / ⚠ + Ponów or the error's `akcja`); `beforeunload` armed only while pending/failed; **`await autoZapis.przedOpuszczeniem()` before** shift/date switch, reload, filter submit and export links. `zapiszJson()` treats a non-JSON or redirected response as failure — an expired session redirects to `/login` with **200**. Per-row saves only: forecast saves one day (`saved === 1`), daily stats one `(user, activity)`, general stats one line (`gs:<id>:main|dr`, amount fields only — the readonly cost field also has `inline-input`; no amount fields → send nothing, an empty dict would wipe the line's categories). Other endpoints unchanged (assignment: see Core data flows). **Gotcha:** some pages (e.g. `general_stats.html`) put their `<script>` in `{% block content %}`, which runs **before** base.html's script — call `autoZapis`/`zapiszJson` there only from events or `DOMContentLoaded`, or the page gets a `ReferenceError` and silently stops saving.
- **Explicit-save forms stay explicit** (modals, `/admin/settings`, stats target, **cost mapping** — billing, and „copy previous month" is deliberate). Cost mapping shows „● Niezapisane zmiany stawek", arms `beforeunload` and asks before loading another month while rates differ from the loaded ones. **Save and „copy previous month" use the *loaded* month (`loadedYear`/`loadedMonth`), never the live selects** — switching the month list without „Pokaż stawki" used to save the old month's rates under the new one; the button shows which month it writes. Modals with fields carry **`data-modal-guard`**: a backdrop click with changed fields asks first (it used to discard silently); „Anuluj" does not ask. New modal with a form → add the attribute.
- **Shift colours:** `--shift-1` (blue) / `--shift-2` (orange) in `:root`, applied by `data-shift="1|2"` on `.shift-tab.active`, `.shift-badge`, `.shift-frame` (working area of the edited shift), `.shift-card` (dashboard), `.scanner-shift-badge` / `.scanner-page`. Never yellow (double rate / warnings), green/red (statuses) or purple (accent); always next to the „Zmiana N" text, never colour alone. New place showing a shift → reuse these classes.

## Pending work (from TODO.md)

- Touch/tablet support for drag & drop
- Excel export for worker times
