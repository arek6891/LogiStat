"""Przydzielanie osob do czynnosci (szkolenia, estymacja, sugestie AI, wersja) i Wpis ilosci."""
from datetime import timedelta

from flask import Blueprint, jsonify, render_template, request
from flask_login import current_user
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from logistat.czas import local_today, teraz_utc
from logistat.extensions import db
from logistat.models import (
    Activity, ActivityAssignment, DailyStat, Shift, ShiftAttendance, User, get_or_create_shift,
    szkolenia_czynnosci)
from logistat.przydzial import (
    CZYNNOSC_SKANOW_PACZEK, do_zrobienia_dnia, grupy_wydajnosci, osob_pp_na_zmianie,
    sugestie_przydzialu, wersja_przydzialu, wydajnosc_czynnosci)
from logistat.web.wspolne import (
    json_body, leader_required, parse_date, parse_shift_number, require_int)

bp = Blueprint('przydzial', __name__)


@bp.route('/assignment')
@leader_required
def assignment():
    activities = Activity.query.filter_by(is_active=True)\
        .order_by(Activity.sort_order).all()
    return render_template('assignment.html', activities=activities,
                           czynnosc_pp=CZYNNOSC_SKANOW_PACZEK)


@bp.route('/data-entry')
@leader_required
def data_entry():
    activities = Activity.query.filter_by(is_active=True)\
        .order_by(Activity.sort_order).all()
    return render_template('data_entry.html', activities=activities)


@bp.route('/api/assignment/data', methods=['GET'])
@leader_required
def api_assignment_data():
    """Get all assignment data for a given date and shift."""
    shift_date = request.args.get('date', local_today().isoformat())
    shift_number = parse_shift_number(request.args.get('shift_number', 1))

    shift = Shift.query.filter_by(
        date=parse_date(shift_date),
        shift_number=shift_number
    ).first()

    activities = Activity.query.filter_by(is_active=True)\
        .order_by(Activity.sort_order).all()

    dzien = parse_date(shift_date)
    plan = _plan_zmiany(dzien, shift_number)
    if not shift:
        return jsonify({
            'shift': None,
            'attendees': [],
            'assignments': [],
            'activities': [a.to_dict() for a in activities],
            'wydajnosc': wydajnosc_czynnosci(dzien),
            'szkolenia': {},
            'wersja': wersja_przydzialu([]),
            'w_wylaczonych': [],
            **plan,
        }), 200

    # joinedload: to_dict() kazdego wiersza siega po user/activity — bez tego
    # lista robila SELECT na kazdego pracownika i kazda czynnosc osobno.
    attendances = ShiftAttendance.query.filter_by(shift_id=shift.id)\
        .options(joinedload(ShiftAttendance.user)).all()
    assignments = ActivityAssignment.query.filter_by(shift_id=shift.id)\
        .options(joinedload(ActivityAssignment.user),
                 joinedload(ActivityAssignment.activity)).all()

    # Build set of already-assigned user IDs
    assigned_user_ids = {a.user_id for a in assignments}
    obecni = {a.user_id for a in attendances}

    return jsonify({
        'wydajnosc': wydajnosc_czynnosci(shift.date),
        'shift': shift.to_dict(),
        'attendees': [a.user.to_dict() for a in attendances],
        'assignments': [a.to_dict() for a in assignments],
        'activities': [a.to_dict() for a in activities],
        'unassigned': [a.user.to_dict() for a in attendances
                       if a.user_id not in assigned_user_ids],
        # {user_id: [activity_id…]} — tablica nie pozwala upuscic osoby na
        # czynnosc bez szkolenia (serwer i tak to sprawdza przy zapisie).
        'szkolenia': {str(u): sorted(a) for u, a in szkolenia_czynnosci(
            {a.user_id for a in attendances} | assigned_user_ids).items()},
        'wersja': wersja_przydzialu(assignments),
        # Obecni przydzieleni do czynnosci wylaczonej w trakcie zmiany — tablica
        # pokazuje ich w Nieprzydzielonych; zapis ich nie rusza, dopoki lider
        # ich nie przeciagnie (przeglad 2026-10-24).
        'w_wylaczonych': [{'user_id': a.user_id, 'czynnosc': a.activity.name}
                          for a in assignments
                          if not a.activity.is_active and a.user_id in obecni],
        **plan,
    }), 200


