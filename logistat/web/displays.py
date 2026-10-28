"""Dekoracje (kafelek od 2026-10-24, do 2026-10-28 „Akcje - Displays”).

Akcje na wykresie Gantta (`/displays`), ekran akcji z indexami (autozapis),
historia zakonczonych akcji i listy typow / modeli stojakow (Supervisor).
Akcja zakonczona jest tylko do odczytu — zmienia ja dopiero „Przywróć”.
Etykiety POS: lista numerow z Excela → arkusz kodow kreskowych (PDF).
"""
import io
import logging

import openpyxl
from flask import Blueprint, abort, flash, jsonify, make_response, redirect, render_template, request, url_for
from flask_login import current_user
from openpyxl import Workbook
from sqlalchemy.exc import IntegrityError

from logistat.czas import local_today, teraz_utc
from logistat.dekoracje import (
    ETYKIET_MAX, KOPIE_MAX, LICZBA_MAX, NAGLOWEK_EKSPORTU_POS, NAZWA_MAX, NAZWA_SLOWNIKA_MAX,
    POLA_LICZB, POLA_PRODUKTYWNOSCI, POLA_SLOWNIKA, RODZAJE_SLOWNIKA, data_z_tekstu, wiersze_pos)
from logistat.dekoracje_dane import (
    akcja_dict, akcje_gantt, akcje_historia, importuj_pos, index_dict, listy_dla_akcji,
    ostatni_import_pos, pos_dict, pos_lista, slownik, uzyte_pozycje_slownika)
from logistat.extensions import db
from logistat.models import AkcjaDekoracji, IndexDekoracji, PosDekoracji, SlownikDekoracji
from logistat.pdf_etykiet import NA_STRONIE, pdf_etykiet
from logistat.web.excel import odpowiedz_xlsx, styl_naglowka
from logistat.web.wspolne import admin_required, json_body, leader_required

bp = Blueprint('displays', __name__)
logger = logging.getLogger(__name__)


# ── ekrany ───────────────────────────────────────────────────────────────────

@bp.route('/displays')
@leader_required
def displays():
    dzis = local_today()
    return render_template('displays.html', akcje=akcje_gantt(dzis), dzis=dzis)


@bp.route('/displays/historia')
@leader_required
def historia():
    return render_template('displays_historia.html', akcje=akcje_historia(local_today()))


@bp.route('/displays/akcje/<int:akcja_id>')
@leader_required
def akcja(akcja_id):
    a = db.get_or_404(AkcjaDekoracji, akcja_id)
    return render_template('displays_akcja.html', akcja=akcja_dict(a, local_today()),
                           listy=listy_dla_akcji(a), pola_liczb=POLA_LICZB,
                           pola_prod=POLA_PRODUKTYWNOSCI, max_nazwy=NAZWA_MAX, max_liczby=LICZBA_MAX)


# ── walidacja ────────────────────────────────────────────────────────────────

def _nazwa(wartosc, maks=NAZWA_MAX):
    nazwa = ' '.join(wartosc.split()) if isinstance(wartosc, str) else ''
    if not nazwa:
        abort(400, 'Nazwa nie może być pusta.')
    if len(nazwa) > maks:
        abort(400, f'Nazwa może mieć najwyżej {maks} znaków.')
    return nazwa


def _daty(d):
    """Obie daty naraz (ekran wysyla je razem) — inaczej zmiana „od” przed „do”
    zapisywalaby posredni, bledny stan."""
    od, do = data_z_tekstu(d.get('od')), data_z_tekstu(d.get('do'))
    if od is None or do is None:
        abort(400, 'Podaj datę startu i końca akcji (RRRR-MM-DD).')
    if do < od:
        abort(400, 'Data końca nie może być przed datą startu.')
    return od, do


def _liczba(pole, wartosc, calkowita):
    if wartosc is None or wartosc == '':
        return None
    if isinstance(wartosc, bool) or not isinstance(wartosc, (int, float)):
        abort(400, f'{pole}: wpisz liczbę.')
    if calkowita and wartosc != int(wartosc):
        abort(400, f'{pole}: wpisz liczbę całkowitą.')
    if wartosc < 0 or wartosc >= LICZBA_MAX:
        abort(400, f'{pole}: liczba od 0 do {LICZBA_MAX - 1}.')
    return int(wartosc) if calkowita else float(wartosc)


def _edytowalna(akcja):
    if akcja.zakonczona_at is not None:
        abort(409, 'Akcja jest zakończona — najpierw „Przywróć”, żeby ją zmienić.')


