"""Stanowiska na hali: skaner zmian (obecnosc), Czasy paczek (start / koniec / do dokonczenia /
zespol, tabela ilosci), podglad paczki i pracownika."""
from flask import Blueprint, jsonify, render_template, request
from sqlalchemy.orm import joinedload

from logistat.czas import local_today, teraz_utc
from logistat.extensions import db
from logistat.models import (
    ImportedCarton, Shift, ShiftAttendance, UDZIAL_PRZEKAZANA, UDZIAL_ZESPOL, UdzialPaczki,
    User, get_or_create_shift)
from logistat.paczki import (
    lista_osob, otwarte_udzialy, parse_scan_categories, przelicz_ilosci_udzialow,
    zamknij_paczke_wielu_osob, zapisz_tabele_kartonu)
from logistat.rozliczenie import klucz_linii, recompute_general_stat
from logistat.tabela_ilosci import TRYB_WZOR, TRYB_ZESPOL, normalizuj_tabele
from logistat.web.wspolne import (
    blad_nieznanej_paczki, json_body, leader_required, parse_date, parse_shift_number)

bp = Blueprint('stanowisko', __name__)


def blad_wlasciciela(carton):
    starter = db.session.get(User, carton.scan_start_by) if carton.scan_start_by else None
    return jsonify({
        'error': f'Paczkę rozpoczął {starter.display_name if starter else "inny pracownik"} — tylko on może ją zakończyć.'
    }), 403


def koniec_udzialu(carton, user, kategorie, zamknij_wszystkich, tabela=None):
    """Koniec paczki wielu osob: zamyka udzial tej osoby; paczka konczy sie,
    gdy nie zostal nikt otwarty (albo „zamknij dla wszystkich")."""
    otwarte = otwarte_udzialy(carton)
    moj = next((u for u in otwarte if u.user_id == user.id), None)
    if otwarte and not moj:
        return jsonify({'error': f'Nie pracujesz przy tej paczce (pracują: {lista_osob(otwarte)}).'}), 403
    if not otwarte:
        # Po przekazaniu: osoba, ktora wbila Start, nie ma jeszcze wiersza.
        if carton.scan_start_by != user.id:
            return blad_wlasciciela(carton)
        moj = UdzialPaczki(carton=carton, user_id=user.id, rodzaj=UDZIAL_PRZEKAZANA,
                           start_at=carton.scan_start_at)
        db.session.add(moj)

    teraz = teraz_utc()
    moj.end_at = teraz
    if tabela:
        moj.set_tabela(tabela)
    else:
        moj.set_ilosci(kategorie)
    if zamknij_wszystkich:
        for u in otwarte_udzialy(carton):
            u.end_at = teraz
            u.zamkniete_przez = user.id
    pozostali = otwarte_udzialy(carton)
    if not pozostali:
        zamknij_paczke_wielu_osob(carton, user.id, teraz)
    przelicz_ilosci_udzialow(carton, user.id)
    db.session.commit()

    if pozostali:
        msg = (f'Zakończono Twój udział ({moj.sztuki()} szt.). Przy paczce pracują jeszcze: '
               f'{lista_osob(pozostali)} — paczka zamknie się po ich końcu.')
    else:
        secs = carton.processing_seconds() or 0
        msg = f'Koniec zarejestrowany — paczka zamknięta, czas procesowania: {secs // 60}m {secs % 60}s.'
    return jsonify({'message': msg, 'zamknieta': not pozostali, 'carton': carton.to_dict()}), 200


def pracownik_i_paczka_z_body():
    """Wspolne wejscie stanowiska: (user, carton zablokowany FOR UPDATE) albo odpowiedz bledu."""
    data = json_body()
    employee_barcode = (data.get('employee_barcode') or '').strip()
    package_barcode = (data.get('package_barcode') or '').strip()
    if not employee_barcode:
        return data, None, None, (jsonify({'error': 'Brak kodu pracownika.'}), 400)
    if not package_barcode:
        return data, None, None, (jsonify({'error': 'Brak kodu paczki.'}), 400)
    user = User.query.filter_by(barcode_id=employee_barcode, is_active_user=True).first()
    if not user:
        return data, None, None, (jsonify({'error': 'Nieznany kod pracownika.'}), 404)
    carton = (ImportedCarton.query.filter_by(barcode=package_barcode)
              .with_for_update().first())
    if not carton:
        return data, user, None, blad_nieznanej_paczki(package_barcode)
    return data, user, carton, None


