"""Czas: zapis w naive UTC, doba pracy po Warszawie (jedyna definicja „dzis")."""
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

# ── Time helpers ───────────────────────────────────────────────────────────────
# Everything is STORED in UTC (naive). For display we serialize with an explicit
# 'Z' so the browser's `new Date()` parses it as UTC and converts to local, and we
# provide a Jinja filter for server-rendered timestamps (single-site: Europe/Warsaw).
LOCAL_TZ = ZoneInfo('Europe/Warsaw')


def iso_z(dt):
    """Serialize a naive-UTC datetime as an explicit-UTC ISO string (…Z).

    Without the 'Z', `new Date(iso)` in the browser parses a date-time string as
    LOCAL, so a stored UTC value would render unconverted (2h off in PL summer).
    Returns None for falsy input. Use ONLY for datetime columns, not date-only.
    """
    return dt.isoformat() + 'Z' if dt else None


def teraz_utc():
    """Teraz jako naive UTC — tak zapisujemy wszystkie znaczniki czasu w bazie.

    Zamiast `datetime.utcnow()`, przestarzalego od Pythona 3.12 (i do usuniecia).
    Wynik ten sam: bez strefy, w UTC.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def local_today():
    """Dzisiejsza data w Europe/Warsaw — niezaleznie od strefy serwera.

    `date.today()` zwraca date wedlug TZ procesu: w kontenerze bez TZ jest to
    UTC, wiec miedzy 00:00 a 02:00 czasu polskiego oddawalo jeszcze wczoraj.
    """
    return datetime.now(LOCAL_TZ).date()


def utc_to_local(dt):
    """Naive UTC -> aware datetime w Europe/Warsaw."""
    return dt.replace(tzinfo=timezone.utc).astimezone(LOCAL_TZ)


def local_day_bounds(d):
    """Granice doby lokalnej `d` jako naive UTC: [start, koniec).

    Timestampy trzymamy jako naive UTC, a doba pracy jest liczona po Warszawie
    (dwie zmiany, druga pracuje przez polnoc). Polnoc lokalna to 22:00 UTC
    latem i 23:00 UTC zima — DST liczy ZoneInfo, nie staly offset.
    """
    start = datetime.combine(d, time.min, tzinfo=LOCAL_TZ)
    end = datetime.combine(d + timedelta(days=1), time.min, tzinfo=LOCAL_TZ)
    to_naive_utc = lambda dt: dt.astimezone(timezone.utc).replace(tzinfo=None)  # noqa: E731
    return to_naive_utc(start), to_naive_utc(end)
