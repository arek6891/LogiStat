# LogiStat — Specyfikacja bazy danych

## Środowiska

| Środowisko | Host | Silnik | Baza | Użytkownik |
|---|---|---|---|---|
| Development | 10.153.1.32 | SQLite | `instance/logistat.db` | — |
| Test | 10.153.1.31 | **PostgreSQL 16** (kontener `logistat-test-db`) | `logistat` | `logistat` |
| Production | 10.153.1.30 | PostgreSQL 16 *(nie wdrożone)* | `logistat` | `logistat` |

Silnik wybiera zmienna **`DATABASE_URL`**; bez niej aplikacja działa na SQLite.
Hasła w `docker-compose.override.yml` na serwerze (`chmod 600`, poza repozytorium) —
nigdy w kodzie ani w repozytorium. Procedura: `docs/DEPLOY.md`.

> ⚠️ **Nie ma ręcznie pisanego pliku DDL i nie należy go zakładać.**
> Schemat na obu silnikach tworzy `db.create_all()` (ORM = źródło prawdy). W tym pliku
> `category_data`/`rates_data` są `JSONB` — psycopg2 zwraca wtedy dict, a `get_category_data()`
> robi na tym `json.loads`; a `DEFAULT NOW()` na `TIMESTAMP` wpisuje czas lokalny serwera do
> kolumn, które aplikacja czyta jako naive UTC (2 h błędu w PL latem). Do decyzji: poprawić
> (JSONB→TEXT, usunąć `DEFAULT NOW()`) albo usunąć plik.

**Tworzenie schematu jest serializowane między workerami.** Gunicorn importuje `app.py`
raz na worker, więc przy **pustej** bazie wszystkie wchodzą jednocześnie w `db.create_all()`
i `seed_data()`. Bez blokady przegrany dostaje `UniqueViolation` na `pg_class` (Postgres)
albo `table user already exists` (SQLite), gunicorn melduje `Worker failed to boot` i ubija
cały kontener — losowo, więc wygląda to na zaciętą instalację, nie na błąd. `init_db()`
używa dlatego `pg_advisory_lock(5001)` na Postgresie i `fcntl.flock` na `instance/.init.lock`
na SQLite. Dotyczy tylko pierwszego startu; na gotowej bazie `create_all()` i `seed_data()`
są no-opami.

---

## Szacowany wolumen danych (5 lat)

| Tabela | Wierszy/dzień | Razem 5 lat | Uwagi |
|---|---|---|---|
| `imported_carton` | ~1 500 | ~2 750 000 | Dominująca tabela |
| `worker_time_event` | ~400 | ~730 000 | 100 pracowników × ~4 eventy/zmianę × 2 zmiany |
| `daily_stat` | ~500 | ~910 000 | 50 pracowników × ~5 czynności × 2 zmiany |
| `shift_attendance` | ~200 | ~365 000 | 100 pracowników × 2 zmiany |
| `activity_assignment` | ~100 | ~182 500 | Przydziały liderów |
| `general_stat` | ~25 | ~45 000 | Agregacja z CSV |
| `forecast` | 1 | ~1 825 | Jeden wpis na dzień |
| `shift` | 2 | ~3 650 | Dwie zmiany dziennie |
| Słowniki | statyczne | < 1 000 | user, activity, country_mapping, cost_mapping |
| **Łącznie** | | **~5 000 000** | **~2–3 GB** |

---

## Tabele

### `user`
Pracownicy systemu. Trzy role: `operator` (skanuje barcode, bez loginu), `leader` (loguje się hasłem, obsługuje moduły), `admin` (pełen dostęp).

| Kolumna | Typ | Ograniczenia | Opis |
|---|---|---|---|
| id | SERIAL | PK | |
| username | VARCHAR(100) | UNIQUE NOT NULL | Login (tylko leader/admin) |
| display_name | VARCHAR(150) | NOT NULL | Imię i nazwisko |
| barcode_id | VARCHAR(100) | UNIQUE | Kod kreskowy na karnecie (operator) |
| password_hash | VARCHAR(200) | | Bcrypt hash; NULL dla operatorów |
| role | VARCHAR(20) | NOT NULL DEFAULT 'operator' | operator / leader / admin |
| is_active_user | BOOLEAN | NOT NULL DEFAULT TRUE | Soft-delete |
| created_at | TIMESTAMP | NOT NULL DEFAULT NOW() | |

---

### `activity`
Słownik czynności produkcyjnych (np. "Post Processing", "Textile-Picking"). Zarządzany przez admina.

| Kolumna | Typ | Ograniczenia | Opis |
|---|---|---|---|
| id | SERIAL | PK | |
| name | VARCHAR(100) | UNIQUE NOT NULL | |
| sort_order | INTEGER | NOT NULL DEFAULT 0 | Kolejność w UI |
| is_active | BOOLEAN | NOT NULL DEFAULT TRUE | |