def tabela_z_body(data, carton, oczekiwany_tryb):
    """(tabela, odpowiedz_bledu) z `tabela` + `tryb` w body stanowiska.

    Tryb wybiera ekran przy otwarciu panelu (z `tryb_tabeli` paczki). Gdy
    w miedzyczasie ktos dolaczyl, tabela ma inny ksztalt — 409, panel od nowa.
    """
    if data.get('tryb') != oczekiwany_tryb:
        return None, (jsonify({
            'error': 'Przy paczce zmienił się skład osób (ktoś dołączył albo przekazał paczkę). '
                     'Zeskanuj paczkę jeszcze raz i wpisz ilości od nowa.',
            'zmiana_trybu': True}), 409)
    tabela, blad = normalizuj_tabele(data.get('tabela'), oczekiwany_tryb, carton.stueckzahl)
    if blad:
        return None, (jsonify({'error': blad}), 400)
    return tabela, None


@bp.route('/scanner/<int:shift_number>')
@leader_required
def scanner(shift_number):
    if shift_number not in (1, 2):
        shift_number = 1
    today = local_today()
    shift = get_or_create_shift(today, shift_number)
    attendances = ShiftAttendance.query.filter_by(shift_id=shift.id)\
        .order_by(ShiftAttendance.scanned_at.desc()).all()
    return render_template('scanner.html',
                           shift_number=shift_number,
                           shift=shift,
                           attendances=attendances,
                           today=today)


@bp.route('/api/scan', methods=['POST'])
@leader_required
def api_scan():
    data = json_body()
    barcode = str(data.get('barcode') or '').strip()
    shift_number = parse_shift_number(data.get('shift_number', 1))
    shift_date = parse_date(data.get('date'))

    if not barcode:
        return jsonify({'error': 'Brak kodu kreskowego.'}), 400

    # Look up user by barcode
    user = User.query.filter_by(barcode_id=barcode, is_active_user=True).first()
    if not user:
        return jsonify({
            'error': 'Nieznany kod kreskowy! Dodaj użytkownika w panelu.'
        }), 404

    # Get or create shift
    shift = get_or_create_shift(shift_date, shift_number)

    # Check if already scanned
    existing = ShiftAttendance.query.filter_by(
        shift_id=shift.id, user_id=user.id
    ).first()
    if existing:
        return jsonify({
            'warning': f'{user.display_name} już zarejestrowany/a na zmianę {shift_number}.',
            'user': user.to_dict(),
            'already_scanned': True
        }), 200

    # Register attendance
    attendance = ShiftAttendance(shift_id=shift.id, user_id=user.id)
    db.session.add(attendance)
    db.session.commit()

    return jsonify({
        'message': f'{user.display_name} zarejestrowany/a na zmianę {shift_number}.',
        'user': user.to_dict(),
        'attendance': attendance.to_dict()
    }), 201


@bp.route('/api/scan/<int:attendance_id>', methods=['DELETE'])
@leader_required
def api_unscan(attendance_id):
    attendance = db.get_or_404(ShiftAttendance, attendance_id)
    db.session.delete(attendance)
    db.session.commit()
    return jsonify({'message': 'Usunięto rejestrację.'}), 200


@bp.route('/api/shift/attendances', methods=['GET'])
@leader_required
def api_shift_attendances():
    shift_date = request.args.get('date', local_today().isoformat())
    shift_number = parse_shift_number(request.args.get('shift_number', 1))
    shift = Shift.query.filter_by(
        date=parse_date(shift_date),
        shift_number=shift_number
    ).first()
    if not shift:
        return jsonify({'attendances': [], 'shift': None}), 200
    attendances = ShiftAttendance.query.filter_by(shift_id=shift.id)\
        .options(joinedload(ShiftAttendance.user))\
        .order_by(ShiftAttendance.scanned_at.desc()).all()
    return jsonify({
        'attendances': [a.to_dict() for a in attendances],
        'shift': shift.to_dict()
    }), 200


@bp.route('/scan-package')
@leader_required
def scan_package():
    return render_template('scan_package.html')


