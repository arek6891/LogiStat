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

## Format błędów

Wszystkie błędy na ścieżkach `/api/` wracają jako **JSON**, nie HTML — dotyczy to także
`404` z `get_or_404` i `405`. Front wszędzie czyta `data.error`.

```json
{ "error": "Nieprawidłowa data w \"date_from\" (oczekiwano YYYY-MM-DD)." }
```

| Kod | Kiedy |
|---|---|
| `400` | Błędne wejście — zła data, nieliczbowe pole, brakujący klucz, nieznany FK. Wcześniej część tych przypadków kończyła się `500`. |
| `403` | Brak uprawnień do konkretnej operacji (patrz *Admin — Użytkownicy*, edycja paczki z importu) |
| `404` | Nie ma takiego zasobu |
| `409` | Konflikt — duplikat barcode, paczka zajęta przez innego pracownika, praca już zakończona |
| `413` | Plik importu większy niż `MAX_UPLOAD_MB` (domyślnie 32 MB) |

Żądania bez ciała albo ze złym `Content-Type` są traktowane jak puste `{}`, więc dają
`400` z nazwą brakującego pola, a nie `415`.

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

Odpowiedź zawiera też `wersja` — odcisk aktualnego przydziału zmiany (do wykrywania konfliktów, patrz niżej).

### POST `/api/assignment/save`
Zapisuje przydzielenia — **podmienia cały przydział zmiany** (ekran wysyła go po każdym przeciągnięciu).

**Body (JSON):**
```json
{
  "date": "2026-02-13",
  "shift_number": 1,
  "assignments": [
    { "user_id": 5, "activity_id": 2, "is_suggestion": false }
  ],
  "wersja": "3f2a9c0d1e4b5a67"
}
```

- `wersja` (opcjonalna) — wersja wczytana z `/api/assignment/data` albo z odpowiedzi poprzedniego zapisu. Jeśli ktoś inny zmienił przydział tej zmiany w międzyczasie → **409** `{error, konflikt: true, wersja}` i **nic nie jest zapisane**. Bez `wersja` zapis działa jak dawniej (bez sprawdzania).
- Zapis blokuje wiersz zmiany (`SELECT … FOR UPDATE`), więc równoległe zapisy tej samej zmiany idą po kolei.
- Odpowiedź: `{message, wersja}` — nowa wersja do kolejnego zapisu.

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

## Admin — Ustawienia

| Method | URL | Opis |
|--------|-----|------|
| PUT | `/api/category-labels` | **Nazwy kategorii dla pracownika** (admin). Body: `{nazwy: {kategoria: "polska nazwa"}}` — dowolny podzbiór kategorii. Pusta nazwa (albo równa domyślnej) = powrót do domyślnej. Maks. 60 znaków, spacje ściskane. Nieznana kategoria / zły typ / za długo → 400. Zwraca `{message, etykiety}` — etykiety w formacie „Polska (English)”. Angielskiej części nie da się zmienić. |
| PUT | `/api/settings` | Zapis ustawień systemowych (admin). Klucze czasu pracy: `break_threshold_minutes` (30), `max_work_minutes` (660), `min_break_minutes` (15). Klucze przeglądu wydajności: `norm_good_pct` (110), `norm_weak_pct` (90), `min_packages_rank` (3). Każdy liczbą ≥ 1, wszystkie opcjonalne. Przechowywane w tabeli `AppSetting`. Zła wartość → 400 i **nic się nie zapisuje**. |

## Dashboard