---

### `shift`
Zmiana robocza (data + numer zmiany 1 lub 2). Tworzona automatycznie przez lidera przy skanowaniu.

| Kolumna | Typ | Ograniczenia | Opis |
|---|---|---|---|
| id | SERIAL | PK | |
| date | DATE | NOT NULL | |
| shift_number | SMALLINT | NOT NULL | 1 lub 2 |
| created_at | TIMESTAMP | NOT NULL DEFAULT NOW() | |

**Unique:** `(date, shift_number)`

---

### `shift_attendance`
Obecność operatora na zmianie — rejestrowana skanem kodu kreskowego przez lidera.

| Kolumna | Typ | Ograniczenia | Opis |
|---|---|---|---|
| id | SERIAL | PK | |
| shift_id | INTEGER | FK → shift.id NOT NULL | |
| user_id | INTEGER | FK → user.id NOT NULL | |
| scanned_at | TIMESTAMP | NOT NULL DEFAULT NOW() | |

**Unique:** `(shift_id, user_id)`

---

### `activity_assignment`
Przydzielenie operatora do czynności na danej zmianie (drag & drop przez lidera).

| Kolumna | Typ | Ograniczenia | Opis |
|---|---|---|---|
| id | SERIAL | PK | |
| shift_id | INTEGER | FK → shift.id NOT NULL | |
| user_id | INTEGER | FK → user.id NOT NULL | |
| activity_id | INTEGER | FK → activity.id NOT NULL | |
| is_suggestion | BOOLEAN | NOT NULL DEFAULT FALSE | Podpowiedź AI (30-dniowa średnia) |
| assigned_by | INTEGER | FK → user.id | Lider który przydzielił |
| assigned_at | TIMESTAMP | NOT NULL DEFAULT NOW() | |

**Unique:** `(shift_id, user_id, activity_id)`

---

### `daily_stat`
Wpisy ilości wykonanych sztuk per pracownik per czynność per zmiana. Audit trail.

| Kolumna | Typ | Ograniczenia | Opis |
|---|---|---|---|
| id | SERIAL | PK | |
| shift_id | INTEGER | FK → shift.id NOT NULL | |
| user_id | INTEGER | FK → user.id NOT NULL | |
| activity_id | INTEGER | FK → activity.id NOT NULL | |
| quantity | INTEGER | NOT NULL DEFAULT 0 | |
| note | VARCHAR(300) | | |
| entered_by | INTEGER | FK → user.id | |
| entered_at | TIMESTAMP | DEFAULT NOW() | |
| modified_by | INTEGER | FK → user.id | |
| modified_at | TIMESTAMP | | |

**Unique:** `(shift_id, user_id, activity_id)`

---

### `country_mapping`
Słownik mapowania kraju na numer zlecenia wewnętrznego (Innenauftrag) z systemu logistycznego.

| Kolumna | Typ | Ograniczenia | Opis |
|---|---|---|---|
| id | SERIAL | PK | |
| country | VARCHAR(150) | NOT NULL | Nazwa kraju |
| innenauftrag | VARCHAR(100) | NOT NULL | Kod zlecenia z systemu |

---

### `imported_carton`
**Główna tabela — największy wolumen.** Każdy wiersz = jeden karton z importu CSV. Deduplikacja po `barcode`.

| Kolumna | Typ | Ograniczenia | Opis |
|---|---|---|---|
| id | BIGSERIAL | PK | |
| barcode | VARCHAR(100) | UNIQUE NOT NULL | EAN-128, klucz dedulikacji |
| land | VARCHAR(150) | | Kraj/Innenauftrag z CSV |
| stueckzahl | INTEGER | DEFAULT 0 | Ilość sztuk w kartonie |
| kategorie | VARCHAR(100) | | Kategoria produktu |
| ziel_datum | DATE | | **Loading date** — data załadunku |
| uebergabe_nr | VARCHAR(100) | | Numer listy (agreguje kartony w GeneralStat) |
| country_mapping_id | INTEGER | FK → country_mapping.id | |
| imported_at | TIMESTAMP | DEFAULT NOW() | |
| imported_by | INTEGER | FK → user.id | Admin który importował |
| processed_by | INTEGER | FK → user.id | Pracownik który zeskanował karton |
| processed_at | TIMESTAMP | | Czas skanowania kartonu |
| scan_start_at | TIMESTAMP | | Start procesowania (moduł Czasy paczek) |
| scan_start_by | INTEGER | FK → user.id | |
| scan_end_at | TIMESTAMP | | Koniec procesowania |
| scan_end_by | INTEGER | FK → user.id | |
| double_rate | BOOLEAN | DEFAULT FALSE | Paczka liczona jako double rate (checkbox w Paczkach) → generuje żółtą linię w GeneralStat |

