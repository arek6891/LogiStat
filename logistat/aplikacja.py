"""Fabryka aplikacji Flask (`create_app`) i ladowanie uzytkownika sesji.
`create_app()` NIE dotyka bazy — schemat, migracje i seed: `logistat.baza.init_db()`."""
import logging
import os
from datetime import timedelta

from flask import Flask, jsonify, redirect, request, session, url_for
from flask_login import current_user
from werkzeug.exceptions import HTTPException

from logistat.config import DEFAULT_MAX_UPLOAD_MB, resolve_database_url, resolve_secret_key
from logistat.czas import utc_to_local
from logistat.extensions import db, login_manager
from logistat.obszary import OBSZARY, obszary_roli

# Katalog projektu (templates/, static/) — pakiet lezy w nim, nie odwrotnie.
KATALOG_PROJEKTU = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def create_app():
    """Aplikacja z konfiguracja ze srodowiska, obsluga bledow i blueprintami.
    Blad konfiguracji (brak SECRET_KEY / DATABASE_URL) = wyjatek tutaj."""
    app = Flask('logistat', root_path=KATALOG_PROJEKTU)
    _dziennik()
    _konfiguruj(app)
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    _obsluga_bledow(app)
    _szablony(app)
    _blueprinty(app)
    return app


def _dziennik():
    """Komunikaty `logistat.*` (seed, migracje) na stderr — trafiaja do `docker logs`
    obok logow gunicorna. Do 2026-10-20 bylo `print()` bez poziomu i czasu."""
    log = logging.getLogger('logistat')
    if not log.handlers:
        uchwyt = logging.StreamHandler()
        uchwyt.setFormatter(logging.Formatter('[%(asctime)s] [%(levelname)s] %(name)s: %(message)s'))
        log.addHandler(uchwyt)
        log.setLevel(logging.INFO)
        log.propagate = False


def _konfiguruj(app):
    app.config['SECRET_KEY'] = resolve_secret_key()
    # Aplikacja chodzi WYLACZNIE na Postgresie — brak DATABASE_URL to blad
    # konfiguracji, nie powod do cichego fallbacku na plik obok kodu.
    app.config['SQLALCHEMY_DATABASE_URI'] = resolve_database_url()
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    # Sprawdz polaczenie przed uzyciem: po restarcie kontenera bazy workery trzymaja
    # martwe polaczenia z puli i pierwsze zadanie na kazdym zwracalo 500
    # ("server closed the connection unexpectedly").
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'pool_pre_ping': True}
    app.config['MAX_CONTENT_LENGTH'] = int(
        os.environ.get('MAX_UPLOAD_MB', DEFAULT_MAX_UPLOAD_MB)) * 1024 * 1024
    # SameSite=Lax: przegladarka nie dosle ciasteczka przy POST z obcej strony.
    # Endpointy JSON byly chronione ubocznie (wymagaja Content-Type: application/json,
    # co wymusza preflight), ale /api/import-csv jest multipart, czyli bylo osiagalne
    # CSRF-em. Secure wlaczamy zmienna, bo do .31 wchodzi sie tez po HTTP z LAN-u.
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SECURE'] = os.environ.get('SESSION_COOKIE_SECURE') == '1'
    # Konto stanowiska (tablet w magazynie) ma sesje stala — tyle trwa (2026-10-24).
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)


def _obsluga_bledow(app):
    @app.errorhandler(HTTPException)
    def _blad_http(e):
        """Na /api/ zwracaj JSON — front wszedzie czyta `data.error`.

        Domyslnie Flask oddaje strone HTML, wiec `await r.json()` w JS wybuchalo i
        uzytkownik widzial "Blad polaczenia" zamiast tresci bledu.
        """
        if request.path.startswith('/api/'):
            return jsonify({'error': e.description}), e.code
        return e

    @app.errorhandler(413)
    def _upload_za_duzy(e):
        """Domyslna odpowiedz 413 to HTML — front na /import-csv czyta JSON."""
        limit_mb = app.config['MAX_CONTENT_LENGTH'] // (1024 * 1024)
        komunikat = f'Plik jest za duzy (limit {limit_mb} MB).'
        if request.path.startswith('/api/'):
            return jsonify({'error': komunikat}), 413
        return komunikat, 413


def _szablony(app):
    @app.context_processor
    def _kafelki():
        """Menu w base.html: kafelki roli i wybrany kafelek (sekcje menu)."""
        role_obszary = obszary_roli(current_user.role) if current_user.is_authenticated else ()
        wybrany = session.get('obszar')
        return {'OBSZARY': OBSZARY, 'obszary_roli': role_obszary,
                # Bez wybranego kafelka (np. tuz po logowaniu) — wszystkie sekcje roli.
                'menu_obszary': (wybrany,) if wybrany in role_obszary else role_obszary}

    @app.context_processor
    def _static_version():
        """`static_v('style.css')` dokleja mtime pliku jako ?v=.

        Dotad w base.html siedzialo recznie wpisane ?v=6 — trzeba bylo pamietac o
        bumpie przy kazdej zmianie CSS, inaczej przegladarka trzymala stary plik.
        """
        def static_v(filename):
            url = url_for('static', filename=filename)
            try:
                mtime = int(os.path.getmtime(os.path.join(app.static_folder, filename)))
            except OSError:
                return url
            return f'{url}?v={mtime}'

        return {'static_v': static_v}

    @app.template_filter('localdt')
    def localdt_filter(dt, fmt='%d.%m.%Y %H:%M'):
        """Jinja filter: render a naive-UTC datetime in Europe/Warsaw (DST-correct)."""
        if not dt:
            return '—'
        return utc_to_local(dt).strftime(fmt)


def _blueprinty(app):
    # Import w funkcji: blueprinty ciagna uslugi i modele — pakiet `logistat`
    # importowany sam (np. logistat.czas w testach) nie laduje calej aplikacji.
    from logistat.web import (
        admin, auth, czas_pracy, dashboard, displays, forecast, imports, normy, paczki,
        przydzial, rozliczenie, stanowisko, zwroty)
    for modul in (auth, admin, imports, forecast, normy, dashboard, przydzial, rozliczenie,
                  paczki, czas_pracy, stanowisko, displays, zwroty):
        app.register_blueprint(modul.bp)


@login_manager.unauthorized_handler
def brak_sesji():
    """Niezalogowany: API → 401 w JSON (np. wygasla sesja przy autozapisie — front
    pokazuje komunikat zamiast „bledu polaczenia"), strona → logowanie z `next`."""
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Sesja wygasła — zaloguj się ponownie.'}), 401
    return redirect(url_for('auth.login', next=request.full_path.rstrip('?')))


@login_manager.user_loader
def load_user(user_id):
    """Zwraca None dla konta nieaktywnego, wiec dezaktywacja wyrzuca tez z
    trwajacej sesji (nie tylko blokuje kolejne logowanie)."""
    from logistat.models import User
    try:
        user = db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None
    if user is None or not user.is_active_user:
        return None
    return user
