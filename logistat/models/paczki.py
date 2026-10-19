"""Paczki (kartony z importu) i udzialy osob w paczce."""
import json
from datetime import datetime

from logistat.czas import iso_z
from logistat.extensions import db
from logistat.kategorie import STAT_CATEGORIES, liczba
from logistat.okresy import suma_zlaczonych_okresow
from logistat.tabela_ilosci import (
    TRYB_WZOR, TRYB_ZESPOL, kategorie_z_tabeli, roznice_tabeli, sztuki_tabeli, wczytaj_json_dict)


class ImportedCarton(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    barcode = db.Column(db.String(100), unique=True, nullable=False)
    land = db.Column(db.String(150), nullable=True)
    stueckzahl = db.Column(db.Integer, default=0)
    kategorie = db.Column(db.String(100), nullable=True)
    ziel_datum = db.Column(db.Date, nullable=True)
    # Dzien pracy, ktorego dotyczy wrzucony plik — podawany przy imporcie
    # (domyslnie dzis). GLOWNA data paczki: klucz linii rozliczenia (Loading
    # date w Statystykach ogolnych), Dashboard, Forecast, filtry. Ziel-Datum
    # zostaje tylko jako informacja z pliku. Patrz klucz_linii().
    data_pliku = db.Column(db.Date, nullable=True)
    uebergabe_nr = db.Column(db.String(100), nullable=True)
    country_mapping_id = db.Column(db.Integer, db.ForeignKey('country_mapping.id'), nullable=True)
    imported_at = db.Column(db.DateTime, default=datetime.utcnow)
    imported_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    processed_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    processed_at = db.Column(db.DateTime, nullable=True)
    double_rate = db.Column(db.Boolean, default=False)
    scan_start_at = db.Column(db.DateTime, nullable=True)
    scan_start_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    scan_end_at = db.Column(db.DateTime, nullable=True)
    scan_end_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    added_manually = db.Column(db.Boolean, default=False)
    modified_at = db.Column(db.DateTime, nullable=True)
    modified_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    # Ilosci per kategoria wpisane przy skanie konca paczki (JSON {kategoria: sztuki}).
    # Zrodlo prawdy dla GeneralStat.category_data linii oznaczonych category_source='scan'.
    scan_category_data = db.Column(db.Text, default='{}')
    # Pelna tabela ilosci z konca paczki (2026-10-15) — JSON, tylko przez
    # get_tabela()/set_tabela(). NULL = paczka sprzed tabeli (stary formularz
    # kategorii, stare reguly bledow). `scan_category_data` jest z niej liczone.
    tabela_ilosci = db.Column(db.Text, nullable=True)
    # ❗ Roznica do potwierdzenia przez lidera (Brak / Nadwyzka / Uszkodzone /
    # suma kilku osob ≠ plik) — kolumna, a nie wyliczenie, zeby licznik na
    # Dashboardzie byl jednym COUNT-em. Liczona w odswiez_roznice().
    roznica = db.Column(db.Boolean, nullable=False, default=False)
    roznica_potwierdzona_at = db.Column(db.DateTime, nullable=True)
    roznica_potwierdzona_przez = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    __table_args__ = (
        db.Index('ix_carton_ziel_datum',    'ziel_datum'),
        db.Index('ix_carton_data_pliku',    'data_pliku'),
        db.Index('ix_carton_uebergabe_nr',  'uebergabe_nr'),
        db.Index('ix_carton_processed_by',  'processed_by'),
        db.Index('ix_carton_land',          'land'),
        db.Index('ix_carton_imported_at',   'imported_at'),
    )

    country_mapping = db.relationship('CountryMapping', backref=db.backref('cartons', lazy=True))
    processed_by_user = db.relationship('User', foreign_keys=[processed_by])
    scan_start_by_user = db.relationship('User', foreign_keys=[scan_start_by])
    scan_end_by_user = db.relationship('User', foreign_keys=[scan_end_by])
    imported_by_user = db.relationship('User', foreign_keys=[imported_by])
    modified_by_user = db.relationship('User', foreign_keys=[modified_by])
    potwierdzajacy = db.relationship('User', foreign_keys=[roznica_potwierdzona_przez])

    def get_tabela(self):
        return wczytaj_json_dict(self.tabela_ilosci)

    def set_tabela(self, tabela):
        self.tabela_ilosci = json.dumps(tabela) if tabela else None

    def tryb_tabeli(self):
        """Paczka kilku osob → kazdy wpisuje swoje sztuki wprost (zespol)."""
        return TRYB_ZESPOL if self.udzialy else TRYB_WZOR

    def powody_roznicy(self):
        osob = len({u.user_id for u in self.udzialy}) or 1
        return roznice_tabeli(self.get_tabela(), self.stueckzahl, osob)

    def roznica_do_potwierdzenia(self):
        return bool(self.roznica) and not self.roznica_potwierdzona_at

    def edytor_ilosci(self):
        """Ktore okno „✎ Ilosci" na /paczki: 'tabela' (paczka jednej osoby),
        'zespol' (kazda osoba osobno) albo 'stary' (paczka sprzed tabeli)."""
        if self.udzialy:
            zamkniete = [u for u in self.udzialy if u.end_at and not u.zamkniete_przez]
            if all(u.tabela for u in zamkniete):
                return 'zespol'
            return 'stary'
        if self.tabela_ilosci or not self.scan_end_at:
            return 'tabela'
        return 'stary'

    def processing_seconds(self):
        # Paczka kilku osob: czas pracy przy niej = zlaczone okresy udzialow
        # (zespol rownolegle liczy sie raz, przerwa miedzy zmianami wcale).
        # Rozpietosc start–koniec dawalaby przy przekazaniu cala noc.
        if self.scan_end_at and self.udzialy:
            return int(suma_zlaczonych_okresow(
                [(u.start_at, u.end_at) for u in self.udzialy if u.end_at]))
        if self.scan_start_at and self.scan_end_at:
            return int((self.scan_end_at - self.scan_start_at).total_seconds())
        return None

    def udzialy_krotko(self):
        """Kto ile wpisal — do okna „✎ Ilosci" na /paczki."""
        return [{'id': u.id, 'kto': u.user.display_name if u.user else '?', 'suma': u.suma(),
                 'sztuki': u.sztuki(), 'tabela': u.get_tabela(),
                 'otwarty': u.end_at is None,
                 'bez_ilosci': bool(u.zamkniete_przez)} for u in self.udzialy]

    def do_dokonczenia(self):
        """Przekazana przez poprzednia osobe, nikt jej jeszcze nie przejal."""
        return (not self.scan_end_at and not self.scan_start_at
                and bool(self.udzialy))

    def get_scan_categories(self):
        """Ilosci per kategoria ze skanu. Zawsze dict {kategoria: int}."""
        try:
            dane = json.loads(self.scan_category_data) if self.scan_category_data else {}
        except (json.JSONDecodeError, TypeError):
            return {}
        if not isinstance(dane, dict):
            return {}
        return {k: liczba(v) for k, v in dane.items()
                if k in STAT_CATEGORIES and isinstance(v, (int, float))}

    def set_scan_categories(self, dane):
        # liczba(), nie int(): Labelling twice ×1,5 daje polowki — int() po
        # cichu ucinalby 4,5 do 4 w rozliczeniu.
        self.scan_category_data = json.dumps(
            {k: liczba(v) for k, v in (dane or {}).items() if k in STAT_CATEGORIES})

    def has_scan_categories(self):
        return bool(self.get_scan_categories())

    def to_dict(self):
        return {
            'id': self.id,
            'barcode': self.barcode,
            'land': self.land,
            'stueckzahl': self.stueckzahl,
            'kategorie': self.kategorie,
            'ziel_datum': self.ziel_datum.isoformat() if self.ziel_datum else None,
            'data_pliku': self.data_pliku.isoformat() if self.data_pliku else None,
            'imported_at': iso_z(self.imported_at),
            'uebergabe_nr': self.uebergabe_nr,
            'country_mapping_id': self.country_mapping_id,
            'processed_by': self.processed_by,
            'double_rate': self.double_rate or False,
            'processed_by_name': self.processed_by_user.display_name if self.processed_by_user else None,
            'processed_at': iso_z(self.processed_at),
            'scan_start_at': iso_z(self.scan_start_at),
            'scan_start_by': self.scan_start_by,
            'scan_start_by_name': self.scan_start_by_user.display_name if self.scan_start_by_user else None,
            'scan_end_at': iso_z(self.scan_end_at),
            'scan_end_by_name': self.scan_end_by_user.display_name if self.scan_end_by_user else None,
            'processing_seconds': self.processing_seconds(),
            'added_manually': self.added_manually or False,
            'imported_by_login': self.imported_by_user.username if self.imported_by_user else None,
            'modified_at': iso_z(self.modified_at),
            'modified_by_login': self.modified_by_user.username if self.modified_by_user else None,
            'scan_categories': self.get_scan_categories(),
            'tabela': self.get_tabela(),
            'tryb_tabeli': self.tryb_tabeli(),
            'roznica': bool(self.roznica),
            'roznica_potwierdzona_at': iso_z(self.roznica_potwierdzona_at),
            # Wiele osob przy paczce (przekazanie / zespol) — to_dict jest
            # wolane tylko dla pojedynczych paczek, wiec bez N+1.
            'do_dokonczenia': self.do_dokonczenia(),
            'udzialy': [u.to_dict() for u in self.udzialy],
        }


# Rodzaje udzialu: jak paczka stala sie paczka wielu osob.
UDZIAL_PRZEKAZANA = 'przekazana'   # „Paczka do dokonczenia" — kolejno, po sobie
UDZIAL_ZESPOL = 'zespol'           # „Pakowanie zespolowe" — rownolegle


class UdzialPaczki(db.Model):
    """Udzial jednej osoby w paczce, gdy pracuje przy niej wiecej niz jedna (2026-10-13).

    Paczka jednej osoby NIE ma wierszy — czyta sie ja z pol kartonu jak dawniej
    (16 tys. starych paczek bez migracji). Wiersze powstaja przy przekazaniu
    („Paczka do dokonczenia") i przy dolaczeniu („Pakowanie zespolowe").
    Karton trzyma agregat: `scan_category_data` = suma `ilosci` wszystkich
    udzialow (z sumy, nigdy delta), `scan_end_*` dopiero przy zamknieciu.
    Normy licza kazda osobe z jej udzialu: jej czas i jej wpisane ilosci.
    """
    __tablename__ = 'udzial_paczki'
    id = db.Column(db.Integer, primary_key=True)
    carton_id = db.Column(db.Integer, db.ForeignKey('imported_carton.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    rodzaj = db.Column(db.String(20), nullable=False)
    start_at = db.Column(db.DateTime, nullable=False)
    end_at = db.Column(db.DateTime, nullable=True)
    # JSON {kategoria: sztuki} — tylko przez get_ilosci()/set_ilosci().
    ilosci = db.Column(db.Text, default='{}')
    # Tabela ilosci tej osoby (tryb zespol, 2026-10-15); `ilosci` jest z niej
    # liczone. NULL = udzial sprzed tabeli — Normy biora wtedy suma().
    tabela = db.Column(db.Text, nullable=True)
    # Kto zamknal CUDZY udzial (kolega „zamknij dla wszystkich" albo lider) —
    # taki udzial nie ma ilosci i nie wchodzi do norm.
    zamkniete_przez = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    # delete-orphan: Odblokuj kasuje otwarte udzialy przez usuniecie z listy.
    carton = db.relationship('ImportedCarton', backref=db.backref(
        'udzialy', lazy='select', order_by='UdzialPaczki.start_at',
        cascade='all, delete-orphan'))
    user = db.relationship('User', foreign_keys=[user_id])
    zamykajacy = db.relationship('User', foreign_keys=[zamkniete_przez])

    def get_ilosci(self):
        try:
            dane = json.loads(self.ilosci) if self.ilosci else {}
        except (json.JSONDecodeError, TypeError):
            return {}
        if not isinstance(dane, dict):
            return {}
        return {k: liczba(v) for k, v in dane.items()
                if k in STAT_CATEGORIES and isinstance(v, (int, float))}

    def set_ilosci(self, dane):
        self.ilosci = json.dumps(
            {k: liczba(v) for k, v in (dane or {}).items() if k in STAT_CATEGORIES})

    def get_tabela(self):
        return wczytaj_json_dict(self.tabela)

    def set_tabela(self, tabela):
        self.tabela = json.dumps(tabela) if tabela else None
        self.set_ilosci(kategorie_z_tabeli(tabela))

    def suma(self):
        return liczba(sum(self.get_ilosci().values()))

    def sztuki(self):
        """Sztuki do Norm: z tabeli (Pojedynczo + Podwojnie + Potrojnie +
        Uszkodzone), a dla udzialu sprzed tabeli — suma wpisanych kategorii."""
        tabela = self.get_tabela()
        return sztuki_tabeli(tabela) if tabela else self.suma()

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'user_name': self.user.display_name if self.user else None,
            'rodzaj': self.rodzaj,
            'start_at': iso_z(self.start_at),
            'end_at': iso_z(self.end_at),
            'otwarty': self.end_at is None,
            'ilosci': self.get_ilosci(),
            'suma': self.suma(),
            'sztuki': self.sztuki(),
            'tabela': self.get_tabela(),
            'zamkniete_przez': self.zamykajacy.display_name if self.zamykajacy else None,
        }
