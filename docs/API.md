# LogiStat — API Reference

Wszystkie endpointy API wymagają zalogowania jako leader lub admin (chyba że zaznaczono inaczej).

---

## Autentykacja

| Method | URL | Opis |
|--------|-----|------|
| POST | `/login` | Logowanie (form: `username`, `password`) |
| GET | `/logout` | Wylogowanie |
| GET/POST | `/profile` | Zmiana hasła zalogowanego użytkownika (form: `current_password`, `new_password`, `confirm_password`; min. 6 znaków, nowe ≠ stare) |

---

## Skanowanie (Shift Attendance)

### POST `/api/scan`
Rejestruje obecność pracownika na zmianie.

**Body (JSON):**
```json
{
  "barcode": "ABC123",
  "shift_number": 1,
  "date": "2026-02-13"
}
```

**Odpowiedzi:**
- `201` — zarejestrowano pomyślnie
- `200` + `already_scanned: true` — już zeskanowany (warning)
- `404` — nieznany kod kreskowy

### DELETE `/api/scan/<attendance_id>`
Usuwa rejestrację obecności.

### GET `/api/shift/attendances?date=YYYY-MM-DD&shift_number=N`
Lista obecnych na danej zmianie.

---

## Przydzielanie (Assignment)

### GET `/api/assignment/data?date=YYYY-MM-DD&shift_number=N`
Dane do tablicy drag & drop: obecni, przydzieleni, czynności.

### GET `/api/assignment/suggestions?date=YYYY-MM-DD&shift_number=N`
Sugestie AI na podstawie średnich ilości z ostatnich 30 dni.

**Algorytm:**
1. Dla każdej czynności oblicz średnią/dzień każdego pracownika
2. Zacznij od czynności z najmniejszą liczbą kwalifikowanych operatorów
3. Przydziel najlepszego dostępnego pracownika
4. Resztę rozdziel równomiernie

### POST `/api/assignment/save`
Zapisuje przydzielenia.

**Body (JSON):**
```json
{
  "date": "2026-02-13",
  "shift_number": 1,
  "assignments": [
    { "user_id": 5, "activity_id": 2, "is_suggestion": false }
  ]
}
```

---

## Statystyki (Daily Stats)

### GET `/api/daily-stats?date=YYYY-MM-DD&shift_number=N`
Pobiera statystyki i przydzielenia na dany dzień/zmianę.

### POST `/api/daily-stats`
Zapisuje/aktualizuje ilości (z audit trailem).

**Body (JSON):**
```json
{
  "date": "2026-02-13",
  "shift_number": 1,
  "entries": [
    { "user_id": 5, "activity_id": 2, "quantity": 150, "note": "" }
  ]
}
```

### PUT `/api/daily-stats/<stat_id>`
Korekta pojedynczego wpisu.

**Body (JSON):**
```json
{ "quantity": 160, "note": "poprawka" }
```

---

## Statystyki użytkownika

### GET `/api/stats/user/<user_id>`
Parametry query: `activity_id`, `date_from`, `date_to`

