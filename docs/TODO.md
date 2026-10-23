# LogiStat — TODO & Notatki

## 🔴 Do zrobienia (priorytetowe)

- [ ] **Tabela ilości — dalsze kroki** (wersja 2 wdrożona 2026-10-23)
  - Flagi – Card Change wpisuje dziś pracownik (liczba kart); automat z algorytmu
    (pierścionki, RFID — Warengruppe ID w pliku?) czeka na regułę i źródło danych
  - Ilość per grupa z pliku klienta, gdy zacznie ją przysyłać — wtedy Nadwyżka/Brak
    mogłyby być per grupa (dziś tylko na cały karton)
  - Bez odpowiedzi operacji: czy kategoria A/B z pliku ma związek z grupą; Normy paczki
    jednej osoby dalej po Stückzahl
  - Labelling polybag nie ma już źródła w tabeli — potwierdzić, że nie jest potrzebny
  - Nowa grupa artykułowa = zmiana w kodzie (`GRUPY_ARTYKULOWE` + kolumna rozliczenia)

- [x] **Total Amount w żółtym wierszu double rate** — rozstrzygnięte 2026-10-15: oba wiersze
  = suma wszystkich kolumn oprócz Labelling twice i triple

- [x] **PostgreSQL** — wdrożony na środowisku TESTOWYM (`.31`) 2026-08-31
  - Własny kontener `logistat-test-db` (`postgres:16-alpine`), bez portu na hoście
  - `DATABASE_URL` wskazuje bazę; od 2026-09 jest **wymagany** (SQLite usunięty)
  - Schemat z `db.create_all()` (ORM = jedyne źródło prawdy). Ręcznie pisany
    `docs/postgres_schema.sql` rozjechał się z modelami i został usunięty 2026-09-01
  - `migrate_columns()` **została** i jest jedyną drogą dla nowych kolumn na żyjącej bazie
  - Przetestowane: import CSV 595 paczek, dedup, czasy paczek, `/api/stats/user`,
    dashboard, per zmiana, sekwencje, `pg_dump` + odtworzenie
  - Szczegóły i procedura: `docs/DEPLOY.md`

- [x] **PROD na `10.153.1.30`** — działa od 2026-10-22, aktualizowany razem z `.31`,
      `https://logistat-prod.logwin-logistics.com.pl/`; szczegóły w `docs/DEPLOY.md`
  - [x] Dostęp SSH (`optm_user`), własne hasła w override, schemat z ORM
  - [x] Kopia z `.31`: 142 użytkowników z hasłami, stawki, kraje, czynności, opcje
        użytkowników, ustawienia, cel + historia, szkolenia z czynności (sumy zgodne)
  - [x] Backup: cron 22:30 do `~/logistat/backups`, retencja 14 dni
  - [ ] **Konta testowe na prod** (`admin`, `lider`, 2 z „test” w nazwie) — mają hasła
        z testu; dezaktywować albo zmienić hasła
  - [ ] **Hasło konta `admin`** — nieznane (losowe z sierpnia, nigdzie niezapisane);
        ustawić nowe przez „Użytkownicy” albo zlecić reset (test i prod)
  - [ ] **Liderzy/admini zmieniają hasła** na prod (te same co na teście)
  - [ ] **Hasła do baz** (`logistat` na `.31` i `.30`) przenieść do firmowego menedżera
        haseł — leżą tylko w `docker-compose.override.yml` na serwerach
  - [ ] **Backup poza maszyną** — zrzuty leżą na tej samej VM co baza; zapytać IT
        o ich system backupów / miejsce na kopie; zrobić próbę odtworzenia kopii prod
  - [ ] **Stanowiska skanerów** — zakładki na adres https prod (po `http://10.153.1.30:5001`
        logowanie nie działa: `SESSION_COOKIE_SECURE=1`)
  - [ ] **Stawki kosztów na prod** — skopiowane są tylko za 03/2026; bez stawek za
        bieżące miesiące koszt w Statystykach ogólnych = 0
  - [ ] Każde kolejne wdrożenie: najpierw `.31`, potem `.30` (+ `sprawdz_spojnosc.py` na obu)

