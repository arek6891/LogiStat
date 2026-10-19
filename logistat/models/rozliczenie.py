"""Rozliczenie: linie Statystyk ogolnych, stawki, mapowanie krajow, Forecast, nazwy kategorii."""
import json

from flask import g, has_request_context

from logistat.czas import teraz_utc
from logistat.extensions import db
from logistat.kategorie import STAT_CATEGORIES, STAT_CATEGORY_LABELS, STAT_CATEGORY_LABELS_PL
from logistat.models.ustawienia import AppSetting


class CountryMapping(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    country = db.Column(db.String(150), nullable=False)
    innenauftrag = db.Column(db.String(100), nullable=False)

    def to_dict(self):
        return {
            'id': self.id,
            'country': self.country,
            'innenauftrag': self.innenauftrag
        }


KLUCZ_NAZWY_PL = 'kategoria_pl:'
NAZWA_PL_MAX = 60


def nazwy_kategorii_pl():
    """Polska nazwa kazdej kategorii: nadpisana przez admina albo domyslna.

    Jedno zapytanie na wszystkie kategorie — wolajacy w petli dostaja mape.
    """
    nadpisane = {
        row.key[len(KLUCZ_NAZWY_PL):]: row.value
        for row in AppSetting.query.filter(AppSetting.key.like(KLUCZ_NAZWY_PL + '%'))
        if (row.value or '').strip()
    }
    return {k: nadpisane.get(k) or STAT_CATEGORY_LABELS_PL.get(k, '') for k in STAT_CATEGORIES}


def etykieta_kategorii(kat, nazwy_pl=None):
    """Etykieta na ekrany: najpierw polska nazwa, w nawiasie angielska ze
    Statystyk ogolnych — „Niesprocesowane (Sorting)". Angielska czesc jest
    stala (rozliczenie i eksport Excel jej uzywaja), wiec pracownik i
    rozliczajacy zawsze mowia o tej samej kategorii."""
    ang = STAT_CATEGORY_LABELS.get(kat, kat)
    pl = (nazwy_pl if nazwy_pl is not None else nazwy_kategorii_pl()).get(kat)
    return f'{pl} ({ang})' if pl else ang


def etykiety_kategorii():
    """Mapa kategoria → etykieta (do szablonow), jednym zapytaniem."""
    nazwy = nazwy_kategorii_pl()
    return {k: etykieta_kategorii(k, nazwy) for k in STAT_CATEGORIES}


def empty_category_data():
    """Return default empty category_data dict."""
    return {cat: {'amount': 0, 'cost': 0.0} for cat in STAT_CATEGORIES}


class Forecast(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, unique=True)
    quantity = db.Column(db.Integer, default=0)
    notes = db.Column(db.String(500), nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=teraz_utc)
    updated_at = db.Column(db.DateTime, nullable=True)
    updated_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    created_by_user = db.relationship('User', foreign_keys=[created_by])
    updated_by_user = db.relationship('User', foreign_keys=[updated_by])


class GeneralStat(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    loading_date = db.Column(db.Date, nullable=False)
    week_number = db.Column(db.Integer, nullable=False)
    list_id = db.Column(db.String(100), nullable=False)
    country_of_destination = db.Column(db.String(150), nullable=True)
    country_ledger = db.Column(db.String(150), nullable=False)
    amounts = db.Column(db.Integer, default=0)
    category_data = db.Column(db.Text, default='{}')
    double_rate_category_data = db.Column(db.Text, default='{}')  # yellow row: manual per-category amounts for double-rate packages
    # 'manual' = kategorie wpisane recznie (linie sprzed skanowania ilosci) — recompute ich NIE rusza.
    # 'scan'   = kategorie sa suma skanow paczek — pole reczne zablokowane.
    category_source = db.Column(db.String(10), default='manual')
    created_at = db.Column(db.DateTime, default=teraz_utc)
    updated_at = db.Column(db.DateTime, nullable=True)
    updated_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    __table_args__ = (
        db.UniqueConstraint('list_id', 'country_ledger', 'loading_date',
                            name='uq_general_stat'),
        db.Index('ix_gstat_loading_date', 'loading_date'),
        db.Index('ix_gstat_list_id',      'list_id'),
    )

    def get_category_data(self):
        try:
            return json.loads(self.category_data) if self.category_data else empty_category_data()
        except (json.JSONDecodeError, TypeError):
            return empty_category_data()

    def set_category_data(self, data):
        self.category_data = json.dumps(data)

    def get_double_rate_category_data(self):
        try:
            return json.loads(self.double_rate_category_data) if self.double_rate_category_data else empty_category_data()
        except (json.JSONDecodeError, TypeError):
            return empty_category_data()

    def set_double_rate_category_data(self, data):
        self.double_rate_category_data = json.dumps(data)

    def to_dict(self):
        """Serializacja linii razem z kosztem policzonym ze stawek jej miesiaca.

        Front nie zapisuje kosztow — sa wyliczane z `CostMapping` przy kazdym
        odczycie. Stawki idą przez `rates_for()` (cache na zadanie), bo inaczej
        kazdy wiersz odpalalby wlasne SELECT-y (N+1 na calej liscie).
        """
        cd = self.get_category_data()
        rates = rates_for(self.loading_date.year, self.loading_date.month)

        # Iterujemy po STAT_CATEGORIES, nie po kluczach z bazy — inaczej kategoria
        # usunieta z systemu dalej doliczalaby sie z historycznych wierszy.
        total_cost = 0.0
        for cat in STAT_CATEGORIES:
            data = cd.setdefault(cat, {'amount': 0, 'cost': 0.0})
            amt = data.get('amount', 0)
            rate = rates.get(cat, 0.0)
            data['computed_cost'] = amt * rate
            total_cost += data['computed_cost']
        cd = {kat: cd[kat] for kat in STAT_CATEGORIES}

        return {
            'id': self.id,
            'loading_date': self.loading_date.isoformat(),
            'week_number': self.week_number,
            'category_source': self.category_source or 'manual',
            'list_id': self.list_id,
            'country_of_destination': self.country_of_destination,
            'country_ledger': self.country_ledger,
            'amounts': self.amounts,
            'category_data': cd,
            'total_cost': total_cost,
        }


class CostMapping(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)
    rates_data = db.Column(db.Text, default='{}')
    created_at = db.Column(db.DateTime, default=teraz_utc)
    updated_at = db.Column(db.DateTime, nullable=True)
    updated_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    __table_args__ = (
        db.UniqueConstraint('year', 'month', name='uq_cost_mapping_ym'),
    )

    def get_rates_data(self):
        try:
            return json.loads(self.rates_data) if self.rates_data else {}
        except (json.JSONDecodeError, TypeError):
            return {}

    def set_rates_data(self, data):
        self.rates_data = json.dumps(data)
        
    def to_dict(self):
        return {
            'id': self.id,
            'year': self.year,
            'month': self.month,
            'rates_data': self.get_rates_data()
        }


def rates_for(year, month):
    """Stawki kategorii na dany miesiac, z cache na jedno zadanie.

    `GeneralStat.to_dict()` jest wolane per wiersz, a stawek jest kilka na rok —
    bez cache lista statystyk robila jedno SELECT na wiersz.
    """
    klucz = (year, month)
    cache = g.get('_rates_cache') if has_request_context() else None
    if cache is None:
        cache = {}
        if has_request_context():
            g._rates_cache = cache
    if klucz not in cache:
        mapping = CostMapping.query.filter_by(year=year, month=month).first()
        cache[klucz] = mapping.get_rates_data() if mapping else {}
    return cache[klucz]