| Method | URL | Opis |
|--------|-----|------|
| GET | `/api/dashboard` | Dane dashboardu dziennego (dziś): `done_today` + `pieces_today` (zakończone dziś wg czasu skanu), `present_count`, `workers_today[]`, `activities_today[]`, `per_worker[]`, **`plik_dzis`** (plan dzisiejszego pliku — kształt jak `/api/dashboard/plik`) i **`zalegle`** `{paczek, sztuk, dni: [{data_pliku, paczek, sztuk, w_toku}]}` — wszystkie niezakończone paczki wg daty pliku, od najstarszej. Pola `remaining_*`, `total_cartons`, `done_cartons`, `progress_pct` zostają w odpowiedzi dla zgodności, ekran ich już nie pokazuje. |
| GET | `/api/dashboard/plik?date=YYYY-MM-DD` | **Plan dnia pliku** (domyślnie dziś): `{data_pliku, paczek, sztuk, zrobione, zrobione_sztuk, pozostalo, pozostalo_sztuk, w_toku, procent}`. „Zrobione” = paczka tego pliku ma `scan_end_at`, niezależnie od dnia zakończenia. |
| GET | `/api/dashboard/shifts?date=YYYY-MM-DD` | **Podział per zmiana** dla wybranego dnia (domyślnie dziś). Zwraca `shifts[]` (zmiana 1 i 2: `present_count`, `packages`, `pieces`, `activities[]`) oraz `unattributed` (paczki pracowników bez jednoznacznej obecności). Paczki przypisywane do zmiany wg obecności pracownika (`ShiftAttendance`); DailyStat wg `shift_id`. |

## Normy (`/stats`) — przegląd zespołu

### GET `/api/stats/overview?date_from=&date_to=`
Przegląd wydajności **wszystkich** pracowników (lider+) — zakładka „Przegląd ogólny" na `/stats`.

Liczone z **zakończonych paczek**, nie z `DailyStat` (wpis ilości jest uzupełniany sporadycznie, skan paczek leci przy każdej sztuce). Miara: **sztuki na godzinę skanowania**.

Czas to **suma złączonych okresów** `(scan_start_at, scan_end_at)`, nie suma ich długości — dwie paczki otwarte równocześnie liczyłyby ten sam kwadrans dwa razy. Mianownikiem jest czas *skanowania*, nie czas obecności: przerwy i „Inne" go nie pomniejszają.

Odniesieniem jest **średnia zespołu** z okresu = **wszystkie sztuki / wszystkie godziny skanowania** (do 2026-09-28 była to mediana), a **nie zadana norma** — takiej system nie przechowuje. Do średniej wchodzą **wszyscy** ze zmierzonym czasem, także osoby z „za mało danych", ale każdy waży tyle, ile przepracował — dlatego konto z dwiema błyskawicznymi paczkami nie wypacza wyniku. Paczki bez zmierzonego czasu do średniej nie wchodzą. Próg `min_paczek` decyduje tylko o miejscu w rankingu i ocenie.

```json
{
  "date_from": "2026-08-22", "date_to": "2026-09-21",
  "srednia_szt_h": 300.0,
  "progi": { "dobry": 110, "slaby": 90, "min_paczek": 3 },
  "pracownicy": [
    { "user_id": 12, "display_name": "...", "is_active_user": true,
      "worker_type": "Logwin", "shift_group": "Zmiana A", "paczek": 8, "sztuk": 731,
      "godzin": 1.86, "szt_h": 392.3, "proc_sredniej": 131, "ocena": "dobra" }
  ],
  "za_malo_danych": [ { "…": "…", "szt_h": null, "ocena": null } ],
  "podsumowanie": { "osob": 11, "w_rankingu": 9, "paczek": 91, "sztuk": 6961, "godzin": 22.8 }
}
```

`worker_type` / `shift_group` — nazwy pozycji z kont (Rodzaj pracownika, Nazwa zmiany), `null` gdy nieprzypisane; w obu listach (`pracownicy`, `za_malo_danych`).

`ocena`: `dobra` (≥ `norm_good_pct`) · `ok` · `slaba` (≤ `norm_weak_pct`). Oba progi są **domknięte**.

