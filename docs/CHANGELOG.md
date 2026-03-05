# LogiStat — Changelog

## [1.2.0] — 2026-03-05

### Import CSV i Statystyki Ogólne

#### Backend
- Dwa nowe modele: `ImportedCarton` (dane wg pliku CSV) i `GeneralStat` (agregacje statystyk)
- Deduplikacja danych wejściowych po unikalnym `barcode`
- Matchowanie z `CountryMapping` (Land == Innenauftrag)
- Agregacja danych dla statystyk po liście, kraju i dacie ładowania
- Nowe strony: `/import-csv`, `/general-stats`
- Nowe endpointy: `POST /api/import-csv` z autodetekcją kodowania (UTF-8/Latin-1), `GET /api/general-stats`, `PUT /api/general-stats/<id>`

#### Frontend
- Niezależne zakładki w sidebarze: **Import CSV**, **Statystyki ogólne**
- `import_csv.html` — zintegrowany mechanizm drag & drop i szybki wykaz przetworzonych danych
- `general_stats.html` — interaktywna tabela rozliczeniowa (jak widok Excela), umożliwiająca wewnątrzkomórkową edycję kosztów dla 10 konfigurowalnych kategorii. Sumowanie "Total cost" w czasie rzeczywistym.

> ⚠️ Wymaga usunięcia bazy `instance/logistat.db` i restartu (nowy model w bazie danych)

## [1.1.0] — 2026-03-05

### Panel Admina + Mapowanie krajów i zleceń

#### Backend
- Nowy model `CountryMapping` (country, innenauftrag)
- 4 endpointy API CRUD: `/api/country-mappings` (GET, POST, PUT, DELETE)
- Seed 29 domyślnych mapowań Country → Innenauftrag
- Nowe strony: `/admin/panel`, `/admin/country-mapping`

#### Frontend
- Nowy link w sidebarze: **Panel Admina** (widoczny tylko dla admin)
- `admin_panel.html` — hub z kartą-przyciskiem do mapowania
- `admin_country_mapping.html` — tabela z CRUD (dodaj/edytuj/usuń z modalem)

> ⚠️ Wymaga usunięcia bazy `instance/logistat.db` i restartu (nowy model)

## [1.0.0] — 2026-02-13

### Pierwsza wersja aplikacji

#### Backend
- Flask + SQLAlchemy + SQLite
- 6 modeli: User, Activity, Shift, ShiftAttendance, ActivityAssignment, DailyStat
- 18 endpointów API (skanowanie, przydzielanie, statystyki, admin)
- Algorytm sugestii AI (średnia 30-dniowa per czynność)
- Audit trail na DailyStat (entered_by, modified_by, timestamps)
- Seed 9 domyślnych czynności + konto admin
- Role: operator, leader, admin

#### Frontend
- Dark theme z glassmorphism (Inter font, gradientowe akcenty)
- Skaner zmian — EAN-128, timeout 300ms, auto-clear, toasty
- Drag & drop — multi-select, sugestie AI, zapis przydziałów
- Wpis ilości — tabela z inputami per pracownik/czynność
- Statystyki — wykres dzienny (Chart.js), tabele miesięczne, edycja
- Admin czynności — dodawanie, edycja nazw, aktywacja/dezaktywacja
- Admin użytkownicy — dodawanie operatorów z kodem kreskowym

#### Infrastruktura
- Dockerfile + docker-compose.yml (port 5001)
- requirements.txt

### Bugfixy
- Fix: `User is not JSON serializable` w admin_users.html — zmiana `user|tojson` na `user.to_dict()|tojson`
- Fix: port 5001 zamiast 5000 (konflikt z Jewelry-Tracker)