**Indeksy:** `ziel_datum`, `uebergabe_nr`, `processed_by`, `land`, `imported_at`

---

### `general_stat`
Dane zagregowane z importów CSV. Grupowanie po `(uebergabe_nr, land, ziel_datum)`. Zawiera koszty kategorii jako JSONB.

| Kolumna | Typ | Ograniczenia | Opis |
|---|---|---|---|
| id | SERIAL | PK | |
| loading_date | DATE | NOT NULL | |
| week_number | SMALLINT | NOT NULL | Numer tygodnia ISO |
| list_id | VARCHAR(100) | NOT NULL | = uebergabe_nr z ImportedCarton |
| country_of_destination | VARCHAR(150) | | Kraj docelowy (z CountryMapping) |
| country_ledger | VARCHAR(150) | NOT NULL | = land z ImportedCarton |
| amounts | INTEGER | DEFAULT 0 | Suma stueckzahl dla grupy |
| category_data | JSONB | DEFAULT '{}' | Ilości i koszty per kategoria (normalna linia) |
| double_rate_category_data | JSONB/TEXT | DEFAULT '{}' | Ilości per kategoria dla **żółtej linii** double rate (wpisywane ręcznie) |
| created_at | TIMESTAMP | DEFAULT NOW() | |
| updated_at | TIMESTAMP | | |
| updated_by | INTEGER | FK → user.id | |

**Unique:** `(list_id, country_ledger, loading_date)`  
**Indeksy:** `loading_date`, `list_id`

> **Usunięte 2026-09-01:** kolumna `double_rate` (stary mnożnik ×2 per-linia). Wypadła
> z modelu razem ze swoim jedynym writerem — `PUT /api/packages/uebergabe-double-rate`.
> Żółta linia liczy się z `double_rate_amount_map()`, czyli z flag na kartonach, nie stąd.
> **W istniejących bazach kolumna fizycznie zostaje** (nullable, z defaultem) — nic nie
> migrujemy, kod jej po prostu nie dotyka. `db.create_all()` na świeżej bazie już jej
> nie założy, więc schematy starych i nowych instalacji różnią się o tę jedną kolumnę.

**Struktura `category_data`:**
```json
{
  "labelling_on":      {"amount": 120, "cost": 0.0},
  "labelling_tvl":     {"amount": 0,   "cost": 0.0},
  "labelling_try":     {"amount": 45,  "cost": 0.0},
  "textile":           {"amount": 300, "cost": 0.0},
  "accessoire":        {"amount": 0,   "cost": 0.0},
  "sunglasses":        {"amount": 0,   "cost": 0.0},
  "card_facture":      {"amount": 0,   "cost": 0.0},
  "labelling_polybag": {"amount": 0,   "cost": 0.0},
  "sorting":           {"amount": 0,   "cost": 0.0},
  "carton_labeling":   {"amount": 0,   "cost": 0.0}
}
```

---

### `app_setting`
Generyczny magazyn klucz/wartość na ustawienia aplikacji. Czytany przez
`get_setting()` / `get_setting_int()`; wartości domyślne dla znanych kluczy siedzą
w `SETTING_DEFAULTS` w kodzie, więc brak wiersza nie jest błędem.

| Kolumna | Typ | Ograniczenia | Opis |
|---|---|---|---|
| key | VARCHAR(100) | PK | Nazwa ustawienia |
| value | VARCHAR(500) | | Wartość jako tekst; konwersję robi akcesor |

**Znane klucze:**

| Klucz | Domyślnie | Opis |
|---|---|---|
| `break_threshold_minutes` | `30` | Próg czasu przerwy podświetlany na czerwono w `/worker-times`; edytowalny w `/admin/settings` (`PUT /api/settings`) |

### `cost_mapping`
Stawki kosztów per kategoria per miesiąc/rok. Używane do wyliczania kosztów w GeneralStat.

| Kolumna | Typ | Ograniczenia | Opis |
|---|---|---|---|
| id | SERIAL | PK | |
| year | SMALLINT | NOT NULL | |
| month | SMALLINT | NOT NULL | 1–12 |
| rates_data | JSONB | DEFAULT '{}' | Stawki per kategoria (EUR/szt.) |
| created_at | TIMESTAMP | DEFAULT NOW() | |
| updated_at | TIMESTAMP | | |
| updated_by | INTEGER | FK → user.id | |

**Unique:** `(year, month)`

**Struktura `rates_data`:**
```json
{
  "labelling_on":      0.05,
  "labelling_tvl":     0.04,
  "textile":           0.12,
  ...
}
```

