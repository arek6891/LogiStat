// Skrypt strony templates/przydzial_zwrotow.html (2026-10-27): osoby z czynnosci
// „Zwroty” → stanowiska zwrotow / Support. Kazdy wybor zapisuje sie od razu
// (autoZapis, klucz = osoba) i liczy od chwili zapisu. Nazwy przez textContent.

const URL_API = '/api/zwroty/przydzial';
let stan = null;

function el(tag, klasa, tekst) {
    const e = document.createElement(tag);
    if (klasa) e.className = klasa;
    if (tekst !== undefined) e.textContent = tekst;
    return e;
}

const godzina = iso => iso ? new Date(iso).toLocaleTimeString('pl-PL', { hour: '2-digit', minute: '2-digit' }) : '';
const nazwaStanowiska = id => (stan.stanowiska.find(s => s.id === id) || { nazwa: `#${id}` }).nazwa;

function zapisz(userId, miejsce) {
    const body = { date: PRZYDZIAL.date, shift: PRZYDZIAL.shift, user_id: userId, miejsce };
    autoZapis.zaplanuj(`osoba:${userId}`, async () => {
        try {
            rysuj(await zapiszJson(URL_API, 'PUT', body));
        } catch (e) {
            wczytaj();
            throw e;
        }
    });
}

function rysujStanowiska() {
    const box = document.getElementById('przydzialStanowiska');
    box.replaceChildren();
    const kolumny = [...stan.stanowiska.map(s => ({ klucz: s.id, nazwa: `🖥️ ${s.nazwa}` })),
                     { klucz: 'support', nazwa: '🤝 Support' }];
    kolumny.forEach(k => {
        const karta = el('div', 'card przydzial-stanowisko');
        const osoby = stan.osoby.filter(o => o.miejsce === k.klucz);
        karta.append(el('h4', '', k.nazwa), el('div', 'przydzial-liczba', `${osoby.length} os.`));
        const lista = el('ul');
        osoby.forEach(o => lista.append(el('li', '', `${o.nazwa} · od ${godzina(o.od)}`)));
        if (!osoby.length && k.klucz !== 'support') karta.classList.add('pusta');
        karta.append(lista);
        box.append(karta);
    });
}

function rysujOsoby() {
    const tbody = document.getElementById('przydzialOsoby');
    tbody.replaceChildren();
    if (!stan.osoby.length) {
        const tr = el('tr');
        const td = el('td', '', `Nikt nie jest przydzielony do czynności „${stan.czynnosc}” na tej zmianie — najpierw Przydzielanie.`);
        td.colSpan = 3;
        tr.append(td);
        tbody.append(tr);
        return;
    }
    stan.osoby.forEach(o => {
        const tr = el('tr');
        const imie = el('td', '', o.nazwa);
        if (o.poza_zwrotami) imie.append(el('small', 'przydzial-uwaga', ' (już nie na „Zwrotach” w Przydzielaniu)'));
        if (o.na_innej_zmianie) imie.append(el('small', 'przydzial-uwaga', ' (na stanowisku z innej zmiany)'));
        const wybor = el('select', 'form-control');
        wybor.append(new Option('— nie na stanowisku —', ''));
        stan.stanowiska.forEach(s => wybor.append(new Option(`🖥️ ${s.nazwa}`, String(s.id))));
        wybor.append(new Option('🤝 Support', 'support'));
        wybor.value = o.miejsce === null ? '' : String(o.miejsce);
        wybor.disabled = !stan.edycja || (o.poza_zwrotami && o.miejsce === null);
        wybor.addEventListener('change', () => {
            const v = wybor.value;
            zapisz(o.user_id, v === '' ? null : (v === 'support' ? 'support' : parseInt(v, 10)));
        });
        const td = el('td');
        td.append(wybor);
        tr.append(imie, td, el('td', '', o.miejsce === null ? '' : godzina(o.od)));
        tbody.append(tr);
    });
}

function rysujInne() {
    const box = document.getElementById('przydzialInneBox');
    const tbody = document.getElementById('przydzialInne');
    tbody.replaceChildren();
    box.hidden = !stan.inne_zmiany.length;
    stan.inne_zmiany.forEach(w => {
        const tr = el('tr');
        const gdzie = w.support ? '🤝 Support' : `🖥️ ${nazwaStanowiska(w.stanowisko_id)}`;
        const td = el('td');
        const b = el('button', 'btn btn-danger btn-sm', 'Zakończ');
        b.type = 'button';
        b.disabled = !stan.edycja;
        b.addEventListener('click', () => {
            if (confirm(`Zakończyć przydział: ${w.nazwa}?`)) zapisz(w.user_id, null);
        });
        td.append(b);
        tr.append(el('td', '', w.nazwa), el('td', '', gdzie), el('td', '', `${w.zmiana} · od ${godzina(w.od)}`), td);
        tbody.append(tr);
    });
}

function rysuj(dane) {
    stan = dane;
    const uwagi = document.getElementById('przydzialUwagi');
    uwagi.replaceChildren();
    if (stan.brak_czynnosci) {
        uwagi.append(el('div', 'przydzial-komunikat', `Brak czynności „${stan.czynnosc}” — admin musi ją mieć w Supervisor → Czynności (nazwa musi się zgadzać).`));
    }
    if (!stan.stanowiska.length) {
        uwagi.append(el('div', 'przydzial-komunikat', 'Brak kont stanowisk — admin zakłada je w Użytkownicy (rola Stanowisko).'));
    }
    if (!stan.edycja) {
        uwagi.append(el('div', 'przydzial-komunikat info', 'Podgląd: przydział zmienia się tylko na bieżącej zmianie (dziś albo wczoraj).'));
    }
    rysujStanowiska();
    rysujOsoby();
    rysujInne();
}

async function wczytaj() {
    const res = await fetch(`${URL_API}?date=${PRZYDZIAL.date}&shift=${PRZYDZIAL.shift}`);
    if (!res.ok) { pokazBladOdpowiedzi(res); return; }
    rysuj(await res.json());
}

// Zmiana daty / zmiany przeladowuje strone — najpierw wypchnij zapis w toku.
const filtr = document.getElementById('przydzialFiltr');
let wysylam = false;
filtr.addEventListener('submit', async e => {
    if (wysylam) return;
    e.preventDefault();
    if (!await autoZapis.przedOpuszczeniem()) return;
    wysylam = true;
    const shift = e.submitter && e.submitter.name === 'shift' ? e.submitter.value : PRZYDZIAL.shift;
    location.href = `?date=${encodeURIComponent(filtr.date.value)}&shift=${shift}`;
});
filtr.date.addEventListener('change', () => filtr.requestSubmit());

wczytaj();