**Cel wpisany przez lidera** (`target_szt_h`, 0 = nieustawiony) dokłada `cel_szt_h`, `spelnia_cel` oraz per pracownik `proc_celu` i `ocena_celu` — **obok** kolumn średniej, nie zamiast nich. Ocena celu jest **dwustanowa**: `spelnia` (≥ 100%) albo `ponizej`. Celowo nie używa pasm `norm_good_pct`/`norm_weak_pct` — te opisują odchylenie od średniej zespołu, a „równo w celu" musi znaczyć „spełnia". Przy nieustawionym celu albo pustym rankingu `spelnia_cel` = `null` (nie 0 — „0 / 0" czytałoby się jak komplet).

### PUT `/api/stats/target`
Ustawia docelową wydajność (**lider+**, inaczej niż admin-only `PUT /api/settings`).

```json
{ "target_szt_h": 250 }
```

Liczba całkowita ≥ 0; **0 wyłącza** kolumnę celu. Zapis trafia też do `historia_celu` jako cel od dziś (ostatni zapis dnia wygrywa) — paczki ze szkolenia liczą się celem z dnia paczki. Endpoint przyjmuje **wyłącznie ten klucz** — nie jest furtką do reszty `AppSetting`. Uzasadnienie uprawnień: cel jest informacyjny (koloruje kolumnę), nie dotyka rozliczeń ani żadnej blokady, a poprzeczkę ustala lider prowadzący zmianę.

**Skok do paczek:** każdy wiersz przeglądu linkuje do `/paczki?osoba=<id>&date_typ=koniec&date_from=&date_to=` — paczki, które złożyły się na wynik, w tym samym zakresie dat. `date_typ=koniec` sam zdejmuje domyślne „tylko niezrobione".

**`za_malo_danych`** — osoby poniżej `min_packages_rank` paczek albo bez zmierzonego czasu (`szt_h: null`). Nie są ukrywane: pracowały, tylko nie ma z czego liczyć średniej. Bez tego progu konto z jedną błyskawiczną paczką ląduje na szczycie rankingu (na `.31` realnie: 26 038 szt./h przy 2 paczkach).

Zakres dat filtruje `scan_end_at` przez `local_day_bounds()`, górna granica półotwarta.

**Szkolenie (🎓):** czas paczki nakładający się na szkolenie osoby szkolącej liczy się jako 100% celu z dnia paczki; reszta paczki — proporcjonalny ułamek prawdziwych sztuk. Te fragmenty nie wchodzą do `srednia_szt_h`. Wiersz (i punkty wykresów `/api/stats/user`) ma `paczek_szkolenia` i `godzin_szkolenia`; `sztuk` zostaje prawdziwe, więc u szkolącego `szt_h` ≠ `sztuk / godzin`.

**Osoba szkolona (🎓):** czas jej paczek z czasu bycia szkoloną wypada w całości (czas + proporcjonalne sztuki), niezależnie od celu; poza średnią. Pola `paczek_jako_szkolony`, `godzin_jako_szkolony`, `paczek_do_oceny` (to od niej zależy próg `min_packages_rank`). Wszystko wyłączone → `powod_braku_oceny: "szkolony"`.

## Normy — statystyki użytkownika

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
  ],
  "paczki_podsumowanie": {
    "paczek": 92, "sztuk": 6228, "dni_pracy": 5, "miesiecy_pracy": 1,
    "srednio_dziennie": { "paczek": 18.4, "sztuk": 1245.6 },
    "srednio_miesiecznie": { "paczek": 92.0, "sztuk": 6228.0 }
  }
}
```

`paczki_podsumowanie` liczy się **zawsze**, także przy wybranym `activity_id`. Mianownikiem są
dni i miesiące, w których osoba zakończyła choć jedną paczkę, a nie dni kalendarzowe
zakresu — dzień wolny nie zaniża średniej. Bez paczek średnie mają wartość `null`, nie 0.

**`norma`** — ocena na tle zespołu, **wiersz wyjęty z tego samego `przeglad_zespolu()`** co
`/api/stats/overview` (te same średnia, progi, cel), więc `% średniej` i ocena zgadzają się
z rankingiem dla tego samego zakresu:
```json
"norma": {
  "srednia_szt_h": 292.0, "cel_szt_h": null,
  "progi": { "dobry": 110, "slaby": 90, "min_paczek": 3 },
  "miejsce": 2, "w_rankingu": 9,
  "powod_braku_oceny": null,
  "wiersz": { "szt_h": 330.1, "proc_sredniej": 113, "ocena": "dobra", "…": "jak w overview" }
}
```
`powod_braku_oceny`: `null` (oceniony) · `za_malo_paczek` · `brak_czasu` (paczki bez skanu
„Start") · `brak_paczek` (`wiersz` = `null`).

**`wykres_dzienny` / `wykres_miesieczny`** — lista `{okres, paczek, sztuk, godzin, szt_h}`
rosnąco po `okres` (`YYYY-MM-DD` / `YYYY-MM`), tylko dni/miesiące z zakończoną paczką.
`godzin` = suma **złączonych** okresów skanowania; bez zmierzonego czasu `szt_h` = `null`.
`norma`, wykresy i `paczki_podsumowanie` **nie zależą** od `activity_id`.

Ekran `/stats?user=<id>[&date_from=&date_to=]` otwiera od razu zakładkę tej osoby — tak
linkuje dashboard (`user_id` jest w `workers_today` i `unattributed.workers`).

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
  "password": "",
  "worker_type_id": 1,
  "shift_group_id": 4,
  "is_trainer": false
}
```

