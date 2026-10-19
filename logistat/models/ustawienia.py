"""Ustawienia aplikacji (AppSetting) z wartosciami domyslnymi."""
from logistat.extensions import db


class AppSetting(db.Model):
    """Generic key/value store for app-wide configurable settings."""
    key = db.Column(db.String(100), primary_key=True)
    value = db.Column(db.String(500), nullable=True)


# Defaults for known settings (used when a key is not yet stored)
SETTING_DEFAULTS = {
    'break_threshold_minutes': '30',
    # Progi dla filtra bledow na ekranie „Czasy pracownikow"
    'max_work_minutes': '660',      # 11 h
    'min_break_minutes': '15',
    # Progi przegladu ogolnego na ekranie „Normy" (/stats). Odniesieniem jest
    # SREDNIA zespolu z wybranego okresu (wszystkie sztuki / wszystkie godziny),
    # nie zadana z gory norma — takiej w systemie nie ma i nikt jej nie ustawia.
    # Procenty ponizej to odchylenie od tej sredniej; `min_packages_rank` chroni
    # RANKING przed osoba z jedna paczka, ktora wyladowalaby na szczycie albo
    # dnie na czystym szumie (do samej sredniej wchodza wszyscy).
    'norm_good_pct': '110',
    'norm_weak_pct': '90',
    'min_packages_rank': '3',
    # Docelowa wydajnosc (szt./h) wpisana przez lidera. 0 = NIE USTAWIONO —
    # wtedy kolumna celu w ogole sie nie pokazuje i nic sie przez nia nie dzieli.
    'target_szt_h': '0',
}


def get_setting(key, default=None):
    """Return a stored setting value, else its known default, else `default`."""
    row = db.session.get(AppSetting, key)
    if row is not None and row.value is not None:
        return row.value
    return SETTING_DEFAULTS.get(key, default)


def get_setting_int(key, default=0):
    try:
        return int(get_setting(key, default))
    except (TypeError, ValueError):
        return default


def set_setting(key, value):
    row = db.session.get(AppSetting, key)
    if row is None:
        row = AppSetting(key=key, value=str(value))
        db.session.add(row)
    else:
        row.value = str(value)


# ══════════════════════════════════════════════════════════════════════════════
#  AUTH HELPERS
# ══════════════════════════════════════════════════════════════════════════════
