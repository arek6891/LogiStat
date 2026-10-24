"""Total Amount w Statystykach ogolnych = suma wszystkich kategorii OPROCZ
Labelling twice i triple (operacja, 2026-10-15) — w obu wierszach, takze
zoltym double rate. Do tej daty byl to sam „Labelling one".

Twice i triple to te same sztuki biżuterii z dodatkowymi etykietami (×1,5 / ×2),
wiec w sumie liczylyby sie drugi raz.
"""
import io
from datetime import date

import openpyxl

from logistat.extensions import db
from logistat.kategorie import STAT_CATEGORIES, STAT_CATEGORY_LABELS_PL, TOTAL_AMOUNT_BEZ
from logistat.models import GeneralStat
from logistat.web.wspolne import process_import_rows


LADOWANIE = date(2026, 9, 10)
ILOSCI = {
    'labelling_on':  40,
    'labelling_tvl': 7,
    'textile':       3,
    'sorting':       5,
}
KOLUMNA_TOTAL_AMOUNT = 8   # 'Loading date','Double Rate','Week','List-ID',
                           # 'Country of destination','Country ledger','Amounts','Total Amount'


def linia(list_id='UB-1', ilosci=None, amounts=100):
    s = GeneralStat(loading_date=LADOWANIE, week_number=37, list_id=list_id,
                             country_ledger='PL', country_of_destination='Polska',
                             amounts=amounts)
    s.set_category_data({k: {'amount': v, 'cost': 0.0}
                         for k, v in (ilosci if ilosci is not None else ILOSCI).items()})
    db.session.add(s)
    db.session.commit()
    return s


def eksport(admin_client):
    r = admin_client.get('/general-stats/export')
    assert r.status_code == 200
    return openpyxl.load_workbook(io.BytesIO(r.data)).active


# ── stala ────────────────────────────────────────────────────────────────────

def test_kategorie_poza_total_amount_sa_w_liscie_kategorii():
    assert set(TOTAL_AMOUNT_BEZ) == {'labelling_tvl', 'labelling_try'}
    assert set(TOTAL_AMOUNT_BEZ) <= set(STAT_CATEGORIES)


# ── eksport Excel ────────────────────────────────────────────────────────────

def test_eksport_liczy_total_amount_bez_twice_i_triple(admin_client):
    linia()

    ws = eksport(admin_client)

    assert ws.cell(row=3, column=KOLUMNA_TOTAL_AMOUNT).value == 48, \
        '40 + 3 + 5; z twice (7) wyszloby 55'


def test_eksport_total_amount_bez_labelling_one(admin_client):
    linia(ilosci={'sorting': 12, 'textile': 8, 'labelling_try': 4})

    ws = eksport(admin_client)

    assert ws.cell(row=3, column=KOLUMNA_TOTAL_AMOUNT).value == 20


def test_zolty_wiersz_double_rate_liczy_tak_samo(admin_client, acting_admin):
    """Do 2026-10-15 zolty wiersz byl suma wszystkich kategorii (TODO czekalo
    na operacje) — teraz ta sama regula co zwykly wiersz."""
    process_import_rows([{
        'barcode': 'B-DR', 'land': 'PL', 'stueckzahl': 10, 'kategorie': 'textile',
        'ziel_datum': LADOWANIE, 'uebergabe_nr': 'UB-1', 'double_rate': True,
    }], LADOWANIE)
    s = GeneralStat.query.filter_by(list_id='UB-1').first()
    s.set_category_data({k: {'amount': v, 'cost': 0.0} for k, v in ILOSCI.items()})
    s.set_double_rate_category_data({k: {'amount': v, 'cost': 0.0} for k, v in ILOSCI.items()})
    db.session.commit()

    ws = eksport(admin_client)

    assert ws.cell(row=3, column=KOLUMNA_TOTAL_AMOUNT).value == 48, 'zwykly wiersz'
    assert ws.cell(row=4, column=2).value == 'DOUBLE RATE'
    assert ws.cell(row=4, column=KOLUMNA_TOTAL_AMOUNT).value == 48, 'zolty wiersz: ta sama regula'


# ── ekran ────────────────────────────────────────────────────────────────────

def test_strona_pokazuje_total_amount_bez_twice_i_triple(admin_client):
    linia()

    html = admin_client.get(
        f'/general-stats?date_from={LADOWANIE}&date_to={LADOWANIE}').get_data(as_text=True)

    assert 'class="row-total-amount"' in html
    assert 'data-val="48"' in html
    assert 'data-val="55"' not in html
    assert 'TOTAL_AMOUNT_BEZ = ["labelling_tvl", "labelling_try"]' in html, 'JS po edycji'


def test_strona_pokazuje_polowki_z_labelling_twice(admin_client):
    # 3 sztuki podwojnie × 1,5 = 4,5 — nie moze zostac uciete do 4.
    linia(ilosci={'labelling_on': 10, 'labelling_tvl': 4.5})

    html = admin_client.get(
        f'/general-stats?date_from={LADOWANIE}&date_to={LADOWANIE}').get_data(as_text=True)

    assert 'value="4.5"' in html


# ── etykiety dwuczlonowe ─────────────────────────────────────────────────────

def test_kazda_kategoria_ma_polskie_tlumaczenie():
    brakujace = [k for k in STAT_CATEGORIES
                 if k not in STAT_CATEGORY_LABELS_PL]

    assert brakujace == []
