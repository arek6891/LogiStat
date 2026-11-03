// Wykres Gantta akcji Dekoracji (templates/displays.html, 2026-10-28).
// Dane z serwera (GANTT): akcje niezakonczone i „dzis” (dzien lokalny serwera,
// nie przegladarki). Szerokosci w procentach — wykres miesci sie w karcie.
// Koniec akcji wlacznie (pasek do konca dnia „do”).
// Rozwiniecie (2026-11-03, operacja): ▸ przy akcji pokazuje pod nia wszystkie
// kamienie milowe (stan + daty, pasek na tej samej osi). Ktore akcje sa
// rozwiniete — per przegladarka w localStorage (wygoda, try/catch).

const MIESIACE = ['sty', 'lut', 'mar', 'kwi', 'maj', 'cze', 'lip', 'sie', 'wrz', 'paź', 'lis', 'gru'];
const DZIEN_MS = 86400000;

function dzien(iso) {               // 'YYYY-MM-DD' → numer dnia (UTC, bez stref)
    const [r, m, d] = iso.split('-').map(Number);
    return Date.UTC(r, m - 1, d) / DZIEN_MS;
}
function data(nr) { return new Date(nr * DZIEN_MS); }
function krotko(iso) { return `${iso.slice(8, 10)}.${iso.slice(5, 7)}`; }

