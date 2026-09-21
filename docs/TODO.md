# LogiStat — TODO & Notatki

## 🔴 Do zrobienia (priorytetowe)

- [ ] **Total Amount w żółtym wierszu double rate** — do decyzji z operacją (2026-09-18)
  - Zwykły wiersz Statystyk ogólnych liczy od 2026-09-18 **tylko `Labelling one`**
  - Żółty wiersz double rate **celowo został sumą wszystkich kategorii** — zmiana
    wstrzymana do ustalenia z operacją, czy ma działać tak samo jak zwykły wiersz
  - Miejsca do zmiany, jeśli decyzja padnie na „tak samo": `templates/general_stats.html`
    (blok `dr_total_amount`) oraz `write_data_row(..., is_double_rate=True)` w `app.py`

- [x] **PostgreSQL** — wdrożony na środowisku TESTOWYM (`.31`) 2026-08-31
  - Własny kontener `logistat-test-db` (`postgres:16-alpine`), bez portu na hoście
  - `DATABASE_URL` wskazuje bazę; od 2026-09 jest **wymagany** (SQLite usunięty)
  - Schemat z `db.create_all()` (ORM = jedyne źródło prawdy). Ręcznie pisany
    `docs/postgres_schema.sql` rozjechał się z modelami i został usunięty 2026-09-01
  - `migrate_columns()` **została** i jest jedyną drogą dla nowych kolumn na żyjącej bazie
  - Przetestowane: import CSV 595 paczek, dedup, czasy paczek, `/api/stats/user`,
    dashboard, per zmiana, sekwencje, `pg_dump` + odtworzenie
  - Szczegóły i procedura: `docs/DEPLOY.md`

- [ ] **PROD na `10.153.1.30`** — te same kroki co na `.31`
  - [ ] IT: dostęp SSH dla `optmtst_user` (klucz jak na `.31`; teraz `Permission denied`)
  - [ ] Własne hasła w `docker-compose.override.yml` (nie kopiować testowych)
  - [ ] Backup + cron, weryfikacja odtworzenia kopii

- [x] **Domena + HTTPS** — `https://logistat-test.logwin-logistics.com.pl/` działa
  - IT opublikowało nazwy przez **Cloudflare**, nie przez firmowe proxy `10.15.12.67`
  - Własny Nginx i certyfikat **niepotrzebne** — `docs/nginx-logistat.conf` zostaje jako zapas
  - [ ] IT: potwierdzić, czy przed tymi nazwami jest reguła WAF / allowlista IP
        (Cloudflare Access **nie ma** — sprawdzone; do tego czasu zakładamy, że
        strona logowania jest osiągalna z internetu)
  - [ ] IT: `logistat-prod` → `.30:5001` zadziała dopiero po wdrożeniu na produkcji

- [x] **Import danych z Excela** — `POST /api/import/excel` (openpyxl), ten sam pipeline co CSV
  - Kolumny jak w CSV: `Barcode`, `Land`, `Stückzahl`, `Kategorie`, `Ziel-Datum`, `Übergabe Nr.`
  - Strona `/import-csv` przyjmuje teraz `.csv` **i** `.xlsx` (routing po rozszerzeniu)
  - Wspólny helper `process_import_rows()` type-aware (openpyxl zwraca natywne typy)
  - ⚠️ numeryczne barcode w Excelu = float64: długie SSCC/EAN >2^53 tracą precyzję, wiodące zera znikają — kolumnę barcode formatować jako tekst

## 🟡 Planowane usprawnienia

- [x] **Testy** — `tests/` (pytest, 324 testy), nacisk na ścieżki rozliczeniowe
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

- [ ] **Rozbicie `app.py`** (~4000 linii) — modele / API / widoki do osobnych
      modułów. Teraz jest to bezpieczniejsze niż wcześniej, bo testy pokrywają
      ścieżki rozliczeniowe i uprawnienia.

- [ ] **Touch/tablet support** — drag & drop na tablecie wymaga touch events
  - Rozwiązanie: dodać `touchstart`, `touchmove`, `touchend` listenery
  - Albo użyć biblioteki jak Sortable.js / interact.js

- [ ] **Eksport czasów pracowników do Excel** — raport dzienny/tygodniowy
  - Wzorować na istniejącym eksporcie `general_stats_export`

- [ ] **Powiadomienia dźwiękowe** — toast z dźwiękiem przy skanowaniu
  - `new Audio('/static/beep.mp3').play()` po udanym skanie

- [x] **Próg czasu przerwy konfigurowalny** — `/admin/settings` (`PUT /api/settings`, klucz `break_threshold_minutes`, domyślnie 30); tabela `AppSetting` (klucz/wartość)

## 🟢 Ukończone

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
- Volume: `./instance:/app/instance` — baza danych persystuje między restartami
- Gunicorn z 2 workerami (wystarczające dla <50 użytkowników)

### Deployment
- Pełna procedura: **`docs/DEPLOY.md`**
- `docker compose up --build -d`; konfiguracja środowiska w `docker-compose.override.yml`
  (wzór: `docker-compose.override.example.yml`, `chmod 600`, poza repo)
- Publikacja przez Cloudflare/proxy IT — własny Nginx niepotrzebny
- Pamiętaj o `SECRET_KEY` w zmiennych środowiskowych na produkcji!
