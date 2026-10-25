"""Administracja: uzytkownicy (role, szkolenia z czynnosci), czynnosci, listy
slownikowe, ustawienia, nazwy kategorii, mapowanie krajow i stawek."""
from flask import Blueprint, abort, jsonify, render_template
from flask_login import current_user
from sqlalchemy import func

from logistat.czas import teraz_utc
from logistat.extensions import db
from logistat.kategorie import STAT_CATEGORIES, STAT_CATEGORY_LABELS, STAT_CATEGORY_LABELS_PL
from logistat.models import (
    Activity, ActivityAssignment, AppSetting, CostMapping, CountryMapping, DailyStat,
    KLUCZ_NAZWY_PL, NAZWA_PL_MAX, ROLE_Z_LOGOWANIEM, ROLES, SzkolenieCzynnosci, USER_OPTION_KINDS, User, UserOption,
    active_admin_count, etykiety_kategorii, get_setting_int, nazwy_kategorii_pl, set_setting,
    szkolenia_czynnosci, user_options_by_kind)
from logistat.web.wspolne import (
    acting_as_admin, admin_required, json_body, leader_required, require_int)

bp = Blueprint('admin', __name__)


def _user_option_kind(value):
    if value not in USER_OPTION_KINDS:
        abort(400, 'Nieznany rodzaj listy.')
    return value


def _user_option_name(data):
    name = str(data.get('name') or '').strip()
    if not name:
        abort(400, 'Nazwa jest wymagana.')
    if len(name) > 100:
        abort(400, 'Nazwa może mieć najwyżej 100 znaków.')
    return name


def resolve_user_option(value, kind):
    """Id opcji danego rodzaju albo None (puste = brak). Zly id / rodzaj → 400."""
    if value in (None, ''):
        return None
    opt = db.session.get(UserOption, require_int(value, kind))
    if opt is None or opt.kind != kind:
        abort(400, 'Nieprawidłowa wartość listy.')
    return opt.id


def ustaw_szkolenia(user, activity_ids):
    """Zbior czynnosci, w ktorych `user` jest przeszkolony — zastepuje caly."""
    if not isinstance(activity_ids, list):
        abort(400, 'Pole „czynnosci" musi być listą.')
    nowe = {require_int(a, 'czynnosci') for a in activity_ids}
    znane = {a for (a,) in db.session.query(Activity.id).filter(Activity.id.in_(nowe))} \
        if nowe else set()
    if nowe - znane:
        abort(400, 'Nieznana czynność.')
    obecne = {w.activity_id: w for w in SzkolenieCzynnosci.query.filter_by(user_id=user.id)}
    # Ekran pokazuje tylko aktywne czynnosci — szkolenie z wylaczonej zostaje,
    # zeby po jej ponownym wlaczeniu nie trzeba bylo zaznaczac wszystkich od nowa.
    aktywne = {a for (a,) in db.session.query(Activity.id).filter_by(is_active=True)}
    for aid, w in obecne.items():
        if aid not in nowe and aid in aktywne:
            db.session.delete(w)
    for aid in nowe - obecne.keys():
        db.session.add(SzkolenieCzynnosci(user_id=user.id, activity_id=aid,
                                          dodal_id=current_user.id))


@bp.route('/admin/activities')
@admin_required
def admin_activities():
    activities = Activity.query.order_by(Activity.sort_order).all()
    return render_template('admin_activities.html', activities=activities)


@bp.route('/admin/users')
@leader_required
def admin_users():
    users = User.query.order_by(User.display_name).all()
    szkolenia = szkolenia_czynnosci()
    return render_template('admin_users.html', users=users,
                           options=user_options_by_kind(),
                           czynnosci=Activity.query.filter_by(is_active=True)
                           .order_by(Activity.sort_order).all(),
                           szkolenia={u: sorted(a) for u, a in szkolenia.items()})


@bp.route('/admin/panel')
@admin_required
def admin_panel():
    return render_template('admin_panel.html')


@bp.route('/admin/user-options')
@admin_required
def admin_user_options():
    return render_template('admin_user_options.html', options=user_options_by_kind())


@bp.route('/admin/country-mapping')
@admin_required
def admin_country_mapping():
    mappings = CountryMapping.query.order_by(CountryMapping.country).all()
    return render_template('admin_country_mapping.html', mappings=mappings)


@bp.route('/admin/cost-mapping')
@admin_required
def admin_cost_mapping():
    return render_template('admin_cost_mapping.html', categories=STAT_CATEGORIES,
                           category_labels=etykiety_kategorii())