@bp.route('/api/employee-lookup', methods=['GET'])
@leader_required
def api_employee_lookup():
    """Krok 1 na /scan-paczki — sprawdza kod pracownika ZANIM pojdzie dalej.

    Wczesniej zly kod wychodzil dopiero przy zapisie konca, juz po wpisaniu
    ilosci — formularz sie czyscil, ilosci przepadaly, a paczka zostawala
    otwarta (dwie takie wisza od 14.09).
    """
    barcode = (request.args.get('barcode') or '').strip()
    if not barcode:
        return jsonify({'error': 'Brak kodu pracownika.'}), 400

    user = User.query.filter_by(barcode_id=barcode, is_active_user=True).first()
    if not user:
        if ImportedCarton.query.filter_by(barcode=barcode).first():
            return jsonify({'error': 'To jest kod paczki, nie pracownika — '
                                     'najpierw zeskanuj identyfikator.'}), 400
        return jsonify({'error': 'Nieznany kod pracownika.'}), 404
    return jsonify({'user': {'id': user.id, 'display_name': user.display_name}}), 200


@bp.route('/api/package-lookup', methods=['GET'])
@leader_required
def api_package_lookup():
    """Read-only lookup: sprawdza status paczki (przeskanowana / kto / zakończona) + dane."""
    barcode = (request.args.get('barcode') or '').strip()
    if not barcode:
        return jsonify({'error': 'Brak kodu paczki.'}), 400

    carton = ImportedCarton.query.filter_by(barcode=barcode).first()
    if not carton:
        return blad_nieznanej_paczki(
            barcode, 'Nieznany kod paczki. Upewnij się, że paczka została zaimportowana.')

    d = carton.to_dict()
    # Derived status: przeskanowana = przypisana LUB rozpoczęto pomiar czasu
    # Przekazana do dokonczenia nie ma startu, ale ktos juz przy niej pracowal.
    d['scanned'] = bool(carton.processed_by) or bool(carton.scan_start_at) or bool(carton.udzialy)
    d['scanned_by'] = (d.get('processed_by_name') or d.get('scan_start_by_name')
                       or (d['udzialy'][0]['user_name'] if d['udzialy'] else None))
    d['finished'] = bool(carton.scan_end_at)
    return jsonify({'carton': d}), 200


@bp.route('/scan-paczki')
@leader_required
def scan_paczki():
    return render_template('scan_paczki.html')


@bp.route('/api/package-time/przekaz', methods=['POST'])
@leader_required
def api_package_time_przekaz():
    """„Paczka do dokonczenia": koniec zmiany — pracownik wpisuje, co przerobil,
    a paczka NIE jest zamykana. Start zostaje zdjety, wiec nastepna osoba wbija
    zwykly Start i konczy paczke standardowo (2026-10-13)."""
    data, user, carton, blad = pracownik_i_paczka_z_body()
    if blad:
        return blad
    if carton.scan_end_at:
        return jsonify({'error': 'Paczka jest już zakończona.'}), 409
    if not carton.scan_start_at:
        return jsonify({'error': 'Paczka nie jest rozpoczęta — nie ma czego przekazać.'}), 400

    otwarte = otwarte_udzialy(carton)
    moj = next((u for u in otwarte if u.user_id == user.id), None)
    if otwarte:
        if not moj:
            return jsonify({'error': f'Nie pracujesz przy tej paczce (pracują: {lista_osob(otwarte)}).'}), 403
        inni = [u for u in otwarte if u is not moj]
        if inni:
            return jsonify({'error': f'Przy paczce pracują jeszcze: {lista_osob(inni)}. Wbij zwykły '
                                     '„Koniec paczki" — zamknie tylko Twój udział, paczkę dokończy zespół.'}), 409
    elif carton.scan_start_by != user.id:
        return blad_wlasciciela(carton)

    tabela = None
    if 'tabela' in data:
        tabela, blad = tabela_z_body(data, carton, TRYB_ZESPOL)
        if blad:
            return blad
    else:
        # Stary formularz kategorii — karta stanowiska otwarta przed wdrozeniem.
        kategorie, blad = parse_scan_categories(data.get('categories'))
        if blad:
            return jsonify({'error': blad}), 400

    teraz = teraz_utc()
    if not moj:
        moj = UdzialPaczki(carton=carton, user_id=user.id, rodzaj=UDZIAL_PRZEKAZANA,
                           start_at=carton.scan_start_at)
        db.session.add(moj)
    moj.end_at = teraz
    if tabela:
        moj.set_tabela(tabela)
    else:
        moj.set_ilosci(kategorie)
    carton.scan_start_at = None
    carton.scan_start_by = None
    przelicz_ilosci_udzialow(carton, user.id)
    db.session.commit()

    return jsonify({
        'message': f'Paczka {carton.barcode} czeka na dokończenie — wpisano {moj.sztuki()} szt. '
                   'Następna osoba wbija zwykły „Start paczki".',
        'carton': carton.to_dict()
    }), 200


