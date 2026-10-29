"""Dekoracje (2026-10-28) — odczyt akcji z bazy dla Gantta, historii i ekranu
akcji. Bez requestu; zapis i walidacja w `logistat/web/displays.py`."""
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import selectinload

from logistat.czas import iso_z, teraz_utc, utc_to_local
from logistat.dekoracje import (
    ETAPY_AKCJI, ETAPY_OSTRZEZENIA, POLA_LICZB, POLA_PRODUKTYWNOSCI, RODZAJE_SLOWNIKA, STREFA,
    haki_razem, po_terminie, podsumowanie, stan_etapu)
from logistat.extensions import db
from logistat.models import (
    AkcjaDekoracji, EtapAkcji, IndexDekoracji, PosDekoracji, RuchStojaka, SlownikDekoracji, StojakDekoracji)


def index_dict(ix):
    d = {'id': ix.id, 'nazwa': ix.nazwa, 'typ_id': ix.typ_id, 'model_id': ix.model_id}
    for pole, _ in POLA_LICZB + POLA_PRODUKTYWNOSCI:
        d[pole] = getattr(ix, pole)
    d['haki'] = haki_razem(ix.ilosc_stojakow, ix.haki_na_stojak)
    return d


def etapy_akcji(akcja_ids, dzis):
    """{akcja_id: [etap — wszystkie z ETAPY_AKCJI, w ich kolejnosci]} jednym
    zapytaniem. Etap bez wiersza = bez terminu."""
    zapisane = {}
    if akcja_ids:
        for e in EtapAkcji.query.filter(EtapAkcji.akcja_id.in_(list(akcja_ids))):
            zapisane[(e.akcja_id, e.etap)] = e
    wynik = {}
    for akcja_id in akcja_ids:
        lista = []
        for klucz, nazwa, podpowiedz, opcjonalny in ETAPY_AKCJI:
            e = zapisane.get((akcja_id, klucz))
            od, do = (e.data_od, e.data_do) if e else (None, None)
            nie_dotyczy = bool(e and e.nie_dotyczy)
            lista.append({'klucz': klucz, 'nazwa': nazwa, 'podpowiedz': podpowiedz,
                          'opcjonalny': opcjonalny, 'nie_dotyczy': nie_dotyczy,
                          'od': od.isoformat() if od else None, 'do': do.isoformat() if do else None,
                          'stan': stan_etapu(od, do, dzis, nie_dotyczy)})
        wynik[akcja_id] = lista
    return wynik


def zapisz_etap(akcja_id, etap, od, do, nie_dotyczy, kto_id):
    """INSERT … ON CONFLICT DO UPDATE — dwoch liderow na jednym etapie (autozapis
    z dwoch kart) nie wywraca sie na unikalnym (akcja, etap). Commit robi wolajacy."""
    wartosci = {'data_od': od, 'data_do': do, 'nie_dotyczy': nie_dotyczy,
                'zmienil_id': kto_id, 'zmieniono_at': teraz_utc()}
    stmt = insert(EtapAkcji.__table__).values(akcja_id=akcja_id, etap=etap, **wartosci)
    db.session.execute(stmt.on_conflict_do_update(index_elements=['akcja_id', 'etap'], set_=wartosci))


def akcja_dict(akcja, dzis, z_indexami=True, etapy=None):
    """`etapy` = lista z `etapy_akcji()` (Gantt bierze je jednym zapytaniem dla
    wszystkich akcji); None → zapytanie dla tej jednej."""
    indexy = [index_dict(ix) for ix in akcja.indexy]
    if etapy is None:
        etapy = etapy_akcji([akcja.id], dzis)[akcja.id]
    d = {'id': akcja.id, 'nazwa': akcja.nazwa,
         'od': akcja.data_od.isoformat(), 'do': akcja.data_do.isoformat(),
         'zakonczona': akcja.zakonczona_at is not None,
         'zakonczona_at': iso_z(akcja.zakonczona_at) if akcja.zakonczona_at else None,
         'zakonczona_lokalnie': (utc_to_local(akcja.zakonczona_at).strftime('%d.%m.%Y %H:%M')
                                 if akcja.zakonczona_at else None),
         'zakonczyl': akcja.zakonczyl.display_name if akcja.zakonczyl else None,
         'po_terminie': akcja.zakonczona_at is None and po_terminie(akcja.data_do, dzis),
         'liczba_indexow': len(indexy), 'sumy': podsumowanie(indexy), 'etapy': etapy,
         # Ostrzezenia tylko dla akcji w toku — zakonczona nie ma juz czego pilnowac.
         'ostrzezenia': [] if akcja.zakonczona_at else
         [{'nazwa': e['nazwa'], 'stan': e['stan'], 'do': e['do']} for e in etapy
          if e['stan'] in ETAPY_OSTRZEZENIA]}
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
    akcje = _akcje(False)
    etapy = etapy_akcji([a.id for a in akcje], dzis)
    return [akcja_dict(a, dzis, z_indexami=False, etapy=etapy[a.id]) for a in akcje]


