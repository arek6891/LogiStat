"""Dekoracje (2026-10-28) — odczyt akcji z bazy dla Gantta, historii i ekranu
akcji. Bez requestu; zapis i walidacja w `logistat/web/displays.py`."""
from sqlalchemy.orm import selectinload

from logistat.czas import iso_z, teraz_utc, utc_to_local
from logistat.dekoracje import (
    POLA_LICZB, POLA_PRODUKTYWNOSCI, RODZAJE_SLOWNIKA, haki_razem, po_terminie, podsumowanie)
from logistat.extensions import db
from logistat.models import AkcjaDekoracji, IndexDekoracji, PosDekoracji, SlownikDekoracji


def index_dict(ix):
    d = {'id': ix.id, 'nazwa': ix.nazwa, 'typ_id': ix.typ_id, 'model_id': ix.model_id}
    for pole, _ in POLA_LICZB + POLA_PRODUKTYWNOSCI:
        d[pole] = getattr(ix, pole)
    d['haki'] = haki_razem(ix.ilosc_stojakow, ix.haki_na_stojak)
    return d


def akcja_dict(akcja, dzis, z_indexami=True):
    indexy = [index_dict(ix) for ix in akcja.indexy]
    d = {'id': akcja.id, 'nazwa': akcja.nazwa,
         'od': akcja.data_od.isoformat(), 'do': akcja.data_do.isoformat(),
         'zakonczona': akcja.zakonczona_at is not None,
         'zakonczona_at': iso_z(akcja.zakonczona_at) if akcja.zakonczona_at else None,
         'zakonczona_lokalnie': (utc_to_local(akcja.zakonczona_at).strftime('%d.%m.%Y %H:%M')
                                 if akcja.zakonczona_at else None),
         'zakonczyl': akcja.zakonczyl.display_name if akcja.zakonczyl else None,
         'po_terminie': akcja.zakonczona_at is None and po_terminie(akcja.data_do, dzis),
         'liczba_indexow': len(indexy), 'sumy': podsumowanie(indexy)}
    if z_indexami:
        d['indexy'] = indexy
    return d


def _akcje(zakonczone):
    q = AkcjaDekoracji.query.options(selectinload(AkcjaDekoracji.indexy),
                                     selectinload(AkcjaDekoracji.zakonczyl))
    if zakonczone:
        return q.filter(AkcjaDekoracji.zakonczona_at.isnot(None))\
            .order_by(AkcjaDekoracji.data_do.desc(), AkcjaDekoracji.id.desc()).all()
    return q.filter(AkcjaDekoracji.zakonczona_at.is_(None))\
        .order_by(AkcjaDekoracji.data_od, AkcjaDekoracji.data_do, AkcjaDekoracji.id).all()


def akcje_gantt(dzis):
    """Akcje niezakonczone (takze po terminie) — od najwczesniejszego startu."""
    return [akcja_dict(a, dzis, z_indexami=False) for a in _akcje(False)]


def akcje_historia(dzis):
    """Akcje zakonczone — najpozniej konczace sie na gorze."""
    return [akcja_dict(a, dzis, z_indexami=False) for a in _akcje(True)]


def slownik(rodzaj=None):
    q = SlownikDekoracji.query
    if rodzaj:
        q = q.filter_by(rodzaj=rodzaj)
    return q.order_by(SlownikDekoracji.kolejnosc, SlownikDekoracji.id).all()


def listy_dla_akcji(akcja):
    """Listy rozwijane ekranu akcji: aktywne pozycje plus wylaczone, ktore
    ktorys index tej akcji juz ma (nie moga zniknac z jego pola)."""
    uzyte = {ix.typ_id for ix in akcja.indexy} | {ix.model_id for ix in akcja.indexy}
    return {r: [p.to_dict() for p in slownik(r) if p.aktywna or p.id in uzyte]
            for r in RODZAJE_SLOWNIKA}


def uzyte_pozycje_slownika():
    """Id pozycji list, ktore ma jakikolwiek index (te mozna tylko wylaczyc)."""
    typy = db.session.query(IndexDekoracji.typ_id).filter(IndexDekoracji.typ_id.isnot(None))
    modele = db.session.query(IndexDekoracji.model_id).filter(IndexDekoracji.model_id.isnot(None))
    return {i for (i,) in typy.union(modele)}


# ── Etykiety POS ─────────────────────────────────────────────────────────────

def pos_dict(p):
    return {'id': p.id, 'numer': p.numer, 'post_processing': p.post_processing,
            'dodano': utc_to_local(p.utworzono_at).strftime('%d.%m.%Y %H:%M'),
            'import_at': iso_z(p.import_at) if p.import_at else None}


def pos_lista():
    return PosDekoracji.query.order_by(PosDekoracji.numer).all()


def ostatni_import_pos():
    """Wiersze ostatniego importu (druk „z ostatniego importu”)."""
    ostatni = db.session.query(db.func.max(PosDekoracji.import_at)).scalar()
    if ostatni is None:
        return []
    return PosDekoracji.query.filter(PosDekoracji.import_at == ostatni)\
        .order_by(PosDekoracji.numer).all()


def importuj_pos(pozycje, ma_pp, actor_id):
    """Zapis listy z `wiersze_pos()`: nowy numer → wiersz, istniejacy → nowa flaga
    Post Processing (tylko gdy plik ma te kolumne). Wszystkie wiersze pliku
    dostaja ten sam `import_at`. Zwraca liczniki; commit robi wolajacy."""
    teraz = teraz_utc()
    istniejace = {p.numer: p for p in PosDekoracji.query.filter(PosDekoracji.numer.in_(list(pozycje)))} \
        if pozycje else {}
    dodane = zmienione = 0
    for numer, pp in pozycje.items():
        p = istniejace.get(numer)
        if p is None:
            db.session.add(PosDekoracji(numer=numer, post_processing=pp if ma_pp else None,
                                        utworzyl_id=actor_id, utworzono_at=teraz, import_at=teraz))
            dodane += 1
            continue
        p.import_at = teraz
        if ma_pp and p.post_processing != pp:
            p.post_processing = pp
            p.zmienil_id, p.zmieniono_at = actor_id, teraz
            zmienione += 1
    return {'dodane': dodane, 'zmienione': zmienione, 'bez_zmian': len(pozycje) - dodane - zmienione}
