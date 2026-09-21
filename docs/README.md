# LogiStat — Workforce Management System

System do zarządzania pracownikami, przydzielania czynności i śledzenia statystyk wydajności.

## Stack technologiczny

| Warstwa | Technologia |
|---------|-------------|
| Backend | Python 3.11 (obraz Docker) + Flask 3.1 |
| Baza danych | PostgreSQL 16 (wszystkie środowiska) — `DATABASE_URL` wymagany |
| Autentykacja | Flask-Login |
| Frontend | Vanilla HTML/CSS/JS + Chart.js |
| Deploy | Docker + Gunicorn |

## Uruchomienie lokalne

```bash
cd /opt/LogiStat
pip install -r requirements.txt
DATABASE_URL=postgresql+psycopg2://logistat:haslo@127.0.0.1:5432/logistat \
  SECRET_KEY=$(python3 -c 'import secrets;print(secrets.token_hex(32))') python app.py
# → http://localhost:5001
```

Obie zmienne są **wymagane** — bez nich aplikacja rzuca wyjątkiem przy starcie,
zamiast po cichu pisać do pliku, którego nikt nie backupuje (`resolve_database_url()`,
`resolve_secret_key()`). Potrzebny jest działający PostgreSQL.

## Uruchomienie Docker

```bash
docker compose up --build -d
# → http://localhost:5001
```

Aplikacja wymaga PostgreSQL i `SECRET_KEY` — `docker compose up` podnosi bazę razem
z aplikacją, wystarczy skopiować `.env.example` do `.env` i wpisać klucz. Wdrożenie na
serwer (domena, backupy) opisuje **`docs/DEPLOY.md`**.

## Testy

```bash
pip install -r requirements-dev.txt
pytest                       # 354 testów
```

Ten sam zestaw można przejechać po Postgresie (tak chodzi test i produkcja):

```bash
LOGISTAT_TEST_DATABASE_URL=postgresql+psycopg2://user:hasło@host:5432/baza pytest
```

Pokrycie jest celowo skupione na tym, co dotyczy pieniędzy — agregacji importu,
`recompute_general_stat`, double rate i wyliczaniu kosztów — oraz na uprawnieniach,
granicach doby i walidacji wejścia. Zestaw przechodzi pod `TZ=UTC`, `Europe/Warsaw`
i `America/New_York`.

## Środowiska

| Środowisko | Adres | Baza |
|---|---|---|
| dev (`10.153.1.32`) | `http://10.153.1.32:5001` | PostgreSQL 16 |
| test (`10.153.1.31`) | `https://logistat-test.logwin-logistics.com.pl/` | PostgreSQL 16 |
| prod (`10.153.1.30`) | `https://logistat-prod.logwin-logistics.com.pl/` | *(nie wdrożone)* |

## Domyślne konto

| Login | Hasło | Rola |
|-------|-------|------|
| admin | admin123 | admin |

> Hasło konta `admin` ustawia się zmienną `ADMIN_PASSWORD` **przed pierwszym startem**
> (patrz `docs/DEPLOY.md`). Bez niej seed używa `admin123` i wypisuje ostrzeżenie w logu.

> ⚠️ Zmień hasło admina po pierwszym logowaniu!

## Struktura projektu

