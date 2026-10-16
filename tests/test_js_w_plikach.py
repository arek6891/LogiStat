"""JavaScript stron mieszka w static/js/, nie w szablonach (2026-10-16).

W szablonie zostaje najwyzej maly blok danych z serwera
(`const X = {{ x|tojson }};`). Logika w szablonie omijala CI (`node --check`)
i skan XSS w tests/test_xss.py — ten test pilnuje, zeby nie wrocila.
"""
import glob
import os
import re

import pytest

KATALOG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SZABLONY = sorted(glob.glob(os.path.join(KATALOG, 'templates', '*.html')))
INLINE = re.compile(r'<script(?![^>]*\b(?:src|type)=)[^>]*>(.*?)</script>', re.S)
LINIA_DANYCH = re.compile(r'^\s*const [A-Za-z_]\w* = .*;\s*$')


@pytest.mark.parametrize('sciezka', SZABLONY, ids=lambda p: os.path.basename(p))
def test_w_szablonie_tylko_dane_dla_skryptu(sciezka):
    tresc = open(sciezka, encoding='utf-8').read()
    for blok in INLINE.findall(tresc):
        linie = [l for l in blok.split('\n') if l.strip()]
        logika = [l.strip() for l in linie if not LINIA_DANYCH.match(l)]
        assert not logika, (
            f'{os.path.basename(sciezka)}: logika JS w szablonie {logika[:3]} — '
            'przenies do static/js/<strona>.js, w szablonie zostaw tylko const z danymi.')


def test_kazdy_podpiety_skrypt_istnieje():
    for sciezka in SZABLONY:
        for plik in re.findall(r"static_v\('(js/[^']+)'\)", open(sciezka, encoding='utf-8').read()):
            assert os.path.isfile(os.path.join(KATALOG, 'static', plik)), (sciezka, plik)
