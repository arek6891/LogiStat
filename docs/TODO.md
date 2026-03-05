# LogiStat — TODO & Notatki

## 🔴 Do zrobienia (priorytetowe)

- [ ] **Import danych z Excela** — format kolumn do ustalenia z użytkownikiem
  - Endpoint `/api/import/excel` jest zarezerwowany, ale jeszcze nieaktywny
  - Biblioteka `openpyxl` już zainstalowana w requirements.txt
  - Trzeba uzgodnić: jakie kolumny, jak mapować użytkowników, jak rozwiązywać konflikty

- [ ] **Zmiana hasła admina** — brak ekranu do zmiany hasła
  - Dodać stronę `/profile` lub modal w sidebar z formularzem zmiany hasła

- [ ] **Zmiana hasła liderów** — liderzy powinni móc zmieniać swoje hasło

## 🟡 Planowane usprawnienia

- [ ] **Touch/tablet support** — drag & drop na tablecie wymaga touch events
  - Rozwiązanie: dodać `touchstart`, `touchmove`, `touchend` listenery
  - Albo użyć biblioteki jak Sortable.js / interact.js
  
- [ ] **Eksport statystyk do PDF/Excel** — do raportowania
  - Możliwy do dodania na stronie statystyk

- [ ] **Powiadomienia** — toast z dźwiękiem przy skanowaniu
  - `new Audio('/static/beep.mp3').play()` po udanym skanie

- [ ] **Ciemny/jasny motyw** — toggle w sidebar

- [ ] **Logowanie operacji** — pełny audit log (kto co kiedy zrobił)
  - Osobna tabela `AuditLog` z typami zdarzeń

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

---

## 💡 Tipy dla developera

### Baza danych
- SQLite plik: `instance/logistat.db`
- Przy zmianach w modelach trzeba **usunąć bazę** i restartować (brak migracji)
- Jeśli dodasz migracje, użyj `Flask-Migrate` (`flask db init/migrate/upgrade`)
- Backup: skopiuj plik `instance/logistat.db`

### Skaner
- EAN-128 skanery USB HID wysyłają znaki bez Entera
- Timeout 300ms w `scanner.html` — jeśli skaner jest wolny, zwiększ do 500ms
- Pole inputu ma auto-focus z fallbackiem na `blur` event

### Drag & Drop
- Natywne HTML5 Drag & Drop API (nie wymaga bibliotek)
- Multi-select: klik = zaznacz, drag = przeciągnij wszystkie zaznaczone
- Dane przesyłane przez `e.dataTransfer.setData` jako JSON z listą user IDs
- Przy przejściu na tablet: zamienić na touch events lub Sortable.js

### API
- Wszystkie endpointy chronione dekoratorami `@leader_required` / `@admin_required`
- Modele mają metodę `to_dict()` do serializacji
- Audit fields na `DailyStat`: `entered_by`, `entered_at`, `modified_by`, `modified_at`

### Docker
- Port 5001 (nie 5000 — zajęty przez Jewelry-Tracker)
- Volume: `./instance:/app/instance` — baza danych persystuje między restartami
- Gunicorn z 2 workerami (wystarczające dla <50 użytkowników)

### Typowe błędy
- `User is not JSON serializable` → użyj `user.to_dict()|tojson` w szablonach
- Port conflict → sprawdź `docker-compose.yml` i `app.py` (port 5001)
- Brak migracji → przy zmianach modeli usuń `instance/logistat.db` i restartuj

### Mapowanie krajów
- Model `CountryMapping` — przechowuje pary Country → Innenauftrag
- Dane seed: 29 domyślnych mapowań (np. Schweiz → 91000741810)
- API: `/api/country-mappings` (GET/POST/PUT/DELETE), wymaga roli `admin`
- Strony: `/admin/panel` (hub), `/admin/country-mapping` (tabela CRUD)
- Przy dodawaniu nowego modelu — pamiętaj o seed w `seed_data()` i usunięciu bazy
- Template wzorowany na `admin_activities.html` (modal add/edit, potwierdzenie delete)

### Deployment
- Taki sam flow jak Jewelry-Tracker: `docker-compose up --build -d`
- Nginx reverse proxy: `/logistat/ → localhost:5001`
- Pamiętaj o `SECRET_KEY` w zmiennych środowiskowych na produkcji!
