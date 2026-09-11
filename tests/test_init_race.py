"""Rownolegly start wielu workerow na PUSTEJ bazie.

Gunicorn importuje app.py raz na worker, wiec przy pierwszym starcie kilka
procesow wchodzi jednoczesnie w db.create_all(). Bez serializacji przegrany
dostaje "table user already exists", gunicorn melduje "Worker failed to boot"
i ubija caly kontener.
"""
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit, urlunsplit

import pytest
import sqlalchemy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKEROW = 4


@pytest.fixture
def pusta_baza():
    """Swiezo utworzona, PUSTA baza na serwerze testowym.

    Wyscig pierwszego startu widac tylko na bazie, ktorej schematu jeszcze nie
    ma — a `flask_app` z conftesta zawsze podaje juz zainicjowana. Tworzymy
    wiec osobna baze (CREATE DATABASE wymaga AUTOCOMMIT) i kasujemy ja po tescie.
    """
    czesci = urlsplit(os.environ['DATABASE_URL'])
    nazwa = 'logistat_race_' + os.urandom(4).hex()
    serwer = sqlalchemy.create_engine(
        urlunsplit(czesci._replace(path='/postgres')),
        isolation_level='AUTOCOMMIT')
    with serwer.connect() as conn:
        conn.execute(sqlalchemy.text(f'CREATE DATABASE {nazwa}'))
    try:
        yield urlunsplit(czesci._replace(path='/' + nazwa))
    finally:
        with serwer.connect() as conn:
            conn.execute(sqlalchemy.text(
                'SELECT pg_terminate_backend(pid) FROM pg_stat_activity '
                'WHERE datname = :n'), {'n': nazwa})
            conn.execute(sqlalchemy.text(f'DROP DATABASE IF EXISTS {nazwa}'))
        serwer.dispose()


SKRYPT = (
    'import app; '
    'ctx = app.app.app_context(); ctx.push(); '
    "print('ADMINOW=%d' % app.User.query.filter_by(role='admin').count()); "
    "print('TABEL=%d' % len(app.db.metadata.tables))"
)


def _uruchom(db_url):
    env = {
        **os.environ,
        'DATABASE_URL': db_url,
        'SECRET_KEY': 'test-secret-key',
        'PYTHONPATH': ROOT,
    }
    return subprocess.run(
        [sys.executable, '-c', SKRYPT],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=120,
    )


def test_rownolegly_start_na_pustej_bazie(pusta_baza):
    with ThreadPoolExecutor(max_workers=WORKEROW) as pula:
        wyniki = list(pula.map(lambda _: _uruchom(pusta_baza), range(WORKEROW)))

    padly = [w for w in wyniki if w.returncode != 0]
    assert not padly, (
        f'{len(padly)}/{WORKEROW} workerow nie wstalo. Pierwszy blad:\n'
        f'{padly[0].stderr[-1500:]}')


def test_start_na_pustej_bazie_zaklada_jednego_admina(pusta_baza):
    """Seed tez sciga sie miedzy workerami — bez blokady kazdy widzi
    count()==0 i kazdy wstawia admina."""
    with ThreadPoolExecutor(max_workers=WORKEROW) as pula:
        wyniki = list(pula.map(lambda _: _uruchom(pusta_baza), range(WORKEROW)))

    assert all(w.returncode == 0 for w in wyniki)
    adminow = {w.stdout for w in wyniki if 'ADMINOW=' in w.stdout}
    assert all('ADMINOW=1' in linia for linia in adminow), \
        f'oczekiwano dokladnie jednego admina, jest: {adminow}'


def test_ponowny_start_na_gotowej_bazie_jest_no_opem(pusta_baza):
    pierwszy = _uruchom(pusta_baza)
    assert pierwszy.returncode == 0, pierwszy.stderr[-1500:]

    with ThreadPoolExecutor(max_workers=WORKEROW) as pula:
        wyniki = list(pula.map(lambda _: _uruchom(pusta_baza), range(WORKEROW)))

    assert all(w.returncode == 0 for w in wyniki)
    assert all('ADMINOW=1' in w.stdout for w in wyniki)
    assert all('[SEED]' not in w.stdout for w in wyniki), \
        'na gotowej bazie seed nie ma nic do roboty'
