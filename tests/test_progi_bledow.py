"""Progi filtra bledow na „Czasy pracownikow" — konfigurowalne przez admina.

Same flagi licza sie w przegladarce na danych z `/api/worker-times`, wiec tu
pilnujemy kontraktu: ustawienia zapisuja sie, maja sensowne domyslne wartosci
i trafiaja do szablonu jako stale JS.
"""
import app as logistat


def test_domyslne_progi(flask_app):
    assert logistat.get_setting_int('max_work_minutes', 0) == 660     # 11 h
    assert logistat.get_setting_int('min_break_minutes', 0) == 15


def test_admin_zapisuje_progi(admin_client):
    r = admin_client.put('/api/settings', json={
        'max_work_minutes': 600,
        'min_break_minutes': 20,
    })

    assert r.status_code == 200
    assert r.get_json()['max_work_minutes'] == 600
    assert logistat.get_setting_int('min_break_minutes', 0) == 20


def test_prog_musi_byc_dodatni(admin_client):
    r = admin_client.put('/api/settings', json={'max_work_minutes': 0})

    assert r.status_code == 400
    assert logistat.get_setting_int('max_work_minutes', 0) == 660, 'nic nie zapisujemy'


def test_prog_musi_byc_liczba(admin_client):
    r = admin_client.put('/api/settings', json={'min_break_minutes': 'dużo'})

    assert r.status_code == 400


def test_lider_nie_zmieni_progow(leader_client):
    r = leader_client.put('/api/settings', json={'max_work_minutes': 100})

    assert r.status_code in (302, 401, 403)


def test_progi_trafiaja_na_ekran_czasow(admin_client):
    admin_client.put('/api/settings', json={'max_work_minutes': 540, 'min_break_minutes': 25})

    html = admin_client.get('/worker-times').get_data(as_text=True)

    assert 'MAX_WORK_MINUTES  = 540' in html
    assert 'MIN_BREAK_MINUTES = 25' in html


def test_stary_prog_przerwy_dalej_dziala(admin_client):
    """Regresja: nowe pola nie mogly wysadzic istniejacego ustawienia."""
    r = admin_client.put('/api/settings', json={'break_threshold_minutes': 45})

    assert r.status_code == 200
    assert logistat.get_setting_int('break_threshold_minutes', 0) == 45
