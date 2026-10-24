"""Logowanie, wylogowanie, profil (zmiana hasla), wymuszona zmiana domyslnego hasla,
kafelki po zalogowaniu (Magazyn / Post-Process / Ustawienia) i blokada obszaru."""
from datetime import timedelta
from urllib.parse import urlsplit

from flask import (Blueprint, abort, current_app, flash, jsonify, redirect, render_template,
                   request, session, url_for)
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.exceptions import MethodNotAllowed, NotFound

from logistat.config import DEFAULT_ADMIN_PASSWORD
from logistat.czas import teraz_utc
from logistat.extensions import db
from logistat.models import ProbaLogowania, ROLE_Z_LOGOWANIEM, User
from logistat.obszary import OBSZARY, WSPOLNE, obszary_endpointu, obszary_roli
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
        return redirect(url_for('auth.kafelki'))
    return redirect(url_for('auth.login'))


# ── Kafelki (operacja 2026-10-24) ─────────────────────────────────────────────
# Po zalogowaniu wybiera sie kafelek; menu pokazuje tylko jego moduly, a ekrany
# i API innych kafelkow sa zablokowane, dopoki nie wroci sie do kafelkow
# (twarda blokada — decyzja operacji, takze dla lidera). Rola decyduje, ktore
# kafelki widac (`ROLE_OBSZARY`). Jeden kafelek (stanowisko) — od razu do niego.

def _wejdz_do_obszaru(obszar, nastepny=None):
    session['obszar'] = obszar
    return redirect(nastepny or url_for(OBSZARY[obszar]['start']))


@bp.route('/start')
@login_required
def kafelki():
    dozwolone = obszary_roli(current_user.role)
    if len(dozwolone) == 1:
        return _wejdz_do_obszaru(dozwolone[0])
    return render_template('kafelki.html', bez_menu=True,
                           kafelki=[(o, OBSZARY[o]) for o in dozwolone],
                           wybrany=session.get('obszar'),
                           nastepny=bezpieczny_next(request.args.get('next')))


@bp.route('/start/<obszar>', methods=['POST'])
@login_required
def wybierz_obszar(obszar):
    if obszar not in obszary_roli(current_user.role):
        abort(403)
    nastepny = bezpieczny_next(request.form.get('next'))
    if nastepny and obszar not in obszary_endpointu(_endpoint_adresu(nastepny)):
        nastepny = None
    return _wejdz_do_obszaru(obszar, nastepny)


def _endpoint_adresu(adres):
    """Endpoint lokalnego adresu (do sprawdzenia, czy `next` jest w kafelku)."""
    try:
        return current_app.url_map.bind('').match(urlsplit(adres).path)[0]
    except (NotFound, MethodNotAllowed):
        return None


@bp.before_app_request
def pilnuj_obszaru():
    """Blokada ekranow i API spoza wybranego kafelka (i spoza kafelkow roli).

    Bez wybranego kafelka: jesli adres nalezy do dokladnie jednego kafelka
    roli — wybiera go sam (zakladka / link do konkretnego ekranu), inaczej
    ekran kafelkow. API spoza kafelka → 403 JSON z nazwa kafelka.
    `OBSZARY_WYMUSZANE = False` (testy) wylacza tylko te blokade —
    uprawnienia rol (dekoratory) dzialaja zawsze."""
    if not current_app.config.get('OBSZARY_WYMUSZANE', True):
        return None
    if not current_user.is_authenticated or session.get('wymus_zmiane_hasla'):
        return None
    ep = request.endpoint
    if ep is None or ep in WSPOLNE:
        return None
    dozwolone = obszary_roli(current_user.role)
    obszary = obszary_endpointu(ep) & set(dozwolone)
    api = request.path.startswith('/api/')
    if not obszary:
        if api:
            return jsonify({'error': 'Brak uprawnień do tej operacji.'}), 403
        flash('Brak uprawnień do tego ekranu.', 'error')
        return redirect(url_for('auth.kafelki'))
    wybrany = session.get('obszar')
    if wybrany not in dozwolone:
        wybrany = None
        if len(obszary) == 1:
            session['obszar'] = wybrany = next(iter(obszary))
        elif api:
            # API wspolne kilku kafelkom (np. /api/activities), a kafelek jeszcze
            # niewybrany — karta otwarta przed wdrozeniem kafelkow albo przed
            # logowaniem w innej karcie. Prawa roli juz sprawdzone wyzej; blokada
            # dotyczy przechodzenia MIEDZY wybranymi kafelkami.
            return None
    if wybrany in obszary:
        return None
    nazwy = ' / '.join(f'„{OBSZARY[o]["nazwa"]}”' for o in OBSZARY if o in obszary)
    if api:
        return jsonify({'error': f'Ta operacja jest w kafelku {nazwy} — wróć do kafelków '
                                 'i wybierz go.', 'obszar': sorted(obszary)}), 403
    if wybrany:
        flash(f'Ten ekran jest w kafelku {nazwy}. Wybierz go, żeby przejść dalej.', 'info')
    return redirect(url_for('auth.kafelki', next=request.full_path.rstrip('?')))


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
        teraz = teraz_utc()
        klucz = username.lower()
        minuty = zablokowane_logowanie(klucz, teraz)
        if minuty:
            # Nawet poprawne haslo nie przechodzi — inaczej limit nic by nie dawal.
            flash(f'Zbyt wiele nieudanych prób logowania. Spróbuj ponownie za {minuty} min.', 'error')
            return render_template('login.html'), 429
        user = User.query.filter_by(username=username).first()
        if (user and user.is_active_user and user.role in ROLE_Z_LOGOWANIEM
                and user.check_password(password)):
            ProbaLogowania.query.filter_by(login=klucz).delete()
            db.session.commit()
            login_user(user)
            session.pop('wymus_zmiane_hasla', None)
            session.pop('obszar', None)
            # Stanowisko (tablet w magazynie) zostaje zalogowane do wylogowania
            # (PERMANENT_SESSION_LIFETIME) — reszta jak dotad, do zamkniecia przegladarki.
            session.permanent = user.role == 'stanowisko'
            if password == DEFAULT_ADMIN_PASSWORD:
                session['wymus_zmiane_hasla'] = True
                return redirect(url_for('auth.profile'))
            return redirect(bezpieczny_next(request.args.get('next')) or url_for('auth.kafelki'))
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
    session.pop('obszar', None)
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
