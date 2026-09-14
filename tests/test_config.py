"""Konfiguracja: klucz sesji, limit uploadu, ciasteczka."""
import io

import pytest

import app as logistat


# ── SECRET_KEY ───────────────────────────────────────────────────────────────

def test_klucz_z_env_wygrywa():
    assert logistat.resolve_secret_key({'SECRET_KEY': 'wlasny'}) == 'wlasny'


def test_brak_klucza_wybucha():
    """Cichy fallback na staly klucz dev = sesje admina do podrobienia.

    Odkad kazde srodowisko jest serwerowe (Postgres), klucz jest wymagany
    zawsze — nie tylko gdy ustawiony jest DATABASE_URL.
    """
    with pytest.raises(RuntimeError, match='SECRET_KEY'):
        logistat.resolve_secret_key({})


def test_pusty_klucz_traktowany_jak_brak():
    with pytest.raises(RuntimeError):
        logistat.resolve_secret_key({'SECRET_KEY': '   '})


def test_swiadome_pominiecie_dziala():
    env = {'LOGISTAT_ALLOW_DEV_SECRET': '1'}

    assert logistat.resolve_secret_key(env) == logistat.DEV_SECRET_KEY


# ── DATABASE_URL ─────────────────────────────────────────────────────────────

def test_url_bazy_z_env_wygrywa():
    env = {'DATABASE_URL': 'postgresql+psycopg2://u:p@db:5432/logistat'}

    assert logistat.resolve_database_url(env) == env['DATABASE_URL']


def test_brak_url_bazy_wybucha():
    """Zamiast cicho zapisywac do pliku, ktorego nikt nie backupuje."""
    with pytest.raises(RuntimeError, match='DATABASE_URL'):
        logistat.resolve_database_url({})


def test_sqlite_jest_odrzucany():
    with pytest.raises(RuntimeError, match='SQLite'):
        logistat.resolve_database_url({'DATABASE_URL': 'sqlite:///logistat.db'})


# ── Limit uploadu ────────────────────────────────────────────────────────────

def test_limit_uploadu_jest_ustawiony(flask_app):
    assert flask_app.config['MAX_CONTENT_LENGTH'] == 32 * 1024 * 1024


def test_za_duzy_plik_daje_413_jako_json(admin_client, flask_app):
    limit = flask_app.config['MAX_CONTENT_LENGTH']
    duzy = io.BytesIO(b'x' * (limit + 1024))

    r = admin_client.post('/api/import-csv',
                          data={'file': (duzy, 'wielki.csv')},
                          content_type='multipart/form-data')

    assert r.status_code == 413
    assert r.get_json()['error'].startswith('Plik jest za duzy')


# ── Ciasteczko sesji ─────────────────────────────────────────────────────────

def test_ciasteczko_samesite_lax(flask_app):
    """Blokuje POST z obcej strony — /api/import-csv jest multipart, wiec bez
    tego byl osiagalny CSRF-em."""
    assert flask_app.config['SESSION_COOKIE_SAMESITE'] == 'Lax'


def test_ciasteczko_httponly(flask_app):
    assert flask_app.config['SESSION_COOKIE_HTTPONLY'] is True


def test_secure_wlaczane_zmienna(flask_app):
    assert flask_app.config['SESSION_COOKIE_SECURE'] is False, \
        'domyslnie off — do .31 wchodzi sie tez po HTTP z LAN-u'


def test_ciasteczko_faktycznie_ma_samesite(client, leader):
    from conftest import login
    r = login(client, leader.username)

    ciastka = r.headers.getlist('Set-Cookie')
    sesja = next(c for c in ciastka if c.startswith('session='))
    assert 'HttpOnly' in sesja
    assert 'SameSite=Lax' in sesja
