"""Konta i listy slownikowe uzytkownikow; role."""
from datetime import datetime

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from logistat.extensions import db


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    display_name = db.Column(db.String(150), nullable=False)
    barcode_id = db.Column(db.String(100), unique=True, nullable=True)
    password_hash = db.Column(db.String(200), nullable=True)  # only leaders/admins
    role = db.Column(db.String(20), default='operator')  # operator | leader | admin
    is_active_user = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Pola opisowe z list slownikowych, ktore admin definiuje sam (UserOption).
    # `shift_group`, nie `shift` — `Shift` / `shift_id` to juz zmiana 1/2 danego
    # dnia, a „Zmiana A/B/C" to stala brygada pracownika.
    worker_type_id = db.Column(db.Integer, db.ForeignKey('user_option.id'), nullable=True)
    shift_group_id = db.Column(db.Integer, db.ForeignKey('user_option.id'), nullable=True)
    worker_type = db.relationship('UserOption', foreign_keys=[worker_type_id])
    shift_group = db.relationship('UserOption', foreign_keys=[shift_group_id])
    # „Szkolacy" — osoba szkolaca nowych. Tylko ona moze wbic sie na kafelek
    # „Szkolenie" w Czasie pracy, a paczka, ktora choc czesciowo przypada na
    # szkolenie, liczy sie jej w Normach cala jako 100% celu (`policz_wydajnosc()`).
    is_trainer = db.Column(db.Boolean, default=False, nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'display_name': self.display_name,
            'barcode_id': self.barcode_id,
            'role': self.role,
            'is_active_user': self.is_active_user,
            'worker_type_id': self.worker_type_id,
            'worker_type': self.worker_type.name if self.worker_type else None,
            'shift_group_id': self.shift_group_id,
            'shift_group': self.shift_group.name if self.shift_group else None,
            'is_trainer': bool(self.is_trainer),
        }


# Rodzaje list slownikowych przypisywanych uzytkownikom. Klucz = `kind` w
# UserOption, wartosc = kolumna na User, ktora na nia wskazuje.
USER_OPTION_KINDS = {
    'worker_type': 'worker_type_id',   # Rodzaj pracownika: Logwin / agencje
    'shift_group': 'shift_group_id',   # Nazwa zmiany: Zmiana A / B / C
}

USER_OPTION_DEFAULTS = {
    'worker_type': ['Logwin', 'Agencja 1', 'Agencja 2'],
    'shift_group': ['Zmiana A', 'Zmiana B', 'Zmiana C'],
}


class UserOption(db.Model):
    """Pozycja listy rozwijanej na koncie uzytkownika — tresc ustala admin."""
    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(30), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    sort_order = db.Column(db.Integer, default=0)

    __table_args__ = (
        db.UniqueConstraint('kind', 'name', name='uq_user_option_kind_name'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'kind': self.kind,
            'name': self.name,
            'sort_order': self.sort_order,
        }


def user_options_by_kind():
    """{'worker_type': [UserOption…], 'shift_group': […]} — do szablonow."""
    wynik = {k: [] for k in USER_OPTION_KINDS}
    for o in UserOption.query.order_by(UserOption.sort_order, UserOption.name).all():
        wynik.setdefault(o.kind, []).append(o)
    return wynik


ROLES = ('operator', 'leader', 'admin')
# Role z dostepem do logowania i ekranow — konta uprzywilejowane. Zakladac je,
# zmieniac im role/haslo i dezaktywowac moze wylacznie admin.
PRIVILEGED_ROLES = ('leader', 'admin')


def active_admin_count(exclude_id=None):
    """Ilu aktywnych adminow zostanie, jesli pominac `exclude_id`."""
    q = User.query.filter_by(role='admin', is_active_user=True)
    if exclude_id is not None:
        q = q.filter(User.id != exclude_id)
    return q.count()
