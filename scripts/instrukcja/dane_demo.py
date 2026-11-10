"""Fikcyjne dane do zrzutow ekranu instrukcji (baza logistat_demo)."""
import random
import os
import sys

# Konta ze znanymi haslami demo — tylko do bazy demo, nigdy .31 / .30.
if not os.environ.get('DATABASE_URL', '').endswith('/logistat_demo'):
    sys.exit('Tylko baza logistat_demo (DATABASE_URL) — przerwano.')
import uuid
from datetime import timedelta

sys.path.insert(0, '/app')
from app import app  # noqa: E402
from logistat.czas import local_day_bounds, local_today, teraz_utc  # noqa: E402
from logistat.extensions import db  # noqa: E402
from logistat.import_paczek import importuj_wiersze  # noqa: E402
from logistat.models import (  # noqa: E402
    Activity, ActivityAssignment, CountryMapping, ImportedCarton, ShiftAttendance,
    SzkolenieCzynnosci, User, WorkerTimeEvent, get_or_create_shift)
from logistat.models.dekoracje import (  # noqa: E402
    AkcjaDekoracji, EtapAkcji, IndexDekoracji, PosDekoracji, SlownikDekoracji)
from logistat.models.zwroty import PrzydzialZwrotow, ZwrotPaczki  # noqa: E402
from logistat.paczki import odswiez_roznice  # noqa: E402
from logistat.rozliczenie import klucz_linii, recompute_general_stat  # noqa: E402
from logistat.tabela_ilosci import kategorie_z_tabeli  # noqa: E402

random.seed(7)
IMIONA = ['Anna Kowalska', 'Piotr Nowak', 'Maria Wiśniewska', 'Tomasz Wójcik',
          'Katarzyna Kamińska', 'Marek Lewandowski', 'Ewa Zielińska', 'Jan Szymański',
          'Agnieszka Woźniak', 'Paweł Dąbrowski']

