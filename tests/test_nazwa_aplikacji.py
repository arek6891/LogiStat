"""Nazwa na ekranach „SARA” (wielkie litery od 2026-10-26) i stopka z autorami (operacja 2026-10-24)."""
import pathlib

from conftest import login, make_user

AUTORZY = 'Arkadiusz Sobczyk i Adam Reliszka'


def test_logowanie_ma_nazwe_i_autorow(client):
    html = client.get('/login').get_data(as_text=True)

    assert '<h1>SARA</h1>' in html and 'SARA — Login' in html
    assert AUTORZY in html and 'LogiStat' not in html


def test_kafelki_maja_autorow_a_menu_nazwe(client):
    u = make_user('leader')
    login(client, u.username)

    html = client.get('/start').get_data(as_text=True)
    assert AUTORZY in html and '<h1>SARA</h1>' in html

    html = client.get('/dashboard').get_data(as_text=True)
    assert '<h1>SARA</h1>' in html and 'LogiStat' not in html


def test_zadnego_logistat_na_ekranach():
    szablony = list(pathlib.Path(__file__).resolve().parent.parent.joinpath('templates').glob('*.html'))
    assert len(szablony) > 10
    for plik in szablony:
        assert 'LogiStat' not in plik.read_text(encoding='utf-8'), plik.name
