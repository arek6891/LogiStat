"""Niezmienniki agregacji importu — `process_import_rows`.

`GeneralStat.amounts` jest czysta agregacja kartonow: pisze do niej tylko
import (delta za nowe kartony) i `recompute_general_stat` (suma calej grupy).
Te testy pilnuja, ze paczka nie zostanie policzona dwa razy ani zgubiona.
"""
from datetime import date

import app as logistat

ZIEL = date(2026, 9, 10)


def row(barcode, stueckzahl=10, land='PL', ziel_datum=ZIEL, uebergabe_nr='UB-1', **kw):
    r = {
        'barcode': barcode,
        'land': land,
        'stueckzahl': stueckzahl,
        'kategorie': 'textile',
        'ziel_datum': ziel_datum,
        'uebergabe_nr': uebergabe_nr,
    }
    r.update(kw)
    return r


def gstat(list_id='UB-1', country_ledger='PL', loading_date=ZIEL):
    return logistat.GeneralStat.query.filter_by(
        list_id=list_id, country_ledger=country_ledger, loading_date=loading_date
    ).first()


def test_import_tworzy_kartony_i_jedna_linie_z_suma(acting_admin):
    res = logistat.process_import_rows([row('B1', 10), row('B2', 5), row('B3', 7)], ZIEL)

    assert res['imported'] == 3
    assert res['skipped'] == 0
    assert res['stats_created'] == 1
    assert logistat.ImportedCarton.query.count() == 3
    assert gstat().amounts == 22


def test_reimport_tych_samych_barcodow_nie_dolicza_drugi_raz(acting_admin):
    logistat.process_import_rows([row('B1', 10), row('B2', 5)], ZIEL)
    assert gstat().amounts == 15

    res = logistat.process_import_rows([row('B1', 10), row('B2', 5)], ZIEL)

    assert res['imported'] == 0
    assert res['skipped'] == 2
    assert set(res['skipped_barcodes']) == {'B1', 'B2'}
    assert gstat().amounts == 15, 'ponowny import nie moze podwoic rozliczenia'


def test_duplikat_w_obrebie_jednego_pliku_liczy_sie_raz(acting_admin):
    res = logistat.process_import_rows([row('B1', 10), row('B1', 10), row('B2', 5)], ZIEL)

    assert res['imported'] == 2
    assert res['skipped'] == 1
    assert gstat().amounts == 15


def test_kolejny_import_dolicza_tylko_nowe_kartony(acting_admin):
    logistat.process_import_rows([row('B1', 10)], ZIEL)
    res = logistat.process_import_rows([row('B1', 10), row('B2', 4), row('B3', 6)], ZIEL)

    assert res['imported'] == 2
    assert res['stats_updated'] == 1
    assert gstat().amounts == 20


def test_amounts_zawsze_rowna_sumie_kartonow_grupy(acting_admin):
    logistat.process_import_rows([row('B1', 10), row('B2', 5)], ZIEL)
    logistat.process_import_rows([row('B3', 8)], ZIEL)

    suma = sum(c.stueckzahl for c in logistat.ImportedCarton.query.filter_by(
        uebergabe_nr='UB-1', land='PL', data_pliku=ZIEL).all())
    assert gstat().amounts == suma == 23


def test_rozne_grupy_daja_osobne_linie(acting_admin):
    logistat.process_import_rows([
        row('B1', 10, land='PL'),
        row('B2', 20, land='DE'),
        row('B3', 30, uebergabe_nr='UB-2'),
    ], ZIEL)
    logistat.process_import_rows([row('B4', 40)], date(2026, 9, 11))

    assert logistat.GeneralStat.query.count() == 4
    assert gstat(country_ledger='PL').amounts == 10
    assert gstat(country_ledger='DE').amounts == 20
    assert gstat(list_id='UB-2').amounts == 30
    assert gstat(loading_date=date(2026, 9, 11)).amounts == 40, \
        'inna data pliku = osobna linia'


