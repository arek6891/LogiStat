"""Dekoracje (2026-10-28): akcje (Gantt), ich indexy i listy typow / modeli
stojakow z panelu admina. Puste pole = NULL (nie 0)."""
from logistat.czas import teraz_utc
from logistat.extensions import db


class SlownikDekoracji(db.Model):
    """Pozycja listy z Supervisor → Listy Dekoracji: typ stojaka (Twin, Solo…)
    albo model stojaka (Gondola…). Uzyta w indexie → tylko wylaczenie / nazwa."""
    __tablename__ = 'slownik_dekoracji'
    id = db.Column(db.Integer, primary_key=True)
    rodzaj = db.Column(db.String(20), nullable=False)
    nazwa = db.Column(db.String(100), nullable=False)
    kolejnosc = db.Column(db.Integer, nullable=False, default=0)
    aktywna = db.Column(db.Boolean, nullable=False, default=True)

    __table_args__ = (db.UniqueConstraint('rodzaj', 'nazwa', name='uq_slownik_dekoracji_nazwa'),)

    def to_dict(self):
        return {'id': self.id, 'rodzaj': self.rodzaj, 'nazwa': self.nazwa,
                'kolejnosc': self.kolejnosc, 'aktywna': self.aktywna}


class AkcjaDekoracji(db.Model):
    """Akcja — nadrzedna nad reszta modulu. `zakonczona_at` ustawione = w historii
    (znika z Gantta); przywrocenie czysci je."""
    __tablename__ = 'akcja_dekoracji'
    id = db.Column(db.Integer, primary_key=True)
    nazwa = db.Column(db.String(150), nullable=False)
    data_od = db.Column(db.Date, nullable=False)
    data_do = db.Column(db.Date, nullable=False)
    zakonczona_at = db.Column(db.DateTime, nullable=True, index=True)
    zakonczyl_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    utworzyl_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    utworzono_at = db.Column(db.DateTime, nullable=False, default=teraz_utc)
    zmienil_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    zmieniono_at = db.Column(db.DateTime, nullable=True)

    indexy = db.relationship('IndexDekoracji', backref='akcja', cascade='all, delete-orphan',
                             order_by='(IndexDekoracji.kolejnosc, IndexDekoracji.id)')
    zakonczyl = db.relationship('User', foreign_keys=[zakonczyl_id])
    etapy = db.relationship('EtapAkcji', backref='akcja', cascade='all, delete-orphan')


class EtapAkcji(db.Model):
    """Kamien milowy akcji (2026-10-29): termin od–do etapu z `ETAPY_AKCJI`
    (`etap` = klucz). Wiersz powstaje przy pierwszym wpisaniu terminu; brak
    wiersza = etap bez terminu. Daty wewnatrz dat akcji (pilnuje API)."""
    __tablename__ = 'etap_akcji'
    id = db.Column(db.Integer, primary_key=True)
    akcja_id = db.Column(db.Integer, db.ForeignKey('akcja_dekoracji.id'), nullable=False, index=True)
    etap = db.Column(db.String(30), nullable=False)
    data_od = db.Column(db.Date, nullable=True)
    data_do = db.Column(db.Date, nullable=True)
    nie_dotyczy = db.Column(db.Boolean, nullable=False, default=False)
    zmienil_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    zmieniono_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (db.UniqueConstraint('akcja_id', 'etap', name='uq_etap_akcji'),)


class IndexDekoracji(db.Model):
    """Index akcji = szablon / zestaw displaya. Haki razem = stojaki × haki na
    stojak (liczone, nie zapisywane). Produktywnosc w sztukach na osobogodzine."""
    __tablename__ = 'index_dekoracji'
    id = db.Column(db.Integer, primary_key=True)
    akcja_id = db.Column(db.Integer, db.ForeignKey('akcja_dekoracji.id'), nullable=False, index=True)
    nazwa = db.Column(db.String(150), nullable=False)
    kolejnosc = db.Column(db.Integer, nullable=False, default=0)
    ilosc_stojakow = db.Column(db.Integer, nullable=True)
    typ_id = db.Column(db.Integer, db.ForeignKey('slownik_dekoracji.id'), nullable=True)
    model_id = db.Column(db.Integer, db.ForeignKey('slownik_dekoracji.id'), nullable=True)
    haki_na_stojak = db.Column(db.Integer, nullable=True)
    strony_na_stojak = db.Column(db.Integer, nullable=True)
    rgd = db.Column(db.Integer, nullable=True)
    displays = db.Column(db.Integer, nullable=True)
    akcesoria = db.Column(db.Integer, nullable=True)
    pos = db.Column(db.Integer, nullable=True)
    prod_hakowania = db.Column(db.Float, nullable=True)
    prod_dekorowania = db.Column(db.Float, nullable=True)
    zmienil_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    zmieniono_at = db.Column(db.DateTime, nullable=True)