const KLUCZ_ROZWINIETYCH = 'logistat-gantt-rozwiniete';
const rozwiniete = new Set((() => {
    try { return JSON.parse(localStorage.getItem(KLUCZ_ROZWINIETYCH)) || []; } catch (e) { return []; }
})());
function zapamietajRozwiniete() {
    try { localStorage.setItem(KLUCZ_ROZWINIETYCH, JSON.stringify([...rozwiniete])); } catch (e) { /* bez pamieci */ }
}
function przelaczAkcje(id) {
    if (rozwiniete.has(id)) rozwiniete.delete(id); else rozwiniete.add(id);
    zapamietajRozwiniete();
    rysujGantt();
}
function datyEtapu(e) {
    if (e.nie_dotyczy) return 'nie dotyczy';
    return e.od && e.do ? `${krotko(e.od)} – ${krotko(e.do)}` : 'bez terminu';
}

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
    const przycisk = document.getElementById('ganttRozwin');
    przycisk.hidden = !akcje.length;
    if (!akcje.length) {
        box.append(el('div', 'empty-state', 'Brak akcji w toku. Dodaj nową przyciskiem „➕ Nowa akcja”.'));
        return;
    }
    const wszystkie = akcje.every(a => rozwiniete.has(a.id));
    przycisk.textContent = wszystkie ? '▾ Zwiń kamienie milowe' : '▸ Rozwiń kamienie milowe';
    przycisk.setAttribute('aria-expanded', String(wszystkie));
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

    function torZLiniami(klasa) {
        const tor = el('div', klasa);
        tygodnie.forEach(nr => {
            const l = el('div', 'gantt-linia');
            l.style.left = proc(nr);
            tor.append(l);
        });
        return tor;
    }
    function dzisNa(tor) {
        const teraz = el('div', 'gantt-dzis');
        teraz.style.left = proc(dzis);
        tor.append(teraz);
    }

    akcje.forEach(a => {
        const otwarta = rozwiniete.has(a.id);
        const w = el('div', 'gantt-wiersz');
        const komorka = el('div', 'gantt-nazwa-kom');
        const rozwin = el('button', 'gantt-rozwin', otwarta ? '▾' : '▸');
        rozwin.type = 'button';
        rozwin.title = otwarta ? 'Zwiń kamienie milowe' : 'Pokaż kamienie milowe';
        rozwin.setAttribute('aria-expanded', String(otwarta));
        rozwin.addEventListener('click', () => przelaczAkcje(a.id));
        komorka.append(rozwin);
        const nazwa = el('a', 'gantt-nazwa', a.nazwa);
        nazwa.href = `/displays/akcje/${a.id}`;
        nazwa.title = a.nazwa;
        komorka.append(nazwa);
        // Kamienie milowe: ⚠ po terminie / ⏳ konczy sie (stan liczy serwer).
        const po = a.ostrzezenia.filter(e => e.stan === 'po_terminie').length;
        const konczy = a.ostrzezenia.length - po;
        const opisEtapow = a.ostrzezenia.map(e => `${e.stan === 'po_terminie' ? '⚠ po terminie' : '⏳ kończy się'}: ${e.nazwa} (do ${krotko(e.do)})`);
        if (a.ostrzezenia.length) {
            const znak = el('span', 'gantt-etapy');
            if (po) znak.append(el('span', 'po-terminie', `⚠ ${po}`));
            if (konczy) znak.append(el('span', 'konczy-sie', `⏳ ${konczy}`));
            znak.title = 'Kamienie milowe:\n' + opisEtapow.join('\n');
            komorka.append(znak);
        }
        w.append(komorka);
        const tor = torZLiniami('gantt-tor');
        const pasek = el('a', 'gantt-pasek' + (a.po_terminie ? ' po-terminie' : ''));
        pasek.href = nazwa.href;
        pasek.style.left = proc(dzien(a.od));
        pasek.style.width = szer(dzien(a.do) + 1 - dzien(a.od));
        const st = a.sumy.ilosc_stojakow, hk = a.sumy.haki;
        pasek.title = `${a.nazwa}\n${krotko(a.od)} – ${krotko(a.do)}` +
            `\nIndexów: ${a.liczba_indexow} · stojaków: ${st.suma}${st.pelna ? '' : '*'} · haków: ${hk.suma}${hk.pelna ? '' : '*'}` +
            (a.po_terminie ? '\n⚠ Po terminie — nie zakończona' : '') +
            (opisEtapow.length ? '\nKamienie milowe:\n' + opisEtapow.join('\n') : '');
        pasek.textContent = `${a.po_terminie ? '⚠ ' : ''}${krotko(a.od)} – ${krotko(a.do)}`;
        tor.append(pasek);
        dzisNa(tor);
        w.append(tor);
        box.append(w);
        if (otwarta) a.etapy.forEach(e => box.append(wierszEtapu(a, e)));
    });
    box.append(el('div', 'gantt-legenda', '│ czerwona linia = dziś · ⚠ na pasku = akcja po terminie, a nie zakończona · przy nazwie: ⚠ N kamieni milowych po terminie, ⏳ N kończy się · ▸ rozwija kamienie milowe akcji (jasne tło = czas akcji) · najedź na pasek, żeby zobaczyć sumy'));

    // Kamien milowy pod akcja: nazwa + stan + daty; pasek etapu na jasnym tle
    // czasu akcji (etap zawsze miesci sie w datach akcji — pilnuje serwer).
    function wierszEtapu(a, e) {
        const [stanTekst, stanKlasa] = STANY_ETAPU[e.stan];
        const w = el('div', 'gantt-wiersz gantt-etap');
        const kom = el('div', 'gantt-etap-kom');
        const n = el('div', 'gantt-etap-nazwa', e.nazwa);
        n.title = e.podpowiedz ? `${e.nazwa}\n${e.podpowiedz}` : e.nazwa;
        const opis = el('div', 'gantt-etap-opis');
        opis.append(el('span', 'dekoracje-etap-stan ' + stanKlasa, stanTekst));
        if (e.od && e.do && !e.nie_dotyczy) opis.append(el('span', '', ` · ${datyEtapu(e)}`));
        kom.append(n, opis);
        w.append(kom);
        const tor = torZLiniami('gantt-tor gantt-tor-etapu');
        const zakres = el('div', 'gantt-zakres-akcji');
        zakres.style.left = proc(dzien(a.od));
        zakres.style.width = szer(dzien(a.do) + 1 - dzien(a.od));
        tor.append(zakres);
        if (e.od && e.do && !e.nie_dotyczy) {
            const p = el('a', 'gantt-etap-pasek ' + stanKlasa, datyEtapu(e));
            p.href = `/displays/akcje/${a.id}`;
            p.style.left = proc(dzien(e.od));
            p.style.width = szer(dzien(e.do) + 1 - dzien(e.od));
            p.title = `${e.nazwa} — ${stanTekst}\n${datyEtapu(e)}` + (e.podpowiedz ? `\n${e.podpowiedz}` : '');
            tor.append(p);
        }
        dzisNa(tor);
        w.append(tor);
        return w;
    }
}

rysujGantt();

// Wszystkie naraz: gdy kazda jest rozwinieta → zwija wszystkie, inaczej rozwija.
document.getElementById('ganttRozwin').addEventListener('click', () => {
    const wszystkie = GANTT.akcje.every(a => rozwiniete.has(a.id));
    GANTT.akcje.forEach(a => (wszystkie ? rozwiniete.delete(a.id) : rozwiniete.add(a.id)));
    zapamietajRozwiniete();
    rysujGantt();
});

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
            { nazwa: form.nazwa.value, od: form.od.value, do: form.do.value, typ_dostawy: form.typ_dostawy.value });
        location.href = `/displays/akcje/${a.id}`;
    } catch (err) {
        showToast(err.message, 'error');
    }
});
