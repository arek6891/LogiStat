// Skrypt strony templates/przyjecie_zwrotu.html (2026-10-27): Magazyn → Przyjęcie zwrotu.
// Jeden ekran na kolumne raportu, kazdy (oprocz pierwszego) z „Wstecz”. Zapis po
// ostatnim wyborze; `token` raz na paczke — ponowienie po bledzie sieci nie dubluje
// wiersza na serwerze. Napisy z Ustawien wchodza przez textContent (bez innerHTML).

const E = PRZYJECIE.etykiety;
const LISTY = PRZYJECIE.listy;

function nowyToken() {
    // crypto.randomUUID wymaga HTTPS; .31 dziala tez po zwyklym HTTP.
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    return Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 12)
        + Math.random().toString(36).slice(2, 12);
}

// Kolejnosc ekranow = kolejnosc z operacji.
const KROKI = [
    { pole: 'paketnummer', typ: 'skan', etykieta: E.paketnummer },
    { pole: 'brand', typ: 'wybor', etykieta: E.brand, lista: 'brand' },
    { pole: 'pos_nummer', typ: 'pos', etykieta: E.pos_nummer },
    { pole: 'kurier', typ: 'wybor', etykieta: E.kurier, lista: 'kurier' },
    ...PRZYJECIE.liczniki.map(([pole, , minimum, domyslna]) =>
        ({ pole, typ: 'licznik', etykieta: E[pole], minimum, domyslna })),
    { pole: 'verpackungsvorschrift', typ: 'wybor', etykieta: E.verpackungsvorschrift,
      lista: 'opakowanie', ostatni: true },
];

let krok = 0;
let obsada = PRZYJECIE.obsada;
let dane = {};
let token = nowyToken();
let zajete = false;

function el(tag, klasa, tekst) {
    const e = document.createElement(tag);
    if (klasa) e.className = klasa;
    if (tekst !== undefined) e.textContent = tekst;
    return e;
}

function przycisk(klasa, tekst, akcja) {
    const b = el('button', 'btn ' + klasa, tekst);
    b.type = 'button';
    b.addEventListener('click', akcja);
    return b;
}

function wartoscDomyslna(k) {
    if (dane[k.pole] !== undefined) return dane[k.pole];
    if (k.typ === 'licznik') return k.domyslna;
    return '';
}

function dalej() {
    krok += 1;
    pokaz();
}

function wstecz() {
    if (krok > 0) krok -= 1;
    pokaz();
}

function pokazWybrane() {
    const box = document.getElementById('przyjecieWybrane');
    box.replaceChildren();
    KROKI.slice(0, krok).forEach(k => {
        if (dane[k.pole] === undefined) return;
        const chip = el('span', 'przyjecie-chip');
        chip.append(el('small', '', k.etykieta + ': '), el('strong', '', String(dane[k.pole])));
        box.append(chip);
    });
}

function nawigacja(ekran, przyciskDalej) {
    const nav = el('div', 'przyjecie-nawigacja');
    if (krok > 0) nav.append(przycisk('przyjecie-wstecz', '← Wstecz', wstecz));
    else nav.append(el('span'));
    if (przyciskDalej) nav.append(przyciskDalej);
    ekran.append(nav);
}

function ekranSkanu(ekran, k) {
    const pole = el('input', 'form-control przyjecie-pole');
    pole.type = 'text';
    pole.autocomplete = 'off';
    pole.value = wartoscDomyslna(k);
    const zatwierdz = async () => {
        const v = pole.value.trim();
        if (!v) { showToast('Zeskanuj numer paczki.', 'error'); pole.focus(); return; }
        if (zajete) return;
        // Paczka przyjeta juz wczesniej — odmowa od razu po skanie (operacja
        // 2026-10-29), nie dopiero po wszystkich ekranach. Zapis sprawdza znowu.
        zajete = true;
        pole.disabled = true;
        try {
            const res = await fetch(`/api/zwroty/przyjecie/paczka?numer=${encodeURIComponent(v)}`);
            if (!res.ok) {
                const blad = await res.json().catch(() => ({}));
                if (blad.juz_przyjeta) { pokazJuzPrzyjeta(blad.error); return; }
                await pokazBladOdpowiedzi(res);
                return;
            }
        } catch (e) {
            showToast('Brak połączenia z serwerem — spróbuj ponownie.', 'error');
            return;
        } finally {
            zajete = false;
            pole.disabled = false;
        }
        dane[k.pole] = v;
        dalej();
    };
    pole.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); zatwierdz(); } });
    ekran.append(pole);
    nawigacja(ekran, przycisk('przyjecie-dalej', 'Dalej →', zatwierdz));
    pole.focus();
    pole.select();
}

