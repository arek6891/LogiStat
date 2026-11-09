"""Wspolne kawalki eksportow do Excela (Statystyki ogolne, Forecast).

Do 2026-10-20 kazdy eksport mial wlasna kopie: zapis skoroszytu do odpowiedzi
i styl naglowkow kolumn (bialy pogrubiony tekst na kolorze, wysrodkowany).
Kolory zostaja w eksportach — kazdy plik ma swoje.

Formuly (przeglad bezpieczenstwa 2026-11-09): openpyxl zapisuje KAZDY tekst
zaczynajacy sie od „=” jako formule, takze z formatem „@”. Paketnummer czy
numer artykulu wpisany na stanowisku jako `=HYPERLINK("http://…")` bylby w
pliku lidera zywym linkiem. Dlatego `odpowiedz_xlsx()` zamienia na zwykly
tekst kazda formule, ktorej eksport nie wpisal przez `formula()`.
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


def formula(arkusz, wiersz, kolumna, tekst):
    """Komorka z formula napisana przez serwer (`=SUM(…)`, `=E11*C11`) — tylko
    tak wpisana zostaje formula w pobranym pliku."""
    komorka = arkusz.cell(wiersz, kolumna, tekst)
    _formuly(arkusz.parent).add((id(arkusz), komorka.coordinate))
    return komorka


def _formuly(skoroszyt):
    if not hasattr(skoroszyt, '_logistat_formuly'):
        skoroszyt._logistat_formuly = set()
    return skoroszyt._logistat_formuly


def bez_obcych_formul(skoroszyt):
    """Kazda formula spoza `formula()` → tekst (wartosc bez zmian, Excel jej nie liczy)."""
    dozwolone = _formuly(skoroszyt)
    for arkusz in skoroszyt.worksheets:
        for wiersz in arkusz.iter_rows():
            for komorka in wiersz:
                if komorka.data_type == 'f' and (id(arkusz), komorka.coordinate) not in dozwolone:
                    komorka.data_type = 's'


def odpowiedz_xlsx(skoroszyt, nazwa_pliku):
    """Skoroszyt jako plik do pobrania (bez formul z danych — patrz wyzej)."""
    bez_obcych_formul(skoroszyt)
    bufor = io.BytesIO()
    skoroszyt.save(bufor)
    odpowiedz = make_response(bufor.getvalue())
    odpowiedz.headers['Content-Type'] = XLSX_MIME
    odpowiedz.headers['Content-Disposition'] = f'attachment; filename="{nazwa_pliku}"'
    return odpowiedz
