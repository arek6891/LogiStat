"""Kontrola spojnosci danych LogiStat — tylko odczyt, niczego nie zmienia.

Uruchamiac po kazdym wdrozeniu (krok w docs/DEPLOY.md):

    docker exec -w /app logistat-test python scripts/sprawdz_spojnosc.py

Dwa rodzaje wynikow:
- BLAD — dane sie nie zgadzaja (rozliczenie rozjechane z paczkami, zla flaga ❗,
  paczka zakonczona z otwartym udzialem). To jest bug w kodzie albo reczna
  zmiana w bazie — trzeba wyjasnic. Kod wyjscia 1.
- UWAGA — sprawy dla liderow: paczki wiszace bez konca, niepotwierdzone ❗,
  niezamkniete przerwy. Kod wyjscia 0.

Sprawdza te same niezmienniki, ktore opisuje CLAUDE.md: Amounts = suma
Stückzahl linii, linia 'scan' = suma ilosci z jej paczek, kolumny rozliczenia
paczki = kategorie_z_tabeli(), paczka kilku osob = suma tabel osob.
"""
import os
import sys
from collections import defaultdict
from datetime import timedelta

# Uruchamiany jako plik (python scripts/…): katalog projektu na sciezke PRZED
# importem pakietu.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from logistat.czas import teraz_utc  # noqa: E402

PAKA_WISI_PO = timedelta(hours=12)
STAN_CZASU_WISI_PO = timedelta(hours=14)
STANY_CZASU = ('break', 'other', 'training', 'trainee')
POKAZ = 8


def _kategorie_z_udzialow(L, carton):
    suma = {}
    for u in carton.udzialy:
        for kat, ile in u.get_ilosci().items():
            suma[kat] = suma.get(kat, 0) + ile
    return {k: L.liczba(v) for k, v in suma.items() if v}