function ekranPos(ekran, k) {
    const pole = el('input', 'form-control przyjecie-pole przyjecie-duze-litery');
    pole.type = 'text';
    pole.autocomplete = 'off';
    pole.maxLength = 50;
    pole.value = dane[k.pole] === PRZYJECIE.brak_pos ? '' : wartoscDomyslna(k);
    pole.addEventListener('input', () => {
        const poz = pole.selectionStart;
        pole.value = pole.value.toUpperCase();
        pole.setSelectionRange(poz, poz);
    });
    const zatwierdz = () => {
        const v = pole.value.replace(/\s+/g, '').toUpperCase();
        if (!v) { showToast(`Wpisz numer albo wybierz „${E.brak_pos}”.`, 'error'); pole.focus(); return; }
        if (!/^[A-Z0-9][A-Z0-9\-_/.]*$/.test(v)) {
            showToast('Numer POS: tylko litery, cyfry i - _ / .', 'error');
            pole.focus();
            return;
        }
        dane[k.pole] = v;
        dalej();
    };
    pole.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); zatwierdz(); } });
    ekran.append(pole);
    const brak = przycisk('przyjecie-opcja przyjecie-brak-pos', E.brak_pos, () => {
        dane[k.pole] = PRZYJECIE.brak_pos;
        dalej();
    });
    if (dane[k.pole] === PRZYJECIE.brak_pos) brak.classList.add('wybrana');
    ekran.append(brak);
    nawigacja(ekran, przycisk('przyjecie-dalej', 'Dalej →', zatwierdz));
    pole.focus();
}

function ekranWyboru(ekran, k) {
    const opcje = LISTY[k.lista] || [];
    if (!opcje.length) {
        ekran.append(el('p', 'przyjecie-uwaga', 'Lista jest pusta — admin musi dodać pozycje w Supervisor → Przyjęcie zwrotu.'));
    }
    const siatka = el('div', 'przyjecie-opcje');
    opcje.forEach(nazwa => {
        const b = przycisk('przyjecie-opcja', nazwa, () => {
            if (zajete) return;
            dane[k.pole] = nazwa;
            if (k.ostatni) zapisz(); else dalej();
        });
        if (dane[k.pole] === nazwa) b.classList.add('wybrana');
        siatka.append(b);
    });
    ekran.append(siatka);
    nawigacja(ekran, null);
}

function ekranLicznika(ekran, k) {
    const wiersz = el('div', 'przyjecie-licznik');
    const pole = el('input', 'form-control przyjecie-liczba');
    pole.type = 'text';
    pole.inputMode = 'numeric';
    pole.autocomplete = 'off';
    pole.value = String(wartoscDomyslna(k));
    const odczyt = () => {
        const v = pole.value.trim();
        return /^\d+$/.test(v) ? parseInt(v, 10) : NaN;
    };
    const ustaw = v => { pole.value = String(Math.max(k.minimum, v)); };
    const minus = przycisk('przyjecie-plusminus', '−', () => {
        const v = odczyt();
        ustaw(Number.isNaN(v) ? k.minimum : v - 1);
    });
    const plus = przycisk('przyjecie-plusminus', '+', () => {
        const v = odczyt();
        ustaw(Number.isNaN(v) ? k.minimum : v + 1);
    });
    const zatwierdz = () => {
        const v = odczyt();
        if (Number.isNaN(v) || v < k.minimum) {
            showToast(k.minimum > 0 ? `Najmniej ${k.minimum}.` : 'Wpisz liczbę (0 lub więcej).', 'error');
            pole.focus();
            return;
        }
        if (v >= PRZYJECIE.max_licznik) {
            showToast('Za duża liczba — to wygląda na zeskanowany kod.', 'error');
            pole.select();
            return;
        }
        dane[k.pole] = v;
        dalej();
    };
    pole.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); zatwierdz(); } });
    wiersz.append(minus, pole, plus);
    ekran.append(wiersz);
    nawigacja(ekran, przycisk('przyjecie-dalej', 'Dalej →', zatwierdz));
}

