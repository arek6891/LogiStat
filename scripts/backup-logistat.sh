#!/usr/bin/env bash
# Kopia zapasowa bazy LogiStat (test) — PostgreSQL, kontener logistat-test-db.
#
# Historia: do 2026-08-31 baza byla w SQLite i skrypt robil snapshot przez
# sqlite3.Connection.backup(). Po przejsciu na Postgresa uzywamy pg_dump.
# Plik SQLite (instance/logistat.db) zostal jako punkt rollbacku, ale NIE jest
# juz kopiowany — inaczej backup wygladalby zdrowo, a zamrazal stary stan.
set -euo pipefail

BASE="$HOME/logistat-test"
OUT="$BASE/backups"
DB_CONTAINER="${DB_CONTAINER:-logistat-test-db}"
PGUSER="${PGUSER:-logistat}"
PGDATABASE="${PGDATABASE:-logistat}"
KEEP_DAYS=14
STAMP=$(date +%Y-%m-%d_%H%M)
mkdir -p "$OUT"

docker exec "$DB_CONTAINER" pg_dump -U "$PGUSER" -d "$PGDATABASE" --clean --if-exists \
  | gzip > "$OUT/logistat-$STAMP.sql.gz"

# pg_dump w potoku nie przerwie skryptu przy bledzie (gzip zwroci 0), wiec sprawdzamy tresc
if ! gunzip -c "$OUT/logistat-$STAMP.sql.gz" | grep -q "PostgreSQL database dump complete"; then
    echo "[backup] BLAD: zrzut niekompletny, usuwam $OUT/logistat-$STAMP.sql.gz" >&2
    rm -f "$OUT/logistat-$STAMP.sql.gz"
    exit 1
fi

find "$OUT" -name 'logistat-*.sql.gz' -mtime +$KEEP_DAYS -delete
echo "[backup] $OUT/logistat-$STAMP.sql.gz ($(du -h "$OUT/logistat-$STAMP.sql.gz" | cut -f1)), retencja ${KEEP_DAYS} dni"