def sprawdz(L, teraz=None):
    """→ (bledy, uwagi): listy (opis, przyklady). `L` = modul app."""
    teraz = teraz or teraz_utc()
    bledy, uwagi = [], []

    def dodaj(lista, opis, przyklady):
        if przyklady:
            lista.append((opis, przyklady))

    kartony = L.ImportedCarton.query.all()

    # ── Paczki z tabela ilosci ───────────────────────────────────────────────
    zle_kategorie, zly_zespol, zla_flaga = [], [], []
    for c in kartony:
        tabela = c.get_tabela()
        if not tabela:
            continue
        if c.udzialy:
            tabele = [t for t in (u.get_tabela() for u in c.udzialy) if t]
            if tabele and L.suma_tabel(tabele) != tabela:
                zly_zespol.append(c.barcode)
            oczekiwane = _kategorie_z_udzialow(L, c)
        else:
            oczekiwane = L.kategorie_z_tabeli(tabela)
        if oczekiwane != c.get_scan_categories():
            zle_kategorie.append(c.barcode)
        if c.scan_end_at and bool(c.roznica) != bool(c.powody_roznicy()):
            zla_flaga.append(c.barcode)
    dodaj(bledy, 'kolumny rozliczenia paczki ≠ tabela ilości', zle_kategorie)
    dodaj(bledy, 'tabela paczki kilku osób ≠ suma tabel osób', zly_zespol)
    dodaj(bledy, 'flaga ❗ niezgodna z tabelą', zla_flaga)

    # ── Linie rozliczenia (klucz_linii) ──────────────────────────────────────
    grupy = defaultdict(list)
    for c in kartony:
        grupy[L.klucz_linii(c)].append(c)
    linie = L.GeneralStat.query.all()
    zle_amounts, zle_skany, bez_paczek, reczne_ze_skanami = [], [], [], []
    for s in linie:
        klucz = (s.list_id, s.country_ledger, s.loading_date)
        paczki = grupy.get(klucz, [])
        if not paczki:
            bez_paczek.append(klucz)
        suma = sum(c.stueckzahl or 0 for c in paczki)
        if suma != (s.amounts or 0):
            zle_amounts.append((klucz, s.amounts, suma))
        if (s.category_source or 'manual') == 'scan':
            oczekiwane = L.scan_category_totals(*klucz)
            jest = s.get_category_data()
            if any(L.liczba(oczekiwane[k]['amount'])
                   != L.liczba((jest.get(k) or {}).get('amount', 0)) for k in L.STAT_CATEGORIES):
                zle_skany.append(klucz)
        elif any(c.scan_end_at and c.has_scan_categories() for c in paczki):
            reczne_ze_skanami.append(klucz)
    klucze = {(s.list_id, s.country_ledger, s.loading_date) for s in linie}
    bez_linii = [k for k in grupy if k[0] and k[2] and k not in klucze]
    dodaj(bledy, 'Amounts linii ≠ suma Stückzahl jej paczek', zle_amounts)
    dodaj(bledy, "linia 'scan' ≠ suma ilości z jej paczek", zle_skany)
    dodaj(bledy, 'paczki bez linii rozliczenia', bez_linii)
    dodaj(uwagi, 'linie bez paczek (zostają z amounts=0 po przeniesieniu)', bez_paczek)
    dodaj(uwagi, 'linie z ręcznymi ilościami, a paczki mają skany (⚠ → „użyj skanów”)', reczne_ze_skanami)

    # ── Stany paczek ─────────────────────────────────────────────────────────
    dodaj(bledy, 'paczka zakończona z otwartym udziałem',
          [c.barcode for c in kartony if c.scan_end_at and any(u.end_at is None for u in c.udzialy)])
    dodaj(bledy, 'koniec paczki przed startem',
          [c.barcode for c in kartony if c.scan_end_at and c.scan_start_at
           and c.scan_end_at < c.scan_start_at])
    dodaj(uwagi, f'paczki rozpoczęte i niezakończone ponad {PAKA_WISI_PO} (🔓 Odblokuj albo koniec)',
          [(c.barcode, f'{L.utc_to_local(c.scan_start_at):%d.%m %H:%M}') for c in kartony
           if c.scan_start_at and not c.scan_end_at and teraz - c.scan_start_at > PAKA_WISI_PO])
    dodaj(uwagi, 'paczki z ❗ do potwierdzenia przez lidera',
          [c.barcode for c in kartony if c.roznica_do_potwierdzenia()])

    # ── Czas pracy: stan = liczba startow − liczba koncow ───────────────────
    E = L.WorkerTimeEvent
    licznik, ostatnie = defaultdict(int), {}
    for e in E.query.order_by(E.timestamp, E.id).all():
        rodzaj, _, koncowka = e.event_type.rpartition('_')
        if rodzaj in STANY_CZASU and koncowka in ('start', 'end'):
            klucz = (e.user_id, e.shift_id, rodzaj)
            licznik[klucz] += 1 if koncowka == 'start' else -1
            ostatnie[klucz] = e.timestamp
    dodaj(bledy, 'więcej końców niż startów (przerwa / Inne / szkolenie)',
          [k for k, v in licznik.items() if v < 0])
    dodaj(uwagi, f'niezamknięte przerwy / Inne / szkolenia starsze niż {STAN_CZASU_WISI_PO}',
          [(k, f'{L.utc_to_local(ostatnie[k]):%d.%m %H:%M}') for k, v in licznik.items()
           if v > 0 and teraz - ostatnie[k] > STAN_CZASU_WISI_PO])

    # ── Konta ────────────────────────────────────────────────────────────────
    duplikaty = L.db.session.execute(L.db.text(
        'SELECT barcode_id FROM "user" WHERE barcode_id IS NOT NULL '
        'GROUP BY barcode_id HAVING COUNT(*) > 1')).scalars().all()
    dodaj(bledy, 'zduplikowany kod pracownika', list(duplikaty))
    return bledy, uwagi


def main():
    import app as L
    with L.app.app_context():
        bledy, uwagi = sprawdz(L)
        print(f'Paczek: {L.ImportedCarton.query.count()}, linii rozliczenia: '
              f'{L.GeneralStat.query.count()}')
        for naglowek, lista in (('BLAD', bledy), ('UWAGA', uwagi)):
            for opis, przyklady in lista:
                print(f'{naglowek}: {opis} — {len(przyklady)}: {przyklady[:POKAZ]}')
        print('Spójność: ' + ('BŁĘDY — do wyjaśnienia.' if bledy else 'OK.'))
        return 1 if bledy else 0


if __name__ == '__main__':
    # Bez init_db(): sam import app robi create_all, migracje i seed — skrypt
    # „tylko do odczytu" nie moze ruszac schematu produkcji. Tylko tutaj, nie
    # w main(): w procesie testow zmienna przeciekalaby do podprocesow.
    os.environ.setdefault('LOGISTAT_BEZ_INIT', '1')
    sys.exit(main())
