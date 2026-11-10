"""Wiersze Zadan dodatkowych do zrzutow instrukcji (po dane_demo.py)."""
import os
import sys

# Konta ze znanymi haslami demo — tylko do bazy demo, nigdy .31 / .30.
if not os.environ.get('DATABASE_URL', '').endswith('/logistat_demo'):
    sys.exit('Tylko baza logistat_demo (DATABASE_URL) — przerwano.')
from datetime import timedelta
sys.path.insert(0, '/app')
from app import app
from logistat.czas import local_day_bounds, local_today
from logistat.extensions import db
from logistat.models import User, get_or_create_shift
from logistat.models.zadania import ZadanieDodatkowe, CzynnoscDodatkowa
with app.app_context():
    s = get_or_create_shift(local_today(), 1)
    rano = local_day_bounds(local_today())[0]
    lider = User.query.filter_by(username='lider').one()
    cz = {c.nazwa: c for c in CzynnoscDodatkowa.query.all()}
    for user, dzial, g1, g2, c, kom in (('op10', 'magazyn', 7, 9.5, '5S', 'Regały strefa B'),
                                       ('op10', 'dekoracje', 10, 13, None, 'Pomoc przy hakowaniu'),
                                       ('op4', 'zwroty', 12, 13.5, 'Sprzątanie', None)):
        u = User.query.filter_by(username=user).one()
        db.session.add(ZadanieDodatkowe(shift_id=s.id, user_id=u.id, dzial=dzial,
            od=rano + timedelta(hours=g1), do=rano + timedelta(hours=g2),
            czynnosc_id=cz[c].id if c else None, komentarz=kom, wpisal_id=lider.id))
    db.session.commit()
    print('ok')