> Hasło wymagane tylko dla ról `leader` i `admin`.

> `worker_type_id` (rodzaj pracownika) i `shift_group_id` (nazwa zmiany) to id pozycji z
> `/api/user-options` danego rodzaju; `null` / `""` = brak. Pozycja nieistniejąca albo
> z **drugiej** listy → **400**. Pominięte w PUT = bez zmian. Lider może je ustawiać
> operatorom (to dane opisowe). Odpowiedź zawiera też nazwy: `worker_type`, `shift_group`.

**Uprawnienia (od 2026-09-01).** Wszystkie cztery endpointy są `@leader_required`, bo
lider zakłada operatorów na zmianie — ale ma własne guardy, żeby nie dało się przez nie
zdobyć admina:

| Operacja | operator jako cel | lider / admin jako cel |
|---|---|---|
| POST z `role` = `leader`/`admin` | — | **403**, tylko admin |
| PUT zmieniający `role` | **403** dla nie-admina | **403** dla nie-admina |
| PUT ustawiający `password` | **403** dla nie-admina | **403** dla nie-admina |
| PUT / DELETE na koncie uprzywilejowanym | — | **403** dla nie-admina |

Dodatkowo: nieznana rola → **400**; zdegradowanie lub dezaktywacja **ostatniego aktywnego
admina** → **400** (żeby nie dało się zablokować dostępu do panelu).

Soft-delete (`DELETE`) ustawia `is_active_user=False`, co **odbiera też trwającą sesję** —
`login()` i `load_user()` sprawdzają tę flagę.

---

## Admin — Listy na koncie użytkownika

Pozycje list rozwijanych „Rodzaj pracownika" (`kind: worker_type`, seed: Logwin,
Agencja 1, Agencja 2) i „Nazwa zmiany" (`kind: shift_group`, seed: Zmiana A/B/C).
Ekran: `/admin/user-options` (Panel Admina → Listy użytkowników).

| Method | URL | Opis |
|--------|-----|------|
| GET | `/api/user-options` | `{worker_type: [...], shift_group: [...]}` — **lider+** (wybiera z nich przy zakładaniu operatora) |
| POST | `/api/user-options` | Body `{kind, name}` — admin. Pusta nazwa / nieznany `kind` → 400, duplikat w tej samej liście → 409 |
| PUT | `/api/user-options/<id>` | Body `{name}` — admin. Zmiana nazwy obowiązuje u wszystkich przypisanych (konto trzyma id) |
| DELETE | `/api/user-options/<id>` | Admin. Pozycja przypisana komukolwiek → **409** z liczbą osób |

---

## Czas pracy

