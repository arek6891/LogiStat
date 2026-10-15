// Tabela ilosci na koniec paczki (Post Processing, 2026-10-15).
// Jeden komponent dla stanowiska („Czasy paczek") i okna lidera („✎ Ilosci"
// na /paczki). Liczy na biezaco to samo co normalizuj_tabele() w app.py —
// serwer i tak liczy po swojej stronie, tu tylko podglad dla operatora.
//
// Tryb 'wzor' (paczka jednej osoby): Ilosc biżuterii = ilosc z pliku − pozostale
// grupy, Pojedynczo = Ilosc − Brak + Nadwyzka − Uszkodzone − Podwojnie − Potrojnie.
// Tryb 'zespol' (paczka kilku osob): kazdy wpisuje swoje sztuki wprost.
const TabelaIlosci = (() => {
    const GRUPY = [
        ['bizuteria', 'Biżuteria'],
        ['akcesoria', 'Akcesoria'],
        ['okulary', 'Okulary'],
        ['tekstylia', 'Tekstylia'],
    ];
    const GLOWNA = 'bizuteria';
    const KOLUMNY = {
        wzor: [['brak', 'Brak'], ['nadwyzka', 'Nadwyżka'], ['uszkodzone', 'Uszkodzone'],
               ['podwojnie', 'Podwójnie'], ['potrojnie', 'Potrójnie']],
        zespol: [['pojedynczo', 'Pojedynczo'], ['podwojnie', 'Podwójnie'],
                 ['potrojnie', 'Potrójnie'], ['uszkodzone', 'Uszkodzone']],
    };
    const DODATKI = [
        ['sortowanie_inne', 'Sortowanie inne'],
        ['karta_uszkodzona', 'Podmiana karty uszkodzonej'],
        ['karta_algorytm', 'Podmiana karty ze względu na algorytm'],
        ['worki', 'Etykietowanie worków (liczba worków)'],
    ];
    // Ta sama granica co ILOSC_WYGLADA_NA_KOD w app.py.
    const WYGLADA_NA_KOD = 100000;

    function liczbaPola(input) {
        const n = parseInt(input.value, 10);
        return Number.isFinite(n) ? n : 0;
    }

    // kontener: element; opcje: {tryb, stueckzahl, wartosci, naKoniec}
    function zbuduj(kontener, opcje) {
        const tryb = opcje.tryb === 'zespol' ? 'zespol' : 'wzor';
        const wPaczce = Number.isFinite(opcje.stueckzahl) ? opcje.stueckzahl : 0;
        const wartosci = opcje.wartosci || null;
        const kolumny = KOLUMNY[tryb];

        const pole = (atrybuty) => {
            const wejscie = document.createElement('input');
            wejscie.type = 'number';
            wejscie.min = '0';
            wejscie.step = '1';
            wejscie.inputMode = 'numeric';
            wejscie.autocomplete = 'off';
            // Bez placeholdera „0": pole puste do zatwierdzenia (operacja) — szare
            // zero wygladalo jak juz wpisana wartosc.
            Object.entries(atrybuty).forEach(([k, v]) => { wejscie.dataset[k] = v; });
            return wejscie;
        };

        kontener.innerHTML = '';
        kontener.classList.add('tabela-ilosci');

        const przewijanie = document.createElement('div');
        przewijanie.className = 'ti-przewijanie';
        const tabela = document.createElement('table');
        const naglowek = ['Grupa'];
        if (tryb === 'wzor') naglowek.push('Ilość');
        kolumny.forEach(([, et]) => naglowek.push(et));
        if (tryb === 'wzor') naglowek.push('Pojedynczo');
        tabela.innerHTML = '<thead><tr>' + naglowek.map((t, i) =>
            `<th class="${i === 0 ? '' : 'ti-liczba'} ${t === 'Pojedynczo' && tryb === 'wzor' ? 'ti-system' : ''}">${t}</th>`).join('')
            + '</tr></thead>';
        const cialo = document.createElement('tbody');
        GRUPY.forEach(([g, nazwa]) => {
            const tr = document.createElement('tr');
            tr.dataset.grupa = g;
            const td0 = document.createElement('td');
            td0.textContent = nazwa;
            td0.className = 'ti-grupa';
            tr.appendChild(td0);
            const wiersz = (wartosci && wartosci.grupy && wartosci.grupy[g]) || {};
            const dodajPole = (p) => {
                const td = document.createElement('td');
                const w = pole({ grupa: g, pole: p });
                if (wiersz[p]) w.value = wiersz[p];
                td.appendChild(w);
                tr.appendChild(td);
            };
            if (tryb === 'wzor') {
                const td = document.createElement('td');
                if (g === GLOWNA) {
                    td.className = 'ti-system';
                    td.innerHTML = '<span data-wylicz="ilosc-glowna"></span>';
                    td.title = 'Ilość z pliku minus pozostałe grupy';
                    tr.appendChild(td);
                } else {
                    dodajPole('ilosc');
                }
            }
            kolumny.forEach(([p]) => dodajPole(p));
            if (tryb === 'wzor') {
                const td = document.createElement('td');
                td.className = 'ti-system';
                td.innerHTML = `<span data-wylicz="pojedynczo" data-grupa="${g}"></span>`;
                tr.appendChild(td);
            }
            cialo.appendChild(tr);
        });
        tabela.appendChild(cialo);
        przewijanie.appendChild(tabela);
        kontener.appendChild(przewijanie);

        const dodatki = document.createElement('div');
        dodatki.className = 'ti-dodatki';
        const sortUszk = document.createElement('div');
        sortUszk.className = 'ti-dodatek ti-dodatek-system';
        sortUszk.innerHTML = '<span>Sortowane ze względu na uszkodzenie</span><strong data-wylicz="sort-uszk">0</strong>';
        dodatki.appendChild(sortUszk);
        DODATKI.forEach(([p, nazwa]) => {
            const wiersz = document.createElement('label');
            wiersz.className = 'ti-dodatek';
            const opis = document.createElement('span');
            opis.textContent = nazwa;
            const w = pole({ dodatek: p });
            const zapisane = wartosci && wartosci.dodatki && wartosci.dodatki[p];
            if (zapisane) w.value = zapisane;
            wiersz.appendChild(opis);
            wiersz.appendChild(w);
            dodatki.appendChild(wiersz);
        });
        kontener.appendChild(dodatki);

        const stopka = document.createElement('div');
        stopka.className = 'ti-stopka';
        kontener.appendChild(stopka);

        const pola = () => Array.from(kontener.querySelectorAll('input'));
        const poleGrupy = (g, p) => kontener.querySelector(`input[data-grupa="${g}"][data-pole="${p}"]`);
        const wartoscGrupy = (g, p) => { const w = poleGrupy(g, p); return w ? liczbaPola(w) : 0; };

        // → {grupy: {g: {pole: n}}, ilosc_glowna, bledy: [tekst]}
        function wylicz() {
            const wynik = { grupy: {}, bledy: [], sztuk: 0, uszkodzone: 0 };
            let pozostale = 0;
            GRUPY.forEach(([g]) => {
                const w = {};
                if (tryb === 'wzor' && g !== GLOWNA) w.ilosc = wartoscGrupy(g, 'ilosc');
                kolumny.forEach(([p]) => { w[p] = wartoscGrupy(g, p); });
                if (tryb === 'wzor' && g !== GLOWNA) pozostale += w.ilosc;
                wynik.grupy[g] = w;
            });
            if (tryb === 'wzor') {
                wynik.grupy[GLOWNA].ilosc = wPaczce - pozostale;
                if (wynik.grupy[GLOWNA].ilosc < 0) {
                    wynik.bledy.push(`Akcesoria, okulary i tekstylia razem (${pozostale} szt.) to więcej niż w paczce (${wPaczce} szt.). Sztuki ponad plik wpisz jako „Nadwyżka”.`);
                }
                GRUPY.forEach(([g, nazwa]) => {
                    const w = wynik.grupy[g];
                    w.pojedynczo = w.ilosc - w.brak + w.nadwyzka - w.uszkodzone - w.podwojnie - w.potrojnie;
                    if (w.pojedynczo < 0 && !(g === GLOWNA && w.ilosc < 0)) {
                        wynik.bledy.push(`${nazwa}: „Pojedynczo” wychodzi ${w.pojedynczo} — wpisano więcej niż sztuk w tym wierszu.`);
                    }
                });
            }
            GRUPY.forEach(([g]) => {
                const w = wynik.grupy[g];
                wynik.sztuk += (w.pojedynczo || 0) + w.podwojnie + w.potrojnie + w.uszkodzone;
                wynik.uszkodzone += w.uszkodzone;
            });
            return wynik;
        }

        function przelicz() {
            const w = wylicz();
            const glowna = kontener.querySelector('[data-wylicz="ilosc-glowna"]');
            if (glowna) {
                glowna.textContent = w.grupy[GLOWNA].ilosc;
                glowna.parentElement.classList.toggle('ti-ujemne', w.grupy[GLOWNA].ilosc < 0);
            }
            kontener.querySelectorAll('[data-wylicz="pojedynczo"]').forEach(el => {
                const n = w.grupy[el.dataset.grupa].pojedynczo;
                el.textContent = n;
                el.parentElement.classList.toggle('ti-ujemne', n < 0);
            });
            kontener.querySelector('[data-wylicz="sort-uszk"]').textContent = w.uszkodzone;
            if (tryb === 'wzor') {
                stopka.innerHTML = w.bledy.length
                    ? `<span class="ti-blad">⚠️ ${escapeHtml(w.bledy[0])}</span>`
                    : `Sztuk w tabeli: <strong>${w.sztuk}</strong> (w pliku ${wPaczce})`;
            } else {
                stopka.innerHTML = `Twoje sztuki: <strong>${w.sztuk}</strong>`
                    + ' <span class="ti-uwaga">(Pojedynczo + Podwójnie + Potrójnie + Uszkodzone — tyle idzie do Norm)</span>';
            }
            return w;
        }

        // → {tabela, blad, pole}. Puste pola = 0 (dopiero tu, nie wczesniej).
        function odczytaj() {
            for (const w of pola()) {
                const n = parseInt(w.value, 10);
                if (w.value.trim() !== '' && !Number.isFinite(n)) {
                    return { blad: 'Wpisz liczbę całkowitą.', pole: w };
                }
                if (n < 0) return { blad: 'Ilość nie może być ujemna.', pole: w };
                if (n >= WYGLADA_NA_KOD) {
                    return { blad: `Ilość ${n} wygląda na zeskanowany kod, nie liczbę sztuk — popraw pole.`, pole: w };
                }
            }
            const w = przelicz();
            if (w.bledy.length) return { blad: w.bledy[0], pole: null };
            const tabelaWynik = { grupy: {}, dodatki: {} };
            GRUPY.forEach(([g]) => {
                tabelaWynik.grupy[g] = {};
                kontener.querySelectorAll(`input[data-grupa="${g}"]`).forEach(el => {
                    tabelaWynik.grupy[g][el.dataset.pole] = liczbaPola(el);
                });
            });
            kontener.querySelectorAll('input[data-dodatek]').forEach(el => {
                tabelaWynik.dodatki[el.dataset.dodatek] = liczbaPola(el);
            });
            return { tabela: tabelaWynik, blad: null, wyliczone: w };
        }

        // Enter = nastepne pole (skaner i klawiatura numeryczna), w ostatnim — zapis.
        kontener.addEventListener('keydown', (e) => {
            if (e.key !== 'Enter' || e.target.tagName !== 'INPUT') return;
            e.preventDefault();
            const lista = pola();
            const i = lista.indexOf(e.target);
            if (i >= 0 && i < lista.length - 1) lista[i + 1].focus();
            else if (opcje.naKoniec) opcje.naKoniec();
        });
        kontener.addEventListener('input', przelicz);
        przelicz();

        return {
            tryb,
            odczytaj,
            przelicz,
            pierwszePole: () => pola()[0] || null,
        };
    }

    return { zbuduj, GRUPY, DODATKI };
})();
