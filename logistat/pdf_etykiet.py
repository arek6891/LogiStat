"""Arkusz A4 z etykietami POS (kod Code 128 + numer pod spodem) jako PDF —
czysta logika, bez bibliotek (Dekoracje, 2026-10-28).

Przegladarka otwiera PDF w nowej karcie, drukuje sie z jej podgladu. Siatka =
typowy arkusz naklejek 3 × 8 (70 × 37 mm); inny format → zmienic stale ponizej.
Kreski to wektorowe prostokaty (ostre w kazdej skali), tekst Courier-Bold —
czcionka wbudowana w kazdy czytnik PDF, stala szerokosc znaku pozwala go
wysrodkowac bez tablic szerokosci. Numery POS sa ASCII (`pos_nummer()`).
"""
from logistat.kod128 import moduly

MM = 72 / 25.4
STRONA = (210 * MM, 297 * MM)
KOLUMNY, WIERSZE = 3, 8
ETYKIETA = (70 * MM, 37 * MM)
MARGINES = (0 * MM, 0.5 * MM)          # lewy, gorny — reszta arkusza
WCIECIE = 3 * MM                       # odstep tresci od krawedzi etykiety
WYSOKOSC_KRESEK = 18 * MM
MODUL_MAX = 0.5 * MM
MODUL_MIN = 0.25 * MM                  # cienszych kresek czytnik moze nie odczytac
TEKST_MAX = 13
SZEROKOSC_ZNAKU = 0.6                  # Courier: 600/1000 em
NA_STRONIE = KOLUMNY * WIERSZE


def modul(numer):
    """Szerokosc modulu (pt), zeby kod zmiescil sie w etykiecie; None = za dlugi."""
    m = min(MODUL_MAX, (ETYKIETA[0] - 2 * WCIECIE) / len(moduly(numer)))
    return m if m >= MODUL_MIN else None


def miesci_sie(numer):
    return modul(numer) is not None


def _tekst_pdf(s):
    return s.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')


def _etykieta(numer, x, y):
    """Polecenia PDF jednej etykiety; (x, y) = lewy dolny rog."""
    m = modul(numer)
    if m is None:
        raise ValueError(f'Numer {numer} jest za długi na etykietę.')
    kod = moduly(numer)
    x0 = x + (ETYKIETA[0] - len(kod) * m) / 2
    rozmiar = min(TEKST_MAX, (ETYKIETA[0] - 2 * WCIECIE) / (SZEROKOSC_ZNAKU * len(numer)))
    y_kresek = y + WCIECIE + rozmiar + 1.5 * MM
    wysokosc = min(WYSOKOSC_KRESEK, ETYKIETA[1] - 2 * WCIECIE - rozmiar - 1.5 * MM)
    polecenia = []
    i = 0
    while i < len(kod):
        if kod[i] == '1':
            j = i
            while j < len(kod) and kod[j] == '1':
                j += 1
            polecenia.append(f'{x0 + i * m:.3f} {y_kresek:.3f} {(j - i) * m:.3f} {wysokosc:.3f} re')
            i = j
        else:
            i += 1
    polecenia.append('f')
    x_tekstu = x + (ETYKIETA[0] - SZEROKOSC_ZNAKU * rozmiar * len(numer)) / 2
    polecenia.append(f'BT /F1 {rozmiar:.2f} Tf {x_tekstu:.3f} {y + WCIECIE:.3f} Td ({_tekst_pdf(numer)}) Tj ET')
    return polecenia


def _strona(numery):
    polecenia = ['0 g']
    for n, numer in enumerate(numery):
        kol, wiersz = n % KOLUMNY, n // KOLUMNY
        x = MARGINES[0] + kol * ETYKIETA[0]
        y = STRONA[1] - MARGINES[1] - (wiersz + 1) * ETYKIETA[1]
        polecenia += _etykieta(numer, x, y)
    return '\n'.join(polecenia).encode('ascii')


def pdf_etykiet(numery):
    """PDF (bytes) z etykietami w podanej kolejnosci, po NA_STRONIE na arkusz.
    Pusta lista → ValueError (wolajacy mowi uzytkownikowi, ze nie ma czego drukowac)."""
    if not numery:
        raise ValueError('Brak etykiet do druku.')
    strony = [numery[i:i + NA_STRONIE] for i in range(0, len(numery), NA_STRONIE)]
    # 1 katalog, 2 drzewo stron, 3 czcionka, potem para (strona, tresc) na arkusz.
    obiekty = [b'<< /Type /Catalog /Pages 2 0 R >>', None,
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Courier-Bold >>']
    kids = []
    for strona in strony:
        tresc = _strona(strona)
        nr_strony = len(obiekty) + 1
        kids.append(f'{nr_strony} 0 R')
        obiekty.append((f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {STRONA[0]:.2f} {STRONA[1]:.2f}] '
                        f'/Resources << /Font << /F1 3 0 R >> >> /Contents {nr_strony + 1} 0 R >>').encode())
        obiekty.append(f'<< /Length {len(tresc)} >>\nstream\n'.encode() + tresc + b'\nendstream')
    obiekty[1] = f'<< /Type /Pages /Kids [{" ".join(kids)}] /Count {len(kids)} >>'.encode()

    wynik = bytearray(b'%PDF-1.4\n')
    przesuniecia = []
    for nr, obiekt in enumerate(obiekty, start=1):
        przesuniecia.append(len(wynik))
        wynik += f'{nr} 0 obj\n'.encode() + obiekt + b'\nendobj\n'
    xref = len(wynik)
    wynik += f'xref\n0 {len(obiekty) + 1}\n0000000000 65535 f \n'.encode()
    for p in przesuniecia:
        wynik += f'{p:010d} 00000 n \n'.encode()
    wynik += f'trailer\n<< /Size {len(obiekty) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode()
    return bytes(wynik)