def _zmieniono(obiekt):
    obiekt.zmienil_id = current_user.id
    obiekt.zmieniono_at = teraz_utc()


# ── akcje ────────────────────────────────────────────────────────────────────

@bp.route('/api/dekoracje/akcje', methods=['POST'])
@leader_required
def api_akcja_dodaj():
    d = json_body()
    od, do = _daty(d)
    a = AkcjaDekoracji(nazwa=_nazwa(d.get('nazwa')), data_od=od, data_do=do,
                       utworzyl_id=current_user.id)
    db.session.add(a)
    db.session.commit()
    return jsonify(akcja_dict(a, local_today())), 201


@bp.route('/api/dekoracje/akcje/<int:akcja_id>', methods=['PUT'])
@leader_required
def api_akcja_zmien(akcja_id):
    """{nazwa, od, do} — nazwa i daty razem (jeden autozapis naglowka)."""
    a = db.get_or_404(AkcjaDekoracji, akcja_id)
    _edytowalna(a)
    d = json_body()
    a.nazwa = _nazwa(d.get('nazwa'))
    a.data_od, a.data_do = _daty(d)
    _zmieniono(a)
    db.session.commit()
    return jsonify(akcja_dict(a, local_today(), z_indexami=False))


@bp.route('/api/dekoracje/akcje/<int:akcja_id>/status', methods=['PUT'])
@leader_required
def api_akcja_status(akcja_id):
    """{zakonczona: true} — „Zakończ akcję” (do historii); false — „Przywróć”."""
    a = db.get_or_404(AkcjaDekoracji, akcja_id)
    zakonczona = json_body().get('zakonczona')
    if not isinstance(zakonczona, bool):
        abort(400, 'Pole „zakonczona” musi być true/false.')
    if zakonczona and a.zakonczona_at is None:
        a.zakonczona_at, a.zakonczyl_id = teraz_utc(), current_user.id
    elif not zakonczona:
        a.zakonczona_at = a.zakonczyl_id = None
    _zmieniono(a)
    db.session.commit()
    return jsonify(akcja_dict(a, local_today(), z_indexami=False))


# ── indexy ───────────────────────────────────────────────────────────────────

def _pozycja_slownika(pole, rodzaj, wartosc, obecna):
    if wartosc is None or wartosc == '':
        return None
    if isinstance(wartosc, bool) or not isinstance(wartosc, int):
        abort(400, f'Nieznana pozycja listy „{RODZAJE_SLOWNIKA[rodzaj]}”.')
    p = db.session.get(SlownikDekoracji, wartosc)
    # Wylaczona pozycja zostaje mozliwa tylko w indexie, ktory juz ja ma.
    if p is None or p.rodzaj != rodzaj or (not p.aktywna and p.id != obecna):
        abort(400, f'Nieznana albo wyłączona pozycja listy „{RODZAJE_SLOWNIKA[rodzaj]}” — odśwież stronę.')
    return p.id


@bp.route('/api/dekoracje/akcje/<int:akcja_id>/indexy', methods=['POST'])
@leader_required
def api_index_dodaj(akcja_id):
    """„+ Index” — pusty index z nazwa „Index N” (nazwe i reszte wpisuje sie potem)."""
    a = db.get_or_404(AkcjaDekoracji, akcja_id)
    _edytowalna(a)
    nr = (db.session.query(db.func.max(IndexDekoracji.kolejnosc))
          .filter(IndexDekoracji.akcja_id == a.id).scalar() or 0) + 1
    ix = IndexDekoracji(akcja_id=a.id, nazwa=f'Index {nr}', kolejnosc=nr)
    _zmieniono(ix)
    db.session.add(ix)
    db.session.commit()
    return jsonify(index_dict(ix)), 201


@bp.route('/api/dekoracje/indexy/<int:index_id>', methods=['PUT'])
@leader_required
def api_index_zmien(index_id):
    """Czesciowy zapis — zmienia tylko podane pola (dwie osoby na roznych
    polach jednego indexu nie nadpisuja sobie nawzajem)."""
    ix = db.get_or_404(IndexDekoracji, index_id)
    _edytowalna(ix.akcja)
    d = json_body()
    etykiety = dict(POLA_LICZB + POLA_PRODUKTYWNOSCI)
    if 'nazwa' in d:
        ix.nazwa = _nazwa(d['nazwa'])
    for pole, _ in POLA_LICZB:
        if pole in d:
            setattr(ix, pole, _liczba(etykiety[pole], d[pole], calkowita=True))
    for pole, _ in POLA_PRODUKTYWNOSCI:
        if pole in d:
            setattr(ix, pole, _liczba(etykiety[pole], d[pole], calkowita=False))
    for pole, rodzaj in POLA_SLOWNIKA:
        if pole in d:
            setattr(ix, pole, _pozycja_slownika(pole, rodzaj, d[pole], getattr(ix, pole)))
    _zmieniono(ix)
    db.session.commit()
    return jsonify(index_dict(ix))


