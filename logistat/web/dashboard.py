"""Dashboard: Dzis, Wybrany dzien, Podsumowanie (zalegle), Per Loading date, per pracownik i zmiana."""
from datetime import datetime
from types import SimpleNamespace

from flask import Blueprint, abort, jsonify, render_template, request
from sqlalchemy import and_, func

from logistat.czas import LOCAL_TZ, local_day_bounds, local_today
from logistat.dashboard_dane import plan_dnia_pliku, plany_dni_pliku, zalegle_wg_daty_pliku
from logistat.extensions import db
from logistat.models import Activity, DailyStat, ImportedCarton, Shift, ShiftAttendance, User
from logistat.normy_dane import prace_osob
from logistat.web.wspolne import leader_required, parse_date

bp = Blueprint('dashboard', __name__)


MAX_DNI_ZAKRESU_DASHBOARDU = 366


@bp.route('/dashboard')
@leader_required
def dashboard():
    return render_template('dashboard.html')


@bp.route('/api/dashboard')
@leader_required
def api_dashboard():
    today = local_today()
    today_start, today_end = local_day_bounds(today)

    # Paczki — ogólne (przetworzona = ZAKOŃCZONA, scan_end)
    total_cartons = ImportedCarton.query.count()
    done_cartons = ImportedCarton.query.filter(ImportedCarton.scan_end_at.isnot(None)).count()
    remaining_cartons = total_cartons - done_cartons
    # Te same paczki co `remaining_cartons`, liczone w sztukach — lider planuje
    # obsade po ilosci towaru, a paczki potrafia miec od 1 do kilkuset sztuk.
    remaining_pieces = db.session.query(func.sum(ImportedCarton.stueckzahl))\
        .filter(ImportedCarton.scan_end_at.is_(None)).scalar() or 0

    # ❗ Paczki z roznica w tabeli ilosci, ktorej lider jeszcze nie potwierdzil
    # (wszystkie dni — zalegle potwierdzenie nie znika o polnocy).
    do_potwierdzenia = ImportedCarton.query.filter(
        ImportedCarton.roznica.is_(True),
        ImportedCarton.roznica_potwierdzona_at.is_(None)).count()

    # Paczki zakończone dziś
    dzis = and_(ImportedCarton.scan_end_at >= today_start,
                ImportedCarton.scan_end_at < today_end)
    done_today = ImportedCarton.query.filter(dzis).count()
    pieces_today = db.session.query(func.sum(ImportedCarton.stueckzahl))\
        .filter(dzis).scalar() or 0

    # Breakdown per pracownik — dziś. Paczka wielu osob liczy sie kazdej z nich
    # (jej udzial i jej wpisane ilosci) — `prace_osob()`.
    praca_dzis = prace_osob(today, today)
    nazwy = {u.id: u.display_name for u in User.query.filter(
        User.id.in_(list(praca_dzis))).all()} if praca_dzis else {}
    workers_today = sorted((
        {'user_id': uid, 'name': nazwy.get(uid, '?'),
         'packages': len(p), 'pieces': int(sum(x[2] for x in p))}
        for uid, p in praca_dzis.items()
    ), key=lambda w: w['packages'], reverse=True)

    # Obecni na zmianach dziś
    shift1 = Shift.query.filter_by(date=today, shift_number=1).first()
    shift2 = Shift.query.filter_by(date=today, shift_number=2).first()
    present_ids = set()
    if shift1:
        present_ids |= {a.user_id for a in ShiftAttendance.query.filter_by(shift_id=shift1.id).all()}
    if shift2:
        present_ids |= {a.user_id for a in ShiftAttendance.query.filter_by(shift_id=shift2.id).all()}

    # DailyStat dziś — per czynność (sumy)
    daily_rows = db.session.query(
        DailyStat.activity_id,
        func.sum(DailyStat.quantity).label('total_qty'),
    ).join(Shift).filter(Shift.date == today).group_by(DailyStat.activity_id).all()

    act_map = {a.id: a.name for a in Activity.query.all()}
    activities_today = [
        {'activity': act_map.get(r.activity_id, '?'), 'total_qty': int(r.total_qty or 0)}
        for r in sorted(daily_rows, key=lambda r: r.total_qty or 0, reverse=True)
    ]

    # Per pracownik na zmianie — paczki + DailyStat
    pkg_by_user = {w['user_id']: {'packages': w['packages'], 'pieces': w['pieces']}
                   for w in workers_today}

    daily_per_user = db.session.query(
        DailyStat.user_id,
        DailyStat.activity_id,
        func.sum(DailyStat.quantity).label('qty'),
    ).join(Shift).filter(Shift.date == today).group_by(DailyStat.user_id, DailyStat.activity_id).all()

    stat_by_user = {}
    for r in daily_per_user:
        stat_by_user.setdefault(r.user_id, []).append(
            {'activity': act_map.get(r.activity_id, '?'), 'qty': int(r.qty or 0)}
        )

    # Widoczni: obecni na zmianie LUB ci, którzy dziś zakończyli paczki (nic nie chowamy)
    relevant_ids = present_ids | set(pkg_by_user.keys())
    present_users = User.query.filter(User.id.in_(relevant_ids)).order_by(User.display_name).all() \
        if relevant_ids else []

    per_worker = []
    for u in present_users:
        pkg = pkg_by_user.get(u.id, {'packages': 0, 'pieces': 0})
        per_worker.append({
            'id': u.id,
            'name': u.display_name,
            'packages_today': pkg['packages'],
            'pieces_today': pkg['pieces'],
            'activities': sorted(stat_by_user.get(u.id, []), key=lambda x: x['qty'], reverse=True),
        })

    progress_pct = round(done_cartons / total_cartons * 100, 1) if total_cartons else 0

    return jsonify({
        'total_cartons': total_cartons,
        'done_cartons': done_cartons,
        'remaining_cartons': remaining_cartons,
        'remaining_pieces': int(remaining_pieces),
        'done_today': done_today,
        'pieces_today': int(pieces_today),
        'do_potwierdzenia': do_potwierdzenia,
        'progress_pct': progress_pct,
        'present_count': len(present_ids),
        'workers_today': workers_today,
        'activities_today': activities_today,
        'per_worker': per_worker,
        # Plan dnia dla dzisiejszego pliku i zalegle (niezrobione) per data pliku.
        'plik_dzis': plan_dnia_pliku(today),
        'zalegle': zalegle_wg_daty_pliku(),
        'as_of': datetime.now(LOCAL_TZ).strftime('%H:%M:%S'),
    })


