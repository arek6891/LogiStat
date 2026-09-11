# Wdrożenie LogiStat

Stan na 2026-08-31.

## Środowiska

| Środowisko | Serwer | Adres | Baza | Stan |
|---|---|---|---|---|
| dev | `10.153.1.32` (pllas01) | `http://10.153.1.32:5001` | PostgreSQL 16 | działa |
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
  vi docker-compose.override.yml        # SECRET_KEY, ADMIN_PASSWORD, POSTGRES_PASSWORD, DATABASE_URL
  chmod 600 docker-compose.override.yml

# 4. start
  docker compose up --build -d

# 5. backupy — cron wskazuje PROSTO na skrypt z repo, bez kopii obok
#    (kopia obok rozjechalaby sie z repo przy nastepnej aktualizacji kodu)
  chmod +x ~/logistat-test/scripts/backup-logistat.sh
  ( crontab -l 2>/dev/null; echo "30 22 * * * /home/optmtst_user/logistat-test/scripts/backup-logistat.sh >> /home/optmtst_user/logistat-test/backups/backup.log 2>&1" ) | crontab -
```

Hasło admina: ustaw `ADMIN_PASSWORD` w override **przed pierwszym startem**.
Bez tej zmiennej seed zakłada `admin / admin123` i wypisuje ostrzeżenie w logu —
wtedy zmienić natychmiast na `/profile`.

### Zmienne środowiskowe

| Zmienna | Wymagana | Domyślnie | Opis |
|---|---|---|---|
| `SECRET_KEY` | **tak, zawsze** | — | Klucz sesji. Bez niego aplikacja **nie wystartuje**. Compose czyta go z `.env` (patrz `.env.example`). Awaryjny bypass: `LOGISTAT_ALLOW_DEV_SECRET=1`. |
| `DATABASE_URL` | **tak, zawsze** | — | `postgresql+psycopg2://…`. Brak zmiennej albo `sqlite://` → aplikacja nie wstaje (`resolve_database_url()`). |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | nie | `logistat` / `logistat-dev` / `logistat` | Dane usługi `db` w compose. **Na test/prod ustaw własne hasło** w `.env` albo w overridzie. |
| `ADMIN_PASSWORD` | nie | `admin123` | Hasło konta `admin` przy **pierwszym** starcie. |
| `TZ` | nie | UTC | Nie wpływa już na liczenie doby — od `local_day_bounds()` doba jest zawsze liczona po `Europe/Warsaw`. |
| `SESSION_COOKIE_SECURE` | nie | off | `1` tylko gdy dostęp wyłącznie po HTTPS. Przy HTTP z LAN-u zepsuje logowanie. |
| `MAX_UPLOAD_MB` | nie | `32` | Limit rozmiaru importu CSV/Excel. Powyżej → `413` z JSON-em. |

## Aktualizacja kodu

```bash
git archive --format=tar HEAD | ssh -i ~/.ssh/id_ed25519 optmtst_user@10.153.1.31 \
  'tar -x -C ~/logistat-test'
ssh -i ~/.ssh/id_ed25519 optmtst_user@10.153.1.31 \
  'cd ~/logistat-test && docker compose up --build -d'
```

`docker-compose.override.yml`, `.env` i `instance/` nie są w repo, więc `git archive`
ich nie nadpisuje. **Nowe kolumny w modelach: obowiązkowo dopisz je do
`migrate_columns()`** — `db.create_all()` dokłada brakujące tabele, ale nigdy kolumny
do tabeli, która już istnieje, więc bez tego po wdrożeniu każde zapytanie na tym
modelu kończy się `UndefinedColumn`. Pilnuje tego `tests/test_migracje.py`.

## Baza danych

**Wyłącznie PostgreSQL 16** — od 2026-09 SQLite nie jest wspierany (kod obsługi
został usunięty, nie tylko odradzony). `DATABASE_URL` jest wymagany; jego brak albo
`sqlite://` kończy się wyjątkiem przy starcie, zamiast cichego zapisu do pliku,
którego nikt nie backupuje. Usługę `db` dostarcza `docker-compose.yml`.

