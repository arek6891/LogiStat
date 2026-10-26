"""Zwroty (kafelek od 2026-10-24). „Zwroty Paczek” (2026-10-26): tabela jak w
arkuszu operacji Return_<miesiac>, filtry, eksport do Excela."""
from datetime import date

from flask import Blueprint, render_template, request
from openpyxl import Workbook
from openpyxl.styles import Alignment

from logistat.czas import local_today
from logistat.web.excel import odpowiedz_xlsx
from logistat.web.wspolne import leader_required
from logistat.zwroty_dane import NAGLOWKI_ZWROTOW, brandy_zwrotow, wiersze_zwrotow

bp = Blueprint('zwroty', __name__)

# Szerokosci kolumn z arkusza operacji (Return_September_2026).
SZEROKOSCI_KOLUMN = (22.1, 10.7, 13.7, 17.9, 9.3, 9.0, 12.7, 11.6,
                     26.3, 19.3, 28.6, 20.9, 25.6, 13.7, 11.7)


@bp.route('/zwroty')
@leader_required
def zwroty():
    return render_template('zwroty.html')


def _dzien(wartosc):
    """Data z filtra; pusta albo bledna → None (strona Jinja — bez 400)."""
    try:
        return date.fromisoformat(wartosc) if wartosc else None
    except ValueError:
        return None


def _filtry():
    """Filtry z query stringu. Domyslnie tylko dzisiejszy dzien (operacja)."""
    dzis = local_today()
    od_arg = _dzien(request.args.get('date_from', ''))
    do_arg = _dzien(request.args.get('date_to', ''))
    # Jedna granica = jeden dzien; zadnej = dzis.
    od = od_arg or do_arg or dzis
    do = do_arg or od
    if od > do:
        od, do = do, od
    return {
        'od': od, 'do': do,
        'brand': request.args.get('brand', '').strip() or None,
        'paketnummer': request.args.get('paketnummer', '').strip() or None,
    }


@bp.route('/zwroty/paczki')
@leader_required
def zwroty_paczek():
    f = _filtry()
    return render_template('zwroty_paczek.html', naglowki=NAGLOWKI_ZWROTOW,
                           wiersze=wiersze_zwrotow(**f), brandy=brandy_zwrotow(),
                           filtry=f, dzis=local_today())


@bp.route('/zwroty/paczki/export')
@leader_required
def zwroty_paczek_export():
    f = _filtry()
    wb = Workbook()
    ws = wb.active
    ws.title = 'Returns'
    ws.append(list(NAGLOWKI_ZWROTOW))
    for komorka in ws[1]:
        komorka.alignment = Alignment(horizontal='center')
    for wiersz in wiersze_zwrotow(**f):
        ws.append(list(wiersz))
        nr = ws.max_row
        # Paketnummer zaczyna sie od „%” i ma wiodace zera — zawsze tekst.
        ws.cell(nr, 1).number_format = '@'
        if isinstance(ws.cell(nr, 3).value, date):
            ws.cell(nr, 3).number_format = 'DD.MM.YYYY'
    for i, szer in enumerate(SZEROKOSCI_KOLUMN, start=1):
        ws.column_dimensions[ws.cell(1, i).column_letter].width = szer
    ws.auto_filter.ref = ws.dimensions
    nazwa = (f'Returns_{f["od"]:%Y-%m-%d}.xlsx' if f['od'] == f['do']
             else f'Returns_{f["od"]:%Y-%m-%d}_{f["do"]:%Y-%m-%d}.xlsx')
    return odpowiedz_xlsx(wb, nazwa)
