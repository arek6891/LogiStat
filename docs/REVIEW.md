# LogiStat — lista kontrolna przeglądu kodu

Każdy PR przed scaleniem: **zielone CI** (pytest na Postgresie, pyright, składnia JS)
i przegląd według tej listy. Przegląd robimy **przed** scaleniem i wdrożeniem, nie po
(błąd podwójnych minut z PR #31 wyszedł dopiero po wdrożeniu na `.31`).

Szczegóły i uzasadnienia każdej reguły: `CLAUDE.md` i `docs/ARCHITEKTURA.md`.

## 1. Baza i schemat
- [ ] Nowa **kolumna** → `migrate_columns()` + przypadek w `tests/test_migracje.py`
      (`create_all()` nie dokłada kolumn, zwykłe testy tego nie widzą).
- [ ] `"user"` w SQL w cudzysłowie. JSON tylko w `db.Text` przez `get_…()` / `set_…()`.
- [ ] Zmiana danych na żywej bazie = jednorazowa migracja w `init_db()` pod advisory
      lockiem, ze znacznikiem w `AppSetting`.

## 2. Rozliczenie (pieniądze)
- [ ] Linia przeliczana **z sumy**, nigdy przyrostowo; klucz zawsze przez `klucz_linii()`.
- [ ] Linie `'manual'` nietknięte przez przeliczenie; linie `'scan'` odrzucają ręczny zapis.
- [ ] Ilości rozliczenia przez `liczba()`, nigdy `int()` (×1,5 daje połówki).
- [ ] Zmiana mapowania tabeli → `kategorie_z_tabeli()` **i** `ZRODLO_KATEGORII` (dymki).
- [ ] Total Amount w trzech miejscach naraz: Jinja, JS po edycji, `write_data_row()`.
- [ ] Lider nie dostaje kosztów ani stawek (ekran, Excel, źródło strony).

## 3. Czas i daty
- [ ] „Dziś” = `local_today()`, doba = `local_day_bounds()` (półotwarta); nigdy
      `date.today()` ani `func.date()`.
- [ ] Zapis naive UTC, API `iso_z()` tylko dla datetime; Jinja `| localdt`.
- [ ] Przypadki brzegowe w testach: **północ**, zmiana czasu, zakres dat zaczynający się
      po starcie paczki, okresy **równoległe** (ta sama minuta liczona raz).

## 4. Jedna definicja
- [ ] „Kto ile zrobił” tylko `prace_osob()`; szt./h tylko `policz_wydajnosc()`; ocena osoby
      = wiersz z `przeglad_zespolu()`. Żadnego drugiego liczenia „po swojemu”.

## 5. Uprawnienia i współbieżność
- [ ] Każda trasa ma `@leader_required` / `@admin_required`; `/api/general-stats*` admin.
- [ ] Zapis ze stanowiska: karton `with_for_update()`; przydział sprawdza `wersja`.
- [ ] Błędy `/api/` jako JSON (`abort(400, '…')`), komunikat po polsku, mówi co poprawić.

## 5b. Trasy
- [ ] Adresy i metody bez zmian (`tests/test_trasy.py` + `tests/mapa_adresow.txt`); nowa trasa
      = aktualizacja pliku w tym samym PR.
- [ ] Zmiana nazwy endpointu (blueprint) → wszystkie `url_for`, `login_view`,
      `BEZ_WYMOGU_ZMIANY_HASLA` w tym samym PR.
- [ ] Moduly `logistat/` nie importuja `app.py` (test w podprocesie).

## 6. Frontend
- [ ] Dane z bazy do `innerHTML` przez `escapeHtml()`.
- [ ] JSON w atrybucie HTML: `data-x='{{ v | tojson }}'` (apostrofy).
- [ ] Kolory tylko tokenami (`var(--x)`, `rgb(var(--x-rgb) / a)`); wykresy przez `motyw()`;
      tekst na zielonym tle `var(--on-accent)`.
- [ ] Ekrany zbiorcze: autozapis wg zasad (`autoZapis.poWpisaniu`, `przedOpuszczeniem()`).
- [ ] Nowe okno z polami: `data-modal-guard`. Stanowisko: Enter skanera nie może niczego
      zaakceptować (fokus na bezpiecznym przycisku).
- [ ] Teksty dla użytkownika: „Loading date”, nie „data pliku”.

## 7. Wydajność
- [ ] Lista po paczkach / osobach bez N+1 (`selectinload` / `joinedload`; test liczby zapytań).

## 8. Testy i dokumentacja
- [ ] Test na każdą nową regułę i na każdy naprawiony błąd (najpierw czerwony).
- [ ] Ten sam commit: reguła w `CLAUDE.md`, sekcja w `docs/ARCHITEKTURA.md`,
      `docs/CHANGELOG.md`, `docs/API.md` przy zmianie API; licznik testów w `CLAUDE.md`.

## 9. Po wdrożeniu
- [ ] `docker exec -w /app logistat-test python scripts/sprawdz_spojnosc.py` → „Spójność: OK.”
      (BŁĄD = rozjechane dane, wyjaśnić przed kolejną pracą; UWAGA = sprawy dla liderów).