class PosDekoracji(db.Model):
    """Numer POS z listy do etykiet (Dekoracje → Etykiety POS, 2026-10-28).
    Import z Excela dodaje nowe i aktualizuje istniejace po `numer`;
    `import_at` = ostatni import, ktory ten wiersz zawieral (druk „z ostatniego
    importu”). `post_processing` NULL = nie ustalono."""
    __tablename__ = 'pos_dekoracji'
    id = db.Column(db.Integer, primary_key=True)
    numer = db.Column(db.String(50), nullable=False, unique=True)
    post_processing = db.Column(db.Boolean, nullable=True)
    utworzono_at = db.Column(db.DateTime, nullable=False, default=teraz_utc)
    utworzyl_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    import_at = db.Column(db.DateTime, nullable=True, index=True)
    zmienil_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    zmieniono_at = db.Column(db.DateTime, nullable=True)


class StojakDekoracji(db.Model):
    """Gotowy stojak / display w stocku = nosnik (Dekoracje, 2026-10-28). Zaklada
    go pierwszy skan nosnika na stanowisku; POS (z listy Etykiet POS) i akcje
    przypisuje lider. Strefa = gdzie stoi teraz; ruchy w `ruch_stojaka`."""
    __tablename__ = 'stojak_dekoracji'
    id = db.Column(db.Integer, primary_key=True)
    nosnik = db.Column(db.String(50), nullable=False, unique=True)
    pos_id = db.Column(db.Integer, db.ForeignKey('pos_dekoracji.id'), nullable=True, index=True)
    akcja_id = db.Column(db.Integer, db.ForeignKey('akcja_dekoracji.id'), nullable=True, index=True)
    strefa_id = db.Column(db.Integer, db.ForeignKey('slownik_dekoracji.id'), nullable=True, index=True)
    utworzono_at = db.Column(db.DateTime, nullable=False, default=teraz_utc)
    utworzyl_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    zmienil_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    zmieniono_at = db.Column(db.DateTime, nullable=True)

    pos = db.relationship('PosDekoracji')
    akcja = db.relationship('AkcjaDekoracji')
    strefa = db.relationship('SlownikDekoracji')
    ruchy = db.relationship('RuchStojaka', backref='stojak', cascade='all, delete-orphan',
                            order_by='(RuchStojaka.kiedy.desc(), RuchStojaka.id.desc())')


class RuchStojaka(db.Model):
    """Zmiana strefy stojaka: skan na stanowisku albo poprawka lidera w tabeli
    (`recznie`). `z_strefy_id` NULL = pierwsze odlozenie."""
    __tablename__ = 'ruch_stojaka'
    id = db.Column(db.Integer, primary_key=True)
    stojak_id = db.Column(db.Integer, db.ForeignKey('stojak_dekoracji.id'), nullable=False, index=True)
    z_strefy_id = db.Column(db.Integer, db.ForeignKey('slownik_dekoracji.id'), nullable=True)
    do_strefy_id = db.Column(db.Integer, db.ForeignKey('slownik_dekoracji.id'), nullable=False)
    kiedy = db.Column(db.DateTime, nullable=False, default=teraz_utc)
    kto_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    recznie = db.Column(db.Boolean, nullable=False, default=False)

    z_strefy = db.relationship('SlownikDekoracji', foreign_keys=[z_strefy_id])
    do_strefy = db.relationship('SlownikDekoracji', foreign_keys=[do_strefy_id])
    kto = db.relationship('User')
