# LogiStat — Changelog

## [1.7.0] — 2026-07-18

### Dashboard — zakładka „Per zmiana"

#### Backend
- `GET /api/dashboard/shifts?date=YYYY-MM-DD` — dzienny podział per zmiana (domyślnie dziś)
- Paczki (bez `shift_id`) przypisywane do zmiany **wg obecności pracownika** (`ShiftAttendance`): paczka liczy się do jedynej zmiany, na którą pracownik był zeskanowany danego dnia
- Pracownicy bez obecności lub obecni na obu zmianach → kubełek `unattributed` (nic nie ginie, każda paczka liczona raz)
- DailyStat agregowane per zmiana bezpośrednio przez `shift_id`

#### Frontend
- `dashboard.html` — trzecia zakładka „Per zmiana" z **wyborem daty** (przeglądanie historii)
- Dwie karty obok siebie (Zmiana 1 / Zmiana 2): liczba obecnych, paczki, sztuki, rozbicie per czynność
- Sekcja ostrzegawcza dla paczek nieprzypisanych do zmiany

### Ręczne dodawanie i edycja paczek (moduł Paczki)

#### Backend — modele / migracje
- `ImportedCarton.added_manually` (bool) — odróżnia paczki dodane ręcznie od importowanych
- `ImportedCarton.modified_at` / `modified_by` — audyt edycji
- `migrate_columns()`: dodane `imported_carton.added_manually`, `modified_at`, `modified_by`
- Relacje `imported_by_user`, `modified_by_user`; `to_dict()` zwraca `imported_by_login`, `modified_by_login`, `added_manually`, `modified_at`

#### Backend — dodawanie
- `POST /api/packages` (leader+) — ręczne dodanie pojedynczej paczki dla przypadków, których nie ma w plikach CSV
- Przechodzi przez **ten sam** pipeline co import (`process_import_rows`) — dedup po `barcode`, agregacja do `GeneralStat`, rozliczenie identyczne jak paczka z importu; ustawia `added_manually=True`, `imported_by`
- Walidacja: 5 pól wymaganych (`barcode`, `stueckzahl` > 0, `land`, `ziel_datum`, `uebergabe_nr`) → 400; duplikat barcode → 409 (pre-check + fallback na `IntegrityError`)
- `process_import_rows` czyta teraz opcjonalne `double_rate` / `added_manually` z wiersza (brak klucza w CSV/Excel → `False`)

#### Backend — edycja
- `PUT /api/packages/<id>` (leader+) — edycja wszystkich pól danych; dozwolona **tylko** dla paczek `added_manually` (import → 403)
- `recompute_general_stat()` — po zmianie pola grupującego (`uebergabe_nr`/`land`/`ziel_datum`) przelicza dotknięte linie GeneralStat **od zera z sumy paczek** (recompute-from-sum, nie delta) — poprawne także gdy paczka ręczna dzieli linię z paczkami z CSV; pusta grupa zostaje z `amounts=0` (zachowuje `category_data`)
- Zmiana barcode na istniejący → 409 (rollback); ustawia `modified_by`/`modified_at`

#### Frontend
- `/paczki` — przycisk „➕ Dodaj paczkę" + modal (wymagane pola oznaczone `*`); ten sam modal obsługuje edycję („✎ Edytuj" przy paczkach ręcznych)
- Kolumna „Data importu" pokazuje teraz **kto dodał** (login „👤 …"), znacznik „ręczna" i ślad edycji („✏ login · data")
- Land jako lista rozwijana z mapowań krajów (zapisuje `innenauftrag`, gwarantuje mapowanie kosztu)
- Edycja paczki zeskanowanej → potwierdzenie przed zapisem
- Enter (skaner EAN-128) przenosi focus do kolejnego pola zamiast zamykać modal
- Tytuł strony: „Paczki (Dane CSV)" → „Paczki (dane)" (obejmuje też paczki ręczne)

### Import danych z Excela (.xlsx)

#### Backend
- `POST /api/import/excel` — import kartonów z pliku Excel `.xlsx` (openpyxl, `data_only=True, read_only=True`)
- Wydzielony wspólny helper `process_import_rows(rows)` — jeden pipeline (dedup po `barcode` + agregacja do `GeneralStat` + kształt odpowiedzi) dla importu CSV **i** Excel
- Type-aware koercja pól (`_cell_to_barcode/_int/_date/_str`): CSV zwraca stringi, openpyxl natywne `datetime`/`int`/`float`/`None`
  - daty: natywne komórki datowe używane wprost, stringi przez `strptime`
  - barcode: całkowite floaty renderowane bez `.0` (`str(int(val))`)
  - ⚠️ numeryczne barcode w Excelu = float64: długie SSCC/EAN >2^53 tracą precyzję, wiodące zera znikają u źródła — kolumnę barcode formatować jako tekst
