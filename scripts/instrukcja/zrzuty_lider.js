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
  await p.goto(B + '/login');
  await p.fill('input[name=username]', 'lider');
  await p.fill('input[name=password]', 'DemoLider2026');
  await p.click('button[type=submit]');
  await p.waitForLoadState('networkidle');
  const wynik = {};
  const shot = async (name, items, opts = {}) => {
    await p.waitForTimeout(1200);
    await p.evaluate(() => document.querySelectorAll('.toast-container').forEach(e => e.remove()));
    wynik[name] = await p.evaluate((it) => window.__oznacz(it), items);
    await p.screenshot({path: D + name + '.png', ...opts});
  };

  await p.goto(B + '/assignment');
  await shot('10_przydzielanie', [
    {sel: '#assignDate', n: 1, tekst: 'Data', gdzie: 'bottom', odl: 10},
    {sel: '.assignment-controls .shift-tabs', n: 2, tekst: 'Zmiana', gdzie: 'bottom', odl: 10},
    {text: '🤖 Sugestie AI', sel: 'button', n: 3, tekst: 'Sugestie AI', gdzie: 'bottom', odl: 10},
    {sel: '#unassignedZone', n: 4, tekst: 'Nieprzydzieleni', gdzie: 'bottom', odl: 10, pad: 2},
    {sel: '#doZrobieniaPP', n: 5, tekst: 'Do zrobienia i szacunek', gdzie: 'left', odl: 40},
    {sel: '.assignment-user-card', nth: 1, n: 6, tekst: 'Karta osoby (grupa P1–P3, 📊)', gdzie: 'right', odl: 40},
  ]);

  await p.goto(B + '/worker-times');
  await shot('11_czasy_pracownikow', [
    {sel: '#dateFilter', n: 1, tekst: 'Dzień', gdzie: 'bottom', odl: 10},
    {sel: '#workerFilter', n: 2, tekst: 'Jedna osoba — wiele dni', gdzie: 'bottom', odl: 10},
    {sel: '#errorFilter', n: 3, tekst: 'Tylko błędy', gdzie: 'bottom', odl: 10, dx: 150},
    {sel: '.os-tor', nth: 1, n: 4, tekst: 'Oś dnia: klik = popraw / dodaj', gdzie: 'top', odl: 22, dx: 250},
  ]);

  await p.goto(B + '/dashboard');
  await shot('12_dashboard', [
    {sel: 'div:has(> #tab-dzis)', n: 1, tekst: 'Zakładki', gdzie: 'right', odl: 30},
    {sel: '#planDzis', n: 2, tekst: 'Plan dzisiejszej Loading date', gdzie: 'right', odl: 10, pad: 2},
    {sel: '#doPotwierdzeniaVal', n: 3, tekst: 'Klik = lista do potwierdzenia', gdzie: 'right', odl: 60},
  ]);

  await p.goto(B + '/paczki');
  await shot('13_paczki', [
    {sel: '#fpDateTyp', n: 1, tekst: 'Wg której daty', gdzie: 'bottom', odl: 10},
    {sel: '#fpStatus', n: 2, tekst: 'Status', gdzie: 'bottom', odl: 10, dx: -90},
    {text: '➕ Dodaj paczkę', sel: 'button', n: 3, tekst: 'Paczka ręcznie', gdzie: 'right'},
    {text: '🔓', sel: 'button', n: 4, tekst: 'Odblokuj', gdzie: 'left', odl: 30},
  ]);

  await p.goto(B + '/stats');
  await p.click('text=30 dni');
  await shot('14_normy', [
    {text: '30 dni', sel: 'button', n: 1, tekst: 'Zakres', gdzie: 'top', odl: 6},
    {sel: '#celSztH', n: 2, tekst: 'Cel szt./h', gdzie: 'top', odl: 4, dx: -130},
    {sel: '#przegladPodsumowanie', n: 3, tekst: 'Średnia zespołu w okresie', gdzie: 'bottom', odl: 6, dx: 300, pad: 2},
  ]);

  await p.goto(B + '/zadania-dodatkowe');
  await shot('15_zadania', [
    {sel: '#zadaniaWiersze tr:first-child td', nth: 0, n: 1, gdzie: 'top', odl: 2, dx: 50, pad: 0},
    {sel: '#zadaniaWiersze tr:first-child td', nth: 1, n: 2, gdzie: 'top', odl: 2, dx: 40, pad: 0},
    {sel: '#zadaniaWiersze tr:first-child td', nth: 2, n: 3, gdzie: 'top', odl: 2, dx: 100, pad: 0},
    {sel: '#zadaniaWiersze tr:first-child td', nth: 3, n: 4, gdzie: 'top', odl: 2, dx: 60, pad: 0},
    {sel: '#zadaniaWiersze tr:first-child td', nth: 4, n: 5, gdzie: 'top', odl: 2, dx: 60, pad: 0},
    {sel: '#zadaniaWiersze tr:first-child td', nth: 5, n: 6, gdzie: 'top', odl: 2, pad: 0},
    {sel: '#zadaniaDodaj', n: 7, tekst: 'Nowy wiersz', gdzie: 'right'},
    {sel: '#autoZapisStatus', n: 8, tekst: 'Autozapis', gdzie: 'bottom', odl: 10},
    {text: '⬇ Excel', sel: 'button', n: 9, tekst: 'Eksport zakresu dat', gdzie: 'right'},
  ]);

  await p.goto(B + '/displays');
  await p.click('#ganttRozwin').catch(() => {});
  await shot('16_gantt', [
    {sel: '#nowaAkcja', n: 1, tekst: 'Nowa akcja', gdzie: 'right', odl: 30},
    {sel: '#ganttRozwin', n: 2, tekst: 'Kamienie milowe', gdzie: 'bottom', odl: 10},
    {text: 'Christmas 2026', sel: 'a', n: 3, tekst: 'Klik = strona akcji', gdzie: 'top', odl: 4, dx: 60},
  ]);

  await p.goto(B + '/zwroty/paczki');
  await p.evaluate(() => document.querySelectorAll('div').forEach(e => { if (e.scrollWidth > e.clientWidth + 20) e.scrollLeft = e.scrollWidth; }));
  await shot('17_zwroty_paczek', [
    {sel: '.js-popraw', nth: 0, n: 1, gdzie: 'top', odl: 14, dx: -20},
    {sel: '.js-czesc', nth: 0, n: 2, gdzie: 'top', odl: 14},
    {sel: '.js-usun', nth: 0, n: 3, gdzie: 'top', odl: 14, dx: 10},
    {text: '⬇ Excel', sel: 'a, button', n: 4, tekst: 'Excel', gdzie: 'bottom', odl: 10},
  ]);

  await p.goto(B + '/zwroty/przydzial');
  await shot('18_przydzial_zwrotow', [
    {sel: 'select', nth: 0, n: 1, tekst: 'Stanowisko / Support / —', gdzie: 'bottom', odl: 80, dx: -120},
    {sel: '#przydzialStanowiska', n: 2, tekst: 'Kto gdzie stoi teraz', gdzie: 'right', odl: 6},
  ]);
  // admin
  await ctx.clearCookies();
  await p.goto(B + '/login');
  await p.fill('input[name=username]', 'admin');
  await p.fill('input[name=password]', 'DemoAdmin2026');
  await p.click('button[type=submit]');
  await p.waitForLoadState('networkidle');
  await p.goto(B + '/admin/panel');
  await shot('19_panel_admina', []);
  await ctx.close();
  return wynik;
}
