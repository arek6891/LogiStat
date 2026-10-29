// Skrypt strony templates/dekoracje_dostawy.html (2026-10-29): Operacje magazynowe →
// Dekoracje → Dostawy. Ekran 1: wybor akcji. Dalej wedlug typu dostawy akcji:
// - kontener: nr kontenera (GET …/kontener?kod=) → wiersze artykul / kartony / PU
//   (POST …/kontener, `token` raz na wiersz — ponowienie po bledzie nie dubluje),
// - beeline: skan kartonu (POST …/beeline; ten sam karton drugi raz → 409).
// Skaner konczy kod Enterem. Tekst z bazy przez textContent.
(() => {
    const ekran = document.getElementById('dostawaEkran');
    const naglowekAkcji = document.getElementById('dostawaAkcja');
    const ostatni = document.getElementById('dostawaOstatni');
    let akcja = null;
    let zajete = false;

    function nowyToken() {
        // crypto.randomUUID wymaga HTTPS; .31 dziala tez po zwyklym HTTP.
        if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
        return Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 12)
            + Math.random().toString(36).slice(2, 12);
    }

    function el(tag, klasa, tekst) {
        const e = document.createElement(tag);
        if (klasa) e.className = klasa;
        if (tekst !== undefined) e.textContent = tekst;
        return e;
    }

    function przycisk(klasa, tekst, akcjaKlik) {
        const b = el('button', 'btn ' + klasa, tekst);
        b.type = 'button';
        b.addEventListener('click', akcjaKlik);
        return b;
    }

    function pole(etykieta, typ) {
        const grupa = el('div', 'form-group');
        const label = el('label', '', etykieta);
        const input = el('input', 'form-control przyjecie-pole');
        input.type = typ;
        input.autocomplete = 'off';
        if (typ === 'number') {
            input.min = '0';
            input.max = String(DOSTAWY.max_liczby - 1);
            input.step = '1';
            input.inputMode = 'numeric';
        } else {
            input.classList.add('przyjecie-duze-litery');
        }
        grupa.append(label, input);
        return [grupa, input];
    }

    function nawigacja(...przyciski) {
        const n = el('div', 'przyjecie-nawigacja');
        n.append(...przyciski);
        return n;
    }

    function pokazOstatni(tekst) {
        ostatni.textContent = '✓ ' + tekst;
        ostatni.hidden = false;
        showToast(tekst, 'success');
    }

    async function wyslij(url, opcje) {
        // null = blad (komunikat juz pokazany); zajete chroni przed podwojnym Enterem.
        if (zajete) return null;
        zajete = true;
        ekran.querySelectorAll('input, button').forEach(e => { e.disabled = true; });
        try {
            const res = await fetch(url, opcje);
            if (!res.ok) {
                ostatni.hidden = true;   // stary zielony „✓” nie moze wisiec nad bledem
                await pokazBladOdpowiedzi(res);
                return null;
            }
            return await res.json();
        } catch (err) {
            showToast('Brak połączenia — spróbuj jeszcze raz.', 'error');
            return null;
        } finally {
            zajete = false;
            ekran.querySelectorAll('input, button').forEach(e => { e.disabled = false; });
        }
    }

    // ── Ekran 1: wybor akcji ──
    function wyborAkcji() {
        akcja = null;
        naglowekAkcji.textContent = '';
        ostatni.hidden = true;
        ekran.replaceChildren(el('p', 'przyjecie-pytanie', 'Wybierz akcję'));
        if (!DOSTAWY.akcje.length) {
            ekran.append(el('p', 'przyjecie-blokada', 'Nie ma akcji w toku. Logistyk zakłada je w Dekoracje → Akcje.'));
            return;
        }
        const opcje = el('div', 'przyjecie-opcje');
        DOSTAWY.akcje.forEach(a => {
            const b = el('button', 'btn przyjecie-opcja dostawa-akcja');
            b.type = 'button';
            b.append(el('span', '', a.nazwa), el('small', 'dostawa-opcja-opis',
                a.typ ? a.typ_nazwa : '⚠ Typ dostawy nie ustalony'));
            if (!a.typ) {
                b.disabled = true;
                b.title = 'Logistyk ustawia typ dostawy na ekranie akcji (Dekoracje → Akcje).';
            } else {
                b.addEventListener('click', () => {
                    akcja = a;
                    naglowekAkcji.textContent = `${a.nazwa} · ${a.typ_nazwa}`;
                    if (a.typ === 'kontener') krokKontener(); else krokBeeline();
                });
            }
            opcje.append(b);
        });
        ekran.append(opcje);
    }

    // ── Kontenerowa: krok 1 nr kontenera ──
    function krokKontener() {
        ostatni.hidden = true;
        const [grupa, input] = pole('Nr kontenera', 'text');
        ekran.replaceChildren(el('p', 'przyjecie-pytanie', 'Zeskanuj albo wpisz nr kontenera'), grupa,
            nawigacja(przycisk('przyjecie-wstecz', '← Inna akcja', wyborAkcji), el('span')));
        input.addEventListener('keydown', async e => {
            if (e.key !== 'Enter') return;
            e.preventDefault();
            const kod = input.value.trim();
            if (!kod) return;
            const dane = await wyslij(`/api/dekoracje/akcje/${akcja.id}/kontener?kod=${encodeURIComponent(kod)}`);
            if (dane) krokWiersze(dane); else input.focus();
        });
        input.focus();
    }

    function tabelaWierszy(dane) {
        const box = el('div', 'dostawa-wiersze');
        const r = dane.razem;
        box.append(el('p', 'dostawa-razem',
            `Kontener ${dane.kontener}: wierszy ${r.wierszy} · kartonów ${r.kartony} · PU ${r.pu}`));
        if (dane.wiersze.length) {
            const t = el('table', 'data-table');
            const g = el('tr');
            ['Artykuł', 'Kartony', 'PU', 'Wpisano'].forEach(n => g.append(el('th', '', n)));
            t.append(el('thead'));
            t.tHead.append(g);
            const tb = el('tbody');
            // Najnowsze na gorze — magazynier widzi, co wlasnie zapisal.
            dane.wiersze.slice().reverse().slice(0, 10).forEach(w => {
                const tr = el('tr');
                [w.artykul, w.kartony, w.pu, w.kiedy].forEach(v => tr.append(el('td', '', String(v))));
                tb.append(tr);
            });
            t.append(tb);
            box.append(t);
            if (dane.wiersze.length > 10) box.append(el('small', '', `… i ${dane.wiersze.length - 10} starszych`));
        }
        return box;
    }

    // ── Kontenerowa: krok 2 wiersze artykul / kartony / PU ──
    function krokWiersze(dane) {
        let token = nowyToken();
        const [gA, artykul] = pole('Nr artykułu', 'text');
        const [gK, kartony] = pole('Kartony', 'number');
        const [gP, pu] = pole('PU', 'number');
        const siatka = el('div', 'dostawa-formularz');
        siatka.append(gA, gK, gP);
        const lista = el('div');
        lista.append(tabelaWierszy(dane));
        const zapisz = przycisk('przyjecie-dalej', '💾 Zapisz wiersz', zapiszWiersz);
        ekran.replaceChildren(
            el('p', 'przyjecie-pytanie', `Kontener ${dane.kontener}${dane.nowy ? ' (nowy)' : ''}`),
            siatka,
            nawigacja(przycisk('przyjecie-wstecz', '← Inny kontener', krokKontener), zapisz),
            lista);
        // Enter przechodzi dalej: artykul → kartony → PU → zapis.
        artykul.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); kartony.focus(); } });
        kartony.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); pu.focus(); } });
        pu.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); zapiszWiersz(); } });
        // Zmiana danych = nowy wiersz (stary token zostaje tylko dla ponowienia tego samego).
        [artykul, kartony, pu].forEach(p => p.addEventListener('input', () => { token = nowyToken(); }));
        artykul.focus();

        function liczba(p) {
            const v = p.value.trim();
            return v === '' ? 0 : Number(v);
        }

        async function zapiszWiersz() {
            if (!artykul.value.trim()) { artykul.focus(); return; }
            if (kartony.value.trim() === '' && pu.value.trim() === '') { kartony.focus(); return; }
            const wynik = await wyslij(`/api/dekoracje/akcje/${akcja.id}/kontener`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ kontener: dane.kontener, artykul: artykul.value, kartony: liczba(kartony),
                                       pu: liczba(pu), token }),
            });
            if (!wynik) { artykul.focus(); return; }
            pokazOstatni(`${dane.kontener}: ${artykul.value.trim().toUpperCase()} — kartony ${liczba(kartony)}, PU ${liczba(pu)}`);
            dane = wynik;
            token = nowyToken();
            artykul.value = kartony.value = pu.value = '';
            lista.replaceChildren(tabelaWierszy(dane));
            artykul.focus();
        }
    }

    // ── Beeline: skan kartonu ──
    function krokBeeline() {
        ostatni.hidden = true;
        const [grupa, input] = pole('Nr kartonu', 'text');
        const licznik = el('p', 'dostawa-razem',
            `Kartonów w akcji: ${akcja.kartonow ?? 0}`);
        ekran.replaceChildren(el('p', 'przyjecie-pytanie', 'Zeskanuj kod kartonu'), grupa, licznik,
            nawigacja(przycisk('przyjecie-wstecz', '← Inna akcja', wyborAkcji), el('span')));
        input.addEventListener('keydown', async e => {
            if (e.key !== 'Enter') return;
            e.preventDefault();
            const numer = input.value.trim();
            if (!numer) return;
            const wynik = await wyslij(`/api/dekoracje/akcje/${akcja.id}/beeline`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ numer }),
            });
            input.value = '';
            input.focus();
            if (!wynik) return;
            akcja.kartonow = wynik.kartonow;
            licznik.textContent = `Kartonów w akcji: ${wynik.kartonow}`;
            pokazOstatni(`Karton ${wynik.numer} zapisany`);
        });
        input.focus();
    }

    wyborAkcji();
})();