- Kolumny jak w CSV (`normalize_header`): `Barcode`, `Land`, `Stückzahl`, `Kategorie`, `Ziel-Datum`, `Übergabe Nr.`

#### Frontend
- `/import-csv` — strona „Import danych": drag & drop przyjmuje `.csv` **i** `.xlsx`, routing endpointu po rozszerzeniu pliku; ta sama karta wyników
- Sidebar: „Import CSV" → „Import danych"

## [1.6.0] — 2026-07-18

### Zmiana hasła, Double Rate per-paczka, Podgląd paczek, Blokady czasu paczek

#### Backend — modele / migracje
- `ImportedCarton.double_rate` (bool) — flaga double rate **per paczka** (checkbox w Paczkach)
- `GeneralStat.double_rate_category_data` (TEXT JSON) — ręczne ilości per kategoria dla żółtej linii
- Usunięty legacy mnożnik ×2 (`GeneralStat.double_rate` per-linia) z obliczeń i eksportu — kolumna zostaje jako martwy back-compat
- `migrate_columns()`: dodane `imported_carton.double_rate`, `general_stat.double_rate_category_data`

#### Backend — nowe / zmienione endpointy
- `GET /profile` + `POST /profile` — zmiana hasła (walidacja: aktualne, min. 6 znaków, zgodność, różne od starego)
- `GET /api/package-lookup?barcode=` — **podgląd paczki** (status: przeskanowana / przez kogo / zakończona + dane), tylko do odczytu
- `PUT /api/packages/<id>/double-rate` — przełączenie double rate na paczce
- `PUT /api/general-stats/<id>` — przyjmuje teraz `double_rate_category_data`
- `POST /api/package-time/start|end` — **blokada właścicielska**: paczkę w trakcie obsługuje tylko pracownik, który ją zaczął (start innego → 409, koniec innego → 403); paczka zakończona jest zablokowana (ponowny start/koniec → 409)
- `POST /api/scan-package` (stare przypisanie) — wycofane, martwy kod (moduł jest teraz podglądem)

