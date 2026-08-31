# Wdrożenie LogiStat

Stan na 2026-08-31.

## Środowiska

| Środowisko | Serwer | Adres | Baza | Stan |
|---|---|---|---|---|
| dev | `10.153.1.32` (pllas01) | `http://10.153.1.32:5001` | SQLite | działa |
| **test** | `10.153.1.31` (ploptmtst01) | **`https://logistat-test.logwin-logistics.com.pl/`** | PostgreSQL 16 | działa |
| prod | `10.153.1.30` | `https://logistat-prod.logwin-logistics.com.pl/` | PostgreSQL 16 | **brak dostępu SSH** |

Katalog wdrożenia na `.31`: `/home/optmtst_user/logistat-test`
(nie `/opt` — `optmtst_user` nie ma tam prawa zapisu, a `sudo` wymaga hasła).

Dostęp: `ssh -i ~/.ssh/id_ed25519 optmtst_user@10.153.1.31`

## Publikacja pod domeną

Nazwy `logistat-test` / `logistat-prod` i `returns-hub-test` / `returns-hub-prod`
rozwiązują się na **Cloudflare** (104.26.4.187 itd.) — nie na firmowe proxy
`10.15.12.67`, jak zakłada `IT_REQUEST.md`. Ruch dochodzi do backendu na
`10.153.1.31:5001`; póki nic tam nie nasłuchuje, domena zwraca `502`.

Cloudflare Access przed tymi nazwami **nie stoi** (niezalogowane żądanie dociera
do aplikacji — Access przechwyciłby je na edge). Do potwierdzenia przez IT
zostaje tylko, czy jest reguła WAF / allowlista IP. **Do czasu potwierdzenia
zakładamy, że strona logowania jest osiągalna z internetu** — dlatego
`SECRET_KEY` i hasło admina muszą być zmienione przed pierwszym uruchomieniem.

`ProxyFix` nie jest potrzebny — Werkzeug zwraca relatywny `Location`
i logowanie przez domenę działa.

Własny Nginx (`nginx-logistat.conf`) w tym modelu jest zbędny.

## Pierwsze wdrożenie

```bash
# 1. katalog
ssh -i ~/.ssh/id_ed25519 optmtst_user@10.153.1.31 'mkdir -p ~/logistat-test'

# 2. kod (git archive: bez .git, bez instance/, bez __pycache__)
git archive --format=tar HEAD | ssh -i ~/.ssh/id_ed25519 optmtst_user@10.153.1.31 \
  'tar -x -C ~/logistat-test'

# 3. konfiguracja środowiska — na serwerze, z własnymi hasłami
#    wzór: docker-compose.override.example.yml
ssh -i ~/.ssh/id_ed25519 optmtst_user@10.153.1.31
  cd ~/logistat-test
  cp docker-compose.override.example.yml docker-compose.override.yml
  vi docker-compose.override.yml        # SECRET_KEY, POSTGRES_PASSWORD, DATABASE_URL
  chmod 600 docker-compose.override.yml

# 4. start
  docker compose up --build -d

# 5. backupy
  cp scripts/backup-logistat.sh ~/logistat-test/backup-logistat.sh
  chmod +x ~/logistat-test/backup-logistat.sh
  ( crontab -l 2>/dev/null; echo "30 22 * * * /home/optmtst_user/logistat-test/backup-logistat.sh >> /home/optmtst_user/logistat-test/backups/backup.log 2>&1" ) | crontab -
```

Hasło admina po pierwszym starcie to `admin / admin123` z seeda —
**zmienić natychmiast** na `/profile`.

## Aktualizacja kodu

```bash
git archive --format=tar HEAD | ssh -i ~/.ssh/id_ed25519 optmtst_user@10.153.1.31 \
  'tar -x -C ~/logistat-test'
ssh -i ~/.ssh/id_ed25519 optmtst_user@10.153.1.31 \
  'cd ~/logistat-test && docker compose up --build -d'
```

`docker-compose.override.yml` i `instance/` nie są w repo, więc `git archive`
ich nie nadpisuje. Nowe kolumny w modelach: patrz `migrate_columns()` (SQLite)
— na Postgresie schemat zawsze pochodzi z `db.create_all()`.

## Baza danych

Domyślnie SQLite (`instance/logistat.db`). **`DATABASE_URL` przełącza na Postgresa** —
i to jedyna zmiana potrzebna do migracji; brak zmiennej = powrót na SQLite.

Schemat na obu silnikach tworzy `db.create_all()`. **`docs/postgres_schema.sql`
jest nieaktualny i nie wolno go użyć bez poprawek:** jego `JSONB` w
`category_data` / `rates_data` psuje `json.loads` w `get_category_data()`
(psycopg2 zwraca dict), a `DEFAULT NOW()` na `TIMESTAMP` wpisałby czas lokalny
serwera do kolumn, które aplikacja czyta jako naive UTC (2 h błędu w PL latem).

Przeniesienie ustawień z SQLite do Postgresa: aktywności i mapowania krajów
odtwarza `seed_data()` (są identyczne z seedem), więc kopiuje się tylko hash
hasła admina, `cost_mapping` i `app_setting` — bez ID, żeby sekwencje Postgresa
zostały spójne.

Przyrost: ~250 B na paczkę z indeksami, czyli **50–90 MB/rok** przy
500–1000 paczek dziennie. Postgres to ~1,2× tego plus ~40 MB–1 GB stałego
kosztu klastra (WAL, katalogi).

## Backupy

`scripts/backup-logistat.sh` — `pg_dump --clean --if-exists`, gzip, retencja
14 dni, sprawdza kompletność zrzutu (`gzip` w potoku sam by błędu nie zgłosił).
Cron 22:30. Odtworzenie:

```bash
docker exec logistat-test-db psql -U logistat -d postgres -c "CREATE DATABASE restore_check;"
gunzip -c backups/logistat-RRRR-MM-DD_GGMM.sql.gz | \
  docker exec -i logistat-test-db psql -U logistat -d restore_check
```

Na SQLite backup **nie może być zwykłym `cp`** — przy `journal_mode=WAL` część
zmian siedzi w `logistat.db-wal`. Trzeba `sqlite3.Connection.backup()` albo
`VACUUM INTO`. `sqlite3` CLI nie jest zainstalowany ani na `.31`, ani w obrazie
`python:3.11-slim`.

## Znane zachowania

- **Po reboocie hosta** `depends_on: service_healthy` nie obowiązuje (demon
  Dockera wstaje sam), więc aplikacja może wystartować przed bazą, `create_all()`
  padnie i `restart: always` powtórzy. W logach zobaczysz „Worker failed to boot" —
  to się samo naprawia.
- **Postgres wymusza długości `VARCHAR`**, które SQLite ignorował: zniekształcony
  import, który wcześniej po cichu przechodził, teraz zwróci błąd.
- **`imported_carton.id` to 4-bajtowy `INTEGER`** (`db.create_all()`), nie
  `BIGSERIAL` z `postgres_schema.sql` — zapas 2,1 mld wierszy.

## Zasoby na `.31` (2026-08-31)

Dysk 97 GB / 34 GB wolne. RAM 3,8 GB, wolne ~2,0 GB — LogiStat bierze
~111 MiB (app) + ~52 MiB (baza). Na serwerze stoi 12 innych kontenerów
(returns-hub, waveplanning, jewelry_tracker, grafana/loki, portainer,
cloudbeaver). Zajęte porty: 3000, 3002, 5000, 8081; **5001–5005 wolne**.
