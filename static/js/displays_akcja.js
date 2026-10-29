// Ekran akcji Dekoracji (templates/displays_akcja.html, 2026-10-28).
// Naglowek (nazwa + obie daty razem) i kazde pole indexu zapisuja sie same
// (autoZapis, klucz = akcja / index:pole — czesciowy PUT). Dodanie / usuniecie
// indexu i Zakoncz / Przywroc najpierw wypychaja zapisy, potem przeladowuja strone.

function liczbaPola(pole) {
    const v = pole.value.trim();
    if (v === '') return null;
    const n = Number(v.replace(',', '.'));
    return Number.isFinite(n) ? n : v;   // tekst → serwer odpowie 400 z komunikatem
}

function przelicz() {
    // Haki lacznie per index i sumy akcji — od razu, bez czekania na serwer.
    const sumy = { ilosc_stojakow: [], haki: [], rgd: [], displays: [], akcesoria: [], pos: [] };
    document.querySelectorAll('.dekoracje-index').forEach(k => {
        const w = p => liczbaPola(k.querySelector(`[data-pole="${p}"]`));
        const st = w('ilosc_stojakow'), hn = w('haki_na_stojak');
        const haki = (typeof st === 'number' && typeof hn === 'number') ? st * hn : null;
        k.querySelector('[data-haki]').textContent = haki === null ? '—' : haki;
        sumy.haki.push(haki);
        ['ilosc_stojakow', 'rgd', 'displays', 'akcesoria', 'pos'].forEach(p => sumy[p].push(w(p)));
    });
    Object.entries(sumy).forEach(([p, wartosci]) => {
        const el = document.querySelector(`[data-suma="${p}"]`);
        if (!el) return;
        el.textContent = wartosci.filter(v => typeof v === 'number').reduce((a, b) => a + b, 0);
        const pelna = wartosci.every(v => typeof v === 'number');
        let znak = el.parentElement.querySelector('[data-niepelna]');
        if (!pelna && !znak) {
            znak = document.createElement('small');
            znak.className = 'dekoracje-niepelna';
            znak.dataset.niepelna = p;
            znak.title = 'Któryś index ma puste pole — suma tylko z wpisanych';
            znak.textContent = ' niepełna';
            el.after(znak);
        } else if (pelna && znak) {
            znak.remove();
        }
    });
}

// ── Kamienie milowe (2026-10-29) ──
// Stan liczy serwer (stan_etapu, dzien lokalny serwera) — tu tylko etykiety.
// Daty etapu ida razem: zapis dopiero gdy obie wpisane albo obie puste.
const STANY_ETAPU = {
    bez_terminu: ['Bez terminu', ''], nie_dotyczy: ['Nie dotyczy', ''],
    planowany: ['Zaplanowany', ''], w_toku: ['W toku', 'w-toku'],
    konczy_sie: ['⏳ Kończy się', 'konczy-sie'], po_terminie: ['⚠ Po terminie', 'po-terminie'],
};
const DZIEN_MS = 86400000;
const nrDnia = iso => { const [r, m, d] = iso.split('-').map(Number); return Date.UTC(r, m - 1, d) / DZIEN_MS; };
const krotko = iso => `${iso.slice(8, 10)}.${iso.slice(5, 7)}`;

function zakresAkcji() {
    return { od: document.getElementById('akcjaOd').value, do: document.getElementById('akcjaDo').value };
}

function stanEtapu(td, e) {
    const [tekst, klasa] = STANY_ETAPU[e.stan];
    td.replaceChildren();
    const b = document.createElement('span');
    b.className = 'dekoracje-etap-stan ' + klasa;
    b.textContent = tekst;
    td.append(b);
}

function osEtapu(td, e) {
    const tor = document.createElement('div');
    tor.className = 'dekoracje-etap-tor';
    td.replaceChildren(tor);
    const a = zakresAkcji();
    if (!e.od || !e.do || !a.od || !a.do || e.nie_dotyczy) return;
    const start = nrDnia(a.od), dni = nrDnia(a.do) + 1 - start;
    const p = document.createElement('div');
    p.className = 'dekoracje-etap-pasek ' + STANY_ETAPU[e.stan][1];
    p.style.left = `${((nrDnia(e.od) - start) / dni) * 100}%`;
    p.style.width = `${((nrDnia(e.do) + 1 - nrDnia(e.od)) / dni) * 100}%`;
    p.title = `${krotko(e.od)} – ${krotko(e.do)}`;
    tor.append(p);
}

