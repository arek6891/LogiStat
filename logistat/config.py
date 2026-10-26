"""Konfiguracja z srodowiska: SECRET_KEY, DATABASE_URL, limity.
Blad konfiguracji = wyjatek przy starcie, nigdy cichy fallback."""
import os

# ── App Config ───────────────────────────────────────────────────────────────

DEV_SECRET_KEY = 'logistat-dev-key-change-me'
# Gorny limit uploadu (import CSV/Excel czyta plik do pamieci przez file.read(),
# a gunicorn ma 2 workery — bez limitu jeden plik potrafi wywalic kontener).
# Nazwa na ekranach (2026-10-24, operacja: „SaRa”; od 2026-10-26 wielkimi literami „SARA”). Kod, pakiet `logistat`,
# kontenery, bazy, domeny i zmienne LOGISTAT_* zostaja bez zmian.
NAZWA_APLIKACJI = 'SARA'
AUTORZY_APLIKACJI = 'Arkadiusz Sobczyk i Adam Reliszka'

DEFAULT_MAX_UPLOAD_MB = 32
# Haslo konta 'admin' zakladanego przy pierwszym starcie; nadpisywalne
# zmienna ADMIN_PASSWORD (patrz docs/DEPLOY.md).
DEFAULT_ADMIN_PASSWORD = 'admin123'


def resolve_secret_key(env=None):
    """Zwroc SECRET_KEY albo rzuc.

    Dotad brak klucza cicho spadal na staly klucz dev — sesje kazdego admina
    dalyby sie podrobic i nikt by sie o tym nie dowiedzial. Odkad KAZDE
    srodowisko jest serwerowe (Postgres, wlasny compose), klucz jest wymagany
    zawsze. Swiadome pominiecie (lokalny eksperyment): LOGISTAT_ALLOW_DEV_SECRET=1.
    """
    env = os.environ if env is None else env
    key = env.get('SECRET_KEY', '').strip()
    if key:
        return key
    if env.get('LOGISTAT_ALLOW_DEV_SECRET') == '1':
        return DEV_SECRET_KEY
    raise RuntimeError(
        'SECRET_KEY nie jest ustawiony. Wygeneruj go '
        '(python3 -c "import secrets; print(secrets.token_hex(32))") i ustaw '
        'w docker-compose.override.yml albo w srodowisku. '
        'Swiadome pominiecie: LOGISTAT_ALLOW_DEV_SECRET=1.'
    )


def resolve_database_url(env=None):
    """Zwroc DATABASE_URL albo rzuc — LogiStat chodzi wylacznie na PostgreSQL.

    Dotad brak zmiennej cicho spadal na `sqlite:///logistat.db` obok kodu, wiec
    zle skonfigurowany kontener startowal i zapisywal dane do pliku, ktorego
    nikt nie backupuje. Lepiej nie wstac.
    """
    env = os.environ if env is None else env
    url = env.get('DATABASE_URL', '').strip()
    if not url:
        raise RuntimeError(
            'DATABASE_URL nie jest ustawiony. LogiStat dziala wylacznie na '
            'PostgreSQL — ustaw np. '
            'postgresql+psycopg2://logistat:haslo@db:5432/logistat '
            '(patrz docker-compose.yml i docs/DEPLOY.md).'
        )
    if url.startswith('sqlite'):
        raise RuntimeError(
            f'SQLite nie jest juz wspierany (DATABASE_URL={url!r}). '
            'LogiStat dziala wylacznie na PostgreSQL.'
        )
    return url