- [x] **Domena + HTTPS** — `https://logistat-test.logwin-logistics.com.pl/` działa
  - IT opublikowało nazwy przez **Cloudflare**, nie przez firmowe proxy `10.15.12.67`
  - Własny Nginx i certyfikat **niepotrzebne** — `docs/nginx-logistat.conf` zostaje jako zapas
  - [ ] IT: potwierdzić, czy przed tymi nazwami jest reguła WAF / allowlista IP
        (Cloudflare Access **nie ma** — sprawdzone; do tego czasu zakładamy, że
        strona logowania jest osiągalna z internetu)
  - [x] `logistat-prod` → proxy IT `10.15.12.67` → `.30:5001` działa (2026-10-22)

- [x] **Import danych z Excela** — `POST /api/import/excel` (openpyxl), ten sam pipeline co CSV
  - Kolumny jak w CSV: `Barcode`, `Land`, `Stückzahl`, `Kategorie`, `Ziel-Datum`, `Übergabe Nr.`
  - Strona `/import-csv` przyjmuje teraz `.csv` **i** `.xlsx` (routing po rozszerzeniu)
  - Wspólny helper `process_import_rows()` type-aware (openpyxl zwraca natywne typy)
  - ⚠️ numeryczne barcode w Excelu = float64: długie SSCC/EAN >2^53 tracą precyzję, wiodące zera znikają — kolumnę barcode formatować jako tekst

## 🟡 Planowane usprawnienia

- [ ] **Klasa `btn-secondary` nie istnieje w CSS** — przyciski renderują się jak linki na
      `paczki`, `stats`, `import_csv`, `admin_cost_mapping` (Statystyki ogólne poprawione
      2026-10-13 na `btn-ghost`). Zdefiniować klasę albo podmienić na `btn-ghost`.
- [ ] **Estymacja pozostałych czynności** — działa sama, gdy liderzy zaczną wpisywać ilości
      (Wpis ilości) dla czynności innych niż Post Processing.
- [ ] **Masowe zaznaczanie szkoleń dla czynności** — nowa czynność startuje bez
      przeszkolonych, a zaznacza się każdą osobę w jej oknie; ewentualnie „zaznacz
      wszystkich w czynności X” (zaproponowane 2026-10-13, nie zamówione).

- [x] **Testy** — `tests/` (pytest, 495 testów), nacisk na ścieżki rozliczeniowe
  - `pip install -r requirements-dev.txt && pytest`
  - Ten sam zestaw na Postgresie: `LOGISTAT_TEST_DATABASE_URL=... pytest`
  - Zestaw przechodzi pod `TZ=UTC`, `Europe/Warsaw` i `America/New_York`

- [ ] **CSRF na formularzach** — `SameSite=Lax` zamyka najgorszy przypadek
      (multipartowy `/api/import-csv`), ale `/login` i `/profile` to nadal
      zwykłe formularze bez tokenu. Do rozważenia Flask-WTF, jeśli aplikacja
      zostanie na stałe wystawiona publicznie.

- [x] **`docs/postgres_schema.sql`** — **usunięty 2026-09-01**. Był nieaktualny i mylący
      (JSONB psuje `json.loads`, `NOW()` psuje naive UTC), a po usunięciu kolumny
      `general_stat.double_rate` rozjechał się jeszcze bardziej. Schemat bierze się
      wyłącznie z `db.create_all()` — ORM jest jedynym źródłem prawdy.

- [ ] **Rozbicie `app.py`** (~5000 linii) — modele / API / widoki do osobnych
      modułów. Teraz jest to bezpieczniejsze niż wcześniej, bo testy pokrywają
      ścieżki rozliczeniowe i uprawnienia.

- [ ] **Touch/tablet support** — drag & drop na tablecie wymaga touch events
  - Rozwiązanie: dodać `touchstart`, `touchmove`, `touchend` listenery
  - Albo użyć biblioteki jak Sortable.js / interact.js

- [ ] **Eksport czasów pracowników do Excel** — raport dzienny/tygodniowy
  - Wzorować na istniejącym eksporcie `general_stats_export`

- [ ] **Powiadomienia dźwiękowe** — toast z dźwiękiem przy skanowaniu
  - `new Audio('/static/beep.mp3').play()` po udanym skanie

