"""Czas pracy: skan przerw / Inne / konca pracy, szkolenia (trener + szkoleni), przeglad i korekta czasow."""
from datetime import date

from flask import Blueprint, abort, jsonify, render_template, request
from flask_login import current_user
from werkzeug.exceptions import HTTPException

from logistat.czas import iso_z, local_day_bounds, local_today, teraz_utc
from logistat.czas_pracy_dane import MAX_DNI_OSOBY, otwarci_szkoleni, wiersze_czasow
from logistat.extensions import db
from logistat.models import (
    EVENT_TYPES, KOMUNIKATY_TRWANIA, Shift, ShiftAttendance, TRYBY_CZASU, TRYBY_SKANU, User,
    WorkerTimeEvent, get_setting_int)
from logistat.web.wspolne import (
    json_body, leader_required, magazyn_required, parse_czas_utc, require_int)

bp = Blueprint('czas_pracy', __name__)

# ── Szkolenie: szkolacy + osoby szkolone ─────────────────────────────────────
#
# Zakladka „🎓 Szkolenie" w Czasie pracy (decyzja operacji 2026-10-08):
# 1. skan szkolacego — NIC nie zapisuje, tylko sprawdza i pokazuje stan,
# 2. skan osob szkolonych — pierwsza zaczyna szkolenie (szkolacy i ona w tej
#    samej chwili), kolejne dopisuja sie takze w trakcie,
# 3. „Zakończ szkolenie" — koniec dla szkolacego i wszystkich szkolonych naraz.
# Szkolenie bez ani jednej osoby szkolonej nie istnieje — inaczej sam skan
# dawalby szkolacemu 100% celu.


def opis_szkolenia(trener, stan=None):
    """Stan szkolenia dla ekranu: czy trwa, od kiedy i kto jest szkolony."""
    stan = stan or stan_czasu_dzis(trener)
    trwa = 'training' in stan['trwajace']
    od = None
    if trwa:
        od = [e.timestamp for e in stan['events'] if e.event_type == 'training_start'][-1]
    return {
        'trener': {'id': trener.id, 'display_name': trener.display_name,
                   'barcode_id': trener.barcode_id},
        'trwa': trwa,
        'od': iso_z(od),
        'szkoleni': ([{'id': u.id, 'display_name': u.display_name}
                      for u, _ in otwarci_szkoleni(trener.id)] if trwa else []),
    }


def stan_czasu_dzis(user):
    """Dzisiejsza zmiana osoby i jej zdarzenia czasu — albo abort().

    Zwraca `{'shift', 'events', 'work_ended', 'trwajace'}`; `trwajace` to
    otwarte stany z `TRYBY_CZASU` (wiecej `*_start` niz `*_end`, bez flagi na User).
    """
    # Najwczesniejsza obecnosc dnia — ta sama, od ktorej wiersz Czasow pracownikow
    # (wiersze_czasow). Byla najpozniejsza: przy skanie na obie zmiany przerwy
    # szly na druga, a ekran pokazywal pierwsza bez zdarzen (przeglad 2026-10-24).
    obecnosci = ShiftAttendance.query.join(Shift).filter(
        ShiftAttendance.user_id == user.id,
        Shift.date == local_today()
    ).order_by(ShiftAttendance.scanned_at.asc()).all()
    if not obecnosci:
        abort(400, f'{user.display_name} nie jest zeskanowany/a na zmianę dziś.')

    # Nowe zdarzenia na pierwsza obecnosc; stan ze zdarzen WSZYSTKICH obecnosci
    # dnia (do 2026-10-24 szly na najpozniejsza — tamte tez maja sie liczyc).
    shift = obecnosci[0].shift
    events = WorkerTimeEvent.query.filter(
        WorkerTimeEvent.user_id == user.id,
        WorkerTimeEvent.shift_id.in_({a.shift_id for a in obecnosci})
    ).order_by(WorkerTimeEvent.timestamp, WorkerTimeEvent.id).all()

    def otwarte(prefix):
        return (sum(1 for e in events if e.event_type == f'{prefix}_start')
                > sum(1 for e in events if e.event_type == f'{prefix}_end'))

    return {
        'shift': shift,
        'events': events,
        'work_ended': any(e.event_type == 'work_end' for e in events),
        'trwajace': [m for m in TRYBY_CZASU if otwarte(m)],
    }