```
LogiStat/
├── app.py                  # Cały backend (modele, API, routing)
├── requirements.txt        # Zależności Python
├── requirements-dev.txt    # + pytest (testy)
├── pytest.ini              # Konfiguracja testów
├── Dockerfile              # Obraz Docker
├── docker-compose.yml      # Docker Compose (port 5001)
├── docker-compose.override.example.yml  # Wzór konfiguracji środowiska (hasła, Postgres)
├── scripts/
│   └── backup-logistat.sh  # Kopia zapasowa (pg_dump, retencja 14 dni)
├── tests/                  # pytest — nacisk na ścieżki rozliczeniowe
│   ├── conftest.py             # Fixtures: czysta baza na test, klienci z rolami
│   ├── test_import_aggregation.py  # Agregacja importu, dedup
│   ├── test_recompute.py           # recompute_general_stat (suma, nie delta)
│   ├── test_double_rate_i_koszty.py # Żółta linia + amount × stawka
│   ├── test_scan_categories.py     # Ilości ze skanu → rozliczenie, category_source
│   ├── test_total_amount.py        # Total Amount = Labelling one (ekran + eksport)
│   ├── test_packages_api.py        # Ręczne dodanie/edycja paczki
│   ├── test_package_times.py       # Blokada właściciela paczki
│   ├── test_filtry_paczek.py       # Filtry /paczki (daty, osoba, błędy) + odblokowanie
│   ├── test_czas_inne.py           # Tryb „Inne" i złączanie okresów
│   ├── test_przeglad_pracownikow.py # Ranking wydajności zespołu (szt./h)
│   ├── test_progi_bledow.py        # Progi filtra błędów (ustawienia admina)
│   ├── test_permissions.py         # Guardy ról, is_active_user
│   ├── test_day_boundary.py        # Doba lokalna vs UTC (DST)
│   ├── test_validation.py          # Błędne wejście → 400, nie 500
│   ├── test_performance.py         # Licznik SELECT-ów (regresje N+1)
│   ├── test_xss.py                 # Escapowanie + reguła statyczna po szablonach
│   ├── test_smoke_pages.py         # Każda strona się renderuje
│   ├── test_config.py              # SECRET_KEY, limit uploadu, ciasteczka
│   ├── test_migracje.py            # Nowa kolumna wraca przez migrate_columns()
│   └── test_init_race.py           # Równoległy start workerów na pustej bazie
├── docker-compose.yml      # Aplikacja + PostgreSQL
├── docker-compose.test.yml # PostgreSQL pod pytest (port 55432, tmpfs)
├── .env.example            # Wzor konfiguracji lokalnej (SECRET_KEY, haslo bazy)
├── static/
│   └── style.css           # Design system (dark theme)
├── templates/
│   ├── base.html           # Layout + sidebar + toasty
│   ├── login.html          # Logowanie liderów/adminów
│   ├── scanner.html        # Skaner kodów kreskowych
│   ├── assignment.html     # Drag & drop przydzielanie
│   ├── data_entry.html     # Wpis ilości
│   ├── stats.html          # Dashboard statystyk
│   ├── admin_activities.html # CRUD czynności
│   ├── admin_users.html    # Zarządzanie użytkownikami
│   ├── admin_panel.html    # Panel Admina (hub)
│   ├── admin_country_mapping.html # Mapowanie krajów
│   ├── admin_cost_mapping.html # Stawki kosztów per rok/miesiąc
│   ├── admin_settings.html # Ustawienia (progi czasu pracy)
│   ├── import_csv.html     # Importowanie pliku CSV
│   ├── general_stats.html  # Statystyki ogólne z CSV (+ żółta linia double rate)
│   ├── paczki.html         # Surowe paczki CSV (+ filtry dat, double rate, odblokowanie)
│   ├── scan_package.html   # Skan paczek — podgląd statusu (read-only)
│   ├── scan_paczki.html    # Czasy paczek — Start/Koniec
│   ├── dashboard.html      # Dashboard dzienny
│   ├── time_tracking.html  # Czas pracy (przerwa / Inne / koniec)
│   ├── worker_times.html   # Czasy pracowników (korekty + filtry)
│   ├── forecast.html       # Prognoza ilości
│   └── profile.html        # Zmiana hasła
└── docs/
    ├── README.md           # Ten plik
    ├── API.md              # Dokumentacja API (pełne pokrycie endpointów)
    ├── DATABASE_SPEC.md    # Schemat bazy, wolumen, reguły biznesowe
    ├── DEPLOY.md           # Procedura wdrożenia + zmienne środowiskowe
    ├── CHANGELOG.md        # Historia zmian
    ├── TODO.md             # Co zostało do zrobienia
    ├── IT_REQUEST.md       # Zgłoszenie do IT (domeny, porty)
    └── nginx-logistat.conf # Konfiguracja Nginx (zapas — dziś idzie przez Cloudflare)
```

## Role użytkowników

| Rola | Uprawnienia |
|------|-------------|
| **operator** | Skanuje się na zmianę. **Nie loguje się.** |
| **leader** | Loguje się hasłem. Skaner zmian, przydzielanie, wpis ilości, czasy paczek, czasy pracowników, **import CSV/Excel**, zakładanie operatorów. |
| **admin** | Wszystko + Statystyki ogólne, czynności, Panel Admina (mapowanie krajów, stawki kosztów, ustawienia), zakładanie i edycja kont lidera/admina. |

> Konto lidera lub admina może założyć, edytować, zdezaktywować albo zmienić mu rolę
> **wyłącznie admin** — lider dostanie `403`. Zdegradowanie lub dezaktywacja
> **ostatniego aktywnego admina** jest odrzucane (`400`).

## Ekrany aplikacji (struktura menu)

