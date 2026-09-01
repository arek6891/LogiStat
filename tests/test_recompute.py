"""`recompute_general_stat` — przeliczenie linii z SUMY kartonow, nie delty.

To jest wersja odporna na dryf: dziala tez wtedy, gdy w jednej linii siedza
razem kartony z importu i dodane recznie.
"""
from datetime import date

import app as logistat
from test_import_aggregation import ZIEL, gstat, row


def test_przelicza_z_sumy_a_nie_z_delty(acting_admin):
    logistat.process_import_rows([row('B1', 10), row('B2', 5)])

    # Rozjedz `amounts` recznie i sprawdz, ze recompute je naprawia
    gstat().amounts = 999
    logistat.db.session.commit()

    logistat.recompute_general_stat('UB-1', 'PL', ZIEL)
    logistat.db.session.commit()

    assert gstat().amounts == 15


def test_dokladne_przy_mieszance_import_plus_recznie(acting_admin):
    logistat.process_import_rows([row('B1', 10)])
    logistat.process_import_rows([row('M1', 7, added_manually=True)])

    logistat.recompute_general_stat('UB-1', 'PL', ZIEL)
    logistat.db.session.commit()

    assert gstat().amounts == 17


def test_zmiana_stueckzahl_kartonu_przelicza_linie(acting_admin):
    logistat.process_import_rows([row('B1', 10), row('B2', 5)])

    carton = logistat.ImportedCarton.query.filter_by(barcode='B1').first()
    carton.stueckzahl = 30
    logistat.db.session.flush()
    logistat.recompute_general_stat('UB-1', 'PL', ZIEL)
    logistat.db.session.commit()

    assert gstat().amounts == 35


def test_przeniesienie_do_innej_grupy_przelicza_obie_linie(acting_admin):
    logistat.process_import_rows([row('B1', 10), row('B2', 5)])
    logistat.process_import_rows([row('C1', 100, uebergabe_nr='UB-2')])

    carton = logistat.ImportedCarton.query.filter_by(barcode='B1').first()
    carton.uebergabe_nr = 'UB-2'
    logistat.db.session.flush()
    logistat.recompute_general_stat('UB-1', 'PL', ZIEL)
    logistat.recompute_general_stat('UB-2', 'PL', ZIEL)
    logistat.db.session.commit()

    assert gstat(list_id='UB-1').amounts == 5
    assert gstat(list_id='UB-2').amounts == 110
    suma_kartonow = sum(c.stueckzahl for c in logistat.ImportedCarton.query.all())
    suma_linii = sum(s.amounts for s in logistat.GeneralStat.query.all())
    assert suma_linii == suma_kartonow == 115, 'nic nie moze zniknac przy przenoszeniu'


def test_oprozniona_grupa_zostaje_na_zero_z_zachowanym_category_data(acting_admin):
    logistat.process_import_rows([row('B1', 10)])
    line = gstat()
    line.set_category_data({**logistat.empty_category_data(),
                            'sorting': {'amount': 3, 'cost': 0.0}})
    logistat.db.session.commit()

    logistat.db.session.delete(logistat.ImportedCarton.query.filter_by(barcode='B1').first())
    logistat.db.session.flush()
    logistat.recompute_general_stat('UB-1', 'PL', ZIEL)
    logistat.db.session.commit()

    line = gstat()
    assert line is not None, 'linia zostaje, zeby nie zgubic wpisanych kategorii'
    assert line.amounts == 0
    assert line.get_category_data()['sorting']['amount'] == 3


def test_tworzy_brakujaca_linie_gdy_grupa_ma_kartony(acting_admin):
    logistat.db.session.add(logistat.ImportedCarton(
        barcode='X1', land='PL', stueckzahl=42, ziel_datum=ZIEL, uebergabe_nr='UB-NEW'))
    logistat.db.session.commit()
    assert gstat(list_id='UB-NEW') is None

    logistat.recompute_general_stat('UB-NEW', 'PL', ZIEL)
    logistat.db.session.commit()

    line = gstat(list_id='UB-NEW')
    assert line.amounts == 42
    assert line.week_number == ZIEL.isocalendar()[1]


def test_nie_tworzy_linii_dla_pustej_grupy(acting_admin):
    logistat.recompute_general_stat('UB-PUSTA', 'PL', ZIEL)
    logistat.db.session.commit()

    assert gstat(list_id='UB-PUSTA') is None


def test_bez_uebergabe_lub_daty_jest_no_opem(acting_admin):
    logistat.recompute_general_stat('', 'PL', ZIEL)
    logistat.recompute_general_stat('UB-1', 'PL', None)
    logistat.db.session.commit()

    assert logistat.GeneralStat.query.count() == 0