@bp.route('/api/dekoracje/indexy/<int:index_id>', methods=['DELETE'])
@leader_required
def api_index_usun(index_id):
    ix = db.get_or_404(IndexDekoracji, index_id)
    _edytowalna(ix.akcja)
    db.session.delete(ix)
    db.session.commit()
    return jsonify({'ok': True})


# ── listy (Supervisor → Listy Dekoracji) ─────────────────────────────────────

@bp.route('/admin/dekoracje')
@admin_required
def admin_slownik():
    lista = slownik()
    return render_template('admin_dekoracje.html', rodzaje=RODZAJE_SLOWNIKA,
                           licencje={r: [p for p in lista if p.rodzaj == r] for r in RODZAJE_SLOWNIKA},
                           uzywane=uzyte_pozycje_slownika(), max_nazwy=NAZWA_SLOWNIKA_MAX)


def _zapisz_slownik():
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        abort(409, 'Taka nazwa już jest na tej liście.')


@bp.route('/api/dekoracje/slownik', methods=['POST'])
@admin_required
def api_slownik_dodaj():
    d = json_body()
    rodzaj = d.get('rodzaj')
    if rodzaj not in RODZAJE_SLOWNIKA:
        abort(400, 'Nieznana lista.')
    nazwa = _nazwa(d.get('nazwa'), NAZWA_SLOWNIKA_MAX)
    ostatnia = db.session.query(db.func.max(SlownikDekoracji.kolejnosc))\
        .filter(SlownikDekoracji.rodzaj == rodzaj).scalar()
    p = SlownikDekoracji(rodzaj=rodzaj, nazwa=nazwa, kolejnosc=(ostatnia or 0) + 1)
    db.session.add(p)
    _zapisz_slownik()
    return jsonify(p.to_dict()), 201


@bp.route('/api/dekoracje/slownik/<int:poz_id>', methods=['PUT'])
@admin_required
def api_slownik_zmien(poz_id):
    """{nazwa} / {aktywna} / {przesun: -1|1} — jak listy Sorting Data."""
    p = db.get_or_404(SlownikDekoracji, poz_id)
    d = json_body()
    if 'nazwa' in d:
        p.nazwa = _nazwa(d.get('nazwa'), NAZWA_SLOWNIKA_MAX)
    if 'aktywna' in d:
        if not isinstance(d['aktywna'], bool):
            abort(400, 'Pole „aktywna” musi być true/false.')
        p.aktywna = d['aktywna']
    if 'przesun' in d:
        if d['przesun'] not in (-1, 1) or isinstance(d['przesun'], bool):
            abort(400, 'Pole „przesun” musi być -1 albo 1.')
        lista = slownik(p.rodzaj)
        i = lista.index(p)
        j = i + d['przesun']
        if 0 <= j < len(lista):
            lista[i], lista[j] = lista[j], lista[i]
            for poz, element in enumerate(lista):
                element.kolejnosc = poz
    _zapisz_slownik()
    return jsonify(p.to_dict())


@bp.route('/api/dekoracje/slownik/<int:poz_id>', methods=['DELETE'])
@admin_required
def api_slownik_usun(poz_id):
    p = db.get_or_404(SlownikDekoracji, poz_id)
    if p.id in uzyte_pozycje_slownika():
        abort(409, 'Pozycja jest użyta w indexie akcji — można ją wyłączyć albo zmienić nazwę, nie usunąć.')
    db.session.delete(p)
    db.session.commit()
    return jsonify({'ok': True})


# ── Etykiety POS ─────────────────────────────────────────────────────────────

@bp.route('/displays/pos')
@leader_required
def pos():
    lista = pos_lista()
    return render_template('displays_pos.html', lista=[pos_dict(p) for p in lista],
                           ostatni_import=len(ostatni_import_pos()), na_stronie=NA_STRONIE,
                           kopie_max=KOPIE_MAX, naglowki=NAGLOWEK_EKSPORTU_POS)


