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