@bp.route('/api/package-time/dolacz', methods=['POST'])
@leader_required
def api_package_time_dolacz():
    """„Pakowanie zespolowe": druga/trzecia osoba dolacza do paczki juz
    rozpoczetej. Koniec wbija kazdy sam (zakladka Koniec) ze swoimi iloscami."""
    data, user, carton, blad = pracownik_i_paczka_z_body()
    if blad:
        return blad
    if carton.scan_end_at:
        return jsonify({'error': 'Paczka jest już zakończona.'}), 409
    if not carton.scan_start_at:
        return jsonify({'error': 'Paczka nie jest rozpoczęta — pierwsza osoba wbija „Start paczki".'}), 400

    otwarte = otwarte_udzialy(carton)
    if any(u.user_id == user.id for u in otwarte) or (not otwarte and carton.scan_start_by == user.id):
        return jsonify({'message': f'Już pracujesz przy paczce {carton.barcode}.',
                        'carton': carton.to_dict()}), 200

    teraz = teraz_utc()
    # Pierwsze dolaczenie: osoba, ktora zaczela, tez dostaje udzial — od swojego
    # startu. Tylko jesli nie ma JUZ wiersza z tego startu: gdy zaczynajaca
    # skonczyla swoja czesc (wiersz zamkniety), drugi wiersz od tego samego
    # startu bylby otwartym udzialem osoby, ktora poszla do domu.
    if carton.scan_start_by and not any(
            u.user_id == carton.scan_start_by and u.start_at == carton.scan_start_at
            for u in carton.udzialy):
        db.session.add(UdzialPaczki(carton=carton, user_id=carton.scan_start_by,
                                    rodzaj=UDZIAL_ZESPOL, start_at=carton.scan_start_at))
    db.session.add(UdzialPaczki(carton=carton, user_id=user.id, rodzaj=UDZIAL_ZESPOL, start_at=teraz))
    db.session.commit()

    return jsonify({
        'message': f'Dołączono do paczki {carton.barcode} — pracują: {lista_osob(otwarte_udzialy(carton))}. '
                   'Koniec każdy wbija sam w zakładce „Koniec paczki".',
        'carton': carton.to_dict()
    }), 200


@bp.route('/api/package-time/start', methods=['POST'])
@leader_required
def api_package_time_start():
    data = json_body()
    employee_barcode = (data.get('employee_barcode') or '').strip()
    package_barcode = (data.get('package_barcode') or '').strip()

    if not employee_barcode:
        return jsonify({'error': 'Brak kodu pracownika.'}), 400
    if not package_barcode:
        return jsonify({'error': 'Brak kodu paczki.'}), 400

    user = User.query.filter_by(barcode_id=employee_barcode, is_active_user=True).first()
    if not user:
        return jsonify({'error': 'Nieznany kod pracownika.'}), 404

    # FOR UPDATE: sprawdzenie stanu i zapis musza byc atomowe. Bez blokady dwa
    # rownolegle zadania (podwojny Enter, dwa stanowiska) oba przechodzily
    # kontrole — na .31 15.09 ta sama paczka dostala dwa „koniec" z 200.
    carton = (ImportedCarton.query.filter_by(barcode=package_barcode)
              .with_for_update().first())
    if not carton:
        return blad_nieznanej_paczki(package_barcode)

    # Paczka już zakończona — nie można jej rozpocząć ponownie
    if carton.scan_end_at:
        return jsonify({'error': 'Paczka jest już zakończona — nie można jej rozpocząć ponownie.'}), 409

    # Paczka w trakcie (start bez końca) — tylko pracownik, który zaczął, nią zarządza
    if carton.scan_start_at:
        if carton.scan_start_by == user.id:
            return jsonify({
                'message': f'Paczka {package_barcode} już rozpoczęta przez Ciebie — start bez zmian.',
                'carton': carton.to_dict()
            }), 200
        if any(u.user_id == user.id for u in otwarte_udzialy(carton)):
            return jsonify({
                'message': f'Pracujesz już przy paczce {package_barcode} (zespół) — start bez zmian.',
                'carton': carton.to_dict()
            }), 200
        starter = db.session.get(User, carton.scan_start_by) if carton.scan_start_by else None
        return jsonify({
            'error': f'Paczka już rozpoczęta przez {starter.display_name if starter else "innego pracownika"}. '
                     'Nie można jej podebrać — żeby pracować razem, użyj zakładki „Pakowanie zespołowe".'
        }), 409

    # Świeży start (paczka nierozpoczęta albo czekajaca na dokonczenie)
    dokonczenie = carton.do_dokonczenia()
    carton.scan_start_at = teraz_utc()
    carton.scan_start_by = user.id
    db.session.commit()

    po_kim = ''
    if dokonczenie:
        po_kim = f' Dokończenie po: {lista_osob(carton.udzialy)} (wpisano {sum(u.sztuki() for u in carton.udzialy)} szt.).'
    return jsonify({
        'message': f'Start zarejestrowany dla paczki {package_barcode} — {user.display_name}.{po_kim}',
        'carton': carton.to_dict()
    }), 200


