"""Normy: przeglad zespolu, karta pracownika, cel szt./h (historia zmian)."""
from datetime import datetime

from flask import Blueprint, abort, jsonify, render_template, request
from flask_login import current_user

from logistat.czas import iso_z, local_today, utc_to_local
from logistat.extensions import db
from logistat.models import (
    Activity, DailyStat, HistoriaCelu, Shift, User, get_setting_int, historia_celu_lista,
    set_setting)
from logistat.normy_dane import (
    cele_dzienne, norma_pracownika, okresy_szkolen, podsumuj_paczki_pracownika, prace_osob,
    przeglad_zespolu, wykres_wydajnosci, zasiej_historie_celu)
from logistat.web.wspolne import json_body, leader_required, parse_date

bp = Blueprint('normy', __name__)


@bp.route('/stats')
@leader_required
def stats():
    users = User.query.filter_by(is_active_user=True)\
        .order_by(User.display_name).all()
    activities = Activity.query.filter_by(is_active=True)\
        .order_by(Activity.sort_order).all()
    return render_template('stats.html', users=users, activities=activities,
                           cel_szt_h=get_setting_int('target_szt_h', 0),
                           historia_celu=historia_celu_lista())


@bp.route('/api/stats/target', methods=['PUT'])
@leader_required
def api_stats_target_update():
    """Docelowa wydajnosc (szt./h) wpisywana przez lidera na ekranie Statystyk.

    Celowo `@leader_required`, mimo ze reszta `AppSetting` idzie przez
    admin-only `PUT /api/settings`: cel jest **wylacznie informacyjny** —
    koloruje kolumne i nie dotyka ani rozliczen, ani zadnej blokady. Lider
    prowadzi zmiane, wiec to on ustala poprzeczke. Endpoint przyjmuje ten jeden
    klucz i nic wiecej, zeby nie otwierac liderowi calych ustawien.
    """
    data = json_body()
    try:
        wartosc = int(data.get('target_szt_h'))
    except (TypeError, ValueError):
        abort(400, 'Docelowa wydajność musi być liczbą całkowitą.')
    if wartosc < 0:
        abort(400, 'Docelowa wydajność nie może być ujemna.')

    # Historia celu: szkolenie liczy sie celem z dnia paczki, wiec stare dni
    # musza zachowac stary cel. Najpierw (raz) zapisujemy dotychczasowa wartosc
    # jako obowiazujaca „od zawsze", potem nowa od dzis.
    zasiej_historie_celu()
    dzis = db.session.get(HistoriaCelu, local_today())
    if dzis is None:
        dzis = HistoriaCelu(dzien=local_today(), wartosc=wartosc)
        db.session.add(dzis)
    else:
        dzis.wartosc = wartosc         # ostatni zapis danego dnia wygrywa
    dzis.zmienil_id = current_user.id
    dzis.zmieniono_at = datetime.utcnow()
    set_setting('target_szt_h', wartosc)
    db.session.commit()
    return jsonify({
        'message': 'Zapisano cel.' if wartosc else 'Cel wyłączony.',
        'target_szt_h': wartosc,
        'historia': historia_celu_lista(),
    }), 200


@bp.route('/api/stats/overview', methods=['GET'])
@leader_required
def api_stats_overview():
    date_from = parse_date(request.args.get('date_from'), 'date_from') \
        if request.args.get('date_from') else None
    date_to = parse_date(request.args.get('date_to'), 'date_to') \
        if request.args.get('date_to') else None
    return jsonify(przeglad_zespolu(date_from, date_to)), 200