def _trener_z_zadania(data):
    """Szkolacy z `trener_id` albo `barcode` — po sprawdzeniu znacznika."""
    if data.get('trener_id') not in (None, ''):
        trener = db.session.get(User, require_int(data.get('trener_id'), 'trener_id'))
    else:
        barcode = (data.get('barcode') or '').strip()
        if not barcode:
            abort(400, 'Brak kodu.')
        trener = User.query.filter_by(barcode_id=barcode).first()
    if trener is None or not trener.is_active_user:
        abort(404, 'Nieznany kod pracownika.')
    if not trener.is_trainer:
        abort(403, f'{trener.display_name} nie jest osobą szkolącą — szkolenie prowadzą '
                   'tylko osoby ze znacznikiem „Szkolący".')
    return trener


def zakoncz_szkolenie(trener, shift, now, notatka=None):
    """Koniec szkolenia `trener` + wszystkich jego szkolonych, ten sam `now`.

    Jedyna droga zamykania szkolenia ze skanera (przycisk „Zakończ szkolenie"
    i „Koniec pracy" szkolacego) — szkoleni koncza razem ze szkolacym.
    Bez commitu.
    """
    kto = current_user.id if notatka else None
    db.session.add(WorkerTimeEvent(
        user_id=trener.id, shift_id=shift.id, event_type='training_end',
        timestamp=now, recorded_by=kto, is_manual=False, note=notatka))
    for szkolony, shift_id in otwarci_szkoleni(trener.id):
        db.session.add(WorkerTimeEvent(
            user_id=szkolony.id, shift_id=shift_id, event_type='trainee_end',
            timestamp=now, recorded_by=current_user.id, is_manual=False,
            training_lead_id=trener.id,
            note=f'Koniec szkolenia prowadzonego przez {trener.display_name}'))


@bp.route('/time-tracking')
@magazyn_required
def time_tracking():
    return render_template('time_tracking.html')


@bp.route('/worker-times')
@leader_required
def worker_times():
    # Lista do filtra po osobie — wszyscy, takze nieaktywni (historia ich dni).
    osoby = [{'id': u.id, 'nazwa': u.display_name, 'aktywna': bool(u.is_active_user)}
             for u in User.query.order_by(User.display_name).all()]
    return render_template('worker_times.html',
                           osoby=osoby,
                           break_threshold=get_setting_int('break_threshold_minutes', 30),
                           max_work=get_setting_int('max_work_minutes', 660),
                           min_break=get_setting_int('min_break_minutes', 15))


@bp.route('/api/time/scan', methods=['POST'])
@magazyn_required
def api_time_scan():
    data = json_body()
    barcode = (data.get('barcode') or '').strip()
    mode    = data.get('mode', 'break')   # 'break' | 'other' | 'work_end'

    if not barcode:
        return jsonify({'error': 'Brak kodu.'}), 400

    user = User.query.filter_by(barcode_id=barcode, is_active_user=True).first()
    if not user:
        return jsonify({'error': 'Nieznany kod pracownika.'}), 404

    if mode not in TRYBY_SKANU and mode != 'work_end':
        # Szkolenie ma wlasny przeplyw (szkolacy + min. 1 szkolony) — zwykly
        # przelacznik ominalby ten wymog.
        return jsonify({'error': 'Nieprawidłowy tryb skanowania.'}), 400

    stan = stan_czasu_dzis(user)
    shift, trwajace = stan['shift'], stan['trwajace']
    now = teraz_utc()

    if mode == 'work_end':
        if stan['work_ended']:
            return jsonify({'error': f'{user.display_name} już zakończył/a pracę na tej zmianie.'}), 409

        # Niedomkniete przerwa/„Inne"/szkolenie zamykamy sami — inaczej
        # wisialyby otwarte i zjadaly czas pracy az do konca swiata.
        for prefix, opis in (('break', 'przerwy'), ('other', '„Innego"'),
                             ('trainee', 'szkolenia (szkolony)')):
            if prefix in trwajace:
                db.session.add(WorkerTimeEvent(
                    user_id=user.id, shift_id=shift.id, event_type=f'{prefix}_end',
                    timestamp=now, recorded_by=current_user.id, is_manual=False,
                    note=f'Auto-zamknięcie {opis} przy końcu pracy'
                ))
        if 'training' in trwajace:
            # Szkolacy konczy prace → koncza tez jego szkoleni.
            zakoncz_szkolenie(user, shift, now, 'Auto-zamknięcie szkolenia przy końcu pracy')

        db.session.add(WorkerTimeEvent(
            user_id=user.id, shift_id=shift.id, event_type='work_end',
            timestamp=now, recorded_by=None, is_manual=False
        ))
        db.session.commit()
        return jsonify({'message': f'{user.display_name} — koniec pracy zarejestrowany.',
                        'event_type': 'work_end', 'user': user.to_dict()}), 200

    if stan['work_ended']:
        return jsonify({'error': f'{user.display_name} już zakończył/a pracę.'}), 409

    trwa = mode in trwajace
    # Przerwa, „Inne" i szkolenie nie moga trwac jednoczesnie — przerwa
    # i „Inne" odjelyby ten sam czas dwa razy, a paczka z przerwy liczylaby
    # sie jako szkolenie.
    if not trwa and trwajace:
        return jsonify({'error': f'{user.display_name} {KOMUNIKATY_TRWANIA[trwajace[0]]}'}), 409

    event_type = f'{mode}_end' if trwa else f'{mode}_start'

    db.session.add(WorkerTimeEvent(
        user_id=user.id, shift_id=shift.id, event_type=event_type,
        timestamp=now, recorded_by=None, is_manual=False
    ))
    db.session.commit()

    etykiety = {
        'break_start': 'poszedł/poszła na przerwę ☕',
        'break_end':   'wrócił/wróciła z przerwy ✅',
        'other_start': 'wyszedł/wyszła — Inne 🚪',
        'other_end':   'wrócił/wróciła (Inne) ✅',
    }
    return jsonify({'message': f'{user.display_name} — {etykiety[event_type]}',
                    'event_type': event_type, 'user': user.to_dict()}), 200