def _plan_zmiany(dzien, shift_number):
    """Grupy P1/P2/P3 i ilosc do zrobienia dla Post Processing (2026-10-23)."""
    g = grupy_wydajnosci(dzien)
    pp = Activity.query.filter_by(name=CZYNNOSC_SKANOW_PACZEK).first()
    return {
        'grupy': {str(uid): v for uid, v in g['grupy'].items()},
        'okno_grup': g['okno'],
        'do_zrobienia': do_zrobienia_dnia(dzien),
        'pp_activity_id': pp.id if pp else None,
        'osob_pp_druga_zmiana': osob_pp_na_zmianie(dzien, 2 if shift_number == 1 else 1),
    }


@bp.route('/api/assignment/suggestions', methods=['GET'])
@leader_required
def api_assignment_suggestions():
    """Generate AI-based assignment suggestions based on user statistics."""
    shift_date = request.args.get('date', local_today().isoformat())
    shift_number = parse_shift_number(request.args.get('shift_number', 1))

    shift = Shift.query.filter_by(
        date=parse_date(shift_date),
        shift_number=shift_number
    ).first()
    if not shift:
        return jsonify({'suggestions': []}), 200

    attendances = ShiftAttendance.query.filter_by(shift_id=shift.id).all()
    attendee_ids = [a.user_id for a in attendances]
    if not attendee_ids:
        return jsonify({'suggestions': []}), 200

    activities = Activity.query.filter_by(is_active=True)\
        .order_by(Activity.sort_order).all()
    dzien = parse_date(shift_date)

    # Srednia z Wpisu ilosci per osoba x czynnosc (30 dni) — dla czynnosci
    # innych niz Post Processing (te grupy P1–P3 nie opisuja).
    stats = db.session.query(
        DailyStat.user_id, DailyStat.activity_id,
        func.avg(DailyStat.quantity).label('avg_qty')
    ).join(Shift).filter(
        DailyStat.user_id.in_(attendee_ids),
        # Gorna granica: sugestie dla dnia z przeszlosci nie biora pozniejszych wpisow.
        Shift.date >= dzien - timedelta(days=30), Shift.date <= dzien
    ).group_by(DailyStat.user_id, DailyStat.activity_id).all()

    suggestions = sugestie_przydzialu(
        obecni=attendee_ids, czynnosci=activities,
        szkolenia=szkolenia_czynnosci(attendee_ids),
        grupy=grupy_wydajnosci(dzien)['grupy'],
        srednie={(s.user_id, s.activity_id): float(s.avg_qty) for s in stats},
        wydajnosc=wydajnosc_czynnosci(dzien),
        do_zrobienia=do_zrobienia_dnia(dzien),
        osob_pp_druga=osob_pp_na_zmianie(dzien, 2 if shift_number == 1 else 1))
    return jsonify({'suggestions': suggestions}), 200


