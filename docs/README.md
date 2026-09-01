# LogiStat — Workforce Management System

System do zarządzania pracownikami, przydzielania czynności i śledzenia statystyk wydajności.

## Stack technologiczny

| Warstwa | Technologia |
|---------|-------------|
| Backend | Python 3.13 + Flask 3.1 |
| Baza danych | SQLite (dev) / PostgreSQL 16 (test, prod) — przełącznik `DATABASE_URL` |
| Autentykacja | Flask-Login |
| Frontend | Vanilla HTML/CSS/JS + Chart.js |
| Deploy | Docker + Gunicorn |

## Uruchomienie lokalne

```bash
cd /opt/LogiStat
pip install -r requirements.txt
python app.py
# → http://localhost:5001
```

## Uruchomienie Docker

```bash
docker compose up --build -d
# → http://localhost:5001
```

Bez `DATABASE_URL` aplikacja działa na SQLite. Wdrożenie na serwer (Postgres, domena,
backupy) opisuje **`docs/DEPLOY.md`**.

## Testy

```bash
pip install -r requirements-dev.txt
pytest                       # 231 testów
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
| dev (`10.153.1.32`) | `http://10.153.1.32:5001` | SQLite |
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
│   ├── test_packages_api.py        # Ręczne dodanie/edycja paczki
│   ├── test_package_times.py       # Blokada właściciela paczki
│   ├── test_permissions.py         # Guardy ról, is_active_user
│   ├── test_day_boundary.py        # Doba lokalna vs UTC (DST)
│   ├── test_validation.py          # Błędne wejście → 400, nie 500
│   ├── test_performance.py         # Licznik SELECT-ów (regresje N+1)
│   ├── test_xss.py                 # Escapowanie + reguła statyczna po szablonach
│   ├── test_smoke_pages.py         # Każda strona się renderuje
│   ├── test_config.py              # SECRET_KEY, limit uploadu, ciasteczka
│   └── test_init_race.py           # Równoległy start workerów na pustej bazie
├── instance/
│   └── logistat.db         # Baza SQLite (dev; generowana automatycznie)
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
│   ├── admin_settings.html # Ustawienia (próg przerwy)
│   ├── import_csv.html     # Importowanie pliku CSV
│   ├── general_stats.html  # Statystyki ogólne z CSV (+ żółta linia double rate)
│   ├── paczki.html         # Surowe paczki CSV (+ checkbox double rate)
│   ├── scan_package.html   # Skan paczek — podgląd statusu (read-only)
│   ├── scan_paczki.html    # Czasy paczek — Start/Koniec
│   ├── dashboard.html      # Dashboard dzienny
│   ├── time_tracking.html  # Czas pracy (przerwy/koniec)
│   ├── worker_times.html   # Czasy pracowników (korekty)
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
| **operator** | Skanuje się na zmianę. Nie loguje się. |
| **leader** | Loguje się hasłem. Skanuje, przydziela, wpisuje ilości, dodaje użytkowników. |
| **admin** | Wszystko + zarządzanie czynnościami + Panel Admina (mapowanie krajów) |

## Ekrany aplikacji (struktura menu)

Nawigacja w sidebarze jest pogrupowana w sekcje:

### 🗂 Przegląd
- 🏠 **Dashboard** (`/dashboard`) — karty i podsumowanie dnia, per pracownik (metryki paczek = **zakończone**, `scan_end`)
- 📈 **Forecast** (`/forecast`) — prognoza ilości per dzień

### 🗂 Zmiana
- 📷 **Skaner zmian** (`/scanner/1`, `/scanner/2`) — rejestracja obecności EAN-128
- 📋 **Przydzielanie** (`/assignment`) — drag & drop operatorów do czynności
- ✏️ **Wpis ilości** (`/data-entry`) — ilości zrobione per osoba
- 📊 **Statystyki** (`/stats`) — wykresy i tabele per pracownik; zakończone paczki liczone automatycznie

### 🗂 Paczki
- 🔎 **Paczki inspektor** (`/scan-package`) — podgląd statusu paczki (przeskanowana / przez kogo / zakończona), read-only
- ⏱ **Czasy paczek** (`/scan-paczki`) — Start/Koniec procesowania; blokada „kto zaczął, ten kończy"
- 📦 **Paczki (dane)** (`/paczki`) — surowe dane CSV z filtrami; checkbox **double rate**; kolumny czasu

### 🗂 Czas pracy
- 🕐 **Czas pracy** (`/time-tracking`) — skanowanie przerw i końca pracy
- 👥 **Czasy pracowników** (`/worker-times`) — przegląd i korekta czasów (przerwa >30 min na czerwono)

### 🗂 Rozliczenia (CSV) — *tylko admin*
- 📥 **Import danych** (`/import-csv`) — drag & drop plików **CSV lub Excel (.xlsx)** z automatyczną deduplikacją po barcode
- 💶 **Statystyki ogólne** (`/general-stats`) — tabela zestawień wg list i dat; żółta linia **double rate**

### 🗂 Administracja
- 👤 **Użytkownicy** (`/admin/users`) — dodawanie/edycja operatorów
- ⚙️ **Czynności** (`/admin/activities`) — zarządzanie czynnościami *(admin)*
- 🛡️ **Panel Admina** (`/admin/panel`) — hub administracyjny + mapowanie krajów *(admin)*

### Stopka sidebara
- 🔑 **Zmiana hasła** (`/profile`) · **Wyloguj**