@bp.route('/admin/settings')
@admin_required
def admin_settings():
    return render_template('admin_settings.html',
                           break_threshold=get_setting_int('break_threshold_minutes', 30),
                           max_work=get_setting_int('max_work_minutes', 660),
                           min_break=get_setting_int('min_break_minutes', 15),
                           norm_good=get_setting_int('norm_good_pct', 110),
                           norm_weak=get_setting_int('norm_weak_pct', 90),
                           min_packages=get_setting_int('min_packages_rank', 3))


@bp.route('/api/settings', methods=['PUT'])
@admin_required
def api_settings_update():
    data = json_body()
    pola = [
        ('break_threshold_minutes', 'Próg przerwy'),
        ('max_work_minutes',        'Maksymalny czas pracy'),
        ('min_break_minutes',       'Minimalna przerwa'),
        ('norm_good_pct',           'Próg dobrego wyniku'),
        ('norm_weak_pct',           'Próg słabego wyniku'),
        ('min_packages_rank',       'Minimum paczek do rankingu'),
    ]
    for klucz, nazwa in pola:
        if klucz not in data:
            continue
        try:
            val = int(data[klucz])
        except (TypeError, ValueError):
            return jsonify({'error': f'{nazwa} musi być liczbą całkowitą.'}), 400
        if val < 1:
            return jsonify({'error': f'{nazwa} musi być większa od zera.'}), 400
        set_setting(klucz, val)
    # Pilnowal tego tylko JS (przeglad 2026-10-24): slaby >= dobry psuje werdykty Norm.
    if get_setting_int('norm_weak_pct', 90) >= get_setting_int('norm_good_pct', 110):
        db.session.rollback()
        return jsonify({'error': 'Próg słabego wyniku musi być niższy niż próg dobrego.'}), 400
    db.session.commit()
    return jsonify({
        'message': 'Zapisano ustawienia.',
        'break_threshold_minutes': get_setting_int('break_threshold_minutes', 30),
        'max_work_minutes': get_setting_int('max_work_minutes', 660),
        'min_break_minutes': get_setting_int('min_break_minutes', 15),
        'norm_good_pct': get_setting_int('norm_good_pct', 110),
        'norm_weak_pct': get_setting_int('norm_weak_pct', 90),
        'min_packages_rank': get_setting_int('min_packages_rank', 3),
    }), 200


@bp.route('/admin/category-labels')
@admin_required
def admin_category_labels():
    nazwy = nazwy_kategorii_pl()
    return render_template('admin_category_labels.html', kategorie=[
        {'klucz': k, 'ang': STAT_CATEGORY_LABELS.get(k, k), 'pl': nazwy.get(k, ''),
         'domyslna': STAT_CATEGORY_LABELS_PL.get(k, '')}
        for k in STAT_CATEGORIES])


@bp.route('/api/category-labels', methods=['PUT'])
@admin_required
def api_category_labels_update():
    """Polskie nazwy kategorii widziane przez pracownika (koniec paczki,
    ✎ Ilości, cennik). Pusta nazwa = powrot do domyslnej. Angielskiej czesci
    nie da sie zmienic — to klucz rozliczenia i naglowki eksportu."""
    nazwy = json_body().get('nazwy')
    if not isinstance(nazwy, dict):
        abort(400, 'Pole "nazwy" musi być obiektem {kategoria: nazwa}.')
    for kat, nazwa in nazwy.items():
        if kat not in STAT_CATEGORIES:
            abort(400, f'Nieznana kategoria: {kat}.')
        if nazwa is not None and not isinstance(nazwa, str):
            abort(400, f'Nazwa dla „{STAT_CATEGORY_LABELS[kat]}" musi być tekstem.')
        nazwa = ' '.join((nazwa or '').split())
        if len(nazwa) > NAZWA_PL_MAX:
            abort(400, f'Nazwa dla „{STAT_CATEGORY_LABELS[kat]}" może mieć najwyżej {NAZWA_PL_MAX} znaków.')
        klucz = KLUCZ_NAZWY_PL + kat
        if not nazwa or nazwa == STAT_CATEGORY_LABELS_PL.get(kat):
            # Domyslna nie jest zapisywana — zmiana domyslnej w kodzie ma
            # dzialac dla kategorii, ktorych nikt nie nadpisal.
            row = db.session.get(AppSetting, klucz)
            if row is not None:
                db.session.delete(row)
        else:
            set_setting(klucz, nazwa)
    db.session.commit()
    return jsonify({'message': 'Zapisano nazwy kategorii.',
                    'etykiety': etykiety_kategorii()}), 200