function ostrzezeniaEtapow() {
    const box = document.getElementById('etapyOstrzezenia');
    const lista = AKCJA.zakonczona ? [] : AKCJA.etapy.filter(e => e.stan === 'konczy_sie' || e.stan === 'po_terminie');
    box.replaceChildren();
    if (!lista.length) return;
    const d = document.createElement('div');
    d.className = 'dekoracje-etapy-alert';
    d.textContent = lista.map(e => `${STANY_ETAPU[e.stan][0]}: ${e.nazwa} (do ${krotko(e.do)})`).join(' · ');
    box.append(d);
}

function rysujEtapy() {
    const tbody = document.getElementById('etapy');
    tbody.replaceChildren();
    AKCJA.etapy.forEach(e => {
        const tr = document.createElement('tr');
        tr.dataset.etap = e.klucz;
        const nazwa = document.createElement('td');
        const n = document.createElement('strong');
        n.textContent = e.nazwa;
        nazwa.append(n);
        if (e.podpowiedz) {
            const p = document.createElement('small');
            p.className = 'dekoracje-etap-podpowiedz';
            p.textContent = e.podpowiedz;
            nazwa.append(p);
        }
        if (e.opcjonalny) {
            const l = document.createElement('label');
            l.className = 'dekoracje-etap-nd';
            l.innerHTML = '<input type="checkbox" class="js-nd"> nie dotyczy';
            l.querySelector('input').checked = e.nie_dotyczy;
            l.querySelector('input').disabled = AKCJA.zakonczona;
            nazwa.append(l);
        }
        tr.append(nazwa);
        ['od', 'do'].forEach(k => {
            const td = document.createElement('td');
            const i = document.createElement('input');
            i.type = 'date';
            i.className = 'form-control js-' + k;
            i.value = e[k] || '';
            i.disabled = AKCJA.zakonczona || e.nie_dotyczy;
            td.append(i);
            tr.append(td);
        });
        const stan = document.createElement('td');
        stanEtapu(stan, e);
        const os = document.createElement('td');
        os.className = 'dekoracje-etap-os';
        osEtapu(os, e);
        tr.append(stan, os);
        tbody.append(tr);
    });
    ustawZakresDat();
    ostrzezeniaEtapow();
}

function ustawZakresDat() {
    // Wygoda: kalendarz od razu w datach akcji (pilnuje i tak serwer).
    const a = zakresAkcji();
    document.querySelectorAll('#etapy input[type=date]').forEach(i => { i.min = a.od; i.max = a.do; });
}

function odswiezEtap(e) {
    AKCJA.etapy = AKCJA.etapy.map(x => (x.klucz === e.klucz ? e : x));
    const tr = document.querySelector(`#etapy tr[data-etap="${e.klucz}"]`);
    const td = tr.querySelectorAll('td');
    stanEtapu(td[3], e);
    osEtapu(td[4], e);
    tr.querySelector('.js-od').value = e.od || '';
    tr.querySelector('.js-do').value = e.do || '';
    tr.querySelectorAll('input[type=date]').forEach(i => { i.disabled = e.nie_dotyczy; });
    ostrzezeniaEtapow();
}

