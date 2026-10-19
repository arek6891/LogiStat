"""`recompute_general_stat` — przeliczenie linii z SUMY kartonow, nie delty.

To jest wersja odporna na dryf: dziala tez wtedy, gdy w jednej linii siedza
razem kartony z importu i dodane recznie.
"""
from datetime import date

from test_import_aggregation import ZIEL, gstat, row

from logistat.extensions import db
from logistat.models import GeneralStat, ImportedCarton, empty_category_data
from logistat.rozliczenie import recompute_general_stat
from logistat.web.wspolne import process_import_rows


def test_przelicza_z_sumy_a_nie_z_delty(acting_admin):
    process_import_rows([row('B1', 10), row('B2', 5)], ZIEL)

    # Rozjedz `amounts` recznie i sprawdz, ze recompute je naprawia
    gstat().amounts = 999
    db.session.commit()

    recompute_general_stat('UB-1', 'PL', ZIEL)
    db.session.commit()

    assert gstat().amounts == 15


def test_dokladne_przy_mieszance_import_plus_recznie(acting_admin):
    process_import_rows([row('B1', 10)], ZIEL)
    process_import_rows([row('M1', 7, added_manually=True)], ZIEL)

    recompute_general_stat('UB-1', 'PL', ZIEL)
    db.session.commit()

    assert gstat().amounts == 17


def test_zmiana_stueckzahl_kartonu_przelicza_linie(acting_admin):
    process_import_rows([row('B1', 10), row('B2', 5)], ZIEL)

    carton = ImportedCarton.query.filter_by(barcode='B1').first()
    carton.stueckzahl = 30
    db.session.flush()
    recompute_general_stat('UB-1', 'PL', ZIEL)
    db.session.commit()

    assert gstat().amounts == 35


def test_przeniesienie_do_innej_grupy_przelicza_obie_linie(acting_admin):
    process_import_rows([row('B1', 10), row('B2', 5)], ZIEL)
    process_import_rows([row('C1', 100, uebergabe_nr='UB-2')], ZIEL)

    carton = ImportedCarton.query.filter_by(barcode='B1').first()
    carton.uebergabe_nr = 'UB-2'
    db.session.flush()
    recompute_general_stat('UB-1', 'PL', ZIEL)
    recompute_general_stat('UB-2', 'PL', ZIEL)
    db.session.commit()

    assert gstat(list_id='UB-1').amounts == 5
    assert gstat(list_id='UB-2').amounts == 110
    suma_kartonow = sum(c.stueckzahl for c in ImportedCarton.query.all())
    suma_linii = sum(s.amounts for s in GeneralStat.query.all())
    assert suma_linii == suma_kartonow == 115, 'nic nie moze zniknac przy przenoszeniu'


def test_oprozniona_grupa_zostaje_na_zero_z_zachowanym_category_data(acting_admin):
    process_import_rows([row('B1', 10)], ZIEL)
    line = gstat()
    line.set_category_data({**empty_category_data(),
                            'sorting': {'amount': 3, 'cost': 0.0}})
    db.session.commit()

    db.session.delete(ImportedCarton.query.filter_by(barcode='B1').first())
    db.session.flush()
    recompute_general_stat('UB-1', 'PL', ZIEL)
    db.session.commit()

    line = gstat()
    assert line is not None, 'linia zostaje, zeby nie zgubic wpisanych kategorii'
    assert line.amounts == 0
    assert line.get_category_data()['sorting']['amount'] == 3


def test_tworzy_brakujaca_linie_gdy_grupa_ma_kartony(acting_admin):
    db.session.add(ImportedCarton(
        barcode='X1', land='PL', stueckzahl=42, ziel_datum=ZIEL, data_pliku=ZIEL, uebergabe_nr='UB-NEW'))
    db.session.commit()
    assert gstat(list_id='UB-NEW') is None

    recompute_general_stat('UB-NEW', 'PL', ZIEL)
    db.session.commit()

    line = gstat(list_id='UB-NEW')
    assert line.amounts == 42
    assert line.week_number == ZIEL.isocalendar()[1]


def test_nie_tworzy_linii_dla_pustej_grupy(acting_admin):
    recompute_general_stat('UB-PUSTA', 'PL', ZIEL)
    db.session.commit()

    assert gstat(list_id='UB-PUSTA') is None


def test_bez_uebergabe_lub_daty_jest_no_opem(acting_admin):
    recompute_general_stat('', 'PL', ZIEL)
    recompute_general_stat('UB-1', 'PL', None)
    db.session.commit()

    assert GeneralStat.query.count() == 0
