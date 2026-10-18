/* The Outset Calendar — one day, one row per thing. Every block of every
   registered app is a row (chain blocks under their chain, intervals as a comb
   of ticks, weeklies present on the six days they do not run), grouped by app;
   today's instances are drawn on the row, actual calls dotted on the app's
   header row, overlaps outlined, Run now / on-off forwarded through the host's
   callbacks. Shared by the Hub and Atlas; vendored unchanged (CONTRACT mirror
   rule).

   FOUR COLUMNS (1.6.1): a verdict glyph in the gutter, WHAT and WHERE on the
   left, the day across the middle, WHEN and WHETHER on the right. It is the
   grammar the Atlas's own CALENDAR scene reads in, deliberately — the fleet's
   day and the realm's day are drawn by two renderers and must not look like
   two ideas. The gutter is the point of it: a wall of ✓ stays quiet and a ✕ is
   findable by scrolling instead of by reading.

   Usage:
     OutsetCalendar.render(hostEl, view, {
       zone: 'America/Chicago',          // hours axis; default browser zone
       controls: true,                   // filter box + hide-off + collapse
       onRun(app, block), onToggle(app, block, enabled)   // optional
     })
   `view` is the Hub's /api/calendar shape:
     {day, rows[], planned[], overlaps[], actual[], listed[]}
   Each row: {app, app_name, block, label, what, kind, cadence_text, chain,
   lane, model, provider, model_name, enabled, last_ok, last_run, pending}.
   Each planned item adds start/end/hold_min for one instance of a row.
   A view without `rows` (an older planner) is drawn from `planned` alone. */
