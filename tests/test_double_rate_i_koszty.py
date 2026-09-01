"""Double rate (zolty wiersz) + matematyka kosztow.

Podwojenie jest EMERGENTNE: obie linie licza x1, a paczka double-rate jest
policzona dwa razy — raz w normalnym wierszu, raz w zoltym. Zaden mnoznik x2
nie moze siedziec w kodzie.
"""
from datetime import date

import app as logistat
from test_import_aggregation import ZIEL, gstat, row


def key(list_id='UB-1', land='PL', ziel=ZIEL):
    return (list_id, land, ziel)


# ── double_rate_amount_map ───────────────────────────────────────────────────

def test_mapa_sumuje_tylko_kartony_oznaczone(acting_admin):
    logistat.process_import_rows([
        row('B1', 10, double_rate=True),
        row('B2', 5, double_rate=True),
        row('B3', 100),
    ])

    mapa = logistat.double_rate_amount_map()

    assert mapa[key()] == 15, 'liczymy tylko paczki double-rate, nie cala linie'
    assert gstat().amounts == 115, 'normalny wiersz liczy wszystkie paczki'


def test_mapa_pusta_gdy_nic_nie_oznaczone(acting_admin):
    logistat.process_import_rows([row('B1', 10), row('B2', 5)])

    assert logistat.double_rate_amount_map() == {}


def test_mapa_kluczuje_per_grupa(acting_admin):
    logistat.process_import_rows([
        row('B1', 10, double_rate=True),
        row('B2', 20, land='DE', double_rate=True),
        row('B3', 30, uebergabe_nr='UB-2', double_rate=True),
    ])

    mapa = logistat.double_rate_amount_map()

    assert mapa[key()] == 10
    assert mapa[key(land='DE')] == 20
    assert mapa[key(list_id='UB-2')] == 30


def test_odznaczenie_kartonu_usuwa_go_z_mapy(acting_admin):
    logistat.process_import_rows([row('B1', 10, double_rate=True), row('B2', 5)])
    assert logistat.double_rate_amount_map()[key()] == 10

    carton = logistat.ImportedCarton.query.filter_by(barcode='B1').first()
    carton.double_rate = False
    logistat.db.session.commit()

    assert logistat.double_rate_amount_map() == {}


def test_zolty_wiersz_nie_rusza_amounts_normalnego(acting_admin):
    logistat.process_import_rows([row('B1', 10, double_rate=True), row('B2', 5)])
    line = gstat()
    line.set_double_rate_category_data({**logistat.empty_category_data(),
                                        'textile': {'amount': 10, 'cost': 0.0}})
    logistat.db.session.commit()

    line = gstat()
    assert line.amounts == 15, 'zolty wiersz jest osobny — amounts sie nie zmienia'
    assert line.get_category_data()['textile']['amount'] == 0
    assert line.get_double_rate_category_data()['textile']['amount'] == 10


# ── Koszty: amount x rate ────────────────────────────────────────────────────

def rates(**kw):
    mapping = logistat.CostMapping(year=ZIEL.year, month=ZIEL.month)
    mapping.set_rates_data(kw)
    logistat.db.session.add(mapping)
    logistat.db.session.commit()
    return mapping


def test_koszt_to_amount_razy_stawka(acting_admin):
    rates(textile=0.25, sorting=1.5)
    logistat.process_import_rows([row('B1', 10)])
    line = gstat()
    line.set_category_data({**logistat.empty_category_data(),
                            'textile': {'amount': 100, 'cost': 0.0},
                            'sorting': {'amount': 4, 'cost': 0.0}})
    logistat.db.session.commit()

    d = gstat().to_dict()

    assert d['category_data']['textile']['computed_cost'] == 25.0
    assert d['category_data']['sorting']['computed_cost'] == 6.0
    assert d['total_cost'] == 31.0


def test_brak_stawek_na_miesiac_daje_zero_a_nie_blad(acting_admin):
    logistat.process_import_rows([row('B1', 10)])
    line = gstat()
    line.set_category_data({**logistat.empty_category_data(),
                            'textile': {'amount': 100, 'cost': 0.0}})
    logistat.db.session.commit()

    d = gstat().to_dict()

    assert d['total_cost'] == 0.0


def test_stawki_sa_brane_z_miesiaca_loading_date(acting_admin):
    rates(textile=0.25)
    inny = logistat.CostMapping(year=ZIEL.year, month=1)
    inny.set_rates_data({'textile': 99.0})
    logistat.db.session.add(inny)
    logistat.db.session.commit()

    logistat.process_import_rows([row('B1', 10)])
    line = gstat()
    line.set_category_data({**logistat.empty_category_data(),
                            'textile': {'amount': 100, 'cost': 0.0}})
    logistat.db.session.commit()

    assert gstat().to_dict()['total_cost'] == 25.0


def test_uszkodzony_json_nie_wywala_serializacji(acting_admin):
    logistat.process_import_rows([row('B1', 10)])
    line = gstat()
    line.category_data = 'to nie jest json'
    line.double_rate_category_data = None
    logistat.db.session.commit()

    line = gstat()
    assert line.get_category_data() == logistat.empty_category_data()
    assert line.get_double_rate_category_data() == logistat.empty_category_data()
    assert line.to_dict()['total_cost'] == 0.0


def test_obie_linie_licza_razy_jeden(acting_admin):
    """Rachunek konca-do-konca: paczka double-rate placi 2x, bo jest w dwoch
    wierszach po x1 — nie dlatego, ze gdzies jest mnoznik."""
    rates(textile=2.0)
    logistat.process_import_rows([row('B1', 10, double_rate=True)])
    line = gstat()
    line.set_category_data({**logistat.empty_category_data(),
                            'textile': {'amount': 10, 'cost': 0.0}})
    line.set_double_rate_category_data({**logistat.empty_category_data(),
                                        'textile': {'amount': 10, 'cost': 0.0}})
    logistat.db.session.commit()

    line = gstat()
    normalny = line.to_dict()['total_cost']
    zolty = sum(v['amount'] * 2.0 for v in line.get_double_rate_category_data().values())

    assert normalny == 20.0
    assert zolty == 20.0
    assert normalny + zolty == 40.0, 'razem 2x stawka za te same 10 szt.'
