"""Pomocniki wspolne dla tras: dekoratory rol, odczyt danych z zadania
(400 przy zlej wartosci), bezpieczne przekierowanie po logowaniu."""
from datetime import date
from functools import wraps
from urllib.parse import urlsplit

from flask import abort, flash, jsonify, redirect, request, url_for
from flask_login import current_user, login_required
from werkzeug.exceptions import BadRequest

from logistat.czas import local_today
from logistat.models import PRIVILEGED_ROLES, User


def acting_as_admin():
    return current_user.is_authenticated and current_user.role == 'admin'


def leader_required(f):
    """Decorator: requires leader or admin role."""
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if current_user.role not in PRIVILEGED_ROLES:
            flash('Brak uprawnień.', 'error')
            return redirect(url_for('auth.index'))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    """Decorator: requires admin role."""
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if current_user.role != 'admin':
            flash('Brak uprawnień.', 'error')
            return redirect(url_for('auth.index'))
        return f(*args, **kwargs)
    return decorated


def json_body():
    """Cialo JSON jako dict. Brak ciala albo zly Content-Type -> {}, zeby
    walidacja pol dala czytelne 400 zamiast 415/500."""
    return request.get_json(silent=True) or {}


def parse_shift_number(value, default=1):
    """Numer zmiany: 1 albo 2. Cokolwiek innego -> `default`."""
    try:
        numer = int(value)
    except (TypeError, ValueError):
        return default
    return numer if numer in (1, 2) else default


def parse_date(value, pole='date') -> date:
    """Data ISO z requestu. Puste -> dzis lokalnie, zle sformatowana -> 400.

    Dotad `date.fromisoformat()` lecialo bez zabezpieczenia i literowka w URL-u
    konczyla sie 500-ka w logach.

    UWAGA: puste daje DZIS, nie None — to jest wlasciwe dla parametrow typu
    "ktora zmiane pokazac", ale NIE dla filtrow zakresu (`date_from`/`date_to`),
    gdzie brak parametru ma znaczyc "bez filtra". Tam wywoluj warunkowo:
    `parse_date(v, 'date_from') if v else None` (patrz api_stats_user).
    """
    if not value:
        return local_today()
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError:
        # raise, nie abort(): pyright nie wie, ze abort() nie wraca, i widzial
        # tu `date | None` (3 falszywe bledy). Ta sama odpowiedz 400 w JSON.
        raise BadRequest(f'Nieprawidłowa data w "{pole}" (oczekiwano YYYY-MM-DD).')


def require_int(value, pole):
    """Liczba calkowita albo 400 z nazwa pola."""
    try:
        return int(value)
    except (TypeError, ValueError):
        abort(400, f'Pole "{pole}" musi być liczbą całkowitą.')


def bezpieczny_next(adres):
    """`?next=` tylko jako sciezka w tej aplikacji. Pelny adres (`https://…`,
    `//host`) po zalogowaniu wysylalby uzytkownika na obca strone (open redirect)."""
    if not adres:
        return None
    czesci = urlsplit(adres)
    if czesci.scheme or czesci.netloc or not adres.startswith('/') or adres.startswith('//') \
            or '\\' in adres:
        return None
    return adres


def blad_nieznanej_paczki(barcode, komunikat='Nieznany kod paczki.'):
    """Odpowiedz na nieznany kod w polu PACZKI.

    Na hali zdarza sie zeskanowac w to pole identyfikator pracownika
    (`LSMOLIACHENKO` w logach .31) — goly „nieznany kod paczki" nic wtedy nie
    mowi, wiec nazywamy pomylke po imieniu. Sprawdzane dopiero po nietrafionym
    kartonie, zeby szczesliwa sciezka nie placila dodatkowego zapytania.
    """
    user = User.query.filter_by(barcode_id=barcode).first()
    if user:
        return jsonify({
            'error': f'To jest kod pracownika ({user.display_name}), nie paczki — '
                     'zeskanuj etykietę paczki.',
            'kod_pracownika': True,
        }), 400
    return jsonify({'error': komunikat}), 404