@bp.route('/api/activities', methods=['GET'])
@leader_required
def api_activities():
    activities = Activity.query.order_by(Activity.sort_order).all()
    return jsonify([a.to_dict() for a in activities]), 200


@bp.route('/api/activities', methods=['POST'])
@admin_required
def api_activity_create():
    data = json_body()
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'error': 'Nazwa wymagana.'}), 400

    max_order = db.session.query(func.max(Activity.sort_order)).scalar() or 0
    activity = Activity(name=name, sort_order=max_order + 1)
    db.session.add(activity)
    db.session.commit()
    return jsonify(activity.to_dict()), 201


@bp.route('/api/activities/<int:activity_id>', methods=['PUT'])
@admin_required
def api_activity_update(activity_id):
    activity = db.get_or_404(Activity, activity_id)
    data = json_body()

    if 'name' in data:
        nazwa = str(data['name'] or '').strip()
        if not nazwa:
            abort(400, 'Nazwa czynności nie może być pusta.')
        activity.name = nazwa
    if 'sort_order' in data:
        activity.sort_order = require_int(data['sort_order'], 'sort_order')
    if 'is_active' in data:
        activity.is_active = bool(data['is_active'])

    db.session.commit()
    return jsonify(activity.to_dict()), 200


@bp.route('/api/activities/<int:activity_id>', methods=['DELETE'])
@admin_required
def api_activity_delete(activity_id):
    activity = db.get_or_404(Activity, activity_id)
    # Z historia (przydzialy, Wpis ilosci) — tylko dezaktywacja; usuniecie
    # konczylo sie naruszeniem klucza obcego i 500-ka.
    if (ActivityAssignment.query.filter_by(activity_id=activity.id).first()
            or DailyStat.query.filter_by(activity_id=activity.id).first()):
        return jsonify({'error': 'Czynność ma historię (przydziały / wpisy ilości) — '
                                 'można ją tylko dezaktywować.'}), 409
    SzkolenieCzynnosci.query.filter_by(activity_id=activity.id).delete()
    db.session.delete(activity)
    db.session.commit()
    return jsonify({'message': 'Usunięto.'}), 200


@bp.route('/api/activities/reorder', methods=['POST'])
@admin_required
def api_activities_reorder():
    data = json_body()
    order = data.get('order', [])
    for i, activity_id in enumerate(order):
        act = db.session.get(Activity, activity_id)
        if act:
            act.sort_order = i
    db.session.commit()
    return jsonify({'message': 'Kolejność zapisana.'}), 200


@bp.route('/api/users', methods=['GET'])
@leader_required
def api_users():
    users = User.query.order_by(User.display_name).all()
    return jsonify([u.to_dict() for u in users]), 200


@bp.route('/api/users', methods=['POST'])
@leader_required
def api_user_create():
    data = json_body()
    username = data.get('username', '').strip()
    display_name = data.get('display_name', '').strip()
    barcode_id = data.get('barcode_id', '').strip()
    role = data.get('role', 'operator')
    password = data.get('password', '')

    if not username or not display_name:
        return jsonify({'error': 'Login i nazwa wyświetlana są wymagane.'}), 400

    if role not in ROLES:
        return jsonify({'error': 'Nieprawidłowa rola.'}), 400

    # Lider zaklada operatorow na zmianie; kont z logowaniem nie moze zalozyc,
    # bo inaczej dorobilby sobie admina.
    if role in ROLE_Z_LOGOWANIEM and not acting_as_admin():
        return jsonify({
            'error': 'Tylko administrator może zakładać konta z logowaniem '
                     '(stanowisko, lider, administrator).'
        }), 403

    if role in ROLE_Z_LOGOWANIEM and not password:
        return jsonify({'error': 'Konto z logowaniem (stanowisko, lider, administrator) '
                                 'wymaga hasła.'}), 400

    if User.query.filter_by(username=username).first():
        return jsonify({'error': 'Taki login już istnieje.'}), 400

    if barcode_id and User.query.filter_by(barcode_id=barcode_id).first():
        return jsonify({'error': 'Taki kod kreskowy już istnieje.'}), 400

    user = User(
        username=username,
        display_name=display_name,
        barcode_id=barcode_id or None,
        role=role
    )
    for kind, kolumna in USER_OPTION_KINDS.items():
        setattr(user, kolumna, resolve_user_option(data.get(kolumna), kind))
    user.is_trainer = bool(data.get('is_trainer'))
    if role in ROLE_Z_LOGOWANIEM and password:
        user.set_password(password)

    db.session.add(user)
    if 'czynnosci' in data:
        db.session.flush()
        ustaw_szkolenia(user, data['czynnosci'])
    db.session.commit()
    return jsonify(user.to_dict()), 201