@bp.route('/api/stats/user/<int:user_id>', methods=['GET'])
@leader_required
def api_stats_user(user_id):
    """Get per-user statistics, grouped by day and month."""
    user = db.get_or_404(User, user_id)
    activity_id = request.args.get('activity_id', type=int)
    date_from = parse_date(request.args.get('date_from'), 'date_from') \
        if request.args.get('date_from') else None
    date_to = parse_date(request.args.get('date_to'), 'date_to') \
        if request.args.get('date_to') else None

    query = db.session.query(
        DailyStat, Shift
    ).join(Shift).filter(DailyStat.user_id == user_id)

    if activity_id:
        query = query.filter(DailyStat.activity_id == activity_id)
    if date_from:
        query = query.filter(Shift.date >= date_from)
    if date_to:
        query = query.filter(Shift.date <= date_to)

    results = query.order_by(Shift.date.desc()).all()

    daily_stats = []
    monthly_agg = {}

    for stat, shift in results:
        daily_stats.append({
            'date': shift.date.isoformat(),
            'shift_number': shift.shift_number,
            'activity': stat.activity.name,
            'activity_id': stat.activity_id,
            'quantity': stat.quantity,
            'note': stat.note,
            'entered_by': stat.entered_by_user.display_name if stat.entered_by_user else None,
            'modified_by': stat.modified_by_user.display_name if stat.modified_by_user else None,
            'modified_at': iso_z(stat.modified_at),
            'stat_id': stat.id
        })

        month_key = shift.date.strftime('%Y-%m')
        act_name = stat.activity.name
        key = (month_key, act_name)
        if key not in monthly_agg:
            monthly_agg[key] = {'total': 0, 'days': 0}
        monthly_agg[key]['total'] += stat.quantity
        monthly_agg[key]['days'] += 1

    # Zakonczone paczki pracownika w okresie, po DOBIE LOKALNEJ, tak samo jak
    # dashboard. `func.date()` cielo po dacie UTC, wiec paczka zakonczona po
    # lokalnej polnocy trafiala na inny dzien tutaj niz na dashboardzie.
    # Konwersja jest w Pythonie: `local_day_bounds()` jest jedyna definicja doby
    # w calej aplikacji, a zakres jest maly (paczki jednej osoby w okresie).
    praca = prace_osob(date_from, date_to, user_ids=[user_id]).get(user_id, [])

    per_day = {}
    paczki_dnia = {}
    paczki_miesiaca = {}
    for scan_start_at, scan_end_at, stueckzahl in praca:
        d = utc_to_local(scan_end_at).date().isoformat()
        agg = per_day.setdefault(d, {'cnt': 0, 'pcs': 0})
        agg['cnt'] += 1
        agg['pcs'] += stueckzahl or 0
        paczka = (scan_start_at, scan_end_at, stueckzahl or 0)
        paczki_dnia.setdefault(d, []).append(paczka)
        paczki_miesiaca.setdefault(d[:7], []).append(paczka)
    szkolenia, szkoleni = okresy_szkolen(
        [user_id], date_from, date_to,
        najwczesniej=min((p[0] for p in praca if p[0]), default=None))
    szkolenia = szkolenia.get(user_id, ())
    szkoleni = szkoleni.get(user_id, ())
    cel_dnia = cele_dzienne()

    paczki_podsumowanie = podsumuj_paczki_pracownika(per_day)

    # Paczki jako syntetyczne pozycje tabel — tylko w widoku "Wszystkie"
    if not activity_id:
        PKG_METRICS = [('📦 Paczki', lambda cnt, pcs: cnt),
                       ('📦 Paczki (szt.)', lambda cnt, pcs: pcs)]
        for d, agg in per_day.items():
            cnt, pcs = agg['cnt'], agg['pcs']
            for label, metric in PKG_METRICS:
                qty = int(metric(cnt, pcs))
                daily_stats.append({
                    'date': d,
                    'shift_number': None,
                    'activity': label,
                    'activity_id': None,
                    'quantity': qty,
                    'note': '',
                    'entered_by': 'auto (skan paczek)',
                    'modified_by': None,
                    'modified_at': None,
                    'stat_id': None,
                    'is_package': True,
                })
                month_key = d[:7]  # 'YYYY-MM'
                key = (month_key, label)
                if key not in monthly_agg:
                    monthly_agg[key] = {'total': 0, 'days': 0}
                monthly_agg[key]['total'] += qty
                monthly_agg[key]['days'] += 1

    # Wspólne sortowanie malejąco po dacie (paczki wymieszane z czynnościami)
    daily_stats.sort(key=lambda x: x['date'], reverse=True)

    monthly_stats = [
        {
            'month': k[0],
            'activity': k[1],
            'total_quantity': v['total'],
            'days_worked': v['days'],
            'avg_per_day': round(v['total'] / v['days'], 1) if v['days'] > 0 else 0
        }
        for k, v in sorted(monthly_agg.items(), reverse=True)
    ]

    return jsonify({
        'user': user.to_dict(),
        'daily': daily_stats,
        'monthly': monthly_stats,
        'paczki_podsumowanie': paczki_podsumowanie,
        # Ocena i wykresy ida z paczek, wiec — jak podsumowanie — nie zaleza
        # od filtra czynnosci.
        'norma': norma_pracownika(user_id, date_from, date_to),
        'wykres_dzienny': wykres_wydajnosci(paczki_dnia, szkolenia, cel_dnia, szkoleni),
        'wykres_miesieczny': wykres_wydajnosci(paczki_miesiaca, szkolenia, cel_dnia, szkoleni),
    }), 200