with app.app_context():
    admin = User.query.filter_by(username='admin').one()
    admin.display_name = 'Admin Demo'
    lider = User(username='lider', display_name='Lider Demo', role='leader')
    lider.set_password('DemoLider2026')
    st1 = User(username='stanowisko1', display_name='Stanowisko 1', role='stanowisko')
    st1.set_password('DemoSt2026')
    st2 = User(username='stanowisko2', display_name='Stanowisko 2', role='stanowisko')
    st2.set_password('DemoSt2026')
    db.session.add_all([lider, st1, st2])
    ops = []
    for i, n in enumerate(IMIONA, 1):
        u = User(username=f'op{i}', display_name=n, role='operator', barcode_id=f'P{i:04d}')
        if i in (1, 5):
            u.is_trainer = True
        ops.append(u)
    db.session.add_all(ops)
    db.session.commit()
    akt = {a.name: a for a in Activity.query.all()}
    for u in ops:
        for a in akt.values():
            if not (u.display_name == 'Jan Szymański' and a.name == 'Zwroty'):
                db.session.add(SzkolenieCzynnosci(user_id=u.id, activity_id=a.id))
    db.session.commit()

    land = CountryMapping.query.first().innenauftrag
    dzis = local_today()
    pp = ops[:7]
    for d in range(14, -1, -1):
        dzien = dzis - timedelta(days=d)
        if dzien.weekday() >= 5:
            continue
        rows = [{'barcode': f'{dzien:%m%d}{n:05d}', 'land': land,
                 'stueckzahl': random.choice([40, 60, 80, 120, 150]),
                 'kategorie': 'K', 'ziel_datum': None, 'uebergabe_nr': f'UB-{dzien:%m%d}'}
                for n in range(60)]
        importuj_wiersze(rows, dzien, lider.id)
        start_dnia = local_day_bounds(dzien)[0] + timedelta(hours=6)
        kartony = ImportedCarton.query.filter_by(data_pliku=dzien).order_by(ImportedCarton.id).all()
        do_zrobienia = kartony if d else kartony[:34]
        zegar = {u.id: start_dnia + timedelta(minutes=random.randint(0, 20)) for u in pp}
        for i, c in enumerate(do_zrobienia):
            u = pp[i % len(pp)]
            tempo = {0: 1.15, 1: 1.0, 2: 0.8, 3: 1.05, 4: 0.95, 5: 1.25, 6: 0.9}[i % len(pp)]
            minut = c.stueckzahl / (300 * tempo) * 60
            c.scan_start_at, c.scan_start_by = zegar[u.id], u.id
            c.scan_end_at, c.scan_end_by = zegar[u.id] + timedelta(minutes=minut), u.id
            zegar[u.id] = c.scan_end_at + timedelta(minutes=2)
            if d == 0 and c.scan_end_at > start_dnia + timedelta(hours=7, minutes=30):
                c.scan_start_at = c.scan_start_by = c.scan_end_at = c.scan_end_by = None
                continue
            reszta = c.stueckzahl - (5 if i % 9 == 0 else 0)
            tab = {'wersja': 2, 'grupy': {
                'bizuteria': {'ilosc': reszta - 12 + (0 if i % 9 == 0 else 1), 'uszkodzone': 1 if i % 9 == 0 else 0,
                              'niesprocesowane': 0},
                'akcesoria': {'ilosc': 6, 'uszkodzone': 0, 'niesprocesowane': 0},
                'okulary': {'ilosc': 4, 'uszkodzone': 0, 'niesprocesowane': 0},
                'tekstylia': {'ilosc': 1, 'uszkodzone': 0, 'niesprocesowane': 0}},
                'karty': 0, 'podwojnie': 0, 'potrojnie': 0}
            c.set_tabela(tab)
            c.set_scan_categories(kategorie_z_tabeli(tab))
            odswiez_roznice(c)
        db.session.commit()
        recompute_general_stat(*klucz_linii(kartony[0]), from_scan=True)
        db.session.commit()

    # Dzis: obecnosc, przydzial, czas pracy (przerwa w trakcie szkolenia)
    shift = get_or_create_shift(dzis, 1)
    rano = local_day_bounds(dzis)[0] + timedelta(hours=6)
    for i, u in enumerate(ops):
        db.session.add(ShiftAttendance(shift_id=shift.id, user_id=u.id,
                                       scanned_at=rano - timedelta(minutes=10 - i)))
    for u in ops[:7]:
        db.session.add(ActivityAssignment(shift_id=shift.id, user_id=u.id,
                                          activity_id=akt['Post Processing'].id, assigned_by=lider.id))
    for u in ops[7:9]:
        db.session.add(ActivityAssignment(shift_id=shift.id, user_id=u.id,
                                          activity_id=akt['Zwroty'].id, assigned_by=lider.id))
    db.session.add(ActivityAssignment(shift_id=shift.id, user_id=ops[9].id,
                                      activity_id=akt['Orders'].id, assigned_by=lider.id))
    h = lambda g, m=0: rano + timedelta(hours=g - 6, minutes=m)  # noqa: E731
    ev = [(ops[0], 'break_start', h(9)), (ops[0], 'break_end', h(9, 15)),
          (ops[1], 'break_start', h(9, 5)), (ops[1], 'break_end', h(9, 25)),
          (ops[2], 'other_start', h(8, 10)), (ops[2], 'other_end', h(8, 40)),
          (ops[4], 'training_start', h(7)), (ops[6], 'trainee_start', h(7)),
          (ops[4], 'break_start', h(10)), (ops[6], 'break_start', h(10)),
          (ops[4], 'break_end', h(10, 20)), (ops[6], 'break_end', h(10, 20))]
    for k in (0, 1, 2, 3, 5, 9):
        ev.append((ops[k], 'work_end', h(14, 2 + k)))
    for u, typ, ts in ev:
        db.session.add(WorkerTimeEvent(user_id=u.id, shift_id=shift.id, event_type=typ,
                                       timestamp=ts, is_manual=False,
                                       training_lead_id=ops[4].id if typ.startswith('trainee') else None))

    # Zwroty: przydzial do stanowisk + przyjete paczki
    db.session.add(PrzydzialZwrotow(shift_id=shift.id, user_id=ops[7].id, stanowisko_id=st1.id,
                                    od=h(6, 5), przydzielil_id=lider.id))
    db.session.add(PrzydzialZwrotow(shift_id=shift.id, user_id=ops[8].id, stanowisko_id=st2.id,
                                    od=h(6, 5), przydzielil_id=lider.id))
    for n in range(24):
        db.session.add(ZwrotPaczki(
            paketnummer=f'00340434{random.randint(10**9, 10**10 - 1)}',
            brand=random.choice(['ACC', 'SIX', 'NK', 'ITS']), pos_nummer=f'PL{random.randint(1000, 9999)}',
            kurier=random.choice(['DPD', 'UPS', 'DPD']), retoure=random.randint(1, 4),
            defekt=random.choice([0, 0, 1]), verpackungsvorschrift=random.choice(['Yes', 'VKM']),
            przyjeto_at=h(6, 15) + timedelta(minutes=8 * n), przyjal_id=(st1 if n % 2 else st2).id,
            token=uuid.uuid4().hex))

    # Dekoracje: dwie akcje z indexami i kamieniami milowymi
    twin = SlownikDekoracji.query.filter_by(nazwa='Twin').one()
    gond = SlownikDekoracji.query.filter_by(nazwa='Gondola').one()
    for nazwa, od, do, typ in (('Christmas 2026', dzis - timedelta(days=10), dzis + timedelta(days=25), 'kontener'),
                               ('Valentine 2027', dzis + timedelta(days=5), dzis + timedelta(days=60), 'beeline')):
        a = AkcjaDekoracji(nazwa=nazwa, data_od=od, data_do=do, typ_dostawy=typ, utworzyl_id=lider.id)
        db.session.add(a)
        db.session.flush()
        for k in range(1, 3):
            db.session.add(IndexDekoracji(akcja_id=a.id, nazwa=f'Index {k}', kolejnosc=k,
                                          ilosc_stojakow=40 * k, typ_id=twin.id, model_id=gond.id,
                                          haki_na_stojak=24, strony_na_stojak=2, rgd=1200 * k,
                                          displays=40 * k, akcesoria=300, pos=40 * k,
                                          prod_hakowania=180.0, prod_dekorowania=90.0))
        dl = (do - od).days
        for j, etap in enumerate(('komponenty', 'produkty', 'opakowania', 'assembly',
                                  'hakowanie', 'dekoracje', 'pakowanie', 'wysylka')):
            s = od + timedelta(days=dl * j // 9)
            db.session.add(EtapAkcji(akcja_id=a.id, etap=etap, data_od=s,
                                     data_do=s + timedelta(days=max(dl // 8, 1))))
    from logistat.models import HistoriaCelu, POCZATEK_HISTORII_CELU, set_setting
    set_setting('target_szt_h', 320)
    db.session.merge(HistoriaCelu(dzien=POCZATEK_HISTORII_CELU, wartosc=320))
    for k in range(1, 9):
        db.session.add(PosDekoracji(numer=f'PL{1000 + k}', post_processing=k % 2 == 0,
                                    import_at=teraz_utc()))
    db.session.commit()
    print('OK', ImportedCarton.query.count())