#### Frontend
- `/profile` — ekran zmiany hasła + link „🔑 Zmień hasło" w sidebarze
- `/scan-package` („Skan paczek") — przerobiony na **podgląd** (skan kodu paczki → karta statusu, bez modyfikacji danych)
- `paczki.html` — kolumna **Double rate** z checkboxem per paczka
- `general_stats.html` — druga, **żółta linia (2×)** dla linii z paczkami double rate: Amounts auto z sumy Stückzahl, kategorie wpisywane ręcznie; obie linie ×1 (podwojenie z policzenia paczek dwa razy)
- Eksport `.xlsx` — zawiera żółte wiersze double rate
- **Statystyki** — przetworzone (zakończone) paczki liczą się automatycznie jako pozycje `📦 Paczki` (liczba) i `📦 Paczki (szt.)` (suma Stückzahl), atrybucja po dacie zakończenia (`scan_end_by`/`scan_end_at`); wiersze read-only, pomijane w wykresie dziennym i przy filtrze pojedynczej czynności
- **Dashboard dzienny** — ujednolicona metodologia: wszystkie metryki paczek (Zrobione dziś, Postęp całkowity, breakdown i per-pracownik) liczone z **zakończonych** paczek (`scan_end`), spójnie ze Statystykami. „Per pracownik" pokazuje obecnych na zmianie **oraz** każdego, kto dziś zakończył paczki. *(Uwaga: postęp całkowity liczy teraz tylko paczki z zarejestrowanym Końcem.)*
- **Sidebar** — nawigacja pogrupowana w 6 sekcji (Przegląd, Zmiana, Paczki, Czas pracy, Rozliczenia (CSV, admin), Administracja) zamiast płaskiej listy; moduły paczkowe/czasowe razem; rozróżnione ikony; „Skan paczek" → „Paczki inspektor", „Paczki" → „Paczki (dane)"

## [1.5.0] — 2026-04-24

### Forecast, Czasy paczek, dokumentacja DB/infra

#### Backend
- Model `Forecast` (prognoza ilości per dzień) + endpointy CRUD
- `ImportedCarton.scan_start_at/by`, `scan_end_at/by` — pomiar czasu procesowania paczki
- `POST /api/package-time/start`, `POST /api/package-time/end` — rejestracja startu i końca; `processing_seconds()` = koniec − start

#### Frontend
- `/forecast` — ekran prognozy
- `/scan-paczki` („Czasy paczek") — zakładki 🟢 Start / 🔴 Koniec paczki
- `paczki.html` — kolumny Start / Koniec / Czas procesowania
- Scroll sidebara przy dużej liczbie pozycji

#### Dokumentacja / infra
- `docs/DATABASE_SPEC.md`, `docs/postgres_schema.sql`, `docs/nginx-logistat.conf`

## [1.4.0] — 2026-04-20

### Skanowanie paczek, Dashboard dzienny, Czas pracy

#### Backend — nowe modele
- `ImportedCarton.processed_by` + `processed_at` — przypisanie pracownika do paczki
- `GeneralStat.double_rate` — flaga podwójnej stawki per wiersz
- `WorkerTimeEvent` — rejestracja czasu pracy: `break_start`, `break_end`, `work_end`
- Automatyczna migracja kolumn (`migrate_columns()`) — nowe kolumny dodawane bez kasowania bazy
- `db.create_all()` + `seed_data()` przeniesione na poziom modułu (działa z Gunicorn)

#### Backend — nowe endpointy
- `POST /api/scan-package` — przypisanie paczki do pracownika (błąd 409 jeśli już przypisana)
- `POST /api/scan-employee` — weryfikacja kodu pracownika
- `PUT /api/packages/<id>/assign` — przepisanie paczki przez lidera
- `GET /api/dashboard` — dane dziennego dashboardu (paczki, czynności, per pracownik)
- `GET /general-stats/export` — eksport statystyk ogólnych do pliku `.xlsx` (openpyxl)
- `POST /api/time/scan` — skanowanie przerwy / końca pracy
- `GET /api/worker-times` — zestawienie czasów per pracownik dla wybranej daty
- `POST/PUT/DELETE /api/worker-times/event` — ręczne korekty zdarzeń przez lidera

#### Frontend — nowe ekrany
- `/scan-package` — naprzemienne skanowanie: pracownik → paczka → pracownik → paczka
- `/dashboard` — dzienny dashboard z zakładkami: Podsumowanie + Per pracownik
- `/time-tracking` — skanowanie przerw i końca pracy (zakładki ☕ / 🏁)
- `/worker-times` — moduł liderski: przegląd i korekta czasów pracy

#### Frontend — zmiany w istniejących ekranach
- `paczki.html` — kolumna Pracownik + przycisk ✎ do przepisania (modal z dropdownem)
- `paczki.html` — dostępna teraz dla liderów (poprzednio tylko admin)
- `general_stats.html` — kolumna Double Rate (checkbox, natychmiastowy zapis, tło ×2)
- `general_stats.html` — przycisk ⬇ Excel eksportujący aktualnie odfiltrowany zakres
- `worker_times.html` — wiersze z przerwą >30 min podświetlone na czerwono
- `base.html` — nowe pozycje w sidebarze: Dashboard, Paczki (dla liderów), Skan paczek, Czas pracy, Czasy pracowników

## [1.3.0] — 2026-03-06

### Rozszerzenie Statystyk i Moduł Paczki

#### Backend
- Nowy model `CostMapping` z cennikiem kosztów per `year` i `month`.
- Endpoint docelowy `/admin/cost-mapping` do zarządzania stawkami w Panelu Admina.
- Moduł `Paczki` (raw view) i endpoint `GET /paczki` obsługujący paginację oraz zaawansowane filtry `date_from, date_to, barcode, land`.
- Automatyczne wyznaczanie domyślnego zakresu filtrowania od pierwszego do ostatniego dnia obecnego miesiąca w `General Stats`.

#### Frontend
- Widok edycji stawek w `admin_cost_mapping.html` dla 10 kategorii wraz z opcją szybkiego kopiowania stawek z poprzedniego miesiąca.
- W `general_stats.html` całkowite usunięcie masowego modyfikowania stawek kosztów. Zamiast tego zaimplementowano readonly inputy dla kosztów autowyliczane na bieżąco za pomocą przemnożenia zsumowanych kategorii przez stawki przypisane do odpowiedniego miesiąca i roku.
- W formularzu "Statystyki ogólne" dodanie dynamicznej kolumny *Total Amount*. Zlicza na bieżąco ilości i ich aktualny stan względem importowanych statystyk.
- Poprawiony, wyrazisty design kolorystyczny dla kolumn kwot, ilości i łącznych zysków.
- Nowa przeglądarka `paczki.html` (widok surowych zaimportowanych paczek CSV z nowymi filtrami). Przypięto w sidebarze do sekcji Admina (`📦 Paczki`).

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