@bp.route('/api/time/training/aktywne', methods=['GET'])
@magazyn_required
def api_training_aktywne():
    """Trwajace dzis szkolenia — druga stacja moze przejac dowolne z nich."""
    starty = WorkerTimeEvent.query.join(Shift).filter(
        Shift.date == local_today(),
        WorkerTimeEvent.event_type.in_(('training_start', 'training_end'))).all()
    licznik = {}
    for e in starty:
        licznik[e.user_id] = licznik.get(e.user_id, 0) + (
            1 if e.event_type == 'training_start' else -1)
    wynik = []
    for uid in sorted(u for u, n in licznik.items() if n > 0):
        trener = db.session.get(User, uid)
        try:
            stan = stan_czasu_dzis(trener)
        except HTTPException:
            # Szkolacy bez dzisiejszej obecnosci (usunieta w trakcie) — pomin,
            # zamiast wywracac liste na wszystkich stacjach.
            continue
        if 'training' in stan['trwajace']:
            wynik.append(opis_szkolenia(trener, stan))
    return jsonify({'szkolenia': wynik}), 200


@bp.route('/api/time/training/trener', methods=['POST'])
@magazyn_required
def api_training_trener():
    """Krok 1: skan szkolacego. Niczego nie zapisuje."""
    trener = _trener_z_zadania(json_body())
    stan = stan_czasu_dzis(trener)
    if stan['work_ended']:
        abort(409, f'{trener.display_name} już zakończył/a pracę.')
    inne = [m for m in stan['trwajace'] if m != 'training']
    if inne:
        abort(409, f'{trener.display_name} {KOMUNIKATY_TRWANIA[inne[0]]}')
    return jsonify(opis_szkolenia(trener, stan)), 200