@bp.route('/api/assignment/save', methods=['POST'])
@leader_required
def api_assignment_save():
    """Save drag & drop assignments."""
    data = json_body()
    shift_number = parse_shift_number(data.get('shift_number', 1))
    assignments = data.get('assignments') or []
    if not isinstance(assignments, list):
        return jsonify({'error': 'Pole "assignments" musi być listą.'}), 400

    shift = get_or_create_shift(parse_date(data.get('date')), shift_number)
    # Blokada wiersza zmiany serializuje zapisy tej zmiany: bez niej dwa
    # rownolegle delete+insert (autozapis z dwoch stanowisk) wstawialy oba
    # komplety, a sprawdzenie wersji ponizej nie byloby atomowe.
    shift = Shift.query.filter_by(id=shift.id).with_for_update().one()

    # Sprawdz FK przed czyszczeniem, zeby bledne cialo nie wyczyscilo przydzialu
    # i nie zostawilo zmiany pustej.
    znani = {u.id for u in User.query.with_entities(User.id).all()}
    czynnosci = {a.id for a in Activity.query.with_entities(Activity.id).all()}
    nowe = []
    for a in assignments:
        if not isinstance(a, dict):
            return jsonify({'error': 'Każde przydzielenie musi być obiektem.'}), 400
        user_id = require_int(a.get('user_id'), 'user_id')
        activity_id = require_int(a.get('activity_id'), 'activity_id')
        if user_id not in znani:
            return jsonify({'error': f'Nieznany pracownik (id {user_id}).'}), 400
        if activity_id not in czynnosci:
            return jsonify({'error': f'Nieznana czynność (id {activity_id}).'}), 400
        nowe.append((user_id, activity_id, bool(a.get('is_suggestion', False))))

    # Brak `wersja` w ciele = stary klient / API — zapis bez sprawdzania.
    oczekiwana = data.get('wersja')
    if oczekiwana is not None:
        teraz = wersja_przydzialu(
            ActivityAssignment.query.filter_by(shift_id=shift.id).all())
        if oczekiwana != teraz:
            db.session.rollback()
            return jsonify({
                'error': 'Ktoś inny zmienił przydział tej zmiany w międzyczasie. '
                         'Wczytaj aktualny stan i przeciągnij jeszcze raz.',
                'konflikt': True,
                'wersja': teraz,
            }), 409

    # Szkolenia (2026-10-13): NOWY przydzial tylko do czynnosci, w ktorej osoba
    # jest przeszkolona. Juz zapisany zostaje, choc szkolenie odznaczono —
    # inaczej odznaczenie zablokowaloby zapis calej zmiany.
    juz_sa = {(a.user_id, a.activity_id) for a in
              ActivityAssignment.query.filter_by(shift_id=shift.id)}
    do_sprawdzenia = {(u, a) for u, a, _ in nowe if (u, a) not in juz_sa}
    if do_sprawdzenia:
        szkolenia = szkolenia_czynnosci({u for u, _ in do_sprawdzenia})
        brak = sorted((u, a) for u, a in do_sprawdzenia if a not in szkolenia.get(u, ()))
        if brak:
            db.session.rollback()
            osoby = {u.id: u.display_name for u in User.query.filter(
                User.id.in_({u for u, _ in brak}))}
            nazwy = {a.id: a.name for a in Activity.query.filter(
                Activity.id.in_({a for _, a in brak}))}
            lista = [{'user_id': u, 'activity_id': a, 'osoba': osoby.get(u, f'#{u}'),
                      'czynnosc': nazwy.get(a, f'#{a}')} for u, a in brak]
            return jsonify({
                'error': 'Brak szkolenia: ' + '; '.join(
                    f"{x['osoba']} — {x['czynnosc']}" for x in lista)
                    + '. Szkolenia zaznacza się w Użytkownikach.',
                'brak_szkolenia': lista,
            }), 400

    # Podmiana przydzialu — ale tylko tego, co tablica widzi (przeglad 2026-10-24):
    # osoby z ciala zapisu oraz obecni przy AKTYWNYCH czynnosciach. Przydzial
    # nieobecnego albo do czynnosci wylaczonej w trakcie zmiany nie ma karty,
    # wiec pierwsze przeciagniecie kogokolwiek kasowalo go po cichu.
    wyslani = {u for u, _, _ in nowe}
    obecni = {a.user_id for a in ShiftAttendance.query.filter_by(shift_id=shift.id)}
    aktywne = {a.id for a in Activity.query.filter_by(is_active=True).with_entities(Activity.id)}
    for p in ActivityAssignment.query.filter_by(shift_id=shift.id).all():
        if p.user_id in wyslani or (p.user_id in obecni and p.activity_id in aktywne):
            db.session.delete(p)
    db.session.flush()

    for user_id, activity_id, is_suggestion in nowe:
        db.session.add(ActivityAssignment(
            shift_id=shift.id,
            user_id=user_id,
            activity_id=activity_id,
            is_suggestion=is_suggestion,
            assigned_by=current_user.id
        ))

    db.session.commit()
    return jsonify({
        'message': 'Przydzielenie zapisane.',
        'wersja': wersja_przydzialu(
            ActivityAssignment.query.filter_by(shift_id=shift.id).all()),
    }), 200


