// Wykres Gantta akcji Dekoracji (templates/displays.html, 2026-10-28).
// Dane z serwera (GANTT): akcje niezakonczone i „dzis” (dzien lokalny serwera,
// nie przegladarki). Szerokosci w procentach — wykres miesci sie w karcie.
// Koniec akcji wlacznie (pasek do konca dnia „do”).

const MIESIACE = ['sty', 'lut', 'mar', 'kwi', 'maj', 'cze', 'lip', 'sie', 'wrz', 'paź', 'lis', 'gru'];
const DZIEN_MS = 86400000;

function dzien(iso) {               // 'YYYY-MM-DD' → numer dnia (UTC, bez stref)
    const [r, m, d] = iso.split('-').map(Number);
    return Date.UTC(r, m - 1, d) / DZIEN_MS;
}
function data(nr) { return new Date(nr * DZIEN_MS); }
function krotko(iso) { return `${iso.slice(8, 10)}.${iso.slice(5, 7)}`; }

function el(tag, klasa, tekst) {
    const e = document.createElement(tag);
    if (klasa) e.className = klasa;
    if (tekst !== undefined) e.textContent = tekst;
    return e;
}

function rysujGantt() {
    const box = document.getElementById('gantt');
    box.replaceChildren();
    const akcje = GANTT.akcje;
    if (!akcje.length) {
        box.append(el('div', 'empty-state', 'Brak akcji w toku. Dodaj nową przyciskiem „➕ Nowa akcja”.'));
        return;
    }
    const dzis = dzien(GANTT.dzis);
    const start = Math.min(dzis, ...akcje.map(a => dzien(a.od))) - 3;
    const koniec = Math.max(dzis + 1, ...akcje.map(a => dzien(a.do) + 1)) + 3;   // wylacznie
    const dni = koniec - start;
    const proc = nr => `${((nr - start) / dni) * 100}%`;
    const szer = n => `${(n / dni) * 100}%`;

    // Os: miesiace i poniedzialki (cienkie linie z numerem dnia).
    const os = el('div', 'gantt-wiersz gantt-os');
    os.append(el('div', 'gantt-nazwa', 'Akcja'));
    const skala = el('div', 'gantt-tor');
    for (let nr = start; nr < koniec;) {
        const d = data(nr);
        const nast = Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1) / DZIEN_MS;
        const do_ = Math.min(nast, koniec);
        const m = el('div', 'gantt-miesiac', `${MIESIACE[d.getUTCMonth()]} ${d.getUTCFullYear()}`);
        m.style.left = proc(nr);
        m.style.width = szer(do_ - nr);
        skala.append(m);
        nr = do_;
    }
    const tygodnie = [];
    for (let nr = start; nr < koniec; nr++) {
        if (data(nr).getUTCDay() === 1) tygodnie.push(nr);
    }
    tygodnie.forEach(nr => {
        const t = el('div', 'gantt-tydzien', String(data(nr).getUTCDate()));
        t.style.left = proc(nr);
        skala.append(t);
    });
    os.append(skala);
    box.append(os);

    akcje.forEach(a => {
        const w = el('div', 'gantt-wiersz');
        const nazwa = el('a', 'gantt-nazwa', a.nazwa);
        nazwa.href = `/displays/akcje/${a.id}`;
        nazwa.title = a.nazwa;
        w.append(nazwa);
        const tor = el('div', 'gantt-tor');
        tygodnie.forEach(nr => {
            const l = el('div', 'gantt-linia');
            l.style.left = proc(nr);
            tor.append(l);
        });
        const pasek = el('a', 'gantt-pasek' + (a.po_terminie ? ' po-terminie' : ''));
        pasek.href = nazwa.href;
        pasek.style.left = proc(dzien(a.od));
        pasek.style.width = szer(dzien(a.do) + 1 - dzien(a.od));
        const st = a.sumy.ilosc_stojakow, hk = a.sumy.haki;
        pasek.title = `${a.nazwa}\n${krotko(a.od)} – ${krotko(a.do)}` +
            `\nIndexów: ${a.liczba_indexow} · stojaków: ${st.suma}${st.pelna ? '' : '*'} · haków: ${hk.suma}${hk.pelna ? '' : '*'}` +
            (a.po_terminie ? '\n⚠ Po terminie — nie zakończona' : '');
        pasek.textContent = `${a.po_terminie ? '⚠ ' : ''}${krotko(a.od)} – ${krotko(a.do)}`;
        tor.append(pasek);
        const teraz = el('div', 'gantt-dzis');
        teraz.style.left = proc(dzis);
        tor.append(teraz);
        w.append(tor);
        box.append(w);
    });
    box.append(el('div', 'gantt-legenda', '│ czerwona linia = dziś · ⚠ = po terminie, a akcja nie jest zakończona · najedź na pasek, żeby zobaczyć sumy'));
}

rysujGantt();

// ── Nowa akcja (jawny formularz w oknie) ──
const modal = document.getElementById('akcjaModal');
const form = document.getElementById('akcjaForm');
document.getElementById('nowaAkcja').addEventListener('click', () => {
    form.reset();
    form.od.value = GANTT.dzis;
    modal.style.display = 'flex';
    form.nazwa.focus();
});
document.getElementById('akcjaAnuluj').addEventListener('click', () => { modal.style.display = 'none'; });
form.addEventListener('submit', async e => {
    e.preventDefault();
    try {
        const a = await zapiszJson('/api/dekoracje/akcje', 'POST',
            { nazwa: form.nazwa.value, od: form.od.value, do: form.do.value });
        location.href = `/displays/akcje/${a.id}`;
    } catch (err) {
        showToast(err.message, 'error');
    }
});