// Druga paczka z tym samym numerem: duzy komunikat na ekranie skanu, pole czyste
// do nastepnej paczki. Czesc 2/2 dopisuje lider w Zwrotach Paczek.
function pokazJuzPrzyjeta(komunikat) {
    dane = {};
    token = nowyToken();
    krok = 0;
    pokaz();
    const ekran = document.getElementById('przyjecieEkran');
    ekran.insertBefore(el('div', 'przyjecie-blokada', '⛔ ' + komunikat), ekran.children[1]);
    showToast('Ta paczka była już przyjęta', 'error');
}

function pokazObsade() {
    document.getElementById('przyjecieObsada').textContent =
        obsada.length ? `Na stanowisku: ${obsada.join(', ')}` : '';
}

// Nikt nie jest przydzielony do tego stanowiska — paczka nie mialaby do kogo
// isc w statystykach, wiec przyjecie stoi, az lider przydzieli (operacja 2026-10-27).
function pokazBlokade(ponow) {
    pokazObsade();
    document.getElementById('przyjecieKrok').textContent = '';
    document.getElementById('przyjecieWybrane').replaceChildren();
    const ekran = document.getElementById('przyjecieEkran');
    ekran.replaceChildren(el('div', 'przyjecie-blokada', '⛔ ' + PRZYJECIE.brak_obsady));
    const nav = el('div', 'przyjecie-nawigacja');
    nav.append(ponow ? przycisk('przyjecie-wstecz', '← Wstecz', () => { krok = KROKI.length - 1; pokaz(); })
                     : el('span'));
    nav.append(przycisk('przyjecie-dalej', ponow ? 'Spróbuj zapisać ponownie' : 'Sprawdź ponownie',
                        ponow || (() => location.reload())));
    ekran.append(nav);
}

function pokaz() {
    const k = KROKI[krok];
    pokazObsade();
    document.getElementById('przyjecieKrok').textContent = `Krok ${krok + 1} / ${KROKI.length}`;
    pokazWybrane();
    const ekran = document.getElementById('przyjecieEkran');
    ekran.replaceChildren(el('h2', 'przyjecie-pytanie', k.etykieta));
    ({ skan: ekranSkanu, pos: ekranPos, wybor: ekranWyboru, licznik: ekranLicznika })[k.typ](ekran, k);
}

async function zapisz() {
    if (zajete) return;
    zajete = true;
    document.querySelectorAll('#przyjecieEkran button').forEach(b => { b.disabled = true; });
    try {
        const wynik = await zapiszJson('/api/zwroty/przyjecie', 'POST', { ...dane, token });
        if (wynik.obsada) obsada = wynik.obsada;
        const ostatni = document.getElementById('przyjecieOstatni');
        ostatni.textContent = `✓ Przyjęto zwrot ${wynik.paketnummer}`;
        ostatni.hidden = false;
        showToast('✓ Zwrot przyjęty', 'success');
        dane = {};
        token = nowyToken();
        krok = 0;
        zajete = false;
        pokaz();
    } catch (e) {
        // Dane i token zostaja — ponowne klikniecie nie utworzy drugiego wiersza.
        zajete = false;
        if (e.dane && e.dane.brak_obsady) {
            obsada = [];
            pokazBlokade(zapisz);
            return;
        }
        if (e.dane && e.dane.juz_przyjeta) {
            pokazJuzPrzyjeta(e.message);
            return;
        }
        showToast(e.message, 'error');
        pokaz();
    }
}

window.addEventListener('beforeunload', e => {
    if (krok > 0) { e.preventDefault(); e.returnValue = ''; }
});

if (obsada.length) pokaz(); else pokazBlokade(null);