Sidebar jest pogrupowany **wg tego, kto obsługuje ekran**, a nie wg uprawnień — te dwie
rzeczy potrafią się różnić (np. „Czasy paczek" stoi pod Pracownikiem, ale wymaga
zalogowanego lidera, bo to ekran stanowiskowy).

### 👷 Pracownik
- 📷 **Skaner zmian** (`/scanner/1`, `/scanner/2`) — rejestracja obecności, EAN-128
- 🕐 **Czas pracy** (`/time-tracking`) — skan kodu pracownika: ☕ przerwa · 🚪 **Inne** · 🏁 koniec pracy
- ⏱ **Czasy paczek** (`/scan-paczki`) — Start/Koniec procesowania + ilości per kategoria przy końcu
- 🔎 **Paczki inspektor** (`/scan-package`) — podgląd statusu paczki, **tylko do odczytu**

### 🧑‍💼 Lider
- 🏠 **Dashboard** (`/dashboard`) — podsumowanie dnia, per pracownik, per zmiana
- 📈 **Forecast** (`/forecast`) — prognoza ilości per dzień
- 📋 **Przydzielanie** (`/assignment`) — drag & drop operatorów do czynności
- ✏️ **Wpis ilości** (`/data-entry`) — ilości zrobione per osoba
- 📊 **Statystyki** (`/stats`) — przegląd całego zespołu (ranking szt./h, cel lidera) + wykresy per pracownik
- 📦 **Paczki (dane)** (`/paczki`) — surowe dane paczek z filtrami (patrz niżej)
- 👥 **Czasy pracowników** (`/worker-times`) — przegląd i korekta czasów + filtry
- 📥 **Import danych** (`/import-csv`) — CSV (`;`) lub Excel (`.xlsx`), dedup po barcode
- 👤 **Użytkownicy** (`/admin/users`) — zakładanie i edycja kont

### 🛡️ Admin
- 💶 **Statystyki ogólne** (`/general-stats`) — rozliczenie wg list i dat + eksport Excel
- ⚙️ **Czynności** (`/admin/activities`) — zarządzanie czynnościami
- 🛡️ **Panel Admina** (`/admin/panel`) — hub: mapowanie krajów (`/admin/country-mapping`),
  stawki kosztów (`/admin/cost-mapping`), ustawienia (`/admin/settings`)

### Stopka sidebara
- 🔑 **Zmiana hasła** (`/profile`) · **Wyloguj**

## Jak działają kluczowe ekrany