rysujEtapy();
if (!AKCJA.zakonczona) {
    const tbody = document.getElementById('etapy');
    tbody.addEventListener('change', ev => {
        const tr = ev.target.closest('tr[data-etap]');
        if (!tr) return;
        const klucz = tr.dataset.etap;
        const url = `/api/dekoracje/akcje/${AKCJA.id}/etapy/${klucz}`;
        if (ev.target.classList.contains('js-nd')) {
            const body = { nie_dotyczy: ev.target.checked };
            autoZapis.zaplanuj(`etap:${klucz}:nd`, async () => odswiezEtap(await zapiszJson(url, 'PUT', body)), [ev.target]);
            return;
        }
        const od = tr.querySelector('.js-od'), doo = tr.querySelector('.js-do');
        if (ev.target === od && od.value && (!doo.value || doo.value < od.value)) doo.min = od.value;
        if (Boolean(od.value) !== Boolean(doo.value)) return;   // czeka na druga date
        const body = { od: od.value, do: doo.value };
        autoZapis.zaplanuj(`etap:${klucz}`, async () => odswiezEtap(await zapiszJson(url, 'PUT', body)), [od, doo]);
    });
    ['akcjaOd', 'akcjaDo'].forEach(id => document.getElementById(id).addEventListener('change', () => {
        ustawZakresDat();
        AKCJA.etapy.forEach(e => osEtapu(document.querySelector(`#etapy tr[data-etap="${e.klucz}"] .dekoracje-etap-os`), e));
    }));
}

async function przeladuj(akcja) {
    if (!(await autoZapis.przedOpuszczeniem())) return;
    try {
        await akcja();
        location.reload();
    } catch (e) {
        showToast(e.message, 'error');
    }
}

if (!AKCJA.zakonczona) {
    const nazwa = document.getElementById('akcjaNazwa');
    const od = document.getElementById('akcjaOd');
    const doo = document.getElementById('akcjaDo');
    const zapiszNaglowek = () => {
        const body = { nazwa: nazwa.value, od: od.value, do: doo.value };
        autoZapis.zaplanuj('akcja', () => zapiszJson(`/api/dekoracje/akcje/${AKCJA.id}`, 'PUT', body),
            [nazwa, od, doo]);
    };
    autoZapis.poWpisaniu(nazwa, zapiszNaglowek);
    [od, doo].forEach(p => p.addEventListener('change', zapiszNaglowek));

    document.querySelectorAll('.dekoracje-index').forEach(karta => {
        const id = karta.dataset.id;
        karta.querySelectorAll('[data-pole]').forEach(pole => {
            const klucz = pole.dataset.pole;
            const zapisz = () => {
                let wartosc;
                if (pole.tagName === 'SELECT') wartosc = pole.value === '' ? null : parseInt(pole.value, 10);
                else if (pole.dataset.liczba) wartosc = liczbaPola(pole);
                else wartosc = pole.value;
                const body = { [klucz]: wartosc };
                autoZapis.zaplanuj(`index:${id}:${klucz}`,
                    () => zapiszJson(`/api/dekoracje/indexy/${id}`, 'PUT', body), [pole]);
            };
            if (pole.tagName === 'SELECT') pole.addEventListener('change', zapisz);
            else autoZapis.poWpisaniu(pole, zapisz);
            if (pole.dataset.liczba) pole.addEventListener('input', przelicz);
        });
        karta.querySelector('.js-usun-index').addEventListener('click', () => {
            const n = karta.querySelector('[data-pole="nazwa"]').value;
            if (confirm(`Usunąć index „${n}” razem z jego danymi?`)) {
                przeladuj(() => zapiszJson(`/api/dekoracje/indexy/${id}`, 'DELETE', {}));
            }
        });
    });

    document.getElementById('dodajIndex').addEventListener('click', () =>
        przeladuj(() => zapiszJson(`/api/dekoracje/akcje/${AKCJA.id}/indexy`, 'POST', {})));
    document.getElementById('zakoncz').addEventListener('click', () => {
        if (confirm('Zakończyć akcję? Zniknie z wykresu i przejdzie do Historii akcji (można ją przywrócić).')) {
            przeladuj(() => zapiszJson(`/api/dekoracje/akcje/${AKCJA.id}/status`, 'PUT', { zakonczona: true }));
        }
    });
} else {
    document.getElementById('przywroc').addEventListener('click', () =>
        przeladuj(() => zapiszJson(`/api/dekoracje/akcje/${AKCJA.id}/status`, 'PUT', { zakonczona: false })));
}

document.querySelectorAll('.js-wyjdz').forEach(a => a.addEventListener('click', async e => {
    e.preventDefault();
    if (await autoZapis.przedOpuszczeniem()) location.href = a.href;
}));
