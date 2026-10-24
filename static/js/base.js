// Skrypt strony templates/base.html (wyniesiony z szablonu 2026-10-16).
// Dane z bazy (nazwy pracownikow, barcode'y z importu, kraje) wchodza do
// innerHTML w kilku widokach — bez escapowania barcode z CSV-ki moglby
// wstrzyknac znaczniki (XSS stored).
function escapeHtml(value) {
    if (value === null || value === undefined) return '';
    return String(value)
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
}

// Komunikaty flash z serwera (base.html) — np. odmowa dostepu po przekierowaniu.
document.addEventListener('DOMContentLoaded', () => {
    if (typeof KOMUNIKATY_FLASH === 'undefined') return;
    for (const [rodzaj, tekst] of KOMUNIKATY_FLASH) showToast(tekst, rodzaj === 'error' ? 'error' : 'success');
});

function showToast(message, type = 'success') {
    const container = document.getElementById('toastContainer');
    const toast = document.createElement('div');
    const icons = { success: '✅', error: '❌', warning: '⚠️', info: 'ℹ️' };
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `<span>${icons[type] || ''}</span><span>${escapeHtml(message)}</span>`;
    container.appendChild(toast);
    setTimeout(() => toast.remove(), 4000);
}

// Zapis JSON-em. Rzuca Error z komunikatem do pokazania. Wygasla sesja
// konczy sie przekierowaniem na /login (HTML, 200) — bez sprawdzenia
// typu odpowiedzi autozapis uznalby niezapisane dane za zapisane.
async function zapiszJson(url, method, body) {
    let res;
    try {
        res = await fetch(url, {
            method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
    } catch {
        throw new Error('Brak połączenia z serwerem.');
    }
    const json = (res.headers.get('Content-Type') || '').includes('application/json');
    if (res.redirected || !json) {
        throw new Error('Sesja wygasła — zaloguj się ponownie (w nowej karcie), potem „Ponów".');
    }
    const dane = await res.json().catch(() => ({}));
    if (!res.ok) {
        const e = new Error(dane.error || `Błąd zapisu (HTTP ${res.status}).`);
        e.status = res.status;
        e.dane = dane;
        throw e;
    }
    return dane;
}

// ── Autozapis ──
// Ekrany wsadowe (Przydzielanie, Wpis ilości, Forecast, Statystyki
// ogólne) nie maja przycisku „Zapisz" — zapominano o nim i praca
// przepadala. Kazda zmiana idzie od razu pod kluczem (wiersz / zmiana):
// na klucz najwyzej jedno zadanie naraz, a po jego powrocie leci tylko
// NAJNOWSZY oczekujacy stan (inaczej starsze zadanie mogloby wygrac
// wyscig i nadpisac nowsze). Funkcje `wyslij` buduje strona w chwili
// zmiany — z data i zmiana z TEJ chwili, nie z chwili wysylki.
// Status pokazuje element #autoZapisStatus (jesli strona go ma).
const autoZapis = (() => {
    const klucze = new Map();   // klucz -> { wTrakcie, nastepny, blad }
    let ostatniZapis = null;
    const czekajacy = [];
    // Pola, w ktorych ktos pisze, a zapis jeszcze nie ruszyl:
    // pole -> { timer, zapisz }. Liczone jako „niezapisane" — inaczej
    // zamkniecie karty z kursorem w polu gubiloby liczbe bez ostrzezenia
    // (przegladarka nie zglasza wtedy `change`).
    const piszace = new Map();
    const PAUZA_MS = 1200;

    function wpis(k) {
        if (!klucze.has(k)) klucze.set(k, { wTrakcie: false, nastepny: null, blad: null });
        return klucze.get(k);
    }
    function zajety() {
        if (piszace.size) return true;
        for (const w of klucze.values()) if (w.wTrakcie || w.nastepny) return true;
        return false;
    }

    // Pole zapisuje sie po wyjsciu z niego (`change`) ALBO po PAUZA_MS
    // bez pisania — prosba operacji: „zapis od razu po wpisaniu".
    // `zapisz` to funkcja strony, ktora buduje payload i wola zaplanuj().
    // Ta sama wartosc nie idzie drugi raz (pauza, potem Tab).
    function poWpisaniu(pole, zapisz) {
        let wyslane = pole.value;
        const odpal = () => {
            const p = piszace.get(pole);
            if (p) clearTimeout(p.timer);
            piszace.delete(pole);
            if (pole.value === wyslane) { odswiez(); return; }
            wyslane = pole.value;
            zapisz();
        };
        pole.addEventListener('input', () => {
            const p = piszace.get(pole);
            if (p) clearTimeout(p.timer);
            piszace.set(pole, { timer: setTimeout(odpal, PAUZA_MS), odpal });
            odswiez();
        });
        pole.addEventListener('change', odpal);
    }

    // Natychmiast wysyla to, co czeka na pauze (przed przelaczeniem itp.).
    function wypchnijPiszace() {
        [...piszace.values()].forEach(p => p.odpal());
    }
    function bledy() {
        return [...klucze.entries()].filter(([, w]) => w.blad).map(([k, w]) => ({ klucz: k, ...w.blad }));
    }
    function oznacz(pola, blad) {
        (pola || []).forEach(p => p && p.classList.toggle('autozapis-blad', blad));
    }

    function zaplanuj(klucz, wyslij, pola) {
        const w = wpis(klucz);
        const zad = { wyslij, pola };
        if (w.wTrakcie) {
            w.nastepny = zad;
            odswiez();
            return;
        }
        uruchom(klucz, zad);
    }

    async function uruchom(klucz, zad) {
        const w = wpis(klucz);
        w.wTrakcie = true;
        w.blad = null;
        odswiez();
        try {
            await zad.wyslij();
            ostatniZapis = new Date();
            oznacz(zad.pola, false);
        } catch (e) {
            w.blad = { zad, komunikat: e.message || 'Błąd zapisu.', akcja: e.akcja || null };
            oznacz(zad.pola, true);
        }
        w.wTrakcie = false;
        if (w.nastepny) {
            const n = w.nastepny;
            w.nastepny = null;
            // Konflikt (ktos inny zmienil dane): kolejny zapis z tej
            // samej, nieaktualnej wersji tez by przegral — nie wysylaj.
            if (!(w.blad && w.blad.akcja)) {
                uruchom(klucz, n);
                return;
            }
        }
        if (!w.blad) klucze.delete(klucz);
        odswiez();
        if (!zajety()) {
            const ok = bledy().length === 0;
            czekajacy.splice(0).forEach(r => r(ok));
        }
    }

    // Czeka, az wszystko wyjdzie; true = bez bledow.
    function doKonca() {
        wypchnijPiszace();
        if (!zajety()) return Promise.resolve(bledy().length === 0);
        return new Promise(r => czekajacy.push(r));
    }

    // Przed zmiana daty / zmiany / przeladowaniem / eksportem.
    async function przedOpuszczeniem() {
        if (await doKonca()) return true;
        if (!confirm('Część zmian NIE została zapisana (patrz komunikat przy „Zapisano").\n\nKontynuować mimo to? Niezapisane zmiany przepadną.')) {
            return false;
        }
        wyczysc();
        return true;
    }

    function wyczysc() {
        piszace.forEach(p => clearTimeout(p.timer));
        piszace.clear();
        klucze.forEach(w => oznacz(w.blad && w.blad.zad.pola, false));
        klucze.clear();
        odswiez();
    }

    function ponow() {
        for (const [k, w] of klucze.entries()) {
            if (w.blad && !w.blad.akcja && !w.wTrakcie) uruchom(k, w.blad.zad);
        }
    }

    function akcja() {
        const b = bledy().find(x => x.akcja);
        if (!b) return;
        const w = klucze.get(b.klucz);
        oznacz(w.blad.zad.pola, false);
        klucze.delete(b.klucz);
        odswiez();
        b.akcja.fn();
    }

    function odswiez() {
        const el = document.getElementById('autoZapisStatus');
        if (!el) return;
        const lista = bledy();
        el.className = 'autozapis-status';
        if (lista.length) {
            el.classList.add('blad');
            const pierwszy = lista.find(x => x.akcja) || lista[0];
            const ile = lista.length > 1 ? ` (+${lista.length - 1})` : '';
            const przycisk = pierwszy.akcja
                ? `<button type="button" class="btn btn-danger" onclick="autoZapis.akcja()">${escapeHtml(pierwszy.akcja.etykieta)}</button>`
                : `<button type="button" class="btn btn-danger" onclick="autoZapis.ponow()">Ponów</button>`;
            el.innerHTML = `<span>⚠ Nie zapisano: ${escapeHtml(pierwszy.komunikat)}${ile}</span>${przycisk}`;
        } else if (zajety()) {
            el.classList.add('zapisywanie');
            el.textContent = piszace.size && ![...klucze.values()].some(w => w.wTrakcie)
                ? '✎ Zapis za chwilę…' : '⏳ Zapisywanie…';
        } else if (ostatniZapis) {
            el.classList.add('zapisano');
            el.textContent = `✓ Zapisano ${ostatniZapis.toLocaleTimeString('pl')}`;
        } else {
            el.textContent = '💾 Zmiany zapisują się automatycznie';
        }
    }

    window.addEventListener('beforeunload', e => {
        if (zajety() || bledy().length) {
            e.preventDefault();
            e.returnValue = '';
        }
    });
    document.addEventListener('DOMContentLoaded', odswiez);

    return { zaplanuj, poWpisaniu, doKonca, przedOpuszczeniem, wyczysc, ponow, akcja, zajety, bledy };
})();

// ── Modale: klik w tlo nie gubi wpisanych danych ──
// Okna (Dodaj uzytkownika, czynnosc, paczke, zdarzenie…) zamykaly sie
// po kliknieciu obok — po cichu, z utrata wpisanych pol. Okno oznaczone
// `data-modal-guard` zapamietuje stan pol przy otwarciu; klik w tlo przy
// zmienionych polach najpierw pyta. „Anuluj" / ✖ to swiadoma decyzja —
// tych nie ruszamy. Nasluch w fazie capture, wiec dziala przed
// wlasnym handlerem strony.
(() => {
    const stan = el => [...el.querySelectorAll('input, select, textarea')]
        .map(p => (p.type === 'checkbox' || p.type === 'radio') ? p.checked : p.value)
        .join('\u0001');
    const widoczny = el => el.style.display && el.style.display !== 'none';

    document.addEventListener('DOMContentLoaded', () => {
        document.querySelectorAll('[data-modal-guard]').forEach(m => {
            let byl = widoczny(m);
            if (byl) m.dataset.stanPoczatkowy = stan(m);
            new MutationObserver(() => {
                const jest = widoczny(m);
                // Strona wypelnia pola zaraz po otwarciu — zrzut po
                // biezacym zadaniu, zeby edycja nie wygladala na zmiane.
                if (jest && !byl) setTimeout(() => { m.dataset.stanPoczatkowy = stan(m); }, 0);
                byl = jest;
            }).observe(m, { attributes: true, attributeFilter: ['style'] });
        });
    });

    document.addEventListener('click', e => {
        const m = e.target;
        if (!(m instanceof Element) || !m.hasAttribute('data-modal-guard')) return;
        if (m.dataset.stanPoczatkowy === undefined || stan(m) === m.dataset.stanPoczatkowy) return;
        if (!confirm('Wpisane dane nie zostały zapisane.\n\nZamknąć okno i je porzucić?')) {
            e.stopImmediatePropagation();
            e.preventDefault();
        }
    }, true);
})();