---

### `forecast`
Plan dzienny — jeden wpis na dzień, wpisywany ręcznie przez lidera. Porównywany z actual (ImportedCarton per ziel_datum).

| Kolumna | Typ | Ograniczenia | Opis |
|---|---|---|---|
| id | SERIAL | PK | |
| date | DATE | UNIQUE NOT NULL | |
| quantity | INTEGER | DEFAULT 0 | Planowana ilość kartonów |
| notes | VARCHAR(500) | | |
| created_by | INTEGER | FK → user.id | |
| created_at | TIMESTAMP | DEFAULT NOW() | |
| updated_at | TIMESTAMP | | |
| updated_by | INTEGER | FK → user.id | |

---

### `worker_time_event`
Eventy czasu pracy pracownika: rozpoczęcie/zakończenie przerwy, koniec pracy. Stan przerwy = `count(break_start) − count(break_end)`.

| Kolumna | Typ | Ograniczenia | Opis |
|---|---|---|---|
| id | SERIAL | PK | |
| user_id | INTEGER | FK → user.id NOT NULL | |
| shift_id | INTEGER | FK → shift.id NOT NULL | |
| event_type | VARCHAR(20) | NOT NULL | `break_start` / `break_end` / `work_end` |
| timestamp | TIMESTAMP | NOT NULL DEFAULT NOW() | |
| recorded_by | INTEGER | FK → user.id | |
| is_manual | BOOLEAN | DEFAULT FALSE | Korekta ręczna przez lidera |
| note | VARCHAR(300) | | |

**Indeksy:** `(user_id, shift_id)`, `shift_id`

---

## Reguły biznesowe zakodowane w aplikacji

- Przerwa >30 min podświetlana czerwono w widoku Czasy pracowników
- `ImportedCarton.barcode` deduplikowany przy imporcie CSV — duplikaty pomijane
- `GeneralStat` tworzona/aktualizowana automatycznie przy imporcie CSV
- **Double rate:** paczka z `imported_carton.double_rate = TRUE` generuje w GeneralStat drugą, żółtą linię — Amounts = suma `stueckzahl` takich paczek w grupie, kategorie ręcznie w `double_rate_category_data`. Obie linie ×1 (podwojenie z policzenia paczek dwa razy)
- **Czas paczek:** paczkę w trakcie obsługuje tylko pracownik, który ją rozpoczął; paczka zakończona (`scan_end_at`) jest zablokowana przed ponownym startem/końcem
- **Statystyki:** zakończone paczki (`scan_end_by`) liczą się automatycznie do modułu Statystyki jako pozycje `📦 Paczki` (liczba) i `📦 Paczki (szt.)`, po dacie `scan_end_at` — brak osobnej tabeli, wyliczane w locie
- Soft-delete użytkowników: `is_active_user = FALSE` zamiast usunięcia
- Wszystkie timestamps w UTC; frontend konwertuje do czasu lokalnego przez `new Date(iso).toLocaleTimeString('pl')`
- Timeout skanera EAN-128: 300 ms (bufferowanie klawiszy HID)

---

## TODO / Odłożone

- ✅ **Import Excel** — zrobione: `POST /api/import/excel` (openpyxl), wspólny pipeline z CSV.
- ✅ **Backup automatyczny** — `scripts/backup-logistat.sh` (`pg_dump`, gzip, retencja 14 dni,
  kontrola kompletności zrzutu) + cron 22:30 na `.31`. Odtworzenie: patrz `docs/DEPLOY.md`.
- ✅ **Migracja do PostgreSQL** — zrobione na teście (`.31`) 2026-08-31. Zostaje produkcja
  na `.30` (blokada: brak dostępu SSH).
- **Zmierzony przyrost** (2026-08-31, `dbstat` + kontener Postgresa, ten sam zestaw danych):
  `imported_carton` 278 B/wiersz w SQLite vs **248 B w Postgresie** (Postgres mniejszy —
  SQLite trzyma 7 kolumn DATETIME jako 26-znakowy TEXT, Postgres jako 8-bajtowy `timestamp`);
  `worker_time_event` 77 → 128 B, `daily_stat` 63 → 138 B, `general_stat` 648 → 899 B.
  Cały zestaw: 41,6 MB (SQLite) vs 56 MB (Postgres) ≈ ×1,35. Przy 500–1000 paczek/dzień
  i 250 dniach roboczych to **~50–90 MB/rok**; pusty klaster Postgresa to dodatkowo 38,6 MB,
  a `pg_wal` może dobić do 1 GB (`max_wal_size`). Szacunek 2–3 GB / 5 lat z tabeli powyżej
  był zawyżony ~3× (zakładał 1 500 paczek/dzień).
