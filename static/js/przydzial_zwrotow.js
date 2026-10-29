// Skrypt strony templates/przydzial_zwrotow.html (2026-10-27): osoby z czynnosci
// „Zwroty” → stanowiska zwrotow, na stanowisku albo jako Support przy nim
// (2026-10-29: Support bez udzialu w paczkach, „pod wynik stolu”). Kazdy wybor
// zapisuje sie od razu (autoZapis, klucz = osoba) i liczy od chwili zapisu.
// Nazwy przez textContent.

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

function zapisz(userId, miejsce, support = false) {
    const body = { date: PRZYDZIAL.date, shift: PRZYDZIAL.shift, user_id: userId, miejsce, support };
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
    stan.stanowiska.forEach(st => {
        const karta = el('div', 'card przydzial-stanowisko');
        const tu = stan.osoby.filter(o => o.miejsce === st.id);
        const osoby = tu.filter(o => !o.support);
        const pomoc = tu.filter(o => o.support);
        karta.append(el('h4', '', `🖥️ ${st.nazwa}`), el('div', 'przydzial-liczba', `${osoby.length} os.`));
        const lista = el('ul');
        osoby.forEach(o => lista.append(el('li', '', `${o.nazwa} · od ${godzina(o.od)}`)));
        pomoc.forEach(o => lista.append(el('li', 'przydzial-support', `🤝 ${o.nazwa} · od ${godzina(o.od)}`)));
        if (!osoby.length) karta.classList.add('pusta');
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
        // Wartosc opcji: '' | 's:<id>' (na stanowisku) | 'p:<id>' (Support przy nim).
        const wybor = el('select', 'form-control');
        wybor.append(new Option('— nie na stanowisku —', ''));
        const naStanowisku = el('optgroup');
        naStanowisku.label = 'Na stanowisku (dostaje paczki)';
        const wsparcie = el('optgroup');
        wsparcie.label = 'Support przy stanowisku (bez paczek)';
        stan.stanowiska.forEach(s => {
            naStanowisku.append(new Option(`🖥️ ${s.nazwa}`, `s:${s.id}`));
            wsparcie.append(new Option(`🤝 Support — ${s.nazwa}`, `p:${s.id}`));
        });
        wybor.append(naStanowisku, wsparcie);
        wybor.value = o.miejsce === null ? '' : `${o.support ? 'p' : 's'}:${o.miejsce}`;
        wybor.disabled = !stan.edycja || (o.poza_zwrotami && o.miejsce === null);
        wybor.addEventListener('change', () => {
            const v = wybor.value;
            if (v === '') zapisz(o.user_id, null);
            else zapisz(o.user_id, parseInt(v.slice(2), 10), v.startsWith('p:'));
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
        const gdzie = w.stanowisko_id === null ? '🤝 Support'
            : (w.support ? `🤝 Support — ${nazwaStanowiska(w.stanowisko_id)}` : `🖥️ ${nazwaStanowiska(w.stanowisko_id)}`);
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
