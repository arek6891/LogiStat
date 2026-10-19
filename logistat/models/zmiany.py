"""Zmiany, obecnosc, czynnosci, przydzial, szkolenia z czynnosci, wpis ilosci."""
from datetime import datetime

from logistat.czas import iso_z, local_today
from logistat.extensions import db
from logistat.models.ustawienia import AppSetting


class Activity(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    sort_order = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'sort_order': self.sort_order,
            'is_active': self.is_active
        }


class Shift(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    shift_number = db.Column(db.Integer, nullable=False)  # 1 or 2
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('date', 'shift_number', name='uq_shift_date_number'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'date': self.date.isoformat(),
            'shift_number': self.shift_number
        }


class ShiftAttendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    shift_id = db.Column(db.Integer, db.ForeignKey('shift.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    scanned_at = db.Column(db.DateTime, default=datetime.utcnow)

    shift = db.relationship('Shift', backref=db.backref('attendances', lazy=True))
    user = db.relationship('User', backref=db.backref('attendances', lazy=True))

    __table_args__ = (
        db.UniqueConstraint('shift_id', 'user_id', name='uq_attendance_shift_user'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'shift_id': self.shift_id,
            'user_id': self.user_id,
            'user': self.user.to_dict(),
            'scanned_at': iso_z(self.scanned_at)
        }


class ActivityAssignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    shift_id = db.Column(db.Integer, db.ForeignKey('shift.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    activity_id = db.Column(db.Integer, db.ForeignKey('activity.id'), nullable=False)
    is_suggestion = db.Column(db.Boolean, default=False)
    assigned_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    assigned_at = db.Column(db.DateTime, default=datetime.utcnow)

    shift = db.relationship('Shift', backref=db.backref('assignments', lazy=True))
    user = db.relationship('User', foreign_keys=[user_id],
                           backref=db.backref('assignments', lazy=True))
    activity = db.relationship('Activity', backref=db.backref('assignments', lazy=True))
    assigner = db.relationship('User', foreign_keys=[assigned_by])

    def to_dict(self):
        return {
            'id': self.id,
            'shift_id': self.shift_id,
            'user_id': self.user_id,
            'activity_id': self.activity_id,
            'is_suggestion': self.is_suggestion,
            'user': self.user.to_dict(),
            'activity': self.activity.to_dict()
        }


class SzkolenieCzynnosci(db.Model):
    """Osoba przeszkolona w czynnosci (2026-10-13, operacje) — tylko wtedy
    mozna ja do tej czynnosci przydzielic. Wiersz = przeszkolony; brak wiersza
    = nie (nowa osoba i nowa czynnosc startuja bez szkolen). Istniejacych
    w dniu wdrozenia zaznacza raz `zaznacz_wszystkich_przeszkolonych()`.
    """
    __tablename__ = 'szkolenie_czynnosci'
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    activity_id = db.Column(db.Integer, db.ForeignKey('activity.id'), primary_key=True)
    dodano_at = db.Column(db.DateTime, default=datetime.utcnow)
    dodal_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)


def szkolenia_czynnosci(user_ids=None):
    """`{user_id: {activity_id, …}}` — jedno zapytanie (opcjonalnie dla wybranych)."""
    q = db.session.query(SzkolenieCzynnosci.user_id, SzkolenieCzynnosci.activity_id)
    if user_ids is not None:
        if not user_ids:
            return {}
        q = q.filter(SzkolenieCzynnosci.user_id.in_(list(user_ids)))
    wynik = {}
    for uid, aid in q:
        wynik.setdefault(uid, set()).add(aid)
    return wynik


ZNACZNIK_SZKOLEN_CZYNNOSCI = 'migracja_szkolenia_czynnosci'


def zaznacz_wszystkich_przeszkolonych():
    """Jednorazowo (znacznik w AppSetting): kazdy istniejacy uzytkownik
    przeszkolony w kazdej istniejacej czynnosci — decyzja operacji 2026-10-13
    („wszystkich, ktorych mamy na tescie, zaznaczamy"). Kto przyjdzie pozniej,
    startuje bez szkolen."""
    if db.session.get(AppSetting, ZNACZNIK_SZKOLEN_CZYNNOSCI) is not None:
        return
    db.session.execute(db.text("""
        INSERT INTO szkolenie_czynnosci (user_id, activity_id, dodano_at)
        SELECT u.id, a.id, now() AT TIME ZONE 'UTC' FROM "user" u CROSS JOIN activity a
        ON CONFLICT DO NOTHING
    """))
    db.session.add(AppSetting(key=ZNACZNIK_SZKOLEN_CZYNNOSCI, value=local_today().isoformat()))
    db.session.commit()


class DailyStat(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    shift_id = db.Column(db.Integer, db.ForeignKey('shift.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    activity_id = db.Column(db.Integer, db.ForeignKey('activity.id'), nullable=False)
    quantity = db.Column(db.Integer, default=0)
    note = db.Column(db.String(300), nullable=True)

    # Audit fields
    entered_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    entered_at = db.Column(db.DateTime, default=datetime.utcnow)
    modified_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    modified_at = db.Column(db.DateTime, nullable=True)

    shift = db.relationship('Shift', backref=db.backref('stats', lazy=True))
    user = db.relationship('User', foreign_keys=[user_id],
                           backref=db.backref('stats', lazy=True))
    activity = db.relationship('Activity', backref=db.backref('stats', lazy=True))
    entered_by_user = db.relationship('User', foreign_keys=[entered_by])
    modified_by_user = db.relationship('User', foreign_keys=[modified_by])

    __table_args__ = (
        db.UniqueConstraint('shift_id', 'user_id', 'activity_id',
                            name='uq_stat_shift_user_activity'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'shift_id': self.shift_id,
            'user_id': self.user_id,
            'activity_id': self.activity_id,
            'quantity': self.quantity,
            'note': self.note,
            'entered_by': self.entered_by,
            'entered_at': iso_z(self.entered_at),
            'modified_by': self.modified_by,
            'modified_at': iso_z(self.modified_at),
            'user': self.user.to_dict(),
            'activity': self.activity.to_dict()
        }
