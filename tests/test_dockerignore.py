"""Obraz Dockera bez kopii bazy i sekretow (przeglad bezpieczenstwa 2026-11-09):
`COPY . .` w katalogu wdrozenia wkladal do obrazu backups/ (pg_dump) i
docker-compose.override.yml (SECRET_KEY, haslo bazy)."""
from pathlib import Path

KORZEN = Path(__file__).resolve().parent.parent


def test_dockerignore_wyklucza_kopie_i_sekrety():
    wpisy = {w.strip() for w in (KORZEN / '.dockerignore').read_text().splitlines()
             if w.strip() and not w.startswith('#')}
    for wymagany in ('backups/', 'instance/', '.env', 'docker-compose.override.yml', '*.sql.gz'):
        assert wymagany in wpisy, wymagany


def test_obraz_ma_kod_aplikacji():
    """Wykluczenia nie moga zabrac tego, czego gunicorn i skrypty po deployu potrzebuja."""
    wpisy = (KORZEN / '.dockerignore').read_text()
    for potrzebny in ('logistat/', 'templates/', 'static/', 'app.py', 'scripts/sprawdz_spojnosc.py'):
        assert f'\n{potrzebny}\n' not in f'\n{wpisy}\n', potrzebny
