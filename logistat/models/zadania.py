"""Zadania dodatkowe (operacja 2026-11-02, zastepuja „Wpis ilosci”): czas osoby
spedzony na dziale (od–do) + opcjonalna czynnosc dodatkowa z listy admina
(sprzatanie, 5S…) i komentarz. Bez ilosci."""
from logistat.czas import teraz_utc
from logistat.extensions import db


class CzynnoscDodatkowa(db.Model):
    """Pozycja listy Supervisor → Czynności dodatkowe. Uzyta w zadaniu → tylko
    wylaczenie / zmiana nazwy (jak listy zwrotow i Dekoracji)."""
    __tablename__ = 'czynnosc_dodatkowa'
    id = db.Column(db.Integer, primary_key=True)
    nazwa = db.Column(db.String(100), nullable=False, unique=True)
    kolejnosc = db.Column(db.Integer, nullable=False, default=0)
    aktywna = db.Column(db.Boolean, nullable=False, default=True)

    # Partial `_listy_zwrotow.html` grupuje pozycje po `rodzaj` — tu jedna lista.
    rodzaj = 'czynnosc'

    def to_dict(self):
        return {'id': self.id, 'nazwa': self.nazwa, 'kolejnosc': self.kolejnosc,
                'aktywna': self.aktywna}


class ZadanieDodatkowe(db.Model):
    """Wiersz ekranu Zadania dodatkowe: osoba na zmianie, dzial (`DZIALY` w
    logistat/zadania.py), czas od–do (naive UTC), czynnosc dodatkowa (NULL = brak)
    i komentarz. Kilka wierszy na osobe i zmiane."""
    __tablename__ = 'zadanie_dodatkowe'
    id = db.Column(db.Integer, primary_key=True)
    shift_id = db.Column(db.Integer, db.ForeignKey('shift.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    dzial = db.Column(db.String(20), nullable=False)
    od = db.Column(db.DateTime, nullable=False)
    do = db.Column(db.DateTime, nullable=False)
    czynnosc_id = db.Column(db.Integer, db.ForeignKey('czynnosc_dodatkowa.id'), nullable=True)
    komentarz = db.Column(db.String(300), nullable=True)
    wpisal_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    wpisano_at = db.Column(db.DateTime, nullable=False, default=teraz_utc)
    zmienil_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    zmieniono_at = db.Column(db.DateTime, nullable=True)

    shift = db.relationship('Shift')
    user = db.relationship('User', foreign_keys=[user_id])
    czynnosc = db.relationship('CzynnoscDodatkowa')
    wpisal = db.relationship('User', foreign_keys=[wpisal_id])