@bp.route('/api/dashboard/plik')
@leader_required
def api_dashboard_plik():
    """Plan dnia dla wybranej daty pliku (`?date=`, domyslnie dzis)."""
    return jsonify(plan_dnia_pliku(parse_date(request.args.get('date'))))


@bp.route('/api/dashboard/zalegle')
@leader_required
def api_dashboard_zalegle():
    """Podsumowanie (niezrobione per data pliku) z opcjonalnym zakresem
    `date_from` / `date_to` po dacie pliku. Puste = wszystkie dni."""
    od_s, do_s = request.args.get('date_from', ''), request.args.get('date_to', '')
    od = parse_date(od_s, 'date_from') if od_s else None
    do = parse_date(do_s, 'date_to') if do_s else None
    if od and do and od > do:
        abort(400, 'Data „od" jest późniejsza niż „do".')
    return jsonify(zalegle_wg_daty_pliku(od, do))


@bp.route('/api/dashboard/loading-dates')
@leader_required
def api_dashboard_loading_dates():
    """Zakladka „Per Loading date": plan pliku per data pliku z zakresu.
    Bez dat — biezacy miesiac do dzis."""
    dzis = local_today()
    od_s, do_s = request.args.get('date_from', ''), request.args.get('date_to', '')
    od = parse_date(od_s, 'date_from') if od_s else dzis.replace(day=1)
    do = parse_date(do_s, 'date_to') if do_s else dzis
    if od > do:
        abort(400, 'Data „od" jest późniejsza niż „do".')
    if (do - od).days >= MAX_DNI_ZAKRESU_DASHBOARDU:
        abort(400, f'Zakres może mieć najwyżej {MAX_DNI_ZAKRESU_DASHBOARDU} dni.')
    return jsonify(plany_dni_pliku(od, do))


