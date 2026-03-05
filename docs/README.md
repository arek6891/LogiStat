# LogiStat — Workforce Management System

System do zarządzania pracownikami, przydzielania czynności i śledzenia statystyk wydajności.

## Stack technologiczny

| Warstwa | Technologia |
|---------|-------------|
| Backend | Python 3.13 + Flask 3.1 |
| Baza danych | SQLite (via Flask-SQLAlchemy) |
| Autentykacja | Flask-Login |
| Frontend | Vanilla HTML/CSS/JS + Chart.js |
| Deploy | Docker + Gunicorn |

## Uruchomienie lokalne

```bash
cd c:\Users\asobczyk\Downloads\Apps\LogiStat
pip install -r requirements.txt
python app.py
# → http://localhost:5001
```

## Uruchomienie Docker

```bash
docker-compose up --build -d
# → http://localhost:5001
```

## Domyślne konto

| Login | Hasło | Rola |
|-------|-------|------|
| admin | admin123 | admin |

> ⚠️ Zmień hasło admina po pierwszym logowaniu!

## Struktura projektu

```
LogiStat/
├── app.py                  # Cały backend (modele, API, routing)
├── requirements.txt        # Zależności Python
├── Dockerfile              # Obraz Docker
├── docker-compose.yml      # Docker Compose (port 5001)
├── instance/
│   └── logistat.db         # Baza SQLite (generowana automatycznie)
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
│   └── admin_country_mapping.html # Mapowanie krajów → Innenauftrag
└── docs/
    ├── README.md           # Ten plik
    ├── API.md              # Dokumentacja API
    ├── CHANGELOG.md        # Historia zmian
    └── TODO.md             # Co zostało do zrobienia
```

## Role użytkowników

| Rola | Uprawnienia |
|------|-------------|
| **operator** | Skanuje się na zmianę. Nie loguje się. |
| **leader** | Loguje się hasłem. Skanuje, przydziela, wpisuje ilości, dodaje użytkowników. |
| **admin** | Wszystko + zarządzanie czynnościami + Panel Admina (mapowanie krajów) |

## Ekrany aplikacji

1. **Skaner zmian** (`/scanner/1`, `/scanner/2`) — rejestracja obecności EAN-128
2. **Przydzielanie** (`/assignment`) — drag & drop operatorów do czynności
3. **Wpis ilości** (`/data-entry`) — ilości zrobione per osoba
4. **Statystyki** (`/stats`) — wykresy i tabele per pracownik
5. **Czynności** (`/admin/activities`) — zarządzanie czynnościami (admin)
6. **Użytkownicy** (`/admin/users`) — dodawanie/edycja operatorów
7. **Panel Admina** (`/admin/panel`) — hub administracyjny (admin)
8. **Mapowanie krajów** (`/admin/country-mapping`) — tabela Country → Innenauftrag (admin)