@bp.route('/api/daily-stats', methods=['GET'])
@leader_required
def api_daily_stats_get():
    """Get stats for a given date and shift."""
    shift_date = request.args.get('date', local_today().isoformat())
    shift_number = parse_shift_number(request.args.get('shift_number', 1))

    shift = Shift.query.filter_by(
        date=parse_date(shift_date),
        shift_number=shift_number
    ).first()
    if not shift:
        return jsonify({'stats': [], 'shift': None}), 200

    # Get assignments for this shift
    assignments = ActivityAssignment.query.filter_by(shift_id=shift.id)\
        .options(joinedload(ActivityAssignment.user),
                 joinedload(ActivityAssignment.activity)).all()
    stats = DailyStat.query.filter_by(shift_id=shift.id)\
        .options(joinedload(DailyStat.user), joinedload(DailyStat.activity)).all()

    return jsonify({
        'shift': shift.to_dict(),
        'assignments': [a.to_dict() for a in assignments],
        'stats': [s.to_dict() for s in stats]
    }), 200


@bp.route('/api/daily-stats', methods=['POST'])
@leader_required
def api_daily_stats_save():
    """Save or update daily statistics."""
    data = json_body()
    shift_number = parse_shift_number(data.get('shift_number', 1))
    entries = data.get('entries') or []
    if not isinstance(entries, list):
        return jsonify({'error': 'Pole "entries" musi być listą.'}), 400

    shift = get_or_create_shift(parse_date(data.get('date')), shift_number)

    for entry in entries:
        if not isinstance(entry, dict):
            return jsonify({'error': 'Każdy wpis musi być obiektem.'}), 400
        user_id = require_int(entry.get('user_id'), 'user_id')
        activity_id = require_int(entry.get('activity_id'), 'activity_id')
        quantity = require_int(entry.get('quantity', 0) or 0, 'quantity', minimum=0)

        existing = DailyStat.query.filter_by(
            shift_id=shift.id,
            user_id=user_id,
            activity_id=activity_id
        ).first()

        if existing:
            existing.quantity = quantity
            existing.note = entry.get('note', '')
            existing.modified_by = current_user.id
            existing.modified_at = teraz_utc()
        else:
            db.session.add(DailyStat(
                shift_id=shift.id,
                user_id=user_id,
                activity_id=activity_id,
                quantity=quantity,
                note=entry.get('note', ''),
                entered_by=current_user.id
            ))

    db.session.commit()
    return jsonify({'message': 'Statystyki zapisane.'}), 200


@bp.route('/api/daily-stats/<int:stat_id>', methods=['PUT'])
@leader_required
def api_daily_stat_update(stat_id):
    """Update a single daily stat (mistake correction)."""
    stat = db.get_or_404(DailyStat, stat_id)
    data = json_body()

    if 'quantity' in data:
        stat.quantity = require_int(data['quantity'], 'quantity', minimum=0)
    stat.note = data.get('note', stat.note)
    stat.modified_by = current_user.id
    stat.modified_at = teraz_utc()

    db.session.commit()
    return jsonify({'message': 'Zaktualizowano.', 'stat': stat.to_dict()}), 200
