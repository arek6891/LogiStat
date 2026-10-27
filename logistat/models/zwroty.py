"""Zwroty (2026-10-26): listy Sorting Data, wpisy reczne i cennik Invoice specification.

Puste pole = NULL (arkusz operacji rozroznia puste od 0); do sum liczy sie jako 0.
"""
from logistat.czas import teraz_utc
from logistat.extensions import db


class LicencjaZwrotow(db.Model):
    """Wiersz Sorting Data: licencja (boxes built) albo wysylka (boxes shipped)."""
    __tablename__ = 'licencja_zwrotow'
    id = db.Column(db.Integer, primary_key=True)
    rodzaj = db.Column(db.String(10), nullable=False)        # LICENCJA / WYSYLKA
    nazwa = db.Column(db.String(100), nullable=False)
    kolejnosc = db.Column(db.Integer, nullable=False, default=0)
    aktywna = db.Column(db.Boolean, nullable=False, default=True)

    __table_args__ = (db.UniqueConstraint('rodzaj', 'nazwa', name='uq_licencja_zwrotow_nazwa'),)

    def to_dict(self):
        return {'id': self.id, 'rodzaj': self.rodzaj, 'nazwa': self.nazwa,
                'kolejnosc': self.kolejnosc, 'aktywna': self.aktywna}


class SortingDataWpis(db.Model):
    """Cartons / Pallets jednej licencji lub wysylki w miesiacu."""
    __tablename__ = 'sorting_data'
    licencja_id = db.Column(db.Integer, db.ForeignKey('licencja_zwrotow.id'), primary_key=True)
    rok = db.Column(db.Integer, primary_key=True)
    miesiac = db.Column(db.Integer, primary_key=True)
    cartons = db.Column(db.Integer, nullable=True)
    pallets = db.Column(db.Integer, nullable=True)
    zmienil_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    zmieniono_at = db.Column(db.DateTime, nullable=True, default=teraz_utc)


class IloscMiesiacaZwrotow(db.Model):
    """Reczna liczba miesiaca: ilosc czynnosci Invoice specification
    (klucz z KLUCZE_FAKTURY) albo POS processed z Sorting Data (KLUCZ_POS)."""
    __tablename__ = 'ilosc_miesiaca_zwrotow'
    rok = db.Column(db.Integer, primary_key=True)
    miesiac = db.Column(db.Integer, primary_key=True)
    klucz = db.Column(db.String(30), primary_key=True)
    wartosc = db.Column(db.Integer, nullable=True)
    zmienil_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    zmieniono_at = db.Column(db.DateTime, nullable=True, default=teraz_utc)


class CenaZwrotow(db.Model):
    """Price czynnosci Invoice specification w miesiacu (EUR) — ustawia admin."""
    __tablename__ = 'cena_zwrotow'
    rok = db.Column(db.Integer, primary_key=True)
    miesiac = db.Column(db.Integer, primary_key=True)
    czynnosc = db.Column(db.String(30), primary_key=True)
    cena = db.Column(db.Float, nullable=False)
    zmienil_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    zmieniono_at = db.Column(db.DateTime, nullable=True, default=teraz_utc)


class ZwrotPaczki(db.Model):
    """Jeden przyjety zwrot (Magazyn → Przyjęcie zwrotu, 2026-10-27) = jeden
    wiersz raportu Zwroty Paczek. Brand / kurier / Verpackungsvorschrift jako
    TEKST z chwili przyjecia — zmiana nazwy w Ustawieniach nie przepisuje
    historii raportu klienta. Date / Monat / Woche liczone z `przyjeto_at`."""
    __tablename__ = 'zwrot_paczki'
    id = db.Column(db.Integer, primary_key=True)
    paketnummer = db.Column(db.String(100), nullable=False, index=True)
    brand = db.Column(db.String(100), nullable=False)
    pos_nummer = db.Column(db.String(50), nullable=False)
    kurier = db.Column(db.String(100), nullable=False)
    retoure = db.Column(db.Integer, nullable=False)
    defekt = db.Column(db.Integer, nullable=False, default=0)
    neuwarenueberschuss = db.Column(db.Integer, nullable=False, default=0)
    silber = db.Column(db.Integer, nullable=False, default=0)
    defektes_silber = db.Column(db.Integer, nullable=False, default=0)
    reduzierte_ware = db.Column(db.Integer, nullable=False, default=0)
    verpackungsvorschrift = db.Column(db.String(100), nullable=False)
    przyjeto_at = db.Column(db.DateTime, nullable=False, default=teraz_utc, index=True)
    przyjal_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    # Z przegladarki, raz na paczke: podwojny klik / ponowienie po zerwanym
    # polaczeniu nie tworzy drugiego wiersza (Sorting returns idzie na fakture).
    token = db.Column(db.String(64), nullable=False, unique=True)
    # Poprawka lidera w Zwrotach Paczek (2026-10-27).
    zmienil_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    zmieniono_at = db.Column(db.DateTime, nullable=True)


class PrzydzialZwrotow(db.Model):
    """Osoba na stanowisku zwrotow (konto roli `stanowisko`) albo na Supporcie
    (`stanowisko_id` NULL, `support`) — od `od` do `do` (NULL = trwa). Przeniesienie
    = zamkniecie + nowy wiersz w tej samej chwili; historii sie nie poprawia.
    Najwyzej jeden otwarty wiersz na osobe (indeks czesciowy)."""
    __tablename__ = 'przydzial_zwrotow'
    id = db.Column(db.Integer, primary_key=True)
    shift_id = db.Column(db.Integer, db.ForeignKey('shift.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    stanowisko_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    support = db.Column(db.Boolean, nullable=False, default=False)
    od = db.Column(db.DateTime, nullable=False, default=teraz_utc, index=True)
    do = db.Column(db.DateTime, nullable=True)
    przydzielil_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    __table_args__ = (
        db.Index('uq_przydzial_zwrotow_otwarty', 'user_id', unique=True,
                 postgresql_where=db.text('"do" IS NULL')),
    )