| Method | URL | Opis |
|--------|-----|------|
| POST | `/api/time/scan` | Skan kodu pracownika na `/time-tracking`. Body: `{ "barcode": "...", "mode": "break" \| "other" \| "work_end" }`. Tryby `break` i `other` **przełączają** stan (liczony z `count(*_start) - count(*_end)`, brak flagi na User); `work_end` zamyka pracę i **auto-domyka otwartą przerwę, „Inne" i szkolenie** (szkolący → kończy też jego szkolonych). Przerwa, „Inne", prowadzenie szkolenia i bycie szkolonym nie mogą trwać jednocześnie → 409. `mode: "training"` → 400 (szkolenie ma własne endpointy niżej). |
| GET | `/api/time/training/aktywne` | Trwające dziś szkolenia: `{szkolenia: [{trener, trwa, od, szkoleni[]}]}`. |
| POST | `/api/time/training/trener` | Krok 1, `{barcode}` szkolącego. **Nic nie zapisuje** — zwraca `{trener, trwa, od, szkoleni}`. Bez `is_trainer` → 403, nieobecny → 400, koniec pracy / przerwa / „Inne" / sam szkolony → 409. |
| POST | `/api/time/training/szkolony` | Krok 2, `{trener_id, barcode}` szkolonego. Pierwszy szkolony **zaczyna** szkolenie (`training_start` + `trainee_start`, ten sam czas); kolejni dołączają. Nieznany kod → 404, kod szkolącego → 400, nieobecny → 400, koniec pracy / przerwa / „Inne" / inne szkolenie / już na tym szkoleniu → 409. |
| POST | `/api/time/training/koniec` | Krok 3, `{trener_id}`. Koniec dla szkolącego i wszystkich jego szkolonych, ten sam czas. Szkolenie nie trwa → 409. Brak kodu / nieznany tryb → 400, nieznany pracownik → 404, brak obecności dziś → 400, praca już zakończona → 409. |
| GET | `/api/worker-times?date=YYYY-MM-DD` | Podsumowanie per pracownik: `shift_in`, `break_minutes`, `other_minutes`, `training_minutes`, `trainee_minutes`, `work_minutes`, `breaks[]`, `others[]`, `trainings[]`, `trainee_periods[]`, `on_break`, `on_other`, `on_training`, `on_trainee`, `work_ended`, `events[]`. Jeden wpis na pracownika — brana jest **najwcześniejsza** obecność w danym dniu. Czas „Inne" **pomniejsza `work_minutes` tak samo jak przerwa**, ale jest raportowany osobno. Szkolenie (prowadzone i jako szkolony) **nie pomniejsza** `work_minutes` (to praca). Filtr po pracowniku i filtr błędów działają w przeglądarce na tych danych — API ich nie przyjmuje. |
| POST | `/api/worker-times/event` | Ręczne zdarzenie (korekta). Body: `user_id`, `shift_id`, `event_type` (`break_start` \| `break_end` \| `other_start` \| `other_end` \| `training_start` \| `training_end` \| `trainee_start` \| `trainee_end` \| `work_end`), `timestamp` (naive UTC ISO), opcjonalnie `note`. Ustawia `is_manual=True` i `recorded_by`. → **201**. Nieznany `user_id`/`shift_id` lub zły typ → 400; `training_start` dla osoby bez `is_trainer` → 400. |
| PUT | `/api/worker-times/event/<id>` | Edycja zdarzenia (`event_type`, `timestamp`, `note`) |
| DELETE | `/api/worker-times/event/<id>` | Usunięcie zdarzenia |

> `timestamp` jedzie jako **naive UTC**. Przeglądarka wysyła `new Date(local).toISOString().slice(0,19)`, a serwer zapisuje to bez konwersji — patrz sekcja o czasie w `CLAUDE.md`.

---

## Forecast

| Method | URL | Opis |
|--------|-----|------|
| GET | `/api/forecast/chart-data?date_from=&date_to=` | Prognoza vs wykonanie, dzień po dniu. Zwraca listę `{date, forecast, actual, diff, notes}`, gdzie **`diff = actual − forecast`** (minus = przyjechało mniej niż plan; do 2026-10-08 było odwrotnie). Ten sam znak w eksporcie Excel (kolumna „Różnica (A-F)”). `actual` = suma `stueckzahl` paczek z daną **datą pliku** (do 2026-10: `ziel_datum`). Domyślny zakres: −7 / +14 dni. Zła data → cichy powrót do domyślnej. |
| POST | `/api/forecast/save` | Zapis prognozy. Body: obiekt **albo lista** obiektów `{date, quantity, notes}`. Upsert po dacie. Wiersz z niesparsowalną datą jest **pomijany po cichu**; nieliczbowe `quantity` → 400. Zwraca `{message, saved}`. |
| GET | `/api/forecast/export?date_from=&date_to=` | Eksport XLSX z wykresem słupkowym (forecast vs actual) |

---

## Admin — Stawki kosztów

| Method | URL | Opis |
|--------|-----|------|
| GET | `/api/cost-mapping/<year>/<month>` | Stawki na dany miesiąc — zwraca **bezpośrednio** słownik `{kategoria: stawka}`; brak wpisu → `{}` |
| PUT/POST | `/api/cost-mapping/<year>/<month>` | Zapis stawek. Body: `{ "rates": { "textile": 0.25, ... } }`. Upsert po `(year, month)`. Zwraca `{success, mapping}`. |

