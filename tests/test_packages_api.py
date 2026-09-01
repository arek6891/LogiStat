"""API paczek: reczne dodanie i edycja — ta sama sciezka rozliczeniowa co import."""
from datetime import date

import app as logistat
from test_import_aggregation import ZIEL, gstat


def payload(**kw):
    p = {
        'barcode': 'M1',
        'land': 'PL',
        'stueckzahl': 12,
        'kategorie': 'textile',
        'ziel_datum': ZIEL.isoformat(),
        'uebergabe_nr': 'UB-1',
    }
    p.update(kw)
    return p


def carton(barcode):
    return logistat.ImportedCarton.query.filter_by(barcode=barcode).first()


# ── POST /api/packages ───────────────────────────────────────────────────────

def test_reczne_dodanie_agreguje_jak_import(leader_client):
    r = leader_client.post('/api/packages', json=payload())

    assert r.status_code == 201
    c = carton('M1')
    assert c.added_manually is True
    assert c.imported_by is not None
    assert gstat().amounts == 12


def test_reczne_dodanie_dolicza_do_istniejacej_linii(leader_client):
    leader_client.post('/api/packages', json=payload(barcode='M1', stueckzahl=10))
    leader_client.post('/api/packages', json=payload(barcode='M2', stueckzahl=5))

    assert gstat().amounts == 15
    assert logistat.GeneralStat.query.count() == 1


def test_duplikat_barcode_daje_409(leader_client):
    leader_client.post('/api/packages', json=payload())
    r = leader_client.post('/api/packages', json=payload())

    assert r.status_code == 409
    assert logistat.ImportedCarton.query.count() == 1
    assert gstat().amounts == 12, 'odrzucony duplikat nie moze doliczyc drugi raz'


def test_brakujace_pola_daja_400(leader_client):
    for pole in ('barcode', 'land', 'uebergabe_nr', 'ziel_datum'):
        r = leader_client.post('/api/packages', json=payload(**{pole: ''}))
        assert r.status_code == 400, pole
    assert logistat.ImportedCarton.query.count() == 0


def test_zla_stueckzahl_daje_400(leader_client):
    for zla in (0, -5, 'abc', None):
        r = leader_client.post('/api/packages', json=payload(stueckzahl=zla))
        assert r.status_code == 400, zla
    assert logistat.ImportedCarton.query.count() == 0


def test_zla_data_daje_400(leader_client):
    r = leader_client.post('/api/packages', json=payload(ziel_datum='32.13.2026'))

    assert r.status_code == 400
    assert logistat.ImportedCarton.query.count() == 0


def test_double_rate_przy_recznym_dodaniu(leader_client):
    leader_client.post('/api/packages', json=payload(double_rate=True))

    assert carton('M1').double_rate is True
    assert logistat.double_rate_amount_map()[('UB-1', 'PL', ZIEL)] == 12


def test_operator_nie_moze_dodac_paczki(client):
    r = client.post('/api/packages', json=payload())

    assert r.status_code in (302, 401)
    assert logistat.ImportedCarton.query.count() == 0


# ── PUT /api/packages/<id> ───────────────────────────────────────────────────

def test_edycja_zaimportowanej_paczki_zabroniona(leader_client):
    logistat.db.session.add(logistat.ImportedCarton(
        barcode='IMP1', land='PL', stueckzahl=10, ziel_datum=ZIEL,
        uebergabe_nr='UB-1', added_manually=False))
    logistat.db.session.commit()

    r = leader_client.put(f'/api/packages/{carton("IMP1").id}',
                          json=payload(barcode='IMP1', stueckzahl=99))

    assert r.status_code == 403
    assert carton('IMP1').stueckzahl == 10


def test_edycja_ilosci_przelicza_linie(leader_client):
    leader_client.post('/api/packages', json=payload(stueckzahl=12))
    cid = carton('M1').id

    r = leader_client.put(f'/api/packages/{cid}', json=payload(stueckzahl=30))

    assert r.status_code == 200
    assert gstat().amounts == 30
    assert carton('M1').modified_by is not None


def test_zmiana_grupy_przenosi_miedzy_liniami(leader_client):
    leader_client.post('/api/packages', json=payload(barcode='M1', stueckzahl=10))
    leader_client.post('/api/packages', json=payload(barcode='M2', stueckzahl=5))
    cid = carton('M1').id

    r = leader_client.put(f'/api/packages/{cid}',
                          json=payload(barcode='M1', stueckzahl=10, uebergabe_nr='UB-2'))

    assert r.status_code == 200
    assert gstat(list_id='UB-1').amounts == 5
    assert gstat(list_id='UB-2').amounts == 10
    suma_linii = sum(s.amounts for s in logistat.GeneralStat.query.all())
    assert suma_linii == 15, 'przeniesienie nie moze zgubic ani zdublowac sztuk'


def test_kolizja_barcode_przy_edycji_daje_409(leader_client):
    leader_client.post('/api/packages', json=payload(barcode='M1'))
    leader_client.post('/api/packages', json=payload(barcode='M2'))
    cid = carton('M1').id

    r = leader_client.put(f'/api/packages/{cid}', json=payload(barcode='M2'))

    assert r.status_code == 409
    assert carton('M1') is not None


def test_edycja_z_bledna_walidacja_nic_nie_zmienia(leader_client):
    leader_client.post('/api/packages', json=payload(stueckzahl=12))
    cid = carton('M1').id

    r = leader_client.put(f'/api/packages/{cid}', json=payload(stueckzahl=-1))

    assert r.status_code == 400
    assert carton('M1').stueckzahl == 12
    assert gstat().amounts == 12


def test_edycja_nieistniejacej_paczki_daje_404(leader_client):
    assert leader_client.put('/api/packages/9999', json=payload()).status_code == 404