(function (global) {
  'use strict';
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const state = { filter: '', hideOff: false, collapsed: new Set() };

  /* The block's tone, and the one place the colour ladder is decided:
     a model call is the precious lane (gilt), the model too big for the local
     card is the warning tone, everything else is the day's ink. Overlap and
     pending are outlines on top, never a fourth and fifth fill — "if
     everything glows, nothing does". */
  const HEAVY = /\b(3[02]b|70b|72b|405b)\b/i;
  function tone(row) {
    if (!row.model) return 'net';
    return HEAVY.test(String(row.model_name || '')) ? 'heavy' : 'warm';
  }

  /* The row's verdict, read the way someone at 2am reads it: did it run, and
     did it work. `null` last_ok is "never reported", which is an honest
     answer and not a failure. */
  function verdict(row) {
    const ran = String(row.last_run || '').slice(11, 16);
    if (row.kind === 'parked' || row.enabled === false) return { cls: 'v-off', mark: '⏻', say: 'switched off' };
    if (row.last_ok === false) return { cls: 'v-failed', mark: '✕', say: 'last run FAILED' };
    if (row.pending) return { cls: 'v-pending', mark: '◔', say: 'queued' };
    if (row.last_ok === true) return { cls: 'v-kept', mark: '✓', say: ran ? `ran ${ran}` : 'last run ok' };
    return { cls: 'v-awaited', mark: '·', say: 'never reported' };
  }

  function minutesIntoDay(iso, day, zone) {
    // minutes since local midnight of `day` in `zone`, may be <0 or >1440
    const t = new Date(iso);
    const parts = new Intl.DateTimeFormat('en-US', { timeZone: zone, hour12: false,
      year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).formatToParts(t);
    const g = k => parts.find(p => p.type === k).value;
    const local = `${g('year')}-${g('month')}-${g('day')}`;
    const h = parseInt(g('hour'), 10) % 24, m = parseInt(g('minute'), 10);
    const dayOffset = (new Date(local + 'T00:00:00Z') - new Date(day + 'T00:00:00Z')) / 86400000;
    return dayOffset * 1440 + h * 60 + m;
  }

  function rowsFromPlanned(planned) {
    const seen = new Map();
    for (const p of planned || []) {
      const k = p.app + ':' + p.block;
      if (!seen.has(k)) seen.set(k, { app: p.app, app_name: p.app_name, block: p.block, label: p.label,
        what: '', kind: p.chain ? 'chain' : '', cadence_text: '', chain: p.chain, lane: p.lane, model: p.model,
        provider: p.provider, model_name: p.model_name, enabled: p.enabled, last_ok: p.last_ok,
        last_run: p.last_run, pending: p.pending });
    }
    return [...seen.values()];
  }

  function render(host, view, opts) {
    opts = opts || {};
    const zone = opts.zone || Intl.DateTimeFormat().resolvedOptions().timeZone;
    const day = view.day;
    const pct = min => Math.max(0, Math.min(100, min / 1440 * 100));
    const overlapBlocks = new Set((view.overlaps || []).flatMap(o => [o.a, o.b]));
    const rows = (view.rows && view.rows.length) ? view.rows : rowsFromPlanned(view.planned);

    // instances per row, calls per app
    const inst = new Map();
    (view.planned || []).forEach(p => { const k = p.app + ':' + p.block; (inst.get(k) || inst.set(k, []).get(k)).push(p); });
    const calls = new Map();
    (view.actual || []).forEach(c => { (calls.get(c.app) || calls.set(c.app, []).get(c.app)).push(c); });

    // groups in row order
    const groups = new Map();
    rows.forEach(r => { if (!groups.has(r.app)) groups.set(r.app, { name: r.app_name || r.app, rows: [] }); groups.get(r.app).rows.push(r); });

    const q = state.filter.trim().toLowerCase();
    const matches = r => !q || [r.app, r.app_name, r.block, r.label, r.what, r.cadence_text, r.lane, r.model_name]
      .some(v => String(v || '').toLowerCase().includes(q));
    const nowMin = minutesIntoDay(new Date().toISOString(), day, zone);
    const nowLine = (nowMin >= 0 && nowMin <= 1440) ? `<span class="oc-now" style="left:${pct(nowMin)}%"></span>` : '';
    // labels on every hour; the stylesheet drops the alternates when the page
    // is too narrow to carry them, so the axis never crowds into itself
    const hours = `<div class="oc-hours"><i></i><span class="oc-name"><b>THE HOURS</b><i>${esc(zone)}</i></span>` +
      `<div class="oc-ticks">${Array.from({length: 24}, (_, h) =>
        `<span style="left:${pct(h * 60)}%">${String(h).padStart(2, '0')}</span>`).join('')}</div>` +
      `<span class="oc-meta"></span></div>`;

    let html = '';
    if (opts.controls) {
      html += `<div class="oc-controls">
        <input class="oc-filter" type="search" placeholder="filter rows — app, block, host, model…" value="${esc(state.filter)}">
        <label><input type="checkbox" class="oc-hideoff" ${state.hideOff ? 'checked' : ''}> hide off / parked</label>
        <button class="oc-btn" data-act="expand">expand all</button>
        <button class="oc-btn" data-act="collapse">collapse all</button>
        <span class="oc-count"></span></div>`;
    }
    html += hours;
    let shown = 0, total = 0;
    for (const [app, g] of groups) {
      const visible = g.rows.filter(r => matches(r) && !(state.hideOff && (!r.enabled || r.kind === 'parked')));
      total += g.rows.length;
      if (!visible.length) continue;
      const collapsed = state.collapsed.has(app);
      const nBlocks = g.rows.filter(r => r.block).length;
      const appCalls = calls.get(app) || [];
      const dots = appCalls.map(c => {
        const m = minutesIntoDay(c.ts, day, zone);
        if (m < 0 || m > 1440) return '';
        return `<span class="oc-dot ${c.ok === false ? 'bad' : ''}" style="left:${pct(m)}%" title="${esc((c.lane || '') + ' ' + (c.model || '') + ' ' + (c.ms || 0) + 'ms' + (c.ok === false ? ' FAILED' : ''))}"></span>`;
      }).join('');
      html += `<div class="oc-group" data-app="${esc(app)}">
        <button class="oc-caret" data-act="fold" data-app="${esc(app)}" title="${collapsed ? 'expand' : 'collapse'}">${collapsed ? '▸' : '▾'}</button>
        <span class="oc-name"><b>${esc(g.name)}</b><i>${esc(app)}</i></span>
        <div class="oc-track head">${dots}${nowLine}</div>
        <span class="oc-meta"><em>${nBlocks} row${nBlocks === 1 ? '' : 's'}</em>${
          appCalls.length ? `<i>${appCalls.length} call${appCalls.length === 1 ? '' : 's'} today</i>` : '<i></i>'}</span></div>`;
      if (collapsed) continue;
      for (const r of visible) {
        shown++;
        if (!r.block) {
          html += `<div class="oc-row none"><i class="oc-mark">·</i><span class="oc-name"><b>${esc(r.label)}</b><i></i></span>` +
                  `<div class="oc-track">${nowLine}</div><span class="oc-meta"></span></div>`;
          continue;
        }
        const key = r.app + ':' + r.block;
        const items = inst.get(key) || [];
        const v = verdict(r);
        const cls = ['oc-row', `tone-${tone(r)}`, v.cls, r.enabled ? '' : 'off', r.kind === 'parked' ? 'parked' : ''].filter(Boolean).join(' ');
        const where = [r.chain ? `in ${r.chain}` : '', r.model ? `${r.provider || ''} ${r.model_name || ''}`.trim() : ''].filter(Boolean).join(' · ');
        const acts = (opts.onRun || opts.onToggle) ? `<span class="oc-actions">` +
          (opts.onRun ? `<button data-act="run" data-app="${esc(r.app)}" data-block="${esc(r.block)}" title="Run now">▶</button>` : '') +
          (opts.onToggle ? `<button data-act="toggle" data-app="${esc(r.app)}" data-block="${esc(r.block)}" data-enabled="${r.enabled ? 1 : 0}" title="${r.enabled ? 'Switch off' : 'Switch on'}">${r.enabled ? '⏻' : '○'}</button>` : '') + `</span>` : '';
        html += `<div class="${cls}" data-app="${esc(r.app)}" data-block="${esc(r.block)}">
          <i class="oc-mark" title="${esc(v.say)}">${v.mark}</i>
          <span class="oc-name" title="${esc(r.what || r.label)}"><b>${esc(r.label)}</b><i>${esc(where)}</i></span>
          <div class="oc-track">`;
        for (const p of items) {
          const s = minutesIntoDay(p.start, day, zone), e = minutesIntoDay(p.end, day, zone);
          if (e < 0 || s > 1440) continue;
          const bcls = ['oc-block', p.enabled ? '' : 'off', overlapBlocks.has(key) ? 'overlap' : '',
                        p.pending ? 'pending' : '', items.length > 8 ? 'tick' : ''].filter(Boolean).join(' ');
          const title = `${r.label} · ${p.start.slice(11, 16)}Z · ${p.hold_min}m · ${p.model ? (p.provider + ' ' + (p.model_name || '')) : 'no model'}` +
                        (p.last_ok === false ? ' · last run FAILED' : '') + (p.enabled ? '' : ' · off');
          html += `<div class="${bcls}" style="left:${pct(s)}%;width:${Math.max(0.2, pct(e) - pct(s))}%" title="${esc(title)}"></div>`;
        }
        if (!items.length && r.kind !== 'none') html += `<i class="oc-idle">not on this day</i>`;
        html += `${nowLine}</div>
          <span class="oc-meta"><em title="${esc(r.cadence_text)}">${esc(r.cadence_text)}</em>
            <span class="oc-line"><i class="oc-said">${esc(v.say)}</i>${acts}</span></span></div>`;
      }
    }
    if (!groups.size) html += `<div class="oc-row none"><i class="oc-mark"></i><span class="oc-name"><b>nothing registered</b><i></i></span><div class="oc-track"></div><span class="oc-meta"></span></div>`;
    html += `<div class="oc-legend"><span><i class="oc-swatch sw-warm"></i>model block</span>` +
            `<span><i class="oc-swatch sw-heavy"></i>a model too big for the local card</span>` +
            `<span><i class="oc-swatch sw-net"></i>no model</span>` +
            `<span><i class="oc-swatch sw-off"></i>off</span>` +
            `<span><i class="oc-swatch sw-overlap"></i>two want one model at once</span>` +
            `<span><i class="oc-swatch sw-call"></i>actual call</span>` +
            `<span>hours in ${esc(zone)}</span></div>`;
    host.innerHTML = html;
    const count = host.querySelector('.oc-count');
    if (count) count.textContent = `${shown} of ${total} rows`;
    host.onclick = ev => {
      const b = ev.target.closest('button[data-act]');
      if (!b) return;
      ev.preventDefault();
      const act = b.dataset.act;
      if (act === 'run' && opts.onRun) opts.onRun(b.dataset.app, b.dataset.block);
      else if (act === 'toggle' && opts.onToggle) opts.onToggle(b.dataset.app, b.dataset.block, b.dataset.enabled !== '1');
      else if (act === 'fold') { state.collapsed.has(b.dataset.app) ? state.collapsed.delete(b.dataset.app) : state.collapsed.add(b.dataset.app); render(host, view, opts); }
      else if (act === 'expand') { state.collapsed.clear(); render(host, view, opts); }
      else if (act === 'collapse') { groups.forEach((_, app) => state.collapsed.add(app)); render(host, view, opts); }
    };
    const filter = host.querySelector('.oc-filter');
    if (filter) filter.oninput = ev => { state.filter = ev.target.value; const pos = ev.target.selectionStart; render(host, view, opts); const f = host.querySelector('.oc-filter'); if (f) { f.focus(); try { f.setSelectionRange(pos, pos); } catch (e) { /* not a text control */ } } };
    const hide = host.querySelector('.oc-hideoff');
    if (hide) hide.onchange = ev => { state.hideOff = ev.target.checked; render(host, view, opts); };
  }

  global.OutsetCalendar = { render, minutesIntoDay, tone, verdict, state };
})(window);