- [ ] **Stawki na wrzesień/październik 2026 na `.31`** — są tylko za 03/2026, więc koszt
      w Statystykach ogólnych wynosi 0. Przy wpisywaniu: „Loading date" to od 2026-10
      **data pliku** (zwykle dzień wcześniej niż dawna Ziel-Datum).

- [ ] **Forecast wstecz** — historyczne forecasty wpisywano z myślą o Ziel-Datum;
      „Actual" liczy się od 2026-10 po dacie pliku, więc porównanie sprzed zmiany może
      być przesunięte o dzień.

- [ ] **Nazwy kategorii dla pracownika** — wpisać docelowe w Panel Admina → ✏️ Nazwy
      kategorii (np. „Niesprocesowane" dla Sorting).

- [ ] **Błędy na liście paczek** pokazują angielską nazwę kategorii (`bledy_paczki()`
      liczone per paczka — tłumaczenie wymagałoby jednej mapy na całą stronę).

- [x] **Próg czasu przerwy konfigurowalny** — `/admin/settings` (`PUT /api/settings`, klucz `break_threshold_minutes`, domyślnie 30); tabela `AppSetting` (klucz/wartość)

## 🟢 Ukończone

- [x] **Szkolenia z czynności** (2026-10-13) — przydział tylko przeszkolonych, okno
      „⛔ Brak szkolenia”; **cel z dnia pracy** w Normach + historia zmian celu

- [x] Skaner EAN-128 z timeoutem (300ms)
- [x] Drag & drop z multi-select
- [x] Sugestie AI (30-dniowa średnia)
- [x] Wpis ilości z audit trailem
- [x] Statystyki per dzień/miesiąc z wykresem
- [x] Admin czynności (CRUD + reorder)
- [x] Admin użytkownicy (CRUD + barcode)
- [x] Role: operator/leader/admin
- [x] Panel Admina z przyciskiem w sidebarze (admin only)
- [x] Mapowanie krajów i zleceń (Country → Innenauftrag) — CRUD + seed 29 mapowań
- [x] Import CSV z automatyczną deduplikacją po `barcode`
- [x] Tabela statystyk ogólnych (General Stats) z podsumowaniami per List-ID
- [x] Kategorie (10) w ujęciu ilościowym z autowyliczaniem kosztów względem narzuconych stawek
- [x] Centralne zestawienie Cennika (Koszty Kategorii) i zarządzanie stawkami per miesiąc/rok
- [x] Kolumna Total Amount + poprawa stylów wyliczeń kosztowych
- [x] Paging & Filtering w podglądzie "Paczki (Dane CSV)"
- [x] Skanowanie paczek — naprzemienne skan pracownik → paczka z obsługą duplikatów
- [x] Przepisanie paczki do innego pracownika przez lidera (ekran Paczki)
- [x] Kolumna Double Rate w Statystykach ogólnych (×2 stawki, natychmiastowy zapis)
- [x] Eksport Statystyk ogólnych do .xlsx z formatowaniem (openpyxl)
- [x] Dashboard dzienny — karty, pasek postępu, per pracownik (2 zakładki)
- [x] Czas pracy — skanowanie przerw i końca pracy (toggle break_start/break_end)
- [x] Czasy pracowników — moduł liderski z korektami ręcznymi, podświetlenie >30 min przerwy
- [x] Zmiana hasła — ekran `/profile` z formularzem (aktualne + nowe + potwierdzenie), link w sidebarze
- [x] Double Rate — checkbox per paczka w `/paczki`; żółta druga linia w Statystykach ogólnych (Amounts auto z paczek double rate, kategorie ręczne, ×1) + w eksporcie xlsx
- [x] **Kolory zmian** (2026-10-05) — Zmiana 1 niebieska, Zmiana 2 pomarańczowa na wszystkich ekranach ze zmianą
- [x] **Autozapis** (2026-10-05) — Przydzielanie, Wpis ilości, Forecast, Statystyki ogólne bez przycisku „Zapisz"; ostrzeżenie o drugim liderze na tej samej zmianie; okna nie gubią danych po kliknięciu obok; Stawki zapisują się pod wczytany miesiąc
- [x] **Nazwy kategorii ustawiane przez admina** (2026-10-05) — „Polska (English)", `/admin/category-labels`
- [x] **Szkolący i osoby szkolone** (2026-10-08) — zakładka 🎓 Szkolenie (szkolący + min. 1 szkolony, koniec wszystkich naraz); szkolący 100% celu dnia za czas szkolenia, szkoleni poza normami i średnią; historia celu
- [x] **Forecast: różnica = Actual − Forecast** (2026-10-08) — minus = przyjechało mniej niż plan
- [x] **Data pliku** (2026-10-05) — okno daty przy imporcie, główna data pracy i klucz rozliczenia, grupowa poprawa daty, Dashboard Dziś / Wybrany dzień / Podsumowanie niezrobionych; migracja `.31` zweryfikowana
- [x] **Statystyki ogólne dla lidera** (2026-10-12) — podgląd bez kosztów (ekran i Excel), edycja zostaje u admina
- [x] **„Loading date”** (2026-10-12) — nowa nazwa „Data pliku” we wszystkich tekstach UI (baza/API bez zmian)
- [x] **Dashboard: zakresy** (2026-10-12) — Podsumowanie z filtrem Loading date od–do, zakładka „Per Loading date”
- [x] **Przydzielanie: estymacja** (2026-10-13) — przydzieleni × średnia osoby per czynność (szt./zmianę, szt./h)
- [x] **Czasy paczek: nadwyżka + większy ekran** (2026-10-13) — pytanie o nadwyżkę, 5 s „Poinformuj lidera”; zoom 1,27
- [x] **Forecast w sztukach, filtr Stat. ogólnych po lewej** (2026-10-13)

---

## 💡 Tipy dla developera

### Baza danych
- **Tylko PostgreSQL** — `DATABASE_URL` wymagany, `docker compose up` podnosi bazę
- Nowe kolumny do istniejących tabel: **obowiązkowo** dodaj do `migrate_columns()`.
  `db.create_all()` dokłada tabele, ale **nigdy kolumny do istniejącej tabeli** —
  bez wpisu po wdrożeniu leci `UndefinedColumn`. Dopisz też przypadek do
  `tests/test_migracje.py`, bo zwykłe testy tego nie widzą (mają świeży schemat)
- Nowe tabele: `db.create_all()` tworzy automatycznie przy starcie
- Backup: `pg_dump` (`scripts/backup-logistat.sh`)
- Testy wymagają bazy: `docker compose -f docker-compose.test.yml up -d`

### Czas pracy
- Model `WorkerTimeEvent(user_id, shift_id, event_type, timestamp, recorded_by, is_manual, note)`
- Stan przerwy: liczony jako `count(break_start) - count(break_end)` — nie ma flagi w User
- Auto-zamknięcie przerwy przy `work_end` jeśli przerwa jest otwarta
- Wszystkie czasy w UTC; frontend konwertuje do czasu lokalnego przez `new Date(iso).toLocaleTimeString('pl')`

### Skaner
- EAN-128 skanery USB HID wysyłają znaki bez Entera
- Timeout 300ms w `scanner.html` — jeśli skaner jest wolny, zwiększ do 500ms
- Pole inputu ma auto-focus z fallbackiem na `blur` event

### Drag & Drop
- Natywne HTML5 Drag & Drop API (nie wymaga bibliotek)
- Multi-select: klik = zaznacz, drag = przeciągnij wszystkie zaznaczone
- Przy przejściu na tablet: zamienić na touch events lub Sortable.js

### API
- Wszystkie endpointy chronione dekoratorami `@leader_required` / `@admin_required`
- Modele mają metodę `to_dict()` do serializacji
- Audit fields na `DailyStat`: `entered_by`, `entered_at`, `modified_by`, `modified_at`

### Docker
- Port 5001 (nie 5000 — zajęty przez Jewelry-Tracker)
- Baza: wolumen Postgresa (`logistat-test_pgdata` na `.31`, `logistat_pgdata` na `.30`) — **nigdy `down -v`**
- Gunicorn z 2 workerami (wystarczające dla <50 użytkowników)

### Deployment
- Pełna procedura: **`docs/DEPLOY.md`**
- `docker compose up --build -d`; konfiguracja środowiska w `docker-compose.override.yml`
  (wzór: `docker-compose.override.example.yml`, `chmod 600`, poza repo)
- Publikacja przez Cloudflare/proxy IT — własny Nginx niepotrzebny
- Pamiętaj o `SECRET_KEY` w zmiennych środowiskowych na produkcji!