> Koszt linii = `amount × stawka` z miesiąca jej `loading_date`. Stawki są czytane przez
> `rates_for()` z cache na jedno żądanie — lista statystyk nie odpytuje bazy per wiersz.

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

## Admin — Import CSV / Excel i Statystyki

| Method | URL | Opis |
|--------|-----|------|
| POST | `/api/import-csv` | Wrzucenie pliku CSV (`;`-separowany, multipart/form-data: `file` + **`data_pliku`** `YYYY-MM-DD`, wymagane). Brak / zła data pliku → 400 i nic nie jest importowane. Każda paczka dostaje tę datę i **jeden wspólny `imported_at`**. Linie Statystyk ogólnych: Übergabe Nr + kraj + **data pliku** (Ziel-Datum nie grupuje i nie jest wymagana). Zwraca statystyki importowanych, pominiętych i zaktualizowanych kartonów. |
| POST | `/api/import/excel` | Wrzucenie pliku Excel `.xlsx` (multipart/form-data: `file` + **`data_pliku`**, wymagane). Te same kolumny, reguły i odpowiedź co import CSV. ⚠️ numeryczną kolumnę barcode formatować jako tekst (Excel float64 traci precyzję dla długich kodów). |
| GET | `/api/imports` | **Lista importów** do poprawy daty (leader+). Import = paczki jednej osoby z jednej minuty i jednej daty pliku. Filtry (opcjonalne): `data_pliku`, `dzien_importu` (dzień lokalny), `godz_od` / `godz_do` (`HH:MM` czasu polskiego), `osoba` (id). Zwraca `{importy: [{klucz, osoba_id, osoba, login, imported_at, data_pliku, paczek, sztuk, zrobionych, recznych}], osoby: [{id, nazwa, login}], ucieto}` — najwyżej 300 importów, od najnowszego. Zła godzina → 400. |
| POST | `/api/imports/zmien-date` | **Grupowa zmiana daty pliku** (leader+). Body: `{importy: [klucz, …], nowa_data: "YYYY-MM-DD", podglad: bool}`. Z `podglad: true` zwraca skutki i **nic nie zapisuje**: `{paczek, juz_z_ta_data, sztuk, zrobionych, linii_przenoszonych, linii_dzielonych, linii_docelowych_istniejacych, konflikty}`. Bez podglądu zmienia datę, ustawia `modified_by/at` paczek i przelicza linie. Linia przenoszona w całości zabiera ręczne ilości (łączy się z istniejącą linią nowej daty, ręczne ilości sumowane). **409** + `konflikty` gdy trzeba by podzielić ręczne ilości linii albo połączyć ręczne ilości z ilościami ze skanów. Brak zaznaczenia / brak daty / zły klucz → 400; importy bez paczek → 404. |
| POST | `/api/packages` | **Ręczne dodanie paczki** (leader+). JSON: `barcode`, `stueckzahl`, `land`, **`data_pliku`** (`YYYY-MM-DD`), `uebergabe_nr` **(wymagane)** + `ziel_datum`, `kategorie`, `double_rate` (opcjonalne). Przechodzi przez ten sam pipeline co import (agregacja do GeneralStat). Ustawia `added_manually=True` i `imported_by`. Duplikat barcode → 409, brak pól / zła ilość / zła data → 400. |
| PUT | `/api/packages/<id>` | **Edycja paczki** (leader+). Te same pola i walidacja co POST. Dozwolona **tylko** dla paczek `added_manually` (paczka z importu → 403). Zmiana `uebergabe_nr`/`land`/`data_pliku` przelicza dotknięte linie GeneralStat od zera z sumy paczek. Zmiana barcode na istniejący → 409. Ustawia `modified_by`/`modified_at`. |
| GET | `/api/general-stats` | Lista statystyk z importu CSV do tabeli rozliczeniowej. Opcjonalne `?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD`; bez nich zwraca wszystko. Zła data → 400. |
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
| GET | `/api/package-lookup?barcode=` | **Podgląd (read-only)** statusu paczki: `scanned`, `scanned_by`, `finished` + dane (land, stueckzahl, kategorie, ziel_datum, uebergabe_nr, double_rate, czasy) |
| PUT | `/api/packages/<id>/assign` | Przepisanie paczki do pracownika `{ "user_id": 5 }` (lub `null`) |
| PUT | `/api/packages/<id>/double-rate` | Oznaczenie paczki jako double rate `{ "double_rate": true }` |
| GET | `/api/employee-lookup?barcode=` | **Krok 1 na `/scan-paczki`** — sprawdza kod pracownika przed skanem paczki: `200 { user: { id, display_name } }`; nieznany/nieaktywny → `404`; kod paczki zamiast identyfikatora → `400` |
| POST | `/api/package-time/start` | Rejestracja startu procesowania `{ "employee_barcode", "package_barcode" }` |
| POST | `/api/package-time/end` | Rejestracja końca + czas procesowania (to samo body) |
| POST | `/api/packages/<id>/unlock-scan` | **Odblokowanie paczki** rozpoczętej i nigdy nie zakończonej (lider+): kasuje `scan_start_at`/`scan_start_by`, ustawia `modified_by`/`modified_at`. Paczka wraca do stanu „nierozpoczęta". Paczka zakończona → 409, nierozpoczęta → 400. |