### Czasy pracowników — filtry i błędy
Poza wyborem daty są dwa filtry, oba liczone w przeglądarce na danych już pobranych
(API ich nie przyjmuje, więc definicja „błędu" jest jedna):

- **filtr po pracowniku** — lista zawiera tylko osoby obecne w wybranym dniu,
- **⚠️ Tylko błędy** — czas pracy ponad progiem, brak przerwy, przerwa poniżej progu.

Brak przerwy i za krótka przerwa liczą się **dopiero po zarejestrowaniu końca pracy** —
pracownik, który wszedł godzinę temu, jeszcze nie ma przerwy i nie jest to pomyłka.

Progi ustawia admin w `/admin/settings`:

| Ustawienie | Domyślnie | Znaczenie |
|---|---|---|
| `break_threshold_minutes` | 30 | przerwa dłuższa → ⚠️ na czerwono |
| `max_work_minutes` | 660 (11 h) | czas pracy powyżej → błąd |
| `min_break_minutes` | 15 | krótsza (lub żadna) przerwa → błąd |

### Czas pracy — tryb „Inne"
Trzeci tryb obok przerwy i końca pracy, na wyjścia inne niż przerwa (np. do HR).
**Pomniejsza czas pracy tak samo jak przerwa**, ale jest raportowany osobno — operacja
rozlicza te dwie rzeczy inaczej. Przerwa i „Inne" nie mogą trwać jednocześnie, a skan
końca pracy domyka oba otwarte okresy. Ręczna korekta zdarzeń potrafi stworzyć okresy
nachodzące na siebie, dlatego czas pracy odejmuje **sumę złączonych okresów**, a nie
sumę ich długości.

### Paczki (dane) — filtry i odblokowanie
**Domyślnie widać tylko paczki niezrobione** (bez zarejestrowanego „Końca paczki").
Filtry: **typ daty + zakres dat**, barcode, land, **pracownik** (kto przejął / rozpoczął
/ zakończył), **tylko double rate**, **pokaż zrobione**, **⚠️ pokaż błędy**.

Pusty filtr pracownika znaczy **wszyscy** — nigdy nie zawęża wyników.

**Zakres dat działa na wybranym polu** (lista przed polami dat):

| Opcja | Pole | Uwagi |
|---|---|---|
| **Ziel-Datum** (domyślnie) | `ziel_datum` | data z importu CSV |
| **Data importu** | `imported_at` | kiedy paczka trafiła do systemu |
| **Start paczki** | `scan_start_at` | kiedy pracownik zaczął |
| **Koniec paczki** | `scan_end_at` | kiedy skończył |

Wcześniej zakres działał tylko po `Ziel-Datum`, więc paczki, których `Ziel-Datum` nie
pokrywa się z dniem skanowania, wypadały z widoku — wyglądało to, jakby filtr pracownika
gubił ludzi. Szukając „co zrobiono wczoraj", wybierz **Koniec paczki**.

Trzy ostatnie opcje liczą dobę **po warszawsku** (jak dashboard i statystyki), więc
nocna zmiana nie ląduje w złym dniu. Granica „do" jest półotwarta — „do 15.06" nie
wciąga paczek z 16.06 nad ranem.

**„Koniec paczki" automatycznie pokazuje zakończone** — z definicji tylko takie mają tę
datę, więc trzymanie domyślnego „tylko niezrobione" dawałoby zawsze pustą listę.
**„Start paczki"** tego nie robi: bez „pokaż zrobione" znaczy „rozpoczęte w zakresie
i wciąż otwarte".

⚠️ **„Pokaż zrobione" wymaga zakresu dat** — bez niego widok objąłby całą historię
(tysiące paczek). Zaznaczenie bez daty blokuje filtrowanie i podświetla pola dat.

Filtr błędów łapie dwie rzeczy:
1. paczkę **rozpoczętą i nigdy nie zakończoną**,
2. ilość w kategorii przekraczającą Stückzahl o **ponad 10%**.

Paczka w trakcie należy do pracownika, który ją rozpoczął — inny dostanie `409` przy
starcie i `403` przy końcu. Jeśli ten pracownik już do niej nie wróci, lider zdejmuje
blokadę przyciskiem **🔓 Odblokuj**: start skanu znika, paczka wraca do stanu
„nierozpoczęta" i każdy może ją zeskanować od nowa. Paczki **zakończonej** odblokować
się nie da.

### Statystyki ogólne — Amounts vs Total Amount
Dwie kolumny, które łatwo pomylić (na ekranie mają dymek ⓘ z tym samym wyjaśnieniem):

| Kolumna | Skąd się bierze | Co mówi |
|---|---|---|
| **Amounts** | suma `Stückzahl` wszystkich paczek linii, z importu CSV/Excel | ile sztuk **przyjechało** |
| **Total Amount** | ilość z kategorii **Labelling one**, wpisana przy zakończeniu paczki | ile sztuk **przerobiono** |

`Total Amount` **nie jest sumą wszystkich kategorii**: jedna sztuka przechodzi przez
kilka czynności (etykietowanie, sortowanie…), więc taka suma liczyłaby ten sam towar
wielokrotnie i potrafiła przebić `Amounts`. Rozjazd między kolumnami w trakcie zmiany
jest normalny — licznik 🔒 przy List-ID pokazuje, ile paczek linii jest już
zeskanowanych.

> ⚠️ **Żółty wiersz double rate liczy Total Amount jako sumę wszystkich kategorii** —
> świadoma niespójność, czeka na decyzję z operacją (`docs/TODO.md`).

Koszt liczy się bez zmian: `ilość × stawka` per kategoria, stawki z `/admin/cost-mapping`.

### Nazwy kategorii
Na ekranach kategorie mają etykiety dwuczłonowe, np. **Labelling one — Etykietowanie
pojedyncze**, **Card facture — Karta / faktura**. **Nagłówki eksportu Excel zostają po
angielsku** — to arkusz rozliczeniowy wychodzący na zewnątrz.

## Dalsza dokumentacja

| Plik | Zawartość |
|---|---|
| `docs/API.md` | Wszystkie endpointy, kody błędów, kształt odpowiedzi |
| `docs/DATABASE_SPEC.md` | Schemat bazy i reguły biznesowe |
| `docs/DEPLOY.md` | Wdrożenie, zmienne środowiskowe, backupy |
| `docs/CHANGELOG.md` | Historia zmian |
| `docs/TODO.md` | Co zostało do zrobienia |
| `CLAUDE.md` | Notatki architektoniczne — dlaczego coś jest zrobione tak, a nie inaczej |
