"""Pakiet logistat/ — czysta logika (podzial app.py, 2026-10-16).

Granica architektury: moduly nie importuja `app` ani Flaska/SQLAlchemy, wiec
da sie je testowac i uzywac bez bazy. Plus testy jednostkowe scalania okresow
(dwie implementacje polaczone w jedna).
"""
import subprocess
import sys
from datetime import date, datetime, timedelta

import pytest

from logistat.czas import local_day_bounds
from logistat.okresy import odejmij_okresy, suma_zlaczonych_okresow, w_okresach, zlacz_okresy

MODULY = ['logistat.czas', 'logistat.kategorie', 'logistat.tabela_ilosci',
          'logistat.okresy', 'logistat.normy']


@pytest.mark.parametrize('modul', MODULY)
def test_modul_nie_ciagnie_aplikacji_ani_flaska(modul):
    kod = (f'import sys, {modul}; '
           "zle = [m for m in ('app', 'flask', 'flask_sqlalchemy', 'sqlalchemy') if m in sys.modules]; "
           'print(",".join(zle))')
    wynik = subprocess.run([sys.executable, '-c', kod], capture_output=True, text=True,
                           timeout=60, cwd='.')
    assert wynik.returncode == 0, wynik.stderr
    assert wynik.stdout.strip() == '', f'{modul} importuje: {wynik.stdout.strip()}'


@pytest.mark.parametrize('modul', ['logistat.config', 'logistat.extensions', 'logistat.models'])
def test_warstwa_danych_nie_importuje_app(modul):
    """Modele i rozszerzenia moga uzywac Flaska/SQLAlchemy, ale nigdy app.py —
    inaczej wraca cykl app → models → app (krok 3, 2026-10-16)."""
    kod = f"import sys, {modul}; print('app' in sys.modules)"
    wynik = subprocess.run([sys.executable, '-c', kod], capture_output=True, text=True,
                           timeout=60, cwd='.')
    assert wynik.returncode == 0, wynik.stderr
    assert wynik.stdout.strip() == 'False'


def test_logistat_models_rejestruje_wszystkie_tabele():
    """Sam import pakietu modeli = komplet tabel dla create_all()."""
    import app as logistat
    kod = ('import logistat.models as m; from logistat.extensions import db; '
           'print(",".join(sorted(db.metadata.tables)))')
    wynik = subprocess.run([sys.executable, '-c', kod], capture_output=True, text=True,
                           timeout=60, cwd='.')
    assert wynik.returncode == 0, wynik.stderr
    assert wynik.stdout.strip().split(',') == sorted(logistat.db.metadata.tables)


T = datetime(2026, 10, 16, 8, 0)


def h(godz):
    return T + timedelta(hours=godz)


def test_zlacz_okresy_scala_nakladajace_i_stykajace_sie():
    assert zlacz_okresy([(h(2), h(3)), (h(0), h(1)), (h(0.5), h(2))]) == [(h(0), h(3))]


def test_zlacz_okresy_pomija_odwrocone_i_puste():
    assert zlacz_okresy([(h(2), h(1)), (h(1), h(1)), (h(4), h(5))]) == [(h(4), h(5))]


@pytest.mark.parametrize('okresy,sekundy', [
    ([], 0.0),
    ([(h(0), h(1)), (h(0.5), h(1.5))], 1.5 * 3600),     # wspolne pol godziny raz
    ([(h(0), h(1)), (h(2), h(3))], 2 * 3600),
    ([(h(1), h(0))], 0.0),                              # odwrocony po recznej korekcie
])
def test_suma_zlaczonych_okresow(okresy, sekundy):
    assert suma_zlaczonych_okresow(okresy) == sekundy


def test_odejmij_i_w_okresach():
    assert odejmij_okresy(h(0), h(3), [(h(1), h(2))]) == [(h(0), h(1)), (h(2), h(3))]
    assert w_okresach(h(1), [(h(1), h(2))]) and not w_okresach(h(3), [(h(1), h(2))])


def test_doba_lokalna_przy_zmianie_czasu():
    # 25.10.2026: zmiana czasu letniego na zimowy — doba ma 25 godzin.
    start, koniec = local_day_bounds(date(2026, 10, 25))
    assert (koniec - start) == timedelta(hours=25)