**Filtry na `/paczki`** (query string): `date_from`, `date_to`, `date_typ`, `barcode`,
`land`, `osoba` (id — kto przejął / rozpoczął / zakończył), `double_rate=1`,
`status`, `bledy=1`, `page`. **`status`**: `niezrobione` (domyślne — bez `scan_end_at`) ·
`zrobione` (tylko z `scan_end_at`) · `wszystkie`. Stary `pokaz_zrobione=1` działa jako
alias `status=wszystkie`. `bledy=1` ignoruje status (błąd ilości występuje na
paczce już zakończonej) i liczy się w Pythonie — ilości ze skanu to JSON w kolumnie
tekstowej, SQL ich nie przefiltruje.

`date_typ` wybiera, **po którym polu daty** działa zakres `date_from`/`date_to`:

| `date_typ` | Pole | Uwagi |
|---|---|---|
| `ziel` (domyślne) | `ziel_datum` | `db.Date` — porównanie wprost |
| `import` | `imported_at` | naive UTC → granice doby przez `local_day_bounds()` |
| `start` | `scan_start_at` | j.w. |
| `koniec` | `scan_end_at` | j.w.; przy `status=niezrobione` serwer przestawia na **`zrobione`**, bo inaczej wynik zawsze byłby pusty |

Górna granica jest półotwarta (`<` północ następnej doby lokalnej) — `<=` wciągałoby
paczki z pierwszych godzin kolejnego dnia. Nieznana wartość `date_typ` → `ziel`.

**`status=zrobione` i `status=wszystkie` wymagają zakresu dat** (`date_from` lub `date_to`). Bez niego widok
obejmowałby całą historię, więc status wraca do `niezrobione`, a strona pokazuje komunikat
i widok domyślny. W formularzu pilnuje tego JS; warunek po stronie serwera łapie ręcznie
sklejony URL i zakładkę.

**Blokady czasu paczek** (`/api/package-time/*`):
- Paczkę w trakcie (start bez końca) obsługuje **tylko** pracownik, który ją rozpoczął:
  - inny pracownik robi start → `409` „nie można podebrać"
  - inny pracownik robi koniec → `403` „tylko on może zakończyć"
  - ten sam pracownik robi start ponownie → `200`, start bez zmian
- Paczka **zakończona** jest zablokowana: ponowny start → `409`, ponowny koniec → `409`
- Start i koniec czytają karton z `SELECT … FOR UPDATE` — dwa równoległe żądania tej samej
  paczki nie przejdą obu kontroli (drugie dostaje `409`)
- **Kod pracownika w polu paczki** (`package-lookup`, `start`, `end`) → `400`
  z `kod_pracownika: true` i nazwiskiem w `error`; naprawdę nieznany kod dalej `404`

**Definicje statusu w `/api/package-lookup`:**
- `scanned` = ma `processed_by` **lub** `scan_start_at`
- `scanned_by` = pracownik z przypisania, w razie braku → kto zrobił start
- `finished` = ma `scan_end_at`

> `/api/package-lookup` i `/api/package-time/*` wymagają roli `leader`+.
