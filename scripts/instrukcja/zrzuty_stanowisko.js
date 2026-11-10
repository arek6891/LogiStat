async (page) => {
  // Zrzuty laduja w .playwright-mcp/zrzuty/ (gitignore) — tylko tam MCP Playwright moze pisac.
  const D = '/opt/LogiStat/.playwright-mcp/zrzuty/';
  const B = 'http://127.0.0.1:5099';
  // Rysuje na stronie ramki, numerki i strzalki: [{sel, nth?, text?, n, tekst?, gdzie: right|left|top|bottom, odl?, dx?, pad?}].
  const oznacz = (items) => {
    document.querySelectorAll('.__ozn').forEach(e => e.remove());
    const KOLOR = '#E11D48';
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', '__ozn');
    Object.assign(svg.style, {position: 'absolute', left: 0, top: 0, width: document.documentElement.scrollWidth + 'px',
      height: document.documentElement.scrollHeight + 'px', pointerEvents: 'none', zIndex: 99998});
    svg.innerHTML = `<defs><marker id="__grot" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="${KOLOR}"/></marker></defs>`;
    document.body.appendChild(svg);
    const brak = [];
    for (const it of items) {
      let el;
      if (it.text) {
        const kand = [...document.querySelectorAll(it.sel || '*')].filter(e => e.offsetParent !== null && e.textContent.trim().startsWith(it.text));
        kand.sort((a, b) => a.textContent.length - b.textContent.length);
        el = kand[0];
      } else {
        el = [...document.querySelectorAll(it.sel)].filter(e => e.offsetParent !== null || e.tagName === 'svg')[it.nth || 0];
      }
      if (!el) { brak.push(it.n); continue; }
      const r = el.getBoundingClientRect();
      const sx = window.scrollX, sy = window.scrollY;
      const pad = it.pad ?? 4;
      const box = document.createElement('div');
      box.className = '__ozn';
      Object.assign(box.style, {position: 'absolute', left: (r.left + sx - pad) + 'px', top: (r.top + sy - pad) + 'px',
        width: (r.width + 2 * pad) + 'px', height: (r.height + 2 * pad) + 'px', border: `3px solid ${KOLOR}`,
        borderRadius: '8px', zIndex: 99997, pointerEvents: 'none', boxSizing: 'border-box'});
      document.body.appendChild(box);
      const g = it.gdzie || 'right', odl = it.odl || 70;
      const lab = document.createElement('div');
      lab.className = '__ozn';
      lab.innerHTML = `<span style="display:inline-flex;align-items:center;justify-content:center;width:26px;height:26px;border-radius:50%;background:${KOLOR};color:#fff;font-weight:800;font-size:15px;margin-right:${it.tekst ? 8 : 0}px;flex:none">${it.n}</span>${it.tekst ? `<span>${it.tekst}</span>` : ''}`;
      Object.assign(lab.style, {position: 'absolute', display: 'flex', alignItems: 'center', background: '#fff',
        border: `2px solid ${KOLOR}`, borderRadius: '18px', padding: '3px 12px 3px 3px', font: '600 14px Inter, sans-serif',
        color: '#111', zIndex: 99999, whiteSpace: 'nowrap', boxShadow: '0 2px 8px rgb(0 0 0 / .25)', pointerEvents: 'none'});
      document.body.appendChild(lab);
      const lw = lab.offsetWidth, lh = lab.offsetHeight;
      const cx = r.left + sx + r.width / 2, cy = r.top + sy + r.height / 2;
      let lx, ly, ax, ay;
      if (g === 'right') { lx = r.right + sx + odl; ly = cy - lh / 2; ax = r.right + sx + pad + 2; ay = cy; }
      if (g === 'left')  { lx = r.left + sx - odl - lw; ly = cy - lh / 2; ax = r.left + sx - pad - 2; ay = cy; }
      if (g === 'top')   { lx = cx - lw / 2 + (it.dx || 0); ly = r.top + sy - odl - lh; ax = cx; ay = r.top + sy - pad - 2; }
      if (g === 'bottom'){ lx = cx - lw / 2 + (it.dx || 0); ly = r.bottom + sy + odl; ax = cx; ay = r.bottom + sy + pad + 2; }
      lx = Math.max(6, Math.min(lx, document.documentElement.clientWidth - lw - 6)); ly = Math.max(6, ly);
      lab.style.left = lx + 'px'; lab.style.top = ly + 'px';
      let px = g === 'right' ? lx : g === 'left' ? lx + lw : lx + lw / 2;
      const py = g === 'top' ? ly + lh : g === 'bottom' ? ly : ly + lh / 2;
      if (g === 'top' || g === 'bottom') px = Math.min(Math.max(px, lx + 13), lx + lw - 13);
      const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      Object.entries({x1: px, y1: py, x2: ax, y2: ay, stroke: KOLOR, 'stroke-width': 3, 'marker-end': 'url(#__grot)'}).forEach(([k, v]) => line.setAttribute(k, v));
      svg.appendChild(line);
    }
    return brak;
  };
  const ctx = await page.context().browser().newContext({timezoneId: 'Europe/Warsaw', locale: 'pl-PL', viewport: {width: 1440, height: 900}});
  await ctx.addInitScript(`window.__oznacz = ${oznacz.toString()};`);
  const p = await ctx.newPage();
  const login = async (u, pw) => {
    await p.goto(B + '/login');
    await p.fill('input[name=username]', u);
    await p.fill('input[name=password]', pw);
    await p.click('button[type=submit]');
    await p.waitForLoadState('networkidle');
  };
  const wynik = {};
  const shot = async (name, items, opts = {}) => {
    await p.evaluate(() => document.querySelectorAll('.toast-container').forEach(e => e.remove()));
    wynik[name] = await p.evaluate((it) => window.__oznacz(it), items);
    await p.screenshot({path: D + name + '.png', ...opts});
  };
  const skan = async (sel, kod) => { await p.fill(sel, kod); await p.press(sel, 'Enter'); await p.waitForTimeout(900); };

  await login('stanowisko1', 'DemoSt2026');

  // Ekran po zalogowaniu: cztery kafelki Operacji magazynowych (od 2026-11-06)
  // Kafelki same opisuja, co zawieraja — bez ramek (napisy zaslanialy naglowek).
  await shot('01_kafelki_magazynu', []);

  // Czas pracy — szkolenie
  await p.goto(B + '/time-tracking');
  await p.click('#tab-training');
  await skan('#scanInput', 'P0005');
  await shot('02_czas_pracy', [
    {sel: '#tab-break', n: 1, tekst: 'Przerwa', gdzie: 'top', odl: 18, dx: -60},
    {sel: '#tab-other', n: 2, tekst: 'Inne (np. HR)', gdzie: 'top', odl: 18, dx: -10},
    {sel: '#tab-training', n: 3, tekst: 'Szkolenie', gdzie: 'top', odl: 18, dx: 70},
    {sel: '#tab-work-end', n: 4, tekst: 'Koniec pracy', gdzie: 'right'},
    {sel: '#scanInput', n: 5, tekst: 'Tu skanujesz identyfikator', gdzie: 'right'},
    {sel: '#szkoleniePanel', n: 6, tekst: 'Trwające szkolenie i osoby szkolone', gdzie: 'left', odl: 40},
    {sel: '#szkoleniePanel .btn-danger', n: 7, tekst: 'Zakończ szkolenie', gdzie: 'right', odl: 420},
  ]);

  // Czasy paczek — start
  const d = new Intl.DateTimeFormat('pl-PL', {timeZone: 'Europe/Warsaw', month: '2-digit', day: '2-digit'}).formatToParts(new Date());
  const mmdd = d.find(x => x.type === 'month').value + d.find(x => x.type === 'day').value;
  const paczka = mmdd + '00057';
  await p.goto(B + '/scan-paczki');
  await skan('#start-emp', 'P0001');
  await shot('03_paczka_start', [
    {sel: '.scan-tab', nth: 0, n: 1, gdzie: 'bottom', odl: 14},
    {sel: '.scan-tab', nth: 1, n: 2, gdzie: 'bottom', odl: 14},
    {sel: '.scan-tab', nth: 2, n: 3, gdzie: 'bottom', odl: 14},
    {sel: '.scan-tab', nth: 3, n: 4, gdzie: 'bottom', odl: 14},
    {sel: '#start-emp', n: 5, tekst: 'Krok 1: identyfikator', gdzie: 'right'},
    {sel: '#start-pkg', n: 6, tekst: 'Krok 2: kod paczki', gdzie: 'right'},
  ]);
  await skan('#start-pkg', paczka);

  // Czasy paczek — koniec, tabela ilosci
  await p.click('.scan-tab[data-tab=end]');
  await p.setViewportSize({width: 1440, height: 1760});
  await skan('#end-emp', 'P0001');
  await skan('#end-pkg', paczka);
  await p.waitForTimeout(600);
  const pola = await p.$$('#end-qty-tabela input');
  const wart = ['30', '1', '', '6', '', '', '', '', '', '2', '', '', '', '1', ''];
  for (let i = 0; i < pola.length && i < wart.length; i++) if (wart[i]) await pola[i].fill(wart[i]);
  await shot('04_paczka_koniec', [
    {sel: '#end-qty-tabela table', n: 1, tekst: 'Ilości per grupa', gdzie: 'right', odl: 16, pad: 2},
    {text: 'Wpisane razem', sel: 'div', n: 5, tekst: 'Liczy SARA', gdzie: 'top', odl: 8, dx: 640},
    {sel: '#end-qty-barcode', n: 2, tekst: 'Paczka i liczba sztuk z pliku', gdzie: 'right'},
    {sel: '.przycisk-anuluj', nth: 0, n: 3, tekst: 'Anuluj', gdzie: 'right', odl: 30},
    {sel: '.przycisk-zapisz', nth: 0, n: 4, tekst: 'Zapisz koniec', gdzie: 'top', odl: 20},
  ]);
  await p.click('.przycisk-anuluj');
  await p.setViewportSize({width: 1440, height: 900});

  // Przyjecie zwrotu
  await p.goto(B + '/zwroty/przyjecie');
  await p.waitForTimeout(800);
  await shot('05_zwrot_krok1', [
    {sel: '#przyjecieObsada', n: 1, tekst: 'Kto jest na tym stanowisku', gdzie: 'bottom', odl: 6, dx: 60},
    {sel: '#przyjecieEkran input', n: 2, tekst: 'Zeskanuj numer paczki', gdzie: 'bottom', odl: 40, dx: -200},
    {sel: '#przyjecieKrok', n: 3, tekst: 'Który krok', gdzie: 'left'},
  ]);
  await skan('#przyjecieEkran input.przyjecie-pole', '003404341234567890');
  await shot('06_zwrot_brand', [
    {sel: '#przyjecieWybrane', n: 1, tekst: 'Co już wybrano', gdzie: 'right'},
    {sel: '#przyjecieEkran button', nth: 1, n: 2, tekst: 'Kliknij brand', gdzie: 'bottom', odl: 14},
    {sel: '.przyjecie-wstecz', n: 3, tekst: 'Krok wstecz', gdzie: 'right'},
  ]);

  // Stanowisko bez obsady — blokada przyjecia (konto demo stanowisko3 bez przydzialu)
  await p.goto(B + '/start');
  await p.click('form[action$="/logout"] button');
  await login('stanowisko3', 'DemoSt2026');
  await p.goto(B + '/zwroty/przyjecie');
  await p.waitForTimeout(800);
  await shot('07_zwrot_blokada', [
    {sel: '.przyjecie-blokada', n: 1, tekst: 'Nikt nie jest przydzielony', gdzie: 'bottom', odl: 30},
    {sel: '.przyjecie-dalej', n: 2, tekst: 'Po przydziale: sprawdź ponownie', gdzie: 'bottom', odl: 30, dx: -120},
  ]);
  await ctx.close();
  return wynik;
}