@bp.route('/api/time/training/szkolony', methods=['POST'])
@magazyn_required
def api_training_szkolony():
    """Krok 2: skan osoby szkolonej. Pierwsza zaczyna szkolenie."""
    data = json_body()
    trener = _trener_z_zadania({'trener_id': data.get('trener_id')})
    # Blokada wiersza szkolacego: podwojny Enter / dwie stacje przy pierwszym
    # szkolonym dalyby dwa `training_start`.
    db.session.query(User).filter_by(id=trener.id).with_for_update().one()

    barcode = (data.get('barcode') or '').strip()
    if not barcode:
        abort(400, 'Brak kodu.')
    szkolony = User.query.filter_by(barcode_id=barcode, is_active_user=True).first()
    if szkolony is None:
        abort(404, 'Nieznany kod pracownika.')
    if szkolony.id == trener.id:
        abort(400, f'To kod osoby szkolącej ({trener.display_name}) — zeskanuj osobę szkoloną. '
                   'Szkolenie kończy przycisk „Zakończ szkolenie".')

    stan_trenera = stan_czasu_dzis(trener)
    if stan_trenera['work_ended']:
        abort(409, f'{trener.display_name} już zakończył/a pracę.')
    inne = [m for m in stan_trenera['trwajace'] if m != 'training']
    if inne:
        abort(409, f'{trener.display_name} {KOMUNIKATY_TRWANIA[inne[0]]}')

    stan = stan_czasu_dzis(szkolony)
    if stan['work_ended']:
        abort(409, f'{szkolony.display_name} już zakończył/a pracę.')
    if stan['trwajace']:
        if 'trainee' in stan['trwajace'] and any(
                u.id == szkolony.id for u, _ in otwarci_szkoleni(trener.id)):
            abort(409, f'{szkolony.display_name} już jest na tym szkoleniu.')
        abort(409, f'{szkolony.display_name} {KOMUNIKATY_TRWANIA[stan["trwajace"][0]]}')

    now = teraz_utc()
    rozpoczete = 'training' not in stan_trenera['trwajace']
    if rozpoczete:
        db.session.add(WorkerTimeEvent(
            user_id=trener.id, shift_id=stan_trenera['shift'].id,
            event_type='training_start', timestamp=now, is_manual=False))
    db.session.add(WorkerTimeEvent(
        user_id=szkolony.id, shift_id=stan['shift'].id, event_type='trainee_start',
        timestamp=now, is_manual=False, training_lead_id=trener.id))
    db.session.commit()

    wynik = opis_szkolenia(trener)
    wynik['message'] = (f'Szkolenie rozpoczęte — {trener.display_name} szkoli '
                        f'{szkolony.display_name} 🎓' if rozpoczete else
                        f'{szkolony.display_name} dołączył/a do szkolenia 🎓')
    return jsonify(wynik), 200


@bp.route('/api/time/training/koniec', methods=['POST'])
@magazyn_required
def api_training_koniec():
    """Krok 3: koniec szkolenia — szkolacy i wszyscy szkoleni naraz.

    Szkolacy bez znacznika (zdjetego w trakcie) tez moze zakonczyc — inaczej
    jego szkolenie wisialoby otwarte."""
    data = json_body()
    trener = db.get_or_404(User, require_int(data.get('trener_id'), 'trener_id'))
    db.session.query(User).filter_by(id=trener.id).with_for_update().one()
    stan = stan_czasu_dzis(trener)
    if 'training' not in stan['trwajace']:
        abort(409, f'{trener.display_name} nie prowadzi teraz szkolenia.')
    szkoleni = [u.display_name for u, _ in otwarci_szkoleni(trener.id)]
    zakoncz_szkolenie(trener, stan['shift'], teraz_utc())
    db.session.commit()
    return jsonify({
        'message': f'Szkolenie zakończone — {trener.display_name}'
                   + (f' i {len(szkoleni)} os. szkolonych' if szkoleni else '') + ' ✅',
        'szkoleni': szkoleni,
    }), 200


def _data_lub_none(tekst):
    try:
        return date.fromisoformat(tekst or '')
    except ValueError:
        return None


@bp.route('/api/worker-times')
@leader_required
def api_worker_times():
    """Jeden dzien (`date`, wszyscy) albo jedna osoba w zakresie dni
    (`user_id` + `date_from` / `date_to`, filtr po osobie — 2026-10-23)."""
    if request.args.get('user_id'):
        user_id = require_int(request.args.get('user_id'), 'user_id')
        od = _data_lub_none(request.args.get('date_from'))
        do = _data_lub_none(request.args.get('date_to'))
        if od is None or do is None:
            abort(400, 'Podaj zakres dat od–do.')
            return
        if od > do:
            abort(400, 'Data „od” jest późniejsza niż „do”.')
        if (do - od).days + 1 > MAX_DNI_OSOBY:
            abort(400, f'Zakres najwyżej {MAX_DNI_OSOBY} dni.')
        return jsonify({'workers': wiersze_czasow(od, do, user_id),
                        'user_id': user_id, 'date_from': od.isoformat(),
                        'date_to': do.isoformat()}), 200

    date_str = request.args.get('date', local_today().isoformat())
    try:
        query_date = date.fromisoformat(date_str)
    except ValueError:
        query_date = local_today()
    return jsonify({'workers': wiersze_czasow(query_date, query_date),
                    'date': query_date.isoformat()}), 200