def akcje_historia(dzis):
    """Akcje zakonczone — najpozniej konczace sie na gorze."""
    akcje = _akcje(True)
    etapy = etapy_akcji([a.id for a in akcje], dzis)
    return [akcja_dict(a, dzis, z_indexami=False, etapy=etapy[a.id]) for a in akcje]


def slownik(rodzaj=None):
    q = SlownikDekoracji.query
    if rodzaj:
        q = q.filter_by(rodzaj=rodzaj)
    return q.order_by(SlownikDekoracji.kolejnosc, SlownikDekoracji.id).all()


def listy_dla_akcji(akcja):
    """Listy rozwijane ekranu akcji: aktywne pozycje plus wylaczone, ktore
    ktorys index tej akcji juz ma (nie moga zniknac z jego pola). Bez stref."""
    uzyte = {ix.typ_id for ix in akcja.indexy} | {ix.model_id for ix in akcja.indexy}
    return {r: [p.to_dict() for p in slownik(r) if p.aktywna or p.id in uzyte]
            for r in RODZAJE_SLOWNIKA if r != STREFA}


def uzyte_pozycje_slownika():
    """Id pozycji list, ktore ma jakikolwiek index (te mozna tylko wylaczyc)."""
    typy = db.session.query(IndexDekoracji.typ_id).filter(IndexDekoracji.typ_id.isnot(None))
    modele = db.session.query(IndexDekoracji.model_id).filter(IndexDekoracji.model_id.isnot(None))
    strefy = db.session.query(StojakDekoracji.strefa_id).filter(StojakDekoracji.strefa_id.isnot(None))
    # Strefa z historii ruchow tez zostaje — historia musi miec do czego wskazywac.
    z_ruchow = db.session.query(RuchStojaka.do_strefy_id)
    return {i for (i,) in typy.union(modele, strefy, z_ruchow)}


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


# ── Stock stojakow ───────────────────────────────────────────────────────────

def _lokalnie(chwila):
    return utc_to_local(chwila).strftime('%d.%m.%Y %H:%M') if chwila else None


def stojak_dict(s, ostatni=None):
    """`ostatni` = ostatni ruch (RuchStojaka) — tabela bierze je jednym zapytaniem."""
    return {'id': s.id, 'nosnik': s.nosnik,
            'pos': s.pos.numer if s.pos else None,
            'post_processing': s.pos.post_processing if s.pos else None,
            'akcja_id': s.akcja_id, 'akcja': s.akcja.nazwa if s.akcja else None,
            'strefa_id': s.strefa_id, 'strefa': s.strefa.nazwa if s.strefa else None,
            'utworzono': _lokalnie(s.utworzono_at),
            'ostatni_ruch': _lokalnie(ostatni.kiedy) if ostatni else None,
            'ostatni_kto': (ostatni.kto.display_name if ostatni and ostatni.kto else None)}


def ruch_dict(r):
    return {'kiedy': _lokalnie(r.kiedy), 'kto': r.kto.display_name if r.kto else None,
            'z': r.z_strefy.nazwa if r.z_strefy else None, 'do': r.do_strefy.nazwa,
            'recznie': r.recznie}


def ostatnie_ruchy(ids=None):
    """{stojak_id: najnowszy RuchStojaka} — jedno zapytanie (DISTINCT ON)."""
    q = RuchStojaka.query.options(selectinload(RuchStojaka.kto))
    if ids is not None:
        if not ids:
            return {}
        q = q.filter(RuchStojaka.stojak_id.in_(ids))
    q = q.distinct(RuchStojaka.stojak_id)\
        .order_by(RuchStojaka.stojak_id, RuchStojaka.kiedy.desc(), RuchStojaka.id.desc())
    return {r.stojak_id: r for r in q}


def stock_stojakow():
    lista = StojakDekoracji.query.options(
        selectinload(StojakDekoracji.pos), selectinload(StojakDekoracji.akcja),
        selectinload(StojakDekoracji.strefa)).order_by(StojakDekoracji.nosnik).all()
    ostatnie = ostatnie_ruchy()
    return [stojak_dict(s, ostatnie.get(s.id)) for s in lista]


def strefa_po_kodzie(kod, tylko_aktywne=True):
    q = SlownikDekoracji.query.filter_by(rodzaj=STREFA, nazwa=kod)
    if tylko_aktywne:
        q = q.filter_by(aktywna=True)
    return q.first()


def przenies_stojak(stojak, strefa_id, kto_id, recznie, teraz=None):
    """Nowa strefa stojaka + ruch. Ta sama strefa → nic (False). Commit robi wolajacy."""
    if stojak.strefa_id == strefa_id:
        return False
    teraz = teraz or teraz_utc()
    db.session.add(RuchStojaka(stojak_id=stojak.id, z_strefy_id=stojak.strefa_id,
                               do_strefy_id=strefa_id, kiedy=teraz, kto_id=kto_id, recznie=recznie))
    stojak.strefa_id = strefa_id
    stojak.zmienil_id, stojak.zmieniono_at = kto_id, teraz
    return True


def pos_w_stocku():
    """Id POS-ow przypisanych do stojakow (takiego POS nie usuwa sie z listy)."""
    return {i for (i,) in db.session.query(StojakDekoracji.pos_id)
            .filter(StojakDekoracji.pos_id.isnot(None)).distinct()}
