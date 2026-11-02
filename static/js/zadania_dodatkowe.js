// Skrypt strony templates/zadania_dodatkowe.html (operacja 2026-11-02, zastepuje
// Wpis ilosci). Wiersz = osoba, dzial, czas od–do (suwak z dwoma uchwytami +
// pola godzin), czynnosc dodatkowa, komentarz. Autozapis per wiersz: pierwszy
// zapis (gdy jest osoba i dzial) to POST, kolejne PUT calego wiersza.
// Nazwy przez textContent.

const URL_API = '/api/zadania-dodatkowe';
// Suwak: minuty od polnocy dnia zmiany, od 6:00 do 6:00 nastepnego dnia —
// godzina z pola < ZADANIA.po_polnocy:00 to juz nastepny dzien.
const SUWAK_OD = ZADANIA.po_polnocy * 60;
const SUWAK_DO = SUWAK_OD + 24 * 60;
const KROK = 15;
let stan = null;
let licznik = 0;

function el(tag, klasa, tekst) {
    const e = document.createElement(tag);
    if (klasa) e.className = klasa;
    if (tekst !== undefined) e.textContent = tekst;
    return e;
}

const [ROK, MIES, DZIEN] = ZADANIA.date.split('-').map(Number);
const naIso = minuty => new Date(ROK, MIES - 1, DZIEN, 0, minuty).toISOString().slice(0, 19);
const naMinuty = iso => Math.round((new Date(iso) - new Date(ROK, MIES - 1, DZIEN)) / 60000);
const naGodzine = minuty => {
    const m = ((minuty % 1440) + 1440) % 1440;
    return `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`;
};
const zGodziny = tekst => {
    const [h, m] = tekst.split(':').map(Number);
    const minuty = h * 60 + m;
    return minuty < SUWAK_OD ? minuty + 1440 : minuty;
};
const przytnij = m => Math.min(SUWAK_DO, Math.max(SUWAK_OD, Math.round(m / KROK) * KROK));

function domyslnyCzas() {
    // Dzis: ostatnia godzina; inny dzien: pierwsza godzina zmiany.
    if (ZADANIA.date === dzisLokalnie()) {
        const teraz = new Date();
        const doo = przytnij(Math.floor(naMinuty(teraz.toISOString()) / KROK) * KROK);
        return [Math.max(SUWAK_OD, doo - 60), Math.max(SUWAK_OD + KROK, doo)];
    }
    const start = ZADANIA.shift === 1 ? 6 * 60 : 14 * 60;
    return [start, start + 60];
}

function zapisz(w, tr) {
    const uwaga = tr.querySelector('.zadania-uwaga');
    if (!w.user_id || !w.dzial) {
        uwaga.textContent = 'Wybierz pracownika i dział — wtedy wiersz się zapisze.';
        return;
    }
    uwaga.textContent = '';
    const body = {
        date: ZADANIA.date, shift: ZADANIA.shift, user_id: w.user_id, dzial: w.dzial,
        od: naIso(w.od), do: naIso(w.do), czynnosc_id: w.czynnosc_id, komentarz: w.komentarz,
    };
    autoZapis.zaplanuj(`zadanie:${w.klucz}`, async () => {
        const dane = w.id ? await zapiszJson(`${URL_API}/${w.id}`, 'PUT', body)
            : await zapiszJson(URL_API, 'POST', body);
        w.id = dane.id;
    }, [tr]);
}

function opcjeOsob(wybor, w) {
    wybor.append(new Option('— wybierz —', ''));
    const obecni = el('optgroup');
    obecni.label = 'Obecni na tej zmianie';
    const reszta = el('optgroup');
    reszta.label = 'Pozostali';
    stan.osoby.forEach(o => (o.obecny ? obecni : reszta).append(
        new Option(o.nazwa + (o.aktywny ? '' : ' (nieaktywna)'), String(o.id))));
    if (obecni.children.length) wybor.append(obecni);
    wybor.append(reszta);
    wybor.value = w.user_id ? String(w.user_id) : '';
}

