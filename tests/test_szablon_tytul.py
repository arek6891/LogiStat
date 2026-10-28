"""Blok `title` to sam tekst w jednej linii.

2026-10-28: w `zwroty_paczek.html` brakowalo `{% endblock %}` po tytule, wiec
okno „✎ Popraw zwrot” wyladowalo w `<title>` — przegladarka traktuje to jako
tekst, okna nie bylo w DOM, a JS strony padal (poprawka i usuniecie zwrotu nie
dzialaly). Testy szukajace napisow w HTML tego nie widzialy.
"""
import re
from pathlib import Path

import pytest

SZABLONY = sorted((Path(__file__).resolve().parent.parent / 'templates').glob('*.html'))
BLOK_TYTULU = re.compile(r'{%-?\s*block title\s*-?%}(.*?){%-?\s*endblock', re.S)


@pytest.mark.parametrize('sciezka', SZABLONY, ids=lambda p: p.name)
def test_tytul_bez_znacznikow_html(sciezka):
    for tytul in BLOK_TYTULU.findall(sciezka.read_text(encoding='utf-8')):
        assert '<' not in tytul and '\n' not in tytul.strip(), f'{sciezka.name}: {tytul[:80]!r}'


def test_okno_poprawki_zwrotu_jest_w_tresci_strony(leader_client):
    html = leader_client.get('/zwroty/paczki').get_data(as_text=True)
    tytul = html[html.index('<title>'):html.index('</title>')]
    assert 'zwrotModal' not in tytul
    assert html.index('id="zwrotModal"') > html.index('</title>')
