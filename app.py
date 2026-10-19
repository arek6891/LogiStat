"""Punkt wejscia LogiStat: `gunicorn app:app` (Dockerfile) i `python app.py` (dev).

Cala aplikacja jest w pakiecie `logistat/` (uklad: logistat/__init__.py). Tu tylko:
1. aplikacja z `create_app()` — konfiguracja, obsluga bledow, blueprinty;
2. `init_db()` przy imporcie — schemat, migracje, seed pod advisory lockiem
   (kazdy worker gunicorna importuje ten plik); `LOGISTAT_BEZ_INIT=1` pomija
   (narzedzia tylko do odczytu, scripts/sprawdz_spojnosc.py).
Nowy kod nigdy tutaj — testy importuja z pakietu (`from logistat.models import …`).
"""
import os

from logistat import create_app
from logistat.baza import init_db

app = create_app()

if os.environ.get('LOGISTAT_BEZ_INIT') != '1':
    with app.app_context():
        init_db()

if __name__ == '__main__':
    # Debugger Werkzeuga pozwala wykonac dowolny kod, wiec domyslnie sluchamy
    # tylko na loopbacku. Dostep z LAN-u w dev: HOST=0.0.0.0 python app.py
    # (produkcja i tak chodzi na gunicornie z Dockerfile, nie tedy).
    app.run(
        debug=os.environ.get('FLASK_DEBUG', '1') == '1',
        host=os.environ.get('HOST', '127.0.0.1'),
        port=int(os.environ.get('PORT', 5001)),
    )
