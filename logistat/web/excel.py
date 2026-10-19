"""Wspolne kawalki eksportow do Excela (Statystyki ogolne, Forecast).

Do 2026-10-20 kazdy eksport mial wlasna kopie: zapis skoroszytu do odpowiedzi
i styl naglowkow kolumn (bialy pogrubiony tekst na kolorze, wysrodkowany).
Kolory zostaja w eksportach — kazdy plik ma swoje.
"""
import io

from flask import make_response
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

XLSX_MIME = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
_CIENKA = Side(style='thin', color='555555')
RAMKA = Border(left=_CIENKA, right=_CIENKA, top=_CIENKA, bottom=_CIENKA)


def styl_naglowka(komorka, kolor, rozmiar=None, ramka=False, zawijaj=False):
    """Naglowek kolumny: bialy pogrubiony tekst na tle `kolor` (hex bez #)."""
    komorka.font = Font(bold=True, color='FFFFFF', size=rozmiar)
    komorka.fill = PatternFill('solid', fgColor=kolor)
    komorka.alignment = Alignment(horizontal='center', vertical='center', wrap_text=zawijaj)
    if ramka:
        komorka.border = RAMKA


def odpowiedz_xlsx(skoroszyt, nazwa_pliku):
    """Skoroszyt jako plik do pobrania."""
    bufor = io.BytesIO()
    skoroszyt.save(bufor)
    odpowiedz = make_response(bufor.getvalue())
    odpowiedz.headers['Content-Type'] = XLSX_MIME
    odpowiedz.headers['Content-Disposition'] = f'attachment; filename="{nazwa_pliku}"'
    return odpowiedz
