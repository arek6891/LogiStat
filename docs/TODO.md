# LogiStat — TODO & Notatki

## 🔴 Do zrobienia (priorytetowe)

- [ ] **Zbudować bazę PostgreSQL na serwerze developerskim (10.153.1.32)**
  - Baza: kontener `wave-planning-postgres-1`, host `127.0.0.1:5432`, user `app`, db `appdb`
  - Uruchomić `docs/postgres_schema.sql` na bazie `appdb`
  - Wygenerować hash hasła admina i wstawić do seeda
  - Zmienić `SQLALCHEMY_DATABASE_URI` w `docker-compose.yml` na `postgresql://app:change_me@127.0.0.1:5432/appdb`
  - Dodać `psycopg2-binary` do `requirements.txt`
  - Usunąć `migrate_columns()` z `app.py` — niepotrzebna przy PostgreSQL
  - Przetestować wszystkie moduły po migracji

- [ ] **Nginx + domena: https://logistat.logwin-logistics.com/**
  - [x] Nginx zainstalowany i działa
  - [x] Config: `/etc/nginx/sites-available/logistat` (proxy → localhost:5001)
  - [x] Tymczasowy HTTP działa — gotowy na DNS od IT
  - [ ] IT: dodać rekord DNS `logistat.logwin-logistics.com → 10.153.1.32`
  - [ ] IT: dostarczyć certyfikat SSL dla `logistat.logwin-logistics.com` (lub wildcard `*.logwin-logistics.com`)
        — format PEM: plik `cert.crt` (certyfikat + łańcuch pośredni) i `cert.key` (klucz prywatny)
        — przesłać bezpiecznym kanałem (nie email)
        — jeśli dostarczą `.pfx`/`.p12` (format Windows) — trzeba przekonwertować (możemy to zrobić)
  - [ ] Po otrzymaniu certyfikatów:
        `sudo mkdir -p /etc/nginx/ssl/logistat`
        `sudo cp cert.crt /etc/nginx/ssl/logistat/cert.crt`
        `sudo cp cert.key /etc/nginx/ssl/logistat/cert.key`
        `sudo chmod 600 /etc/nginx/ssl/logistat/cert.key`
        następnie odkomentować blok HTTPS w `/etc/nginx/sites-available/logistat` i `sudo systemctl reload nginx`

- [ ] **Double Rate — dokończyć implementację w module Paczki**
  - UI usunięte z Paczek i Statystyk Ogólnych (backend i pole w bazie pozostały)
  - Brakuje informacji: skąd pochodzi double rate? Z CSV? Ręcznie per lista? Per kraj/data?
  - Gdy będą info: backend gotowy (`GeneralStat.double_rate` + API `/api/packages/uebergabe-double-rate`), dodać tylko UI

- [ ] **Import danych z Excela** — format kolumn do ustalenia z użytkownikiem
  - Endpoint `/api/import/excel` jest zarezerwowany, ale jeszcze nieaktywny
  - Biblioteka `openpyxl` już zainstalowana w requirements.txt
  - Trzeba uzgodnić: jakie kolumny, jak mapować użytkowników, jak rozwiązywać konflikty

## 🟡 Planowane usprawnienia

- [ ] **Touch/tablet support** — drag & drop na tablecie wymaga touch events
  - Rozwiązanie: dodać `touchstart`, `touchmove`, `touchend` listenery
  - Albo użyć biblioteki jak Sortable.js / interact.js

- [ ] **Eksport czasów pracowników do Excel** — raport dzienny/tygodniowy
  - Wzorować na istniejącym eksporcie `general_stats_export`

- [ ] **Powiadomienia dźwiękowe** — toast z dźwiękiem przy skanowaniu
  - `new Audio('/static/beep.mp3').play()` po udanym skanie

- [ ] **Próg czasu przerwy konfigurowalny** — aktualnie hardcoded 30 min

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

---

## 💡 Tipy dla developera

### Baza danych
- SQLite plik: `instance/logistat.db`
- Nowe kolumny do istniejących tabel: dodaj do `migrate_columns()` w `app.py`
- Nowe tabele: `db.create_all()` tworzy automatycznie przy starcie
- Backup: skopiuj plik `instance/logistat.db`

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
- `docker compose up --build -d`
- Nginx reverse proxy: `/logistat/ → localhost:5001`
- Pamiętaj o `SECRET_KEY` w zmiennych środowiskowych na produkcji!