@bp.route('/api/users/<int:user_id>', methods=['PUT'])
@leader_required
def api_user_update(user_id):
    user = db.get_or_404(User, user_id)
    data = json_body()

    # Lider edytuje wylacznie operatorow i tylko ich dane opisowe. Bez tego
    # moglby podniesc sobie role albo przestawic haslo adminowi i wejsc na jego
    # konto.
    if not acting_as_admin():
        if user.role in ROLE_Z_LOGOWANIEM:
            return jsonify({
                'error': 'Konta z logowaniem (stanowisko, lider, administrator) może zmieniać '
                         'tylko administrator.'
            }), 403
        if 'role' in data and data['role'] != user.role:
            return jsonify({'error': 'Tylko administrator może zmieniać rolę.'}), 403
        if data.get('password'):
            return jsonify({'error': 'Tylko administrator może zmieniać hasło.'}), 403

    if 'role' in data and data['role'] not in ROLES:
        return jsonify({'error': 'Nieprawidłowa rola.'}), 400

    # Nie pozwol zdjac uprawnien ostatniemu aktywnemu adminowi — inaczej nikt
    # nie wejdzie juz do panelu.
    degraduje = 'role' in data and user.role == 'admin' and data['role'] != 'admin'
    dezaktywuje = user.role == 'admin' and data.get('is_active_user') is False
    if (degraduje or dezaktywuje) and active_admin_count(exclude_id=user.id) == 0:
        return jsonify({
            'error': 'To ostatnie aktywne konto administratora — najpierw utwórz inne.'
        }), 400

    if 'display_name' in data:
        user.display_name = str(data['display_name'] or '').strip()
    if 'barcode_id' in data:
        new_barcode = str(data['barcode_id'] or '').strip()
        if new_barcode:
            existing = User.query.filter(
                User.barcode_id == new_barcode, User.id != user_id
            ).first()
            if existing:
                return jsonify({'error': 'Taki kod kreskowy już istnieje.'}), 400
            user.barcode_id = new_barcode
        else:
            user.barcode_id = None
    for kind, kolumna in USER_OPTION_KINDS.items():
        if kolumna in data:
            setattr(user, kolumna, resolve_user_option(data[kolumna], kind))
    if 'is_trainer' in data:
        user.is_trainer = bool(data['is_trainer'])
    if 'czynnosci' in data:
        ustaw_szkolenia(user, data['czynnosci'])
    if 'role' in data:
        user.role = data['role']
    if 'is_active_user' in data:
        user.is_active_user = data['is_active_user']
    if 'password' in data and data['password']:
        user.set_password(data['password'])

    db.session.commit()
    return jsonify(user.to_dict()), 200


@bp.route('/api/users/<int:user_id>', methods=['DELETE'])
@leader_required
def api_user_delete(user_id):
    user = db.get_or_404(User, user_id)

    if user.role in ROLE_Z_LOGOWANIEM and not acting_as_admin():
        return jsonify({
            'error': 'Konta z logowaniem (stanowisko, lider, administrator) może '
                     'dezaktywować tylko administrator.'
        }), 403

    if user.role == 'admin' and active_admin_count(exclude_id=user.id) == 0:
        return jsonify({
            'error': 'To ostatnie aktywne konto administratora — najpierw utwórz inne.'
        }), 400

    user.is_active_user = False  # soft delete — load_user odbiera tez trwajaca sesje
    db.session.commit()
    return jsonify({'message': 'Dezaktywowano.'}), 200


@bp.route('/api/user-options', methods=['GET'])
@leader_required  # lider zaklada operatorow i wybiera z tych list
def api_user_options():
    return jsonify({k: [o.to_dict() for o in v]
                    for k, v in user_options_by_kind().items()}), 200


@bp.route('/api/user-options', methods=['POST'])
@admin_required
def api_user_option_create():
    data = json_body()
    kind = _user_option_kind(data.get('kind'))
    name = _user_option_name(data)
    if UserOption.query.filter_by(kind=kind, name=name).first():
        abort(409, 'Taka pozycja już istnieje.')
    ostatnia = db.session.query(func.max(UserOption.sort_order))\
        .filter(UserOption.kind == kind).scalar()
    opt = UserOption(kind=kind, name=name, sort_order=(ostatnia or 0) + 1)
    db.session.add(opt)
    db.session.commit()
    return jsonify(opt.to_dict()), 201