@bp.route('/api/dekoracje/pos/import', methods=['POST'])
@leader_required
def api_pos_import():
    """Plik .xlsx: kolumna POS (wymagana) i Post Processing (opcjonalna)."""
    plik = request.files.get('file')
    if plik is None or not plik.filename:
        abort(400, 'Wybierz plik Excel (.xlsx).')
    try:
        wb = openpyxl.load_workbook(io.BytesIO(plik.read()), data_only=True, read_only=True)
    except Exception:
        abort(400, 'Nie można odczytać pliku — potrzebny Excel .xlsx.')
    try:
        ws = wb.active
        if ws is None:
            abort(400, 'Plik Excel jest pusty.')
        pozycje, ma_pp, bledy = wiersze_pos(ws.iter_rows(values_only=True))
    except ValueError as e:
        abort(400, str(e))
    finally:
        wb.close()
    if not pozycje and not bledy:
        abort(400, 'W pliku nie ma numerów POS.')
    wynik = importuj_pos(pozycje, ma_pp, current_user.id)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        abort(409, 'Ktoś w tej chwili importował te same numery — wczytaj plik jeszcze raz.')
    logger.info('Import listy POS: %s, bledow %d (uzytkownik %s)', wynik, len(bledy), current_user.id)
    return jsonify({**wynik, 'wczytane': len(pozycje), 'bledy': bledy, 'ma_pp': ma_pp,
                    'lista': [pos_dict(p) for p in pos_lista()],
                    'ostatni_import': len(ostatni_import_pos())})


@bp.route('/api/dekoracje/pos/<int:pos_id>', methods=['DELETE'])
@leader_required
def api_pos_usun(pos_id):
    p = db.get_or_404(PosDekoracji, pos_id)
    db.session.delete(p)
    db.session.commit()
    return jsonify({'ok': True})


@bp.route('/displays/pos/etykiety', methods=['POST'])
@leader_required
def pos_etykiety():
    """Arkusz etykiet (PDF w nowej karcie). Formularz: `zakres` = wszystkie |
    import (ostatni) | wybrane (+ `id`), `kopie` kazdej etykiety."""
    zakres = request.form.get('zakres')
    if zakres == 'wszystkie':
        lista = pos_lista()
    elif zakres == 'import':
        lista = ostatni_import_pos()
    elif zakres == 'wybrane':
        ids = {int(i) for i in request.form.getlist('id') if i.isdigit()}
        lista = [p for p in pos_lista() if p.id in ids]
    else:
        lista = []
    try:
        kopie = int(request.form.get('kopie') or 1)
    except ValueError:
        kopie = 0
    if not 1 <= kopie <= KOPIE_MAX:
        flash(f'Liczba kopii od 1 do {KOPIE_MAX}.', 'error')
        return redirect(url_for('displays.pos'))
    if not lista:
        flash('Nie ma etykiet do druku — zaznacz numery POS albo wczytaj listę.', 'error')
        return redirect(url_for('displays.pos'))
    if len(lista) * kopie > ETYKIET_MAX:
        flash(f'Za dużo etykiet naraz ({len(lista) * kopie}) — najwyżej {ETYKIET_MAX}.', 'error')
        return redirect(url_for('displays.pos'))
    odpowiedz = make_response(pdf_etykiet([p.numer for p in lista for _ in range(kopie)]))
    odpowiedz.headers['Content-Type'] = 'application/pdf'
    odpowiedz.headers['Content-Disposition'] = f'inline; filename="etykiety-pos-{local_today():%Y-%m-%d}.pdf"'
    return odpowiedz


@bp.route('/displays/pos/export')
@leader_required
def pos_export():
    """Lista do poprawki w Excelu — ten sam uklad wczytuje import (klucz = POS)."""
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = 'POS'
    ws.append(list(NAGLOWEK_EKSPORTU_POS))
    for komorka in ws[1]:
        styl_naglowka(komorka, '325C96')
    for p in pos_lista():
        ws.append([p.numer, {True: 'Tak', False: 'Nie'}.get(p.post_processing)])
        # Numer zawsze jako tekst — inaczej Excel zjada wiodace zera.
        ws.cell(ws.max_row, 1).number_format = '@'
    ws.column_dimensions['A'].width = 24
    ws.column_dimensions['B'].width = 18
    ws.auto_filter.ref = ws.dimensions
    return odpowiedz_xlsx(wb, f'POS_{local_today():%Y-%m-%d}.xlsx')
