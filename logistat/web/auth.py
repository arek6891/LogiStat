"""Logowanie, wylogowanie, profil (zmiana hasla), wymuszona zmiana domyslnego hasla,
kafelki po zalogowaniu (grupy: Operacje magazynowe / Dzial etykietowania / Supervisor) i blokada obszaru."""
from datetime import timedelta

from flask import (Blueprint, abort, flash, jsonify, redirect, render_template, request, session,
                   url_for)
from flask_login import current_user, login_required, login_user, logout_user

from logistat.config import DEFAULT_ADMIN_PASSWORD
from logistat.czas import teraz_utc
from logistat.extensions import db
from logistat.models import ProbaLogowania, ROLE_Z_LOGOWANIEM, User
from logistat.obszary import OBSZARY, WSPOLNE, grupy_roli, obszary_endpointu, obszary_roli
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
# Po zalogowaniu wybiera sie kafelek; menu pokazuje tylko jego moduly. Rola
# decyduje, ktore kafelki widac (`ROLE_OBSZARY`) i do czego jest dostep; kafelek
# niczego nie blokuje. Od 2026-10-28 ekran startowy pokazuje GRUPY kafelkow
# (`GRUPY`): Dzial etykietowania rozwija sie w swoje kafelki, grupa z jednym
# kafelkiem prowadzi od razu do niego; jedna grupa z jednym kafelkiem (stanowisko)
# — od razu do niego.

def _wejdz_do_obszaru(obszar):
    session['obszar'] = obszar
    return redirect(url_for(OBSZARY[obszar]['start']))


@bp.route('/start')
@login_required
def kafelki():
    """Ekran startowy: kafelki-grupy roli (operacja 2026-10-28), a z `?grupa=`
    kafelki tej grupy. Grupa z jednym kafelkiem roli = od razu do niego, wiec
    jedna grupa z jednym kafelkiem (stanowisko) = od razu do Magazynu. Nieznana
    grupa albo spoza roli → ekran glowny."""
    grupy = grupy_roli(current_user.role)
    if len(grupy) == 1:
        klucz = grupy[0][0]
    else:
        klucz = request.args.get('grupa')
    wybrana = next((g for g in grupy if g[0] == klucz), None)
    if wybrana:
        _, grupa, obszary = wybrana
        if len(obszary) == 1:
            return _wejdz_do_obszaru(obszary[0])
        return render_template('kafelki.html', bez_menu=True, grupa=grupa, wiele_grup=len(grupy) > 1,
                               kafelki=[(o, OBSZARY[o]) for o in obszary],
                               wybrany=session.get('obszar'))
    wybrany = session.get('obszar')
    return render_template('kafelki.html', bez_menu=True, grupy=grupy,
                           aktywna=next((k for k, _, o in grupy if wybrany in o), None))


@bp.route('/start/<obszar>', methods=['POST'])
@login_required
def wybierz_obszar(obszar):
    if obszar not in obszary_roli(current_user.role):
        abort(403)
    return _wejdz_do_obszaru(obszar)


@bp.before_app_request
def pilnuj_obszaru():
    """Kafelek wybiera tylko MENU (decyzja operacji 2026-10-24, wersja lagodna):
    ekran z innego kafelka roli otwiera sie normalnie, a menu przelacza sie na
    jego kafelek. Blokada jest tylko na ekrany spoza kafelkow ROLI (konto
    stanowiska → tylko Magazyn) — to samo pilnuja dekoratory; tu na wypadek
    trasy z za szerokim dekoratorem. API nie zmienia wybranego kafelka, wiec
    dwie karty na roznych kafelkach dzialaja obie."""
    if not current_user.is_authenticated or session.get('wymus_zmiane_hasla'):
        return None
    ep = request.endpoint
    if ep is None or ep in WSPOLNE:
        return None
    dozwolone = obszary_roli(current_user.role)
    obszary = [o for o in dozwolone if o in obszary_endpointu(ep)]
    if not obszary:
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Brak uprawnień do tej operacji.'}), 403
        flash('Brak uprawnień do tego ekranu.', 'error')
        return redirect(url_for('auth.kafelki'))
    if not request.path.startswith('/api/') and session.get('obszar') not in obszary:
        session['obszar'] = obszary[0]
    return None


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
    # Konto stanowiska jest wspolne — haslo ustawia admin (Uzytkownicy). Sam ukryty
    # link nie wystarczal: POST przechodzil (przeglad 2026-10-24). Wyjatek: wymuszona
    # zmiana domyslnego hasla, inaczej petla przekierowan /profile ↔ /start.
    if current_user.role == 'stanowisko' and not session.get('wymus_zmiane_hasla'):
        flash('Hasło konta stanowiska zmienia administrator.', 'error')
        return redirect(url_for('auth.kafelki'))
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
