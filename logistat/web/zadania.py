"""Zadania dodatkowe (operacja 2026-11-02) — kafelek w Dziale etykietowania,
zastepuje „Wpis ilosci”: osoba, dzial, czas od–do (suwak), czynnosc dodatkowa
z listy admina, komentarz; autozapis per wiersz, eksport do Excela.
Lista czynnosci dodatkowych: Supervisor → Czynności dodatkowe."""
import logging

from flask import Blueprint, abort, jsonify, redirect, render_template, request, url_for
from flask_login import current_user
from openpyxl import Workbook
from sqlalchemy.exc import IntegrityError

from logistat.czas import teraz_utc, utc_to_local
from logistat.extensions import db
from logistat.models import CzynnoscDodatkowa, User, ZadanieDodatkowe, get_or_create_shift
from logistat.web.excel import odpowiedz_xlsx, styl_naglowka
from logistat.web.wspolne import (
    admin_required, json_body, leader_required, parse_czas_utc, parse_date, parse_shift_number,
    require_int)
from logistat.zadania import (
    DZIALY, GODZIN_PO_POLNOCY, KOMENTARZ_MAX, MAX_DNI_EKSPORTU, NAZWA_CZYNNOSCI_MAX, blad_zakresu)
from logistat.zadania_dane import (
    czynnosci_dodatkowe, stan_zmiany, uzyte_czynnosci, wiersze_eksportu, zadanie_dict)

log = logging.getLogger(__name__)
bp = Blueprint('zadania', __name__)


@bp.route('/zadania-dodatkowe')
@leader_required
def zadania_dodatkowe():
    dzien = parse_date(request.args.get('date'))
    numer = request.args.get('shift', type=int)
    return render_template('zadania_dodatkowe.html', dzien=dzien,
                           zmiana=numer if numer in (1, 2) else 1,
                           godzin_po_polnocy=GODZIN_PO_POLNOCY)


@bp.route('/api/zadania-dodatkowe', methods=['GET'])
@leader_required
def api_zadania():
    dzien = parse_date(request.args.get('date'))
    shift = get_or_create_shift(dzien, parse_shift_number(request.args.get('shift')))
    db.session.commit()
    return jsonify(stan_zmiany(shift))


def _pola_zadania(d, dzien, obecna_czynnosc=None):
    """Walidacja pelnego wiersza → dict pol modelu (400 przy bledzie)."""
    user_id = require_int(d.get('user_id'), 'user_id')
    osoba = db.session.get(User, user_id)
    if osoba is None:
        abort(400, 'Nieznana osoba.')
    dzial = d.get('dzial')
    if dzial not in DZIALY:
        abort(400, 'Wybierz dział z listy.')
    od, do = parse_czas_utc(d.get('od')), parse_czas_utc(d.get('do'))
    blad = blad_zakresu(od, do, dzien)
    if blad:
        abort(400, blad)
    czynnosc_id = d.get('czynnosc_id')
    if czynnosc_id is not None:
        czynnosc_id = require_int(czynnosc_id, 'czynnosc_id')
        c = db.session.get(CzynnoscDodatkowa, czynnosc_id)
        # Wylaczona czynnosc zostaje tam, gdzie juz jest (jak listy zwrotow).
        if c is None or (not c.aktywna and c.id != obecna_czynnosc):
            abort(400, 'Tej czynności nie ma już na liście — odśwież stronę.')
    komentarz = d.get('komentarz') or ''
    if not isinstance(komentarz, str):
        abort(400, 'Komentarz musi być tekstem.')
    komentarz = komentarz.strip()
    if len(komentarz) > KOMENTARZ_MAX:
        abort(400, f'Komentarz może mieć najwyżej {KOMENTARZ_MAX} znaków.')
    return {'user_id': user_id, 'dzial': dzial, 'od': od, 'do': do,
            'czynnosc_id': czynnosc_id, 'komentarz': komentarz or None}


@bp.route('/api/zadania-dodatkowe', methods=['POST'])
@leader_required
def api_zadanie_dodaj():
    """{date, shift, user_id, dzial, od, do, czynnosc_id?, komentarz?} → nowy wiersz."""
    d = json_body()
    dzien = parse_date(d.get('date'))
    shift = get_or_create_shift(dzien, parse_shift_number(d.get('shift')))
    z = ZadanieDodatkowe(shift_id=shift.id, wpisal_id=current_user.id,
                         **_pola_zadania(d, dzien))
    db.session.add(z)
    db.session.commit()
    return jsonify(zadanie_dict(z)), 201


@bp.route('/api/zadania-dodatkowe/<int:zadanie_id>', methods=['PUT'])
@leader_required
def api_zadanie_zmien(zadanie_id):
    """Caly wiersz naraz (ekran zapisuje wiersz, nie pole)."""
    z = ZadanieDodatkowe.query.filter_by(id=zadanie_id).with_for_update().first_or_404()
    for pole, wartosc in _pola_zadania(json_body(), z.shift.date, z.czynnosc_id).items():
        setattr(z, pole, wartosc)
    z.zmienil_id, z.zmieniono_at = current_user.id, teraz_utc()
    db.session.commit()
    return jsonify(zadanie_dict(z))


@bp.route('/api/zadania-dodatkowe/<int:zadanie_id>', methods=['DELETE'])
@leader_required
def api_zadanie_usun(zadanie_id):
    z = db.get_or_404(ZadanieDodatkowe, zadanie_id)
    log.info('Zadanie dodatkowe %s (osoba %s, %s) usuniete przez %s',
             z.id, z.user_id, z.dzial, current_user.username)
    db.session.delete(z)
    db.session.commit()
    return jsonify({'ok': True})


