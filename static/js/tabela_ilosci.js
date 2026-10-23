// Tabela ilosci na koniec paczki — wersja 2 (operacja, 2026-10-23).
// Jeden komponent dla stanowiska („Czasy paczek") i okna lidera („✎ Ilosci"
// na /paczki). Liczy na biezaco to samo co normalizuj_tabele() /
// nadwyzka_brak() w logistat/tabela_ilosci.py — serwer i tak liczy po swojej
// stronie, tu tylko podglad dla operatora.
//
// Operator wpisuje wszystko wprost (oba tryby tak samo): per grupa Ilosc
// (pojedyncze) / Uszkodzone / Niesprocesowane, pod tabela Flagi – Card Change,
// Podwojne i Potrojne (cala paczka). Nadwyzka i Brak liczy system: wpisane
// sztuki − ilosc z pliku. Tryb 'zespol' (paczka kilku osob): kazdy wpisuje swoja
// czesc, Nadwyzka/Brak wychodzi dopiero z sumy wszystkich — tu tylko „Twoje sztuki".
const TabelaIlosci = (() => {
    const WERSJA = 2;
    const GRUPY = [
        ['bizuteria', 'Biżuteria'],
        ['akcesoria', 'Akcesoria'],
        ['okulary', 'Okulary'],
        ['tekstylia', 'Tekstylia'],
    ];
    const KOLUMNY = [['ilosc', 'Ilość (pojedyncze)'], ['uszkodzone', 'Uszkodzone'],
                     ['niesprocesowane', 'Niesprocesowane']];
    // Pola na cala paczke — kolejnosc = kolejnosc Entera.
    const KARTY = ['karty', '🚩 Flagi – Card Change'];
    const NA_DOLE = [['podwojnie', 'Podwójne'], ['potrojnie', 'Potrójne']];
    // Ta sama granica co ILOSC_WYGLADA_NA_KOD w logistat/tabela_ilosci.py.
    const WYGLADA_NA_KOD = 100000;

    function liczbaPola(input) {
        const n = parseInt(input.value, 10);
        return Number.isFinite(n) ? n : 0;
    }

    // kontener: element; opcje: {tryb, stueckzahl, wartosci, naKoniec}
    function zbuduj(kontener, opcje) {
        const tryb = opcje.tryb === 'zespol' ? 'zespol' : 'wzor';
        const wPaczce = Number.isFinite(opcje.stueckzahl) ? opcje.stueckzahl : 0;
        const wartosci = opcje.wartosci || {};

        const pole = (atrybuty, zapisane) => {
            const wejscie = document.createElement('input');
            wejscie.type = 'number';
            wejscie.min = '0';
            wejscie.step = '1';
            wejscie.inputMode = 'numeric';
            wejscie.autocomplete = 'off';
            // Bez placeholdera „0": pole puste do zatwierdzenia (operacja) — szare
            // zero wygladalo jak juz wpisana wartosc.
            Object.entries(atrybuty).forEach(([k, v]) => { wejscie.dataset[k] = v; });
            if (zapisane) wejscie.value = zapisane;
            return wejscie;
        };

        kontener.innerHTML = '';
        kontener.classList.add('tabela-ilosci');

        // Duza ilosc z pliku na gorze (operacja: ma byc widoczna od razu).
        const naglowek = document.createElement('div');
        naglowek.className = 'ti-w-paczce';
        naglowek.innerHTML = `<span>W paczce</span><strong>${wPaczce}</strong><span>szt.</span>`;
        kontener.appendChild(naglowek);

        const przewijanie = document.createElement('div');
        przewijanie.className = 'ti-przewijanie';
        const tabela = document.createElement('table');
        tabela.innerHTML = '<thead><tr><th>Grupa</th>'
            + KOLUMNY.map(([, et]) => `<th class="ti-liczba">${et}</th>`).join('') + '</tr></thead>';
        const cialo = document.createElement('tbody');
        GRUPY.forEach(([g, nazwa]) => {
            const tr = document.createElement('tr');
            const td0 = document.createElement('td');
            td0.textContent = nazwa;
            td0.className = 'ti-grupa';
            tr.appendChild(td0);
            const zapisane = (wartosci.grupy && wartosci.grupy[g]) || {};
            KOLUMNY.forEach(([p]) => {
                const td = document.createElement('td');
                td.appendChild(pole({ grupa: g, pole: p }, zapisane[p]));
                tr.appendChild(td);
            });
            cialo.appendChild(tr);
        });
        // Flagi pod Tekstyliami — liczba podmienionych kart (Card facture).
        const trKarty = document.createElement('tr');
        trKarty.className = 'ti-flagi';
        const tdKartyNazwa = document.createElement('td');
        tdKartyNazwa.className = 'ti-grupa';
        tdKartyNazwa.textContent = KARTY[1];
        const tdKarty = document.createElement('td');
        tdKarty.appendChild(pole({ paczka: KARTY[0] }, wartosci[KARTY[0]]));
        const tdKartyOpis = document.createElement('td');
        tdKartyOpis.colSpan = KOLUMNY.length - 1;
        tdKartyOpis.className = 'ti-uwaga';
        tdKartyOpis.textContent = 'liczba kart';
        trKarty.append(tdKartyNazwa, tdKarty, tdKartyOpis);
        cialo.appendChild(trKarty);
        tabela.appendChild(cialo);
        przewijanie.appendChild(tabela);
        kontener.appendChild(przewijanie);

        const naDole = document.createElement('div');
        naDole.className = 'ti-na-dole';
        NA_DOLE.forEach(([p, nazwa]) => {
            const wiersz = document.createElement('label');
            wiersz.className = 'ti-pole-paczki';
            const opis = document.createElement('span');
            opis.textContent = nazwa;
            wiersz.append(opis, pole({ paczka: p }, wartosci[p]));
            naDole.appendChild(wiersz);
        });
        kontener.appendChild(naDole);

        const stopka = document.createElement('div');
        stopka.className = 'ti-stopka';
        kontener.appendChild(stopka);

        const pola = () => Array.from(kontener.querySelectorAll('input'));

        // → {tabela, sztuk, nadwyzka, brak} — sztuki jak sztuki_tabeli() na serwerze.
        function wylicz() {
            const t = { wersja: WERSJA, grupy: {} };
            let sztuk = 0;
            GRUPY.forEach(([g]) => {
                t.grupy[g] = {};
                KOLUMNY.forEach(([p]) => {
                    const w = kontener.querySelector(`input[data-grupa="${g}"][data-pole="${p}"]`);
                    t.grupy[g][p] = liczbaPola(w);
                    sztuk += t.grupy[g][p];
                });
            });
            [KARTY, ...NA_DOLE].forEach(([p]) => {
                t[p] = liczbaPola(kontener.querySelector(`input[data-paczka="${p}"]`));
            });
            sztuk += t.podwojnie + t.potrojnie;
            const roznica = sztuk - wPaczce;
            return { tabela: t, sztuk, nadwyzka: Math.max(roznica, 0), brak: Math.max(-roznica, 0) };
        }

        function przelicz() {
            const w = wylicz();
            if (tryb === 'wzor') {
                const zgodne = !w.nadwyzka && !w.brak;
                stopka.innerHTML =
                    `<div class="ti-wynik ${zgodne ? 'ti-ok' : ''}"><span>Wpisane razem</span>`
                    + `<strong>${w.sztuk} / ${wPaczce}</strong></div>`
                    + `<div class="ti-wynik ${w.nadwyzka ? 'ti-roznica' : ''}"><span>Nadwyżka</span><strong>${w.nadwyzka}</strong></div>`
                    + `<div class="ti-wynik ${w.brak ? 'ti-roznica' : ''}"><span>Brak</span><strong>${w.brak}</strong></div>`;
            } else {
                stopka.innerHTML =
                    `<div class="ti-wynik"><span>Twoje sztuki</span><strong>${w.sztuk}</strong></div>`
                    + '<div class="ti-uwaga">Nadwyżkę i brak system policzy z sumy wszystkich osób przy paczce.</div>';
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
            // Nic nie liczy sie samo, wiec nietknieta tabela (wszystkie pola puste)
            // to najczesciej przypadkowy Enter. Bez okna z pytaniem — Enter skanera
            // by je zatwierdzil (docs/REVIEW.md). Pusta paczka = swiadomie wpisane
            // „0” (cala ilosc wyjdzie jako Brak, ❗ dla lidera).
            if (tryb === 'wzor' && wPaczce > 0 && pola().every(p => p.value.trim() === '')) {
                return { blad: 'Nic nie wpisano. Jeśli paczka jest pusta (wszystko to brak), '
                               + 'wpisz 0 w „Ilość” biżuterii.', pole: pola()[0] || null };
            }
            return { tabela: w.tabela, blad: null, wyliczone: w };
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

    return { zbuduj, GRUPY };
})();