@bp.route('/api/worker-times/wejscie/<int:attendance_id>', methods=['PUT'])
@leader_required
def api_wejscie_update(attendance_id):
    """Korekta godziny wejscia (skan na zmianie) z osi czasu. Wejscie musi
    zostac w dniu zmiany i przed pierwszym zdarzeniem czasu pracy osoby —
    inaczej przerwa / koniec pracy wypadlyby przed poczatkiem pracy."""
    att = db.get_or_404(ShiftAttendance, attendance_id)
    data = json_body()
    ts = parse_czas_utc(data.get('timestamp'))
    od, do = local_day_bounds(att.shift.date)
    if not (od <= ts < do):
        abort(400, f'Wejście musi być w dniu zmiany ({att.shift.date.strftime("%d.%m.%Y")}).')
    pierwsze = (WorkerTimeEvent.query.filter_by(user_id=att.user_id, shift_id=att.shift_id)
                .order_by(WorkerTimeEvent.timestamp).first())
    if pierwsze and ts >= pierwsze.timestamp:
        abort(400, 'Wejście musi być przed pierwszym zdarzeniem tej osoby na zmianie '
                   '(przerwa, Inne, szkolenie albo koniec pracy) — popraw najpierw je.')
    if att.pierwotny_skan is None:
        att.pierwotny_skan = att.scanned_at
    att.scanned_at = ts
    att.poprawione_przez = current_user.id
    att.poprawione_at = teraz_utc()
    db.session.commit()
    return jsonify({'id': att.id, 'scanned_at': iso_z(att.scanned_at),
                    'pierwotny_skan': iso_z(att.pierwotny_skan)}), 200


@bp.route('/api/worker-times/event', methods=['POST'])
@leader_required
def api_time_event_create():
    data = json_body()
    user_id    = data.get('user_id')
    shift_id   = data.get('shift_id')
    event_type = data.get('event_type')
    ts_str     = data.get('timestamp', '')
    note       = (data.get('note') or '').strip()

    if not all([user_id, shift_id, event_type, ts_str]):
        return jsonify({'error': 'Brakuje wymaganych pól.'}), 400
    if event_type not in EVENT_TYPES:
        return jsonify({'error': 'Nieprawidłowy typ zdarzenia.'}), 400
    ts = parse_czas_utc(ts_str)

    # Bez tego bledne id konczylo sie naruszeniem klucza obcego i 500-ka
    # (na Postgresie transakcja padala w commicie).
    user_id = require_int(user_id, 'user_id')
    shift_id = require_int(shift_id, 'shift_id')
    pracownik = db.session.get(User, user_id)
    if pracownik is None:
        return jsonify({'error': f'Nieznany pracownik (id {user_id}).'}), 400
    if event_type == 'training_start' and not pracownik.is_trainer:
        return jsonify({'error': f'{pracownik.display_name} nie jest osobą szkolącą.'}), 400
    if db.session.get(Shift, shift_id) is None:
        return jsonify({'error': f'Nieznana zmiana (id {shift_id}).'}), 400

    event = WorkerTimeEvent(
        user_id=user_id, shift_id=shift_id, event_type=event_type,
        timestamp=ts, recorded_by=current_user.id, is_manual=True, note=note
    )
    db.session.add(event)
    db.session.commit()
    return jsonify(event.to_dict()), 201


@bp.route('/api/worker-times/event/<int:event_id>', methods=['PUT'])
@leader_required
def api_time_event_update(event_id):
    event = db.get_or_404(WorkerTimeEvent, event_id)
    data  = json_body()
    if 'event_type' in data:
        if data['event_type'] not in EVENT_TYPES:
            return jsonify({'error': 'Nieprawidłowy typ.'}), 400
        if (data['event_type'] == 'training_start'
                and not db.session.get(User, event.user_id).is_trainer):
            return jsonify({'error': 'Ta osoba nie jest osobą szkolącą.'}), 400
        event.event_type = data['event_type']
    if 'timestamp' in data:
        event.timestamp = parse_czas_utc(data['timestamp'])
    if 'note' in data:
        event.note = data['note']
    event.recorded_by = current_user.id
    event.is_manual   = True
    db.session.commit()
    return jsonify(event.to_dict()), 200


@bp.route('/api/worker-times/event/<int:event_id>', methods=['DELETE'])
@leader_required
def api_time_event_delete(event_id):
    event = db.get_or_404(WorkerTimeEvent, event_id)
    db.session.delete(event)
    db.session.commit()
    return jsonify({'message': 'Usunięto.'}), 200