@bp.route('/zadania-dodatkowe/export')
@leader_required
def zadania_export():
    od = parse_date(request.args.get('date_from'), 'date_from')
    do = parse_date(request.args.get('date_to'), 'date_to')
    if do < od:
        od, do = do, od
    if (do - od).days >= MAX_DNI_EKSPORTU:
        abort(400, f'Zakres najwyżej {MAX_DNI_EKSPORTU} dni.')
    wb = Workbook()
    ws = wb.active
    ws.title = 'Zadania dodatkowe'
    naglowki = [('Data', 12), ('Zmiana', 8), ('Pracownik', 26), ('Dział', 14), ('Od', 17),
                ('Do', 17), ('Godziny', 9), ('Czynność dodatkowa', 24), ('Komentarz', 40),
                ('Wpisał(a)', 20)]
    for kol, (nazwa, szer) in enumerate(naglowki, 1):
        styl_naglowka(ws.cell(row=1, column=kol, value=nazwa), '325C96')
        ws.column_dimensions[chr(64 + kol)].width = szer
    for nr, w in enumerate(wiersze_eksportu(od, do), 2):
        wartosci = [w['data'], w['zmiana'], w['osoba'], w['dzial'],
                    utc_to_local(w['od']).replace(tzinfo=None), utc_to_local(w['do']).replace(tzinfo=None),
                    round(w['godziny'], 2), w['czynnosc'], w['komentarz'], w['wpisal']]
        for kol, v in enumerate(wartosci, 1):
            ws.cell(row=nr, column=kol, value=v)
        ws.cell(row=nr, column=1).number_format = 'DD.MM.YYYY'
        ws.cell(row=nr, column=5).number_format = 'DD.MM.YYYY HH:MM'
        ws.cell(row=nr, column=6).number_format = 'DD.MM.YYYY HH:MM'
        ws.cell(row=nr, column=7).number_format = '0.00'
    ws.auto_filter.ref = f'A1:J{max(ws.max_row, 1)}'
    ws.freeze_panes = 'A2'
    return odpowiedz_xlsx(wb, f'zadania_dodatkowe_{od.isoformat()}_{do.isoformat()}.xlsx')


@bp.route('/data-entry')
@leader_required
def stary_wpis_ilosci():
    """Wpis ilosci (do 2026-11-02) — zakladki prowadza na Zadania dodatkowe."""
    return redirect(url_for('zadania.zadania_dodatkowe'))


# ── Supervisor → Czynności dodatkowe ─────────────────────────────────────────

@bp.route('/admin/zadania/czynnosci')
@admin_required
def admin_czynnosci():
    return render_template('admin_czynnosci_dodatkowe.html',
                           rodzaje={'czynnosc': 'Czynności dodatkowe'},
                           licencje={'czynnosc': czynnosci_dodatkowe()},
                           uzywane=uzyte_czynnosci(), max_nazwy=NAZWA_CZYNNOSCI_MAX)


def _nazwa(wartosc):
    nazwa = ' '.join(wartosc.split()) if isinstance(wartosc, str) else ''
    if not nazwa:
        abort(400, 'Nazwa nie może być pusta.')
    if len(nazwa) > NAZWA_CZYNNOSCI_MAX:
        abort(400, f'Nazwa może mieć najwyżej {NAZWA_CZYNNOSCI_MAX} znaków.')
    return nazwa


def _zapisz_liste():
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        abort(409, 'Taka nazwa już jest na liście.')


@bp.route('/api/zadania/czynnosci', methods=['POST'])
@admin_required
def api_czynnosc_dodaj():
    nazwa = _nazwa(json_body().get('nazwa'))
    ostatnia = db.session.query(db.func.max(CzynnoscDodatkowa.kolejnosc)).scalar()
    c = CzynnoscDodatkowa(nazwa=nazwa, kolejnosc=(ostatnia or 0) + 1)
    db.session.add(c)
    _zapisz_liste()
    return jsonify(c.to_dict()), 201


@bp.route('/api/zadania/czynnosci/<int:czynnosc_id>', methods=['PUT'])
@admin_required
def api_czynnosc_zmien(czynnosc_id):
    """{nazwa} / {aktywna} / {przesun: -1|1} — jak listy Sorting Data."""
    c = db.get_or_404(CzynnoscDodatkowa, czynnosc_id)
    d = json_body()
    if 'nazwa' in d:
        c.nazwa = _nazwa(d.get('nazwa'))
    if 'aktywna' in d:
        if not isinstance(d['aktywna'], bool):
            abort(400, 'Pole „aktywna” musi być true/false.')
        c.aktywna = d['aktywna']
    if 'przesun' in d:
        if d['przesun'] not in (-1, 1) or isinstance(d['przesun'], bool):
            abort(400, 'Pole „przesun” musi być -1 albo 1.')
        lista = czynnosci_dodatkowe()
        i = lista.index(c)
        j = i + d['przesun']
        if 0 <= j < len(lista):
            lista[i], lista[j] = lista[j], lista[i]
            for poz, element in enumerate(lista):
                element.kolejnosc = poz
    _zapisz_liste()
    return jsonify(c.to_dict())


@bp.route('/api/zadania/czynnosci/<int:czynnosc_id>', methods=['DELETE'])
@admin_required
def api_czynnosc_usun(czynnosc_id):
    c = db.get_or_404(CzynnoscDodatkowa, czynnosc_id)
    if c.id in uzyte_czynnosci():
        abort(409, 'Czynność jest użyta w zadaniach — można ją wyłączyć albo zmienić nazwę, nie usunąć.')
    db.session.delete(c)
    db.session.commit()
    return jsonify({'ok': True})