function wiersz(w) {
    const tr = el('tr');
    const osoba = el('select', 'form-control');
    opcjeOsob(osoba, w);
    osoba.addEventListener('change', () => { w.user_id = osoba.value ? parseInt(osoba.value, 10) : null; zapisz(w, tr); });

    const dzial = el('select', 'form-control');
    dzial.append(new Option('— wybierz —', ''));
    stan.dzialy.forEach(d => dzial.append(new Option(d.nazwa, d.klucz)));
    dzial.value = w.dzial || '';
    dzial.addEventListener('change', () => { w.dzial = dzial.value || null; zapisz(w, tr); });

    // Suwak z dwoma uchwytami (dwa nalozone input range) + pola godzin.
    const czas = el('div', 'zadania-czas');
    const suwak = el('div', 'suwak-zakresu');
    const pasek = el('div', 'suwak-zakresu-pasek');
    const [zakresOd, zakresDo] = [el('input'), el('input')];
    [zakresOd, zakresDo].forEach(r => Object.assign(r, { type: 'range', min: SUWAK_OD, max: SUWAK_DO, step: KROK }));
    zakresOd.setAttribute('aria-label', 'Początek');
    zakresDo.setAttribute('aria-label', 'Koniec');
    suwak.append(pasek, zakresOd, zakresDo);
    const godzOd = Object.assign(el('input', 'form-control'), { type: 'time', step: KROK * 60 });
    const godzDo = Object.assign(el('input', 'form-control'), { type: 'time', step: KROK * 60 });
    const suma = el('span', 'zadania-suma');
    const pola = el('div', 'zadania-godziny');
    pola.append(godzOd, el('span', '', '–'), godzDo, suma);
    czas.append(suwak, pola);

    const pokaz = () => {
        zakresOd.value = w.od;
        zakresDo.value = w.do;
        godzOd.value = naGodzine(w.od);
        godzDo.value = naGodzine(w.do);
        const zakres = SUWAK_DO - SUWAK_OD;
        pasek.style.left = `${(w.od - SUWAK_OD) / zakres * 100}%`;
        pasek.style.width = `${(w.do - w.od) / zakres * 100}%`;
        suma.textContent = `${((w.do - w.od) / 60).toFixed(2).replace('.', ',')} h`;
    };
    const przesun = (ktory) => {
        let od = parseInt(zakresOd.value, 10);
        let doo = parseInt(zakresDo.value, 10);
        if (od >= doo) {
            if (ktory === 'od') od = doo - KROK; else doo = od + KROK;
        }
        w.od = Math.max(SUWAK_OD, od);
        w.do = Math.min(SUWAK_DO, doo);
        pokaz();
    };
    zakresOd.addEventListener('input', () => przesun('od'));
    zakresDo.addEventListener('input', () => przesun('do'));
    zakresOd.addEventListener('change', () => zapisz(w, tr));
    zakresDo.addEventListener('change', () => zapisz(w, tr));
    const zPola = (pole, ktory) => pole.addEventListener('change', () => {
        if (!pole.value) { pokaz(); return; }
        (ktory === 'od' ? zakresOd : zakresDo).value = przytnij(zGodziny(pole.value));
        przesun(ktory);
        zapisz(w, tr);
    });
    zPola(godzOd, 'od');
    zPola(godzDo, 'do');
    pokaz();

    const czynnosc = el('select', 'form-control');
    czynnosc.append(new Option('—', ''));
    stan.czynnosci.forEach(c => czynnosc.append(new Option(c.nazwa + (c.aktywna ? '' : ' (wyłączona)'), String(c.id))));
    czynnosc.value = w.czynnosc_id ? String(w.czynnosc_id) : '';
    czynnosc.addEventListener('change', () => { w.czynnosc_id = czynnosc.value ? parseInt(czynnosc.value, 10) : null; zapisz(w, tr); });

    const komentarz = Object.assign(el('input', 'form-control'), { type: 'text', maxLength: 300, value: w.komentarz || '' });
    autoZapis.poWpisaniu(komentarz, () => { w.komentarz = komentarz.value; zapisz(w, tr); });

    const usun = el('button', 'btn btn-danger btn-sm', '✕');
    usun.type = 'button';
    usun.title = 'Usuń wiersz';
    usun.addEventListener('click', async () => {
        if (!w.id) { tr.remove(); return; }
        if (!confirm('Usunąć ten wiersz?')) return;
        if (!await autoZapis.przedOpuszczeniem()) return;
        try {
            await zapiszJson(`${URL_API}/${w.id}`, 'DELETE', {});
            tr.remove();
        } catch (e) {
            showToast(e.message, 'error');
        }
    });

    const komorka = (...dzieci) => { const td = el('td'); td.append(...dzieci); return td; };
    tr.append(komorka(osoba, el('div', 'zadania-uwaga')), komorka(dzial), komorka(czas),
              komorka(czynnosc), komorka(komentarz), komorka(usun));
    return tr;
}

function dodaj(w) {
    const tbody = document.getElementById('zadaniaWiersze');
    const pusto = tbody.querySelector('.empty-state');
    if (pusto) pusto.closest('tr').remove();
    w.klucz = ++licznik;
    tbody.append(wiersz(w));
}

async function wczytaj() {
    const res = await fetch(`${URL_API}?date=${ZADANIA.date}&shift=${ZADANIA.shift}`);
    if (!res.ok) { pokazBladOdpowiedzi(res); return; }
    stan = await res.json();
    const tbody = document.getElementById('zadaniaWiersze');
    tbody.replaceChildren();
    if (!stan.wiersze.length) {
        const tr = el('tr');
        const td = el('td', 'empty-state', 'Brak zadań na tej zmianie — „➕ Dodaj wiersz”.');
        td.colSpan = 6;
        tr.append(td);
        tbody.append(tr);
    }
    stan.wiersze.forEach(z => dodaj({
        id: z.id, user_id: z.user_id, dzial: z.dzial, od: naMinuty(z.od), do: naMinuty(z.do),
        czynnosc_id: z.czynnosc_id, komentarz: z.komentarz,
    }));
}

document.getElementById('zadaniaDodaj').addEventListener('click', () => {
    if (!stan) return;
    const [od, doo] = domyslnyCzas();
    dodaj({ id: null, user_id: null, dzial: null, od, do: doo, czynnosc_id: null, komentarz: '' });
});

// Zmiana daty / zmiany i eksport — najpierw wypchnij zapisy w toku.
const filtr = document.getElementById('zadaniaFiltr');
let wysylam = false;
filtr.addEventListener('submit', async e => {
    if (wysylam) return;
    e.preventDefault();
    if (!await autoZapis.przedOpuszczeniem()) return;
    wysylam = true;
    const shift = e.submitter && e.submitter.name === 'shift' ? e.submitter.value : ZADANIA.shift;
    location.href = `?date=${encodeURIComponent(filtr.date.value)}&shift=${shift}`;
});
filtr.date.addEventListener('change', () => filtr.requestSubmit());
document.getElementById('zadaniaEksport').addEventListener('submit', async e => {
    e.preventDefault();
    if (!await autoZapis.przedOpuszczeniem()) return;
    const f = e.target;
    location.href = `${f.action}?date_from=${encodeURIComponent(f.date_from.value)}&date_to=${encodeURIComponent(f.date_to.value)}`;
});

wczytaj();
