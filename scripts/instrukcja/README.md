# Zrzuty ekranu do instrukcji użytkownika

Instrukcja dla użytkowników SARA to dokument Claude Docs:
https://claude.ai/artifact/Y1MBNPjaHrAVKSbYcupNdB (od 2026-11-04). Tu leży to, czym robi się do niej
zrzuty — na **fikcyjnych danych** (osobna baza demo), nigdy z `.31` / `.30`.

## Odświeżenie zrzutów (na .32)

```bash
# 1. Baza demo na testowym Postgresie (port 55432, tmpfs — znika przy restarcie)
docker compose -f docker-compose.test.yml up -d
docker exec logistat-test-pg psql -U logistat -d logistat_test \
  -c "drop database if exists logistat_demo" -c "create database logistat_demo"

# 2. Aplikacja demo na :5099 z aktualnym kodem (admin / DemoAdmin2026)
docker run -d --name logistat-demo --network host -v /opt/LogiStat:/app:ro -w /app \
  -e PYTHONDONTWRITEBYTECODE=1 -e TZ=Europe/Warsaw -e ADMIN_PASSWORD=DemoAdmin2026 \
  -e DATABASE_URL=postgresql+psycopg2://logistat:logistat@127.0.0.1:55432/logistat_demo \
  -e SECRET_KEY=$(openssl rand -hex 32) \
  logistat-testrunner:latest gunicorn -b 127.0.0.1:5099 -w 1 --threads 4 app:app

# 3. Dane demo (10 fikcyjnych osób, 2 tygodnie paczek, zwroty, akcje Dekoracji;
#    konta lider / DemoLider2026, stanowisko1-2 / DemoSt2026)
docker exec -e LOGISTAT_BEZ_INIT=1 logistat-demo python /app/scripts/instrukcja/dane_demo.py
docker exec -e LOGISTAT_BEZ_INIT=1 logistat-demo python /app/scripts/instrukcja/dane_demo_zadania.py
# Zrzut blokady bez obsady potrzebuje konta stanowisko3 bez przydziału — załóż je
# (rola stanowisko, hasło DemoSt2026) w Panelu Admina albo skryptem przed zrzutami.
# Przydział do stanowisk zwrotów wygasa po 12 h — przed zrzutami Przyjęcia zwrotu:
docker exec logistat-test-pg psql -U logistat -d logistat_demo \
  -c "update przydzial_zwrotow set od = (now() at time zone 'utc') - interval '2 hours'"
```

4. Zrzuty robi Claude przez MCP Playwright: `browser_run_code_unsafe` z `filename` =
   kopia `zrzuty_stanowisko.js` / `zrzuty_lider.js` w `/opt/LogiStat/.playwright-mcp/`
   (MCP czyta i pisze tylko tam). PNG lądują w `.playwright-mcp/zrzuty/`. Każdy zrzut to lista
   ramek z numerkami: `{sel | text, n, tekst?, gdzie, odl?, dx?}` — skrypt zwraca numery, których
   nie znalazł na stronie.
5. Wgranie do dokumentu: `Artifact` publish `asset: true` na link dokumentu → `create blob` →
   `![opis](blob/<id>)` w odpowiedniej sekcji.
6. Sprzątanie: `docker rm -f logistat-demo`.

Ekrany jeszcze bez zrzutów: Import danych, Forecast, Statystyki ogólne, Etykiety POS,
Stock stojaków, Invoice specification, Sorting Data, Dashboard zwrotów.