@bp.route('/api/package-time/end', methods=['POST'])
@leader_required
def api_package_time_end():
    data = json_body()
    employee_barcode = (data.get('employee_barcode') or '').strip()
    package_barcode = (data.get('package_barcode') or '').strip()

    if not employee_barcode:
        return jsonify({'error': 'Brak kodu pracownika.'}), 400
    if not package_barcode:
        return jsonify({'error': 'Brak kodu paczki.'}), 400

    user = User.query.filter_by(barcode_id=employee_barcode, is_active_user=True).first()
    if not user:
        return jsonify({'error': 'Nieznany kod pracownika.'}), 404

    # FOR UPDATE — patrz api_package_time_start.
    carton = (ImportedCarton.query.filter_by(barcode=package_barcode)
              .with_for_update().first())
    if not carton:
        return blad_nieznanej_paczki(package_barcode)

    if not carton.scan_start_at:
        return jsonify({'error': 'Brak zarejestrowanego startu dla tej paczki.'}), 400

    if carton.scan_end_at:
        return jsonify({'error': 'Paczka jest już zakończona.'}), 409

    if carton.udzialy:
        if 'tabela' in data:
            tabela, blad = tabela_z_body(data, carton, TRYB_ZESPOL)
            if blad:
                return blad
            return koniec_udzialu(carton, user, None, bool(data.get('zamknij_wszystkich')),
                                  tabela=tabela)
        kategorie, blad = parse_scan_categories(data.get('categories'))
        if blad:
            return jsonify({'error': blad}), 400
        return koniec_udzialu(carton, user, kategorie, bool(data.get('zamknij_wszystkich')))

    # Tylko pracownik, który rozpoczął paczkę, może ją zakończyć
    if carton.scan_start_by and carton.scan_start_by != user.id:
        starter = db.session.get(User, carton.scan_start_by)
        return jsonify({
            'error': f'Paczkę rozpoczął {starter.display_name if starter else "inny pracownik"} — tylko on może ją zakończyć.'
        }), 403

    tabela = None
    if 'tabela' in data:
        tabela, blad = tabela_z_body(data, carton, TRYB_WZOR)
        if blad:
            return blad
    else:
        # Stary formularz kategorii (karta otwarta przed wdrozeniem tabeli).
        kategorie, blad = parse_scan_categories(data.get('categories'))
        if blad:
            return jsonify({'error': blad}), 400

    carton.scan_end_at = teraz_utc()
    carton.scan_end_by = user.id
    if tabela:
        zapisz_tabele_kartonu(carton, tabela, user.id)
    elif kategorie:
        carton.set_scan_categories(kategorie)
        # Ilosci ze skanu staja sie zrodlem rozliczenia tej linii.
        recompute_general_stat(*klucz_linii(carton),
                               actor_id=user.id, from_scan=True)
    db.session.commit()

    secs = carton.processing_seconds()
    mins, s = divmod(secs, 60)
    time_str = f'{mins}m {s}s'

    return jsonify({
        'message': f'Koniec zarejestrowany — czas procesowania: {time_str}.',
        'carton': carton.to_dict()
    }), 200