> Gdy brak `activity_id` (widok „Wszystkie"), do `daily`/`monthly` dołączane są syntetyczne pozycje z **zakończonych paczek** pracownika (`scan_end_by`): `📦 Paczki` (liczba) i `📦 Paczki (szt.)` (suma Stückzahl), z `stat_id: null` i `is_package: true`. Grupowane po dacie `scan_end_at`.

**Odpowiedź:**
```json
{
  "user": { ... },
  "daily": [
    { "date": "2026-02-13", "shift_number": 1, "activity": "Post Processing",
      "quantity": 120, "entered_by": "Jan Lider", "modified_by": null }
  ],
  "monthly": [
    { "month": "2026-02", "activity": "Post Processing",
      "total_quantity": 2400, "days_worked": 20, "avg_per_day": 120.0 }
  ]
}
```

---

## Admin — Czynności

| Method | URL | Opis |
|--------|-----|------|
| GET | `/api/activities` | Lista wszystkich czynności |
| POST | `/api/activities` | Dodaj czynność `{ "name": "..." }` |
| PUT | `/api/activities/<id>` | Edytuj `{ "name", "sort_order", "is_active" }` |
| DELETE | `/api/activities/<id>` | Usuń czynność |
| POST | `/api/activities/reorder` | Zmień kolejność `{ "order": [3,1,2,...] }` |

---

## Admin — Użytkownicy

| Method | URL | Opis |
|--------|-----|------|
| GET | `/api/users` | Lista użytkowników |
| POST | `/api/users` | Dodaj użytkownika |
| PUT | `/api/users/<id>` | Edytuj użytkownika |
| DELETE | `/api/users/<id>` | Dezaktywuj (soft delete) |

**POST/PUT body:**
```json
{
  "username": "jkowalski",
  "display_name": "Jan Kowalski",
  "barcode_id": "EAN128CODE",
  "role": "operator",
  "password": ""
}
```

> Hasło wymagane tylko dla ról `leader` i `admin`.

---

## Admin — Mapowanie krajów i zleceń

| Method | URL | Opis |
|--------|-----|------|
| GET | `/api/country-mappings` | Lista mapowań Country → Innenauftrag |
| POST | `/api/country-mappings` | Dodaj mapowanie `{ "country": "...", "innenauftrag": "..." }` |
| PUT | `/api/country-mappings/<id>` | Edytuj mapowanie |
| DELETE | `/api/country-mappings/<id>` | Usuń mapowanie |

**POST/PUT body:**
```json
{
  "country": "Deutschland",
  "innenauftrag": "Orsay DE"
}
```

> Wszystkie endpointy wymagają roli `admin`.

---

## Admin — Import CSV i Statystyki

| Method | URL | Opis |
|--------|-----|------|
| POST | `/api/import-csv` | Wrzucenie pliku CSV (multipart/form-data z kluczem `file`). Zwraca statystyki importowanych, pomiętych i zaaktualizowanych kartonów. |
| GET | `/api/general-stats` | Lista statystyk z importu CSV do tabeli rozliczeniowej |
| PUT | `/api/general-stats/<id>` | Edytuj statystykę: `category_data` (normalna linia) lub `double_rate_category_data` (żółta linia double rate); słownik 10 kategorii |

**PUT body dla /api/general-stats** (jedno z pól):
```json
{
  "category_data": {
    "sorting": { "amount": 25, "cost": 12.50 },
    "textile": { "amount": 0,  "cost": 0.00 }
  }
}
```
```json
{
  "double_rate_category_data": {
    "sorting": { "amount": 10, "cost": 0 }
  }
}
```

> Wszystkie endpointy wymagają roli `admin`.

---

## Paczki — podgląd, przypisanie, czas, double rate

| Method | URL | Opis |
|--------|-----|------|
| POST | `/api/scan-employee` | Weryfikacja kodu pracownika (zwraca dane pracownika) |
| GET | `/api/package-lookup?barcode=` | **Podgląd (read-only)** statusu paczki: `scanned`, `scanned_by`, `finished` + dane (land, stueckzahl, kategorie, ziel_datum, uebergabe_nr, double_rate, czasy) |
| PUT | `/api/packages/<id>/assign` | Przepisanie paczki do pracownika `{ "user_id": 5 }` (lub `null`) |
| PUT | `/api/packages/<id>/double-rate` | Oznaczenie paczki jako double rate `{ "double_rate": true }` |
| POST | `/api/package-time/start` | Rejestracja startu procesowania `{ "employee_barcode", "package_barcode" }` |
| POST | `/api/package-time/end` | Rejestracja końca + czas procesowania (to samo body) |

**Blokady czasu paczek** (`/api/package-time/*`):
- Paczkę w trakcie (start bez końca) obsługuje **tylko** pracownik, który ją rozpoczął:
  - inny pracownik robi start → `409` „nie można podebrać"
  - inny pracownik robi koniec → `403` „tylko on może zakończyć"
  - ten sam pracownik robi start ponownie → `200`, start bez zmian
- Paczka **zakończona** jest zablokowana: ponowny start → `409`, ponowny koniec → `409`

**Definicje statusu w `/api/package-lookup`:**
- `scanned` = ma `processed_by` **lub** `scan_start_at`
- `scanned_by` = pracownik z przypisania, w razie braku → kto zrobił start
- `finished` = ma `scan_end_at`

> `/api/package-lookup` i `/api/package-time/*` wymagają roli `leader`+.
