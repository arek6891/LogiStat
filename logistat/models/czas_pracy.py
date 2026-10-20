"""Zdarzenia czasu pracy (przerwy, Inne, szkolenia) i historia celu Norm."""
from datetime import date

from sqlalchemy.orm import joinedload

from logistat.czas import iso_z, teraz_utc
from logistat.extensions import db


class WorkerTimeEvent(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    shift_id     = db.Column(db.Integer, db.ForeignKey('shift.id'), nullable=False)
    event_type   = db.Column(db.String(20), nullable=False)  # patrz EVENT_TYPES
    timestamp    = db.Column(db.DateTime, nullable=False, default=teraz_utc)
    recorded_by  = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    is_manual    = db.Column(db.Boolean, default=False)
    note         = db.Column(db.String(300), nullable=True)
    # Tylko przy 'trainee_*': kto prowadzi szkolenie. Dwa szkolenia naraz —
    # koniec jednego zamyka tylko jego szkolonych (`zakoncz_szkolenie()`).
    training_lead_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    __table_args__ = (
        db.Index('ix_wte_user_shift', 'user_id', 'shift_id'),
        db.Index('ix_wte_shift_id',   'shift_id'),
    )

    user     = db.relationship('User', foreign_keys=[user_id],
                               backref=db.backref('time_events', lazy=True))
    shift    = db.relationship('Shift', backref=db.backref('time_events', lazy=True))
    recorder = db.relationship('User', foreign_keys=[recorded_by])
    training_lead = db.relationship('User', foreign_keys=[training_lead_id])

    def to_dict(self):
        return {
            'id':             self.id,
            'user_id':        self.user_id,
            'user_name':      self.user.display_name,
            'shift_id':       self.shift_id,
            'event_type':     self.event_type,
            'timestamp':      iso_z(self.timestamp),
            'is_manual':      self.is_manual,
            'note':           self.note or '',
            'recorded_by_name': self.recorder.display_name if self.recorder else None,
            'training_lead_id': self.training_lead_id,
        }


EVENT_TYPES = ('break_start', 'break_end', 'other_start', 'other_end',
               'training_start', 'training_end', 'trainee_start', 'trainee_end',
               'work_end')
# 'other_*' — czas poza stanowiskiem inny niz przerwa (np. wyjscie do HR).
# Liczony jak przerwa: pomniejsza czas pracy, ale raportowany osobno.
# 'training_*' — szkolenie prowadzone przez osobe szkolaca (`User.is_trainer`).
# To CZAS PRACY: niczego nie pomniejsza, raportowane osobno; w Normach paczka
# zahaczajaca o szkolenie = cala po 100% celu (`policz_wydajnosc()`).
# 'trainee_*' — osoba SZKOLONA na szkoleniu prowadzonym przez `training_lead_id`.
# Tez czas pracy; jej paczki z tego czasu wypadaja z Norm i sredniej.
# Szkolenie zaczyna sie dopiero od pierwszej osoby szkolonej, a konczy je
# szkolacy — wszystkim naraz (zakladka „Szkolenie", `/api/time/training/*`).

# Stany, ktore sie wzajemnie wykluczaja (otwarte = wiecej *_start niz *_end).
TRYBY_CZASU = ('break', 'other', 'training', 'trainee')
# Przelaczane zwyklym skanem w `/api/time/scan`; szkolenie ma wlasna zakladke.
TRYBY_SKANU = ('break', 'other')
KOMUNIKATY_TRWANIA = {
    'break':    'jest na przerwie — najpierw zakończ przerwę.',
    'other':    'jest na „Inne" — najpierw zakończ „Inne".',
    'training': 'prowadzi szkolenie — najpierw zakończ szkolenie.',
    'trainee':  'jest na szkoleniu jako osoba szkolona — zakończy je osoba szkoląca.',
}


class HistoriaCelu(db.Model):
    """Cel szt./h obowiazujacy od dnia `dzien` (do nastepnego wpisu).

    `AppSetting.target_szt_h` trzyma tylko biezaca wartosc, a paczka ze
    szkolenia ma byc liczona celem z dnia, w ktorym ja zakonczono — bez historii
    zmiana celu po fakcie przeliczylaby wszystkie stare szkolenia. Wpis robi `PUT /api/stats/target`
    (ostatni zapis danego dnia wygrywa); pierwszy wiersz (`POCZATEK_HISTORII_CELU`)
    zasiewa `zasiej_historie_celu()` biezaca wartoscia sprzed historii.
    """
    __tablename__ = 'historia_celu'
    dzien = db.Column(db.Date, primary_key=True)
    wartosc = db.Column(db.Integer, nullable=False)
    # Kto i kiedy wpisal (2026-10-13) — lista zmian pod polem celu w Normach.
    # Puste w wierszach sprzed tej daty i w zasiewie.
    zmienil_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    zmieniono_at = db.Column(db.DateTime, nullable=True)
    zmienil = db.relationship('User')

    def to_dict(self):
        return {
            'od': None if self.dzien == POCZATEK_HISTORII_CELU else self.dzien.isoformat(),
            'wartosc': self.wartosc,
            'zmienil': self.zmienil.display_name if self.zmienil else None,
            'zmieniono_at': iso_z(self.zmieniono_at),
        }


def historia_celu_lista():
    """Wszystkie wpisy historii celu, od najnowszego — dla listy w Normach."""
    return [w.to_dict() for w in HistoriaCelu.query.options(
        joinedload(HistoriaCelu.zmienil)).order_by(HistoriaCelu.dzien.desc()).all()]


POCZATEK_HISTORII_CELU = date(2000, 1, 1)
