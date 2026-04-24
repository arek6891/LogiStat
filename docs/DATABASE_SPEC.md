# LogiStat — Specyfikacja bazy danych

## Środowiska

| Środowisko | Host | Baza | Użytkownik |
|---|---|---|---|
| Development | 10.153.1.32 | appdb | app |
| Test | *(do uzupełnienia)* | logistat_test | logistat |
| Production | *(do uzupełnienia)* | logistat_prod | logistat |

Hasła przechowywane w zmiennych środowiskowych — nigdy w kodzie ani w repozytorium.

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
| category_data | JSONB | DEFAULT '{}' | Ilości i koszty per kategoria |
| double_rate | BOOLEAN | DEFAULT FALSE | Podwójna stawka (×2 koszty) — *implementacja odłożona* |
| created_at | TIMESTAMP | DEFAULT NOW() | |
| updated_at | TIMESTAMP | | |
| updated_by | INTEGER | FK → user.id | |

**Unique:** `(list_id, country_ledger, loading_date)`  
**Indeksy:** `loading_date`, `list_id`

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
- Soft-delete użytkowników: `is_active_user = FALSE` zamiast usunięcia
- Wszystkie timestamps w UTC; frontend konwertuje do czasu lokalnego przez `new Date(iso).toLocaleTimeString('pl')`
- Timeout skanera EAN-128: 300 ms (bufferowanie klawiszy HID)

---

## TODO / Odłożone

- **Double Rate** — pole `general_stat.double_rate` istnieje, UI usunięte. Czeka na informację skąd pochodzi ta flaga (z CSV? ręcznie? per uebergabe_nr?). Patrz `docs/TODO.md`.
- **Import Excel** — endpoint zarezerwowany (`/api/import/excel`), biblioteka `openpyxl` zainstalowana.
- **Backup automatyczny** — brak harmonogramu backupu bazy. Do skonfigurowania przed produkcją.
- **Migracja do PostgreSQL** — aplikacja używa SQLite (dev). Przed wdrożeniem produkcyjnym zalecana migracja.
