"""Logowanie, wylogowanie, profil (zmiana hasla), wymuszona zmiana domyslnego hasla."""
from datetime import datetime, timedelta

from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user

from logistat.config import DEFAULT_ADMIN_PASSWORD
from logistat.extensions import db
from logistat.models import PRIVILEGED_ROLES, ProbaLogowania, User
from logistat.web.wspolne import bezpieczny_next

bp = Blueprint('auth', __name__)


# Endpointy dostepne, gdy trzeba najpierw zmienic domyslne haslo.
BEZ_WYMOGU_ZMIANY_HASLA = {'auth.profile', 'auth.logout', 'static', 'auth.favicon', 'auth.login'}


@bp.before_app_request
def wymus_zmiane_domyslnego_hasla():
    """Zalogowany domyslnym haslem (`DEFAULT_ADMIN_PASSWORD`) — dopoki go nie
    zmieni, wszystko poza /profile odsyla tam (API: 403 JSON). Wczesniej
    `admin123` mogl zostac na zawsze; dotyczy tez baz juz istniejacych, bo
    sprawdzamy haslo przy logowaniu, nie znacznik w bazie."""
    if not session.get('wymus_zmiane_hasla') or request.endpoint in BEZ_WYMOGU_ZMIANY_HASLA:
        return None
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Najpierw zmień domyślne hasło (Profil).'}), 403
    flash('Ze względów bezpieczeństwa zmień domyślne hasło, zanim przejdziesz dalej.', 'error')
    return redirect(url_for('auth.profile'))


@bp.route('/favicon.ico')
def favicon():
    # Przegladarki pytaja o /favicon.ico same, nawet z <link rel="icon"> —
    # w logach .31 to byl jedyny powtarzajacy sie 404.
    return redirect(url_for('static', filename='favicon.svg'), code=301)


@bp.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('stanowisko.scanner', shift_number=1))
    return redirect(url_for('auth.login'))


# Limit nieudanych logowan na login (2026-10-19, przeglad architektury): bez niego
# haslo dalo sie zgadywac bez ograniczen. Liczone w bazie, nie w pamieci —
# gunicorn ma 2 workery, kazdy liczylby osobno.
MAKS_PROB_LOGOWANIA = 5
OKNO_PROB_LOGOWANIA = timedelta(minutes=15)


def zablokowane_logowanie(login, teraz):
    """Minuty do odblokowania albo None. Blokada = MAKS_PROB nieudanych prob
    tego loginu w oknie; mija OKNO od najstarszej z nich."""
    proby = (ProbaLogowania.query
             .filter(ProbaLogowania.login == login,
                     ProbaLogowania.kiedy >= teraz - OKNO_PROB_LOGOWANIA)
             .order_by(ProbaLogowania.kiedy).all())
    if len(proby) < MAKS_PROB_LOGOWANIA:
        return None
    odblokowanie = proby[-MAKS_PROB_LOGOWANIA].kiedy + OKNO_PROB_LOGOWANIA
    return max(1, -(-int((odblokowanie - teraz).total_seconds()) // 60))


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        teraz = datetime.utcnow()
        klucz = username.lower()
        minuty = zablokowane_logowanie(klucz, teraz)
        if minuty:
            # Nawet poprawne haslo nie przechodzi — inaczej limit nic by nie dawal.
            flash(f'Zbyt wiele nieudanych prób logowania. Spróbuj ponownie za {minuty} min.', 'error')
            return render_template('login.html'), 429
        user = User.query.filter_by(username=username).first()
        if (user and user.is_active_user and user.role in PRIVILEGED_ROLES
                and user.check_password(password)):
            ProbaLogowania.query.filter_by(login=klucz).delete()
            db.session.commit()
            login_user(user)
            session.pop('wymus_zmiane_hasla', None)
            if password == DEFAULT_ADMIN_PASSWORD:
                session['wymus_zmiane_hasla'] = True
                return redirect(url_for('auth.profile'))
            return redirect(bezpieczny_next(request.args.get('next')) or url_for('auth.index'))
        db.session.add(ProbaLogowania(login=klucz, kiedy=teraz,
                                      adres_ip=(request.remote_addr or '')[:64]))
        # Sprzatanie: proby starsze niz doba nie sa juz potrzebne.
        ProbaLogowania.query.filter(ProbaLogowania.kiedy < teraz - timedelta(days=1)).delete()
        db.session.commit()
        flash('Nieprawidłowy login lub hasło.', 'error')
    return render_template('login.html')


@bp.route('/logout', methods=['POST'])
@login_required
def logout():
    session.pop('wymus_zmiane_hasla', None)
    logout_user()
    return redirect(url_for('auth.login'))


@bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        current = request.form.get('current_password', '')
        new = request.form.get('new_password', '')
        confirm = request.form.get('confirm_password', '')
        if not current_user.check_password(current):
            flash('Aktualne hasło jest nieprawidłowe.', 'error')
        elif len(new) < 6:
            flash('Nowe hasło musi mieć co najmniej 6 znaków.', 'error')
        elif new != confirm:
            flash('Nowe hasła nie są identyczne.', 'error')
        elif new == current:
            flash('Nowe hasło musi różnić się od aktualnego.', 'error')
        else:
            current_user.set_password(new)
            db.session.commit()
            session.pop('wymus_zmiane_hasla', None)
            flash('Hasło zostało zmienione.', 'success')
            return redirect(url_for('auth.profile'))
    return render_template('profile.html')