@bp.route('/api/user-options/<int:option_id>', methods=['PUT'])
@admin_required
def api_user_option_update(option_id):
    opt = db.get_or_404(UserOption, option_id)
    name = _user_option_name(json_body())
    if UserOption.query.filter(UserOption.kind == opt.kind, UserOption.name == name,
                               UserOption.id != opt.id).first():
        abort(409, 'Taka pozycja już istnieje.')
    # Zmiana nazwy przenosi sie na wszystkich przypisanych — trzymaja id, nie tekst.
    opt.name = name
    db.session.commit()
    return jsonify(opt.to_dict()), 200


@bp.route('/api/user-options/<int:option_id>', methods=['DELETE'])
@admin_required
def api_user_option_delete(option_id):
    opt = db.get_or_404(UserOption, option_id)
    kolumna = getattr(User, USER_OPTION_KINDS[opt.kind])
    przypisani = User.query.filter(kolumna == opt.id).count()
    # Twarde usuniecie osierocilo by klucz u pracownikow; lepiej powiedziec wprost.
    if przypisani:
        abort(409, f'Pozycja jest przypisana do {przypisani} użytkowników — '
                   'najpierw zmień im wartość albo zmień nazwę pozycji.')
    db.session.delete(opt)
    db.session.commit()
    return jsonify({'message': 'Usunięto.'}), 200


@bp.route('/api/country-mappings', methods=['GET'])
@admin_required
def api_country_mappings():
    mappings = CountryMapping.query.order_by(CountryMapping.country).all()
    return jsonify([m.to_dict() for m in mappings]), 200


@bp.route('/api/country-mappings', methods=['POST'])
@admin_required
def api_country_mapping_create():
    data = json_body()
    country = data.get('country', '').strip()
    innenauftrag = data.get('innenauftrag', '').strip()
    if not country or not innenauftrag:
        return jsonify({'error': 'Kraj i Innenauftrag są wymagane.'}), 400

    mapping = CountryMapping(country=country, innenauftrag=innenauftrag)
    db.session.add(mapping)
    db.session.commit()
    return jsonify(mapping.to_dict()), 201


@bp.route('/api/country-mappings/<int:mapping_id>', methods=['PUT'])
@admin_required
def api_country_mapping_update(mapping_id):
    mapping = db.get_or_404(CountryMapping, mapping_id)
    data = json_body()
    if 'country' in data:
        mapping.country = str(data['country'] or '').strip()
    if 'innenauftrag' in data:
        mapping.innenauftrag = str(data['innenauftrag'] or '').strip()
    db.session.commit()
    return jsonify(mapping.to_dict()), 200


@bp.route('/api/country-mappings/<int:mapping_id>', methods=['DELETE'])
@admin_required
def api_country_mapping_delete(mapping_id):
    mapping = db.get_or_404(CountryMapping, mapping_id)
    db.session.delete(mapping)
    db.session.commit()
    return jsonify({'message': 'Usunięto mapowanie.'}), 200


@bp.route('/api/cost-mapping/<int:year>/<int:month>', methods=['GET'])
@admin_required
def api_cost_mapping_get(year, month):
    mapping = CostMapping.query.filter_by(year=year, month=month).first()
    if mapping:
        return jsonify(mapping.get_rates_data()), 200
    return jsonify({}), 200


@bp.route('/api/cost-mapping/<int:year>/<int:month>', methods=['PUT', 'POST'])
@admin_required
def api_cost_mapping_save(year, month):
    data = json_body()
    rates = data.get('rates', {})
    # Rozliczenie — nic nie zapisujemy na slowo (przeglad 2026-10-24).
    if not 1 <= month <= 12 or not 2000 <= year <= 2100:
        abort(400, 'Nieprawidłowy miesiąc.')
    if not isinstance(rates, dict):
        abort(400, 'Pole "rates" musi być obiektem {kategoria: stawka}.')
    for kat, stawka in rates.items():
        if kat not in STAT_CATEGORIES:
            abort(400, f'Nieznana kategoria: {kat}.')
        if isinstance(stawka, bool) or not isinstance(stawka, (int, float)) or stawka < 0:
            abort(400, f'Stawka dla {kat} musi być liczbą ≥ 0.')

    mapping = CostMapping.query.filter_by(year=year, month=month).first()
    if mapping:
        mapping.set_rates_data(rates)
        mapping.updated_at = teraz_utc()
        mapping.updated_by = current_user.id
    else:
        mapping = CostMapping(
            year=year,
            month=month,
            updated_by=current_user.id
        )
        mapping.set_rates_data(rates)
        db.session.add(mapping)

    db.session.commit()
    return jsonify({'success': True, 'mapping': mapping.to_dict()}), 200
