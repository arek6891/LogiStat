# LogiStat — API Reference

Wszystkie endpointy API wymagają zalogowania jako leader lub admin (chyba że zaznaczono inaczej).

---

## Autentykacja

| Method | URL | Opis |
|--------|-----|------|
| POST | `/login` | Logowanie (form: `username`, `password`) |
| GET | `/logout` | Wylogowanie |

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