def test_ziel_datum_nie_dzieli_linii(acting_admin):
    """Od 2026-10 kluczem linii jest data pliku: ten sam Übergabe Nr + kraj z
    dwiema Ziel-Datum w jednym pliku to JEDNA linia (decyzja operacji)."""
    logistat.process_import_rows([
        row('B1', 10, ziel_datum=date(2026, 9, 11)),
        row('B2', 15, ziel_datum=date(2026, 9, 12)),
    ], ZIEL)

    assert logistat.GeneralStat.query.count() == 1
    assert gstat(loading_date=ZIEL).amounts == 25
    assert gstat(loading_date=ZIEL).week_number == ZIEL.isocalendar()[1]


def test_karton_bez_ziel_datum_tez_sie_rozlicza(acting_admin):
    """Dawniej brak Ziel-Datum wykluczal karton z rozliczenia; od 2026-10
    liczy sie po dacie pliku (na .31: 228 paczek, 34 204 szt.)."""
    logistat.process_import_rows([row('B2', 20, ziel_datum=None)], ZIEL)

    assert gstat(loading_date=ZIEL).amounts == 20


def test_karton_bez_uebergabe_nie_agreguje(acting_admin):
    res = logistat.process_import_rows([row('B1', 10, uebergabe_nr='')], ZIEL)

    assert res['imported'] == 1, 'karton musi powstac, zeby dane nie zniknely'
    assert logistat.GeneralStat.query.count() == 0, 'ale bez Übergabe Nr nie ma linii'


def test_karton_dostaje_date_pliku_i_jeden_czas_importu(acting_admin):
    logistat.process_import_rows([row('B1', 10), row('B2', 5)], date(2026, 9, 9))

    kartony = logistat.ImportedCarton.query.all()
    assert {c.data_pliku for c in kartony} == {date(2026, 9, 9)}
    assert len({c.imported_at for c in kartony}) == 1, \
        'jeden import = jeden czas, inaczej lista importow rozbije plik na kilka'


def test_wiersz_bez_barcode_jest_pomijany_cicho(acting_admin):
    res = logistat.process_import_rows([row(''), row(None), row('B1', 10)], ZIEL)

    assert res['imported'] == 1
    assert logistat.ImportedCarton.query.count() == 1


def test_country_of_destination_z_mapowania_krajow(acting_admin):
    logistat.db.session.add(logistat.CountryMapping(country='Testlandia', innenauftrag='TL9'))
    logistat.db.session.commit()

    logistat.process_import_rows([row('B1', 10, land='TL9')], ZIEL)

    line = gstat(country_ledger='TL9')
    assert line.country_of_destination == 'Testlandia'
    carton = logistat.ImportedCarton.query.filter_by(barcode='B1').first()
    assert carton.country_mapping_id is not None


def test_brak_mapowania_nie_blokuje_importu(acting_admin):
    logistat.process_import_rows([row('B1', 10, land='NIEZNANY')], ZIEL)

    line = gstat(country_ledger='NIEZNANY')
    assert line.amounts == 10
    assert line.country_of_destination is None


def test_week_number_z_daty_zieldatum(acting_admin):
    logistat.process_import_rows([row('B1', 10)], ZIEL)
    assert gstat().week_number == ZIEL.isocalendar()[1]


def test_nowa_linia_ma_pusty_category_data(acting_admin):
    logistat.process_import_rows([row('B1', 10)], ZIEL)
    cd = gstat().get_category_data()

    assert set(cd) == set(logistat.STAT_CATEGORIES)
    assert all(v == {'amount': 0, 'cost': 0.0} for v in cd.values())


def test_import_nie_nadpisuje_wpisanych_kategorii(acting_admin):
    logistat.process_import_rows([row('B1', 10)], ZIEL)
    line = gstat()
    line.set_category_data({**logistat.empty_category_data(),
                            'textile': {'amount': 4, 'cost': 0.0}})
    logistat.db.session.commit()

    logistat.process_import_rows([row('B2', 5)], ZIEL)

    line = gstat()
    assert line.amounts == 15
    assert line.get_category_data()['textile']['amount'] == 4, \
        'recznie wpisane kategorie musza przezyc kolejny import'