@bp.route('/api/dashboard/shifts')
@leader_required
def api_dashboard_shifts():
    """Per-shift daily breakdown for a chosen date.

    DailyStat is already shift-tagged (shift_id) → aggregated directly.
    Packages (ImportedCarton) have no shift, so they are attributed by
    ATTENDANCE: a package finished by a worker counts toward the single shift
    that worker was scanned into that day. Workers with no attendance (or in
    both shifts → ambiguous) land in the 'unattributed' bucket so nothing is
    silently dropped and totals stay exact (each package counted once).
    """
    date_str = request.args.get('date', '')
    try:
        target = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else local_today()
    except ValueError:
        target = local_today()

    act_map = {a.id: a.name for a in Activity.query.all()}
    user_map = {u.id: u.display_name for u in User.query.all()}

    # Shifts that day + attendance (user_id -> set of shift_numbers attended)
    shifts = {s.shift_number: s for s in Shift.query.filter_by(date=target).all()}
    user_shifts = {}
    for snum, sh in shifts.items():
        for a in ShiftAttendance.query.filter_by(shift_id=sh.id).all():
            user_shifts.setdefault(a.user_id, set()).add(snum)

    # Praca tego dnia per osoba (`prace_osob()`): paczka jednej osoby raz,
    # paczka wielu osob — udzial kazdej z nich, wiec kazda trafia do swojej zmiany.
    pkg_rows = [SimpleNamespace(user_id=uid, packages=len(p), pieces=sum(x[2] for x in p))
                for uid, p in prace_osob(target, target).items()]

    per_shift_pkg = {1: {'packages': 0, 'pieces': 0}, 2: {'packages': 0, 'pieces': 0}}
    unattributed = {'packages': 0, 'pieces': 0, 'workers': []}

    for r in pkg_rows:
        attended = user_shifts.get(r.user_id, set())
        pkgs, pcs = int(r.packages), int(r.pieces or 0)
        if len(attended) == 1:
            snum = next(iter(attended))
            per_shift_pkg[snum]['packages'] += pkgs
            per_shift_pkg[snum]['pieces'] += pcs
        else:
            unattributed['packages'] += pkgs
            unattributed['pieces'] += pcs
            unattributed['workers'].append({
                'user_id': r.user_id,
                'name': user_map.get(r.user_id, '?'),
                'packages': pkgs, 'pieces': pcs,
                'reason': 'brak obecności' if not attended else 'obie zmiany',
            })

    # DailyStat per shift + activity (direct via shift_id)
    ds_rows = db.session.query(
        Shift.shift_number,
        DailyStat.activity_id,
        func.sum(DailyStat.quantity).label('qty'),
    ).join(Shift, DailyStat.shift_id == Shift.id)\
     .filter(Shift.date == target)\
     .group_by(Shift.shift_number, DailyStat.activity_id).all()

    per_shift_acts = {1: [], 2: []}
    for r in ds_rows:
        per_shift_acts.setdefault(r.shift_number, []).append(
            {'activity': act_map.get(r.activity_id, '?'), 'qty': int(r.qty or 0)}
        )

    result_shifts = []
    for snum in (1, 2):
        sh = shifts.get(snum)
        present = ShiftAttendance.query.filter_by(shift_id=sh.id).count() if sh else 0
        result_shifts.append({
            'shift_number': snum,
            'exists': sh is not None,
            'present_count': present,
            'packages': per_shift_pkg[snum]['packages'],
            'pieces': per_shift_pkg[snum]['pieces'],
            'activities': sorted(per_shift_acts.get(snum, []), key=lambda x: x['qty'], reverse=True),
        })

    return jsonify({
        'date': target.isoformat(),
        'shifts': result_shifts,
        'unattributed': unattributed,
    })