Schemat tworzy `db.create_all()` — **modele w `app.py` są jedynym
źródłem prawdy**. Nie ma ręcznie pisanego pliku DDL i nie należy go zakładać: poprzedni
(`docs/postgres_schema.sql`, usunięty 2026-09-01) rozjechał się z modelami tak, że jego
użycie zepsułoby aplikację — `JSONB` w `category_data` / `rates_data` psuł `json.loads`
w `get_category_data()` (psycopg2 zwraca dict), a `DEFAULT NOW()` na `TIMESTAMP` wpisywał
czas lokalny serwera do kolumn czytanych jako naive UTC (2 h błędu w PL latem).

Pierwszy start jest serializowany `pg_advisory_lock(5001)` — bo inaczej workery
gunicorna ścigają się w `create_all()` i przegrany ubija cały kontener.

Gdyby trzeba było przenieść ustawienia ze starej bazy: aktywności i mapowania krajów
odtwarza `seed_data()` (są identyczne z seedem), więc kopiuje się tylko hash
hasła admina, `cost_mapping` i `app_setting` — bez ID, żeby sekwencje Postgresa
zostały spójne.

Przyrost: ~250 B na paczkę z indeksami, czyli **50–90 MB/rok** przy
500–1000 paczek dziennie. Postgres to ~1,2× tego plus ~40 MB–1 GB stałego
kosztu klastra (WAL, katalogi).

### Stara baza SQLite na dev

Na `.32` w `instance/logistat.db` zostal plik SQLite sprzed przejscia na Postgresa
(595 paczek, 25 linii `general_stat`, 20 prognoz, stan na 2026-09-11). Katalog
`instance/` jest w `.gitignore` i **nie jest juz przez nic uzywany** — plik lezy
tam wylacznie jako punkt powrotu. Mozna go skasowac, gdy nowa baza dorobi sie
wlasnych danych. Uwaga: `docker compose down -v` kasuje wolumen Postgresa, ale
tego pliku nie rusza (i odwrotnie).

## Backupy

`scripts/backup-logistat.sh` — `pg_dump --clean --if-exists`, gzip, retencja
14 dni, sprawdza kompletność zrzutu (`gzip` w potoku sam by błędu nie zgłosił).
Cron 22:30. Odtworzenie:

```bash
docker exec logistat-test-db psql -U logistat -d postgres -c "CREATE DATABASE restore_check;"
gunzip -c backups/logistat-RRRR-MM-DD_GGMM.sql.gz | \
  docker exec -i logistat-test-db psql -U logistat -d restore_check
```

## Znane zachowania

- **Po reboocie hosta** `depends_on: service_healthy` nie obowiązuje (demon
  Dockera wstaje sam), więc aplikacja może wystartować przed bazą, `create_all()`
  padnie i `restart: always` powtórzy. W logach zobaczysz „Worker failed to boot" —
  to się samo naprawia.
- **Postgres wymusza długości `VARCHAR`**, które SQLite ignorował: zniekształcony
  import, który wcześniej po cichu przechodził, teraz zwróci błąd.
- **`imported_carton.id` to 4-bajtowy `INTEGER`** (tak zakłada `db.create_all()`,
  nie `BIGSERIAL`) — zapas 2,1 mld wierszy.

## Zasoby na `.31` (2026-08-31)

Dysk 97 GB / 34 GB wolne. RAM 3,8 GB, wolne ~2,0 GB — LogiStat bierze
~111 MiB (app) + ~52 MiB (baza). Na serwerze stoi 12 innych kontenerów
(returns-hub, waveplanning, jewelry_tracker, grafana/loki, portainer,
cloudbeaver). Zajęte porty: 3000, 3002, 5000, 8081; **5001–5005 wolne**.
