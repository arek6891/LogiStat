// Skrypt strony templates/dekoracje_skan.html (2026-10-28): Operacje magazynowe →
// Skan stojaków. Krok 1 nosnik (GET /api/dekoracje/nosnik), krok 2 strefa
// (POST /api/dekoracje/skan). Skaner konczy kod Enterem. Tekst z bazy przez textContent.
(() => {
    const pole = document.getElementById('skanPole');
    if (!pole) return;   // brak stref — ekran pokazuje tylko komunikat
    const pytanie = document.getElementById('skanPytanie');
    const info = document.getElementById('skanInfo');
    const krokEl = document.getElementById('skanKrok');
    const wstecz = document.getElementById('skanWstecz');
    const ostatni = document.getElementById('skanOstatni');
    let nosnik = null;
    let zajete = false;

    function el(tag, tekst) {
        const e = document.createElement(tag);
        e.textContent = tekst;
        return e;
    }

    function krok1() {
        nosnik = null;
        krokEl.textContent = 'Krok 1 / 2';
        pytanie.textContent = 'Zeskanuj nośnik';
        info.hidden = true;
        wstecz.hidden = true;
        pole.value = '';
        pole.focus();
    }

    function krok2(dane) {
        nosnik = dane.nosnik;
        krokEl.textContent = 'Krok 2 / 2';
        pytanie.textContent = 'Zeskanuj strefę';
        const s = dane.stojak;
        const wiersze = [['Nośnik', dane.nosnik]];
        if (dane.nowy) wiersze.push(['', 'Nowy nośnik — zapis założy stojak w stocku']);
        else {
            wiersze.push(['Teraz w strefie', s.strefa || '—'], ['POS', s.pos || '—'], ['Akcja', s.akcja || '—']);
        }
        info.replaceChildren(...wiersze.map(([k, v]) => {
            const p = el('p', '');
            if (k) p.append(el('small', k + ': '));
            p.append(el('strong', v));
            return p;
        }));
        info.hidden = false;
        wstecz.hidden = false;
        pole.value = '';
        pole.focus();
    }

    async function wyslij() {
        const kod = pole.value.trim();
        if (!kod || zajete) return;
        zajete = true;
        pole.disabled = true;
        try {
            const res = nosnik === null
                ? await fetch('/api/dekoracje/nosnik?kod=' + encodeURIComponent(kod))
                : await fetch('/api/dekoracje/skan', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ nosnik, strefa: kod }) });
            if (!res.ok) {
                await pokazBladOdpowiedzi(res);
                pole.value = '';
                return;
            }
            const dane = await res.json();
            if (nosnik === null) return krok2(dane);
            const s = dane.stojak;
            const tekst = dane.przeniesiono
                ? `${s.nosnik} → strefa ${s.strefa}${dane.nowy ? ' (nowy stojak)' : ''}`
                : `${s.nosnik} już był w strefie ${s.strefa} — bez zmian`;
            ostatni.textContent = '✓ ' + tekst;
            ostatni.hidden = false;
            showToast(tekst, 'success');
            krok1();
        } finally {
            zajete = false;
            pole.disabled = false;
            pole.focus();
        }
    }

    pole.addEventListener('keydown', e => {
        if (e.key === 'Enter') { e.preventDefault(); wyslij(); }
    });
    wstecz.addEventListener('click', krok1);
    krok1();
})();
