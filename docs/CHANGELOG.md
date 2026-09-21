# LogiStat — Changelog

## 2026-09-21 — filtry dat na Paczkach, wymuszony zakres przy „pokaz zrobione"

### Dodane — Paczki (dane)
- **Wybor pola daty (`date_typ`)** przed zakresem dat. Do tej pory zakres dzialal
  wylacznie po `Ziel-Datum`, przez co paczki o `Ziel-Datum` niezgodnym z dniem
  skanowania wypadaly z widoku — wygladalo to, jakby filtr pracownika gubil ludzi.
  Do wyboru: **Ziel-Datum** (domyslne), **Data importu** (`imported_at`),
  **Start paczki** (`scan_start_at`), **Koniec paczki** (`scan_end_at`).
- Trzy nowe pola to naive-UTC `DateTime`, wiec granice doby licza sie przez
  `local_day_bounds()` — ta sama definicja „dnia", co na dashboardzie i statystykach.
  Gorna granica jest **polotwarta** (`<` polnoc nastepnej doby lokalnej); `<=`
  wciagaloby paczki z pierwszych godzin kolejnego dnia. Nieznane `date_typ` → `ziel`.
- **`date_typ=koniec` zdejmuje domyslne „tylko niezrobione"** — warunek
  `scan_end_at w zakresie` AND `scan_end_at IS NULL` to zawsze zbior pusty, wiec ekran
  wygladalby na zepsuty. Ta sama logika, co przy filtrze bledow. **`date_typ=start`
  celowo go nie zdejmuje** (= „rozpoczete w zakresie i wciaz otwarte").

### Zmienione — Paczki (dane)
- **„Pokaz zrobione" wymaga teraz zakresu dat.** Bez niego widok obejmowal cala
  historie (na `.31` ponad 5000 paczek). JS blokuje wyslanie formularza; warunek na
  serwerze lapie recznie sklejony URL i zakladke — parametr jest ignorowany, a strona
  mowi dlaczego. To strona Jinja, nie `/api/`, wiec bez `abort()`.
- Etykieta filtra pracownika: **„— wszyscy pracownicy —"** zamiast „— pracownik —".
  Zachowanie bez zmian — puste pole nigdy nie zawezalo wynikow; mylaca byla etykieta.
- Checkbox „pokaz zrobione" zaznacza sie sam przy filtrze po dacie konca, zeby nie
  klocil sie z tym, co widac na liscie.

### Testy
- `tests/test_filtry_paczek.py`: 28 testow (bylo 17) — **324 w calym zestawie**.
  Nowe pokrycie: wymuszenie daty, obie granice doby, kazdy `date_typ`, fallback
  nieznanej wartosci, zachowanie `date_typ` przy stronicowaniu oraz regresja
  zgloszonego objawu (paczki dwoch pracownikow z `Ziel-Datum` poza zakresem, widoczne
  po dacie konca bez wybierania osoby).
- `test_pokaz_zrobione_dokłada_zakonczone` wolal endpoint bez daty — czyli to, co
  teraz zabraniamy. Dostal zakres, a obok doszedl test pilnujacy, ze wersja bez daty
  **nie** pokazuje zrobionych.
- Asercja komunikatu o braku daty szukala frazy `wymaga zakresu dat`, ktora wystepuje
  **takze w komentarzu bloku `<script>`** w `paczki.html` — test przechodzil zawsze,
  takze po usunieciu komunikatu. Teraz sprawdza fraze unikalna dla komunikatu.

## 2026-09-18 — filtry czasow i paczek, Total Amount z Labelling one, „Inne"

### Zmienione — rozliczenia
- **`Total Amount` w Statystykach ogolnych liczy sie WYLACZNIE z `Labelling one`**
  (`TOTAL_AMOUNT_CATEGORY`), zamiast sumowac wszystkie kategorie. Jedna sztuka
  przechodzi przez kilka czynnosci, wiec suma liczyla ten sam towar wielokrotnie
  i potrafila przebic `Amounts`. Zmiana dotyczy ekranu, przeliczania w JS po edycji
  i eksportu Excel — koszty (`cost = amount x rate`) sa nietkniete.
- **Zolty wiersz double rate ZOSTAJE na sumie wszystkich kategorii** — swiadoma
  niespojnosc, do ustalenia z operacja (`docs/TODO.md`). `write_data_row()` dostal
  flage `is_double_rate`.
- Naglowek `Total Amount` i `Amounts` maja dymek (ⓘ) tlumaczacy, skad biora sie
  liczby: `Amounts` = suma Stueckzahl z importu, `Total Amount` = ilosci wpisane
  przy zakonczeniu paczki.

### Dodane — czas pracy
- **Tryb „Inne"** na ekranie Czas pracy (np. wyjscie do HR): zdarzenia
  `other_start` / `other_end`. Liczy sie **jak przerwa** — pomniejsza czas pracy —
  ale jest raportowany osobno (`other_minutes`, kolumna „Inne").
- Przerwa i „Inne" nie moga trwac jednoczesnie (409), bo ten sam czas zostalby
  odjety dwa razy. `work_end` domyka **oba** otwarte okresy. Reczna korekta na
  `/worker-times` te blokade omija, wiec czas pracy odejmuje **sume zlaczonych
  okresow** (`suma_zlaczonych_okresow()`), a nie sume ich dlugosci — inaczej
  nachodzaca przerwa i „Inne" zanizylyby czas pracy.
- **Czasy pracownikow: filtr po pracowniku + „⚠️ Tylko bledy"** (czas pracy ponad
  progiem, brak przerwy, przerwa ponizej progu). Oba filtry dzialaja na danych juz
  pobranych z `/api/worker-times` — bez zmian w API. Brak/za krotka przerwa licza
  sie **dopiero po zarejestrowaniu konca pracy**, zeby trwajaca zmiana nie
  swiecila sie na czerwono.
- Nowe ustawienia admina (`/admin/settings`): `max_work_minutes` (660) i
  `min_break_minutes` (15) — obok istniejacego `break_threshold_minutes`.

### Dodane — Paczki (dane)
- Filtry: **po pracowniku** (kto przejal / rozpoczal / zakonczyl), **tylko double
  rate**, **pokaz zrobione**, **⚠️ pokaz bledy**.
- **Domyslnie widac tylko paczki niezrobione** (bez `scan_end_at`). Zakonczone
  pokazuje dopiero „pokaz zrobione".
- Filtr bledow: paczka rozpoczeta i nigdy nie zakonczona **albo** ilosc w kategorii
  przekraczajaca `stueckzahl` o ponad 10% (`TOLERANCJA_ILOSCI`). Porownanie idzie
  w Pythonie, bo ilosci ze skanu to JSON w kolumnie tekstowej (JSONB jest zakazany)
  — stad `StroniceLista`, stronicowanie w pamieci z API `Pagination`.
- **`POST /api/packages/<id>/unlock-scan`** (lider+, przycisk 🔓 Odblokuj) — kasuje
  start skanu paczki rozpoczetej i nigdy nie zakonczonej. Bez tego paczka zostawala
  zablokowana na zawsze: nalezy do pracownika, ktory ja zaczal, wiec inny dostawal
  409 przy starcie i 403 przy koncu. Na bazie testowej wisialo tak 5 paczek,
  najstarsza od tygodnia. Paczki **zakonczonej** nie da sie odblokowac (409).

### Dodane — tlumaczenia
- Kategorie ilosci maja dwuczlonowe etykiety na ekranach
  (`Labelling one — Etykietowanie pojedyncze`) — `STAT_CATEGORY_LABELS_PL`
  + `etykieta_kategorii()`. **Naglowki eksportu Excel zostaja po angielsku**,
  bo to artefakt rozliczeniowy wychodzacy na zewnatrz.

### Testy
- `tests/test_total_amount.py`, `tests/test_czas_inne.py`,
  `tests/test_filtry_paczek.py`, `tests/test_progi_bledow.py` — 307 testow.
- Zadnej nowej kolumny w bazie, wiec `migrate_columns()` bez zmian.


## 2026-09-11 — tylko PostgreSQL, ilosci per kategoria ze skanu, menu wg rol

### Zmienione — baza
- **SQLite nie jest juz wspierany.** Kod obslugi zostal USUNIETY, nie tylko odradzony:
  `_set_sqlite_pragmas` (WAL + busy_timeout), `_sqlite_init_lock` (flock), galaz
  SQLite w `migrate_columns()` i `init_db()`, importy `sqlite3` / `fcntl`.
- **`DATABASE_URL` jest wymagany** — `resolve_database_url()` rzuca przy starcie, gdy
  zmiennej brak albo wskazuje `sqlite://`. Wczesniej cichy fallback zapisywal dane do
  pliku obok kodu, ktorego nikt nie backupuje.
- **`SECRET_KEY` wymagany zawsze** (nie tylko "gdy jest DATABASE_URL") — kazde
  srodowisko jest teraz serwerowe.
- `docker-compose.yml` dostal usluge **`db`** (postgres:16-alpine, bez portu na hoscie)
  i `.env` / `.env.example` na sekrety. **Uwaga:** Compose interpoluje `${...}` w kazdym
  pliku OSOBNO, przed scaleniem overrida — dlatego plik bazowy NIE uzywa skladni
  wymaganej `${X:?}`, bo `.31` nie ma `.env` i taki zapis wysadzilby mu deploy.
- Testy chodza na Postgresie (`docker-compose.test.yml`, port 55432, tmpfs).
  `tests/test_init_race.py` tworzy wlasna baze przez `CREATE DATABASE`.

### Poprawione
- **`migrate_columns()` nie dzialal na Postgresie** — blok `ALTER` byl pod `is_sqlite`,
  a `create_all()` nigdy nie dokłada kolumny do istniejacej tabeli. Nowe kolumny nie
  powstalyby na `.31` i kazde zapytanie na modelu konczyloby sie `UndefinedColumn`.
  Zwykle testy tego nie widza (conftest stawia schemat od zera) — stad
  **`tests/test_migracje.py`**, ktory kasuje kolumne i sprawdza, czy wraca.
- **Pierwszy skan kasowal reczne rozliczenie linii** (120 sztuk -> 6). Linia z
  niezerowymi recznymi iloscami nie przelacza sie sama; ilosci ze skanu i tak zapisuja
  sie na kartonie, a zamiany dokonuje admin przyciskiem **-> uzyj skanow**.
- `scan_coverage_map()` ciagnal cala tabele kartonow przy kazdym otwarciu rozliczen —
  przepisane na `GROUP BY`.
- **Brak access logow** — gunicorn startowal bez `--access-logfile`, 9 dni pracy
  zostawialo 71 linii logu. Doszly logi dostepu, `gthread` (koniec `WORKER TIMEOUT`
  na cichych gniazdach), `--timeout 120` i rotacja `json-file` 10 MB x 5.

### Dodane
- **Ilosci per kategoria przy skanie konca paczki.** Skan loginu -> skan paczki ->
  panel z 9 kategoriami i pokazana iloscia sztuk w paczce. Ilosci lecą na
  `ImportedCarton.scan_category_data` i przez `recompute_general_stat(from_scan=True)`
  staja sie zrodlem `GeneralStat.category_data`, czyli kosztu.
  `GeneralStat.category_source` (`manual`/`scan`) rozdziela linie reczne od skanowanych.
- `PUT /api/packages/<id>/categories` — korekta ilosci przez lidera, takze dla paczek
  z importu (wczesniej pomylki w takiej paczce nie dalo sie naprawic).
- Licznik pokrycia skanami w Statystykach ogolnych (`3/50`), zeby nikt nie wzial
  polowicznie zeskanowanej linii za gotowa.
- **Import CSV/Excel dostepny dla lidera** (byl admin-only).
- **Menu w 3 grupach** wg tego, kto obsluguje ekran: Pracownik / Lider / Admin.
  Naglowki siedza w tym samym warunku roli co pozycje — lider nie widzi juz pustego
  naglowka "Administracja".

### Usuniete
- Kategoria `carton_labeling` (0 wierszy z niezerowa wartoscia na dev i na tescie).
  Etykiety: `Labelling one` / `twice` / `triple`. `GeneralStat.to_dict()` iteruje po
  `STAT_CATEGORIES`, wiec usunieta kategoria nie doliczy sie z historycznego JSON-a.

## 2026-09-01 — przeglad kodu: uprawnienia, doba lokalna, sprzatanie

### Poprawione
- **Eskalacja uprawnien**: lider mogl przez `/api/users` zalozyc konto admina,
  podniesc sobie role albo przestawic haslo adminowi. Guardy na role + walidacja
  + ochrona ostatniego aktywnego admina.
- **Soft-delete nie odbieral dostepu**: `login()` nie sprawdzal `is_active_user`,
  a `load_user()` nie uniewazniał trwajacej sesji. Teraz jedno i drugie.
- **Doba lokalna**: dashboard liczyl granice dnia z `date.today()`, a
  `api_stats_user` grupowal po `func.date()` w UTC — ta sama paczka wypadala na
  roznych dniach na dwoch ekranach. Nowe `local_today()` / `local_day_bounds()`
  (DST z ZoneInfo) uzywane wszedzie; praca II zmiany po polnocy liczy sie do
  wlasciwej doby.
- **Konfiguracja**: SECRET_KEY fail-fast w trybie serwerowym, MAX_UPLOAD_MB +
  413 jako JSON, SameSite=Lax (zamyka CSRF na multipartowym `/api/import-csv`),
  ADMIN_PASSWORD dla seeda, dev server domyslnie na 127.0.0.1.

### Usuniete (martwy kod)
- `POST /api/scan-package` — wycofane przypisanie paczka->pracownik
- `POST /api/scan-employee` — bez konsumenta
- `PUT /api/packages/uebergabe-double-rate` — jedyny writer legacy kolumny
- `GeneralStat.double_rate` — legacy flaga per linia; zolty wiersz jedzie na
  `double_rate_amount_map()`, nie na tej kolumnie
- `GeneralStat.total_cost()` — nieuzywana, liczyla koszt z nieaktualnego klucza
  `cost` (sprzecznie z `to_dict()`, ktore bierze stawki z `CostMapping`)

### Dodane
- `tests/` — pierwsze testy w projekcie, nacisk na sciezki rozliczeniowe


## [1.8.0] — 2026-08-31

### PostgreSQL na środowisku testowym

Powód: SQLite serializuje pisarzy, a przy dwóch zmianach kilku liderów skanuje jednocześnie
przez VPN — to kończy się `database is locked`. Rozmiar nie był argumentem (patrz niżej).

- **`DATABASE_URL` wybiera silnik**; bez zmiennej zostaje `sqlite:///logistat.db`, więc dev
  jest nietknięty, a rollback to usunięcie zmiennej
- `psycopg2-binary` w `requirements.txt`
- Schemat na obu silnikach z `db.create_all()` — **nie** z `docs/postgres_schema.sql`
  (jego `JSONB` psuje `json.loads` w `get_category_data()`, a `DEFAULT NOW()` wpisuje czas
  lokalny serwera do kolumn czytanych jako naive UTC)
- Test (`10.153.1.31`): własny kontener `logistat-test-db` (`postgres:16-alpine`), bez portu
  na hoście, healthcheck `pg_isready -U logistat -d logistat`, `app` czeka na `service_healthy`

#### Naprawione różnice między silnikami

- **`func.date()`** zwraca `str` na SQLite, a `datetime.date` na Postgresie — `api_stats_user`
  wywalał się na `d[:7]`. Ujawnia się tylko gdy pracownik ma zakończone paczki
- **Wyścig przy pierwszym boocie na pustej bazie:** oba workery gunicorna wchodziły w
  `db.create_all()` naraz, przegrany padał na `UniqueViolation ... pg_class (user_id_seq)`
  i gunicorn wyłączał mastera; maskował to `restart: always`. Dodane `init_db()` z
  `pg_advisory_lock(5001)`
- **`pool_pre_ping`** — po restarcie kontenera bazy workery trzymały martwe połączenia
  i pierwsze żądanie zwracało 500 (`server closed the connection unexpectedly`)
- **`migrate_columns()`** — blok `ALTER TABLE` tylko dla SQLite (`db.engine.dialect.name`),
  blok `CREATE INDEX` na obu; `except` robi `conn.rollback()`, bo na Postgresie nieudane
  zapytanie psuje całą transakcję

Wszystkie `GROUP BY` były już zgodne ze strict-mode Postgresa, a każdy handler
`IntegrityError` już robił `rollback` — tam nie było co zmieniać.

### SQLite: WAL + busy_timeout

- `_set_sqlite_pragmas` (listener `connect` na `Engine`): `journal_mode=WAL`,
  `busy_timeout=5000`; no-op dla nie-SQLite, więc Postgres nietknięty
- ⚠️ WAL dokłada `logistat.db-wal` / `-shm` — **backup nie może być zwykłym `cp`**;
  trzeba `sqlite3.Connection.backup()` albo `VACUUM INTO`

### Backupy i wdrożenie

- `scripts/backup-logistat.sh` — `pg_dump --clean --if-exists`, gzip, retencja 14 dni,
  kontrola kompletności zrzutu (`gzip` w potoku sam by błędu nie zgłosił). Cron 22:30 na `.31`
- `docs/DEPLOY.md` — środowiska, publikacja, pierwsze wdrożenie, aktualizacja kodu, baza,
  backupy, znane zachowania
- `docker-compose.override.example.yml` — wzór konfiguracji środowiska; prawdziwy plik jest
  w `.gitignore`, dzięki czemu aktualizacja kodu nie nadpisuje konfiguracji serwera

### Domena

- `https://logistat-test.logwin-logistics.com.pl/` działa. IT opublikowało nazwy przez
  **Cloudflare**, a nie przez firmowe proxy `10.15.12.67` z `docs/IT_REQUEST.md`
- Cloudflare Access przed tymi nazwami nie stoi — do potwierdzenia przez IT zostaje tylko
  reguła WAF / allowlista IP. Własny Nginx i certyfikat niepotrzebne
- `ProxyFix` niepotrzebny — Werkzeug zwraca relatywny `Location`

### Zmierzony rozmiar bazy (SQLite vs PostgreSQL)

Ten sam zestaw danych po obu stronach: `imported_carton` 278 B/wiersz w SQLite vs **248 B
w Postgresie** (Postgres mniejszy — SQLite trzyma DATETIME jako 26-znakowy TEXT),
`worker_time_event` 77 → 128 B, `daily_stat` 63 → 138 B, `general_stat` 648 → 899 B.
Cały zestaw 41,6 MB vs 56 MB (≈ ×1,35). Realnie **~50–90 MB/rok** plus 38,6 MB pustego
klastra i `pg_wal` do 1 GB. Szczegóły w `docs/DATABASE_SPEC.md`.

## [1.7.0] — 2026-07-18

### Konfigurowalny próg przerwy

- Nowa tabela `AppSetting` (klucz/wartość) + helpery `get_setting`/`get_setting_int`/`set_setting`
- `GET /admin/settings` + `PUT /api/settings` (admin) — edycja progu przerwy (klucz `break_threshold_minutes`, domyślnie 30, walidacja ≥ 1)
- `/worker-times` czyta próg z ustawień (`BREAK_THRESHOLD` w JS, podpis w nagłówku) zamiast zahardkodowanego 30
- Karta „⚙️ Ustawienia" w panelu admina

### Poprawka: spójne wyświetlanie czasu (Europe/Warsaw)

**Problem:** czasy zapisywane są w UTC (poprawnie), ale wyświetlały się niespójnie — rekordy pokazywały UTC (2h za zegarem PL latem), a potwierdzenia „na żywo" po skanie prawdziwy czas lokalny. Przyczyna: API zwracało czasy przez `isoformat()` **bez sufiksu `Z`**, więc `new Date()` w przeglądarce traktował je jako lokalne (bez konwersji), a szablony renderowały UTC wprost.

**Rozwiązanie** (zapis dalej w UTC, wyświetlanie Europe/Warsaw, odporne na DST):
- Helper `iso_z()` — serializuje datetime z jawnym `Z` (tylko pola datetime; pola DATE bez zmian)
- Filtr Jinja `localdt('%fmt')` — konwertuje naive-UTC → Europe/Warsaw dla czasów renderowanych serwerowo (paczki: start/koniec/import/edycja; skaner: obecność)
- `as_of` na dashboardzie w czasie lokalnym (usunięto etykietę „UTC")
- Naprawia też **dryf przy ręcznej edycji czasów pracy** (`/worker-times`): stara wersja przy każdym zapisie przesuwała czas o −2h; round-trip zweryfikowany (silnik V8, strefa Warszawa) — brak dryfu

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
