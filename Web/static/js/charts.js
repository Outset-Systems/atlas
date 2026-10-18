/* Atlas — the chart layer: native watchings drawn in the map's own
   ink (v1.35.0). The server's catalogue (`api/v2/charts`, G17) answers a
   watching as a few kilobytes of series; this file turns that into a Chart.js
   figure, a row of stat tiles, or a table — and the "numbers" twin behind
   every one of them.

   Three rules, lifted from the Ledger's chart layer and kept here so both
   apps draw the same way:

   1. Chrome follows the region; series identity does not. Surfaces, gridlines
      and ink read the live `--ch-*` custom properties (the sky's parchment
      viewer and the Abyss's dark one each set their own — atlas.css "chart
      tokens"), so one figure is at home in both. The categorical slots are
      fixed per region and a series keeps its slot by position.
   2. A sign is never carried by hue alone. ok/fallback, 2xx/4xx/5xx use the
      semantic inks, but the reader learns the state from the name in the
      legend and the tooltip, never from colour on its own.
   3. Every figure has a numbers twin. Three of the parchment slots sit below
      3:1 on the light viewer, so the values must be reachable without reading
      a colour — ☷ on the slide head opens the twin, and it is not optional.

   Chart.js itself is vendored (static/js/vendor/) and loaded LAZILY here the
   first time a native watching draws: the core map never pays for it. */

import { esc } from './config.js';

let chartLib = null;

/** The vendored Chart.js UMD, once. A classic <script> rather than an import
    because the build defines `window.Chart` instead of exporting a module. */
export function loadChartJs() {
  if (window.Chart) return Promise.resolve(window.Chart);
  if (chartLib) return chartLib;
  let v = '';
  try { v = JSON.parse(document.getElementById('atlas-config')?.textContent || '{}').version || ''; } catch { /* no cache-buster, still loads */ }
  chartLib = new Promise((ok, fail) => {
    const s = document.createElement('script');
    s.src = 'static/js/vendor/chart.umd.min.js' + (v ? `?v=${encodeURIComponent(v)}` : '');
    s.onload = () => (window.Chart ? ok(window.Chart) : fail(new Error('Chart.js loaded but defined nothing')));
    s.onerror = () => { chartLib = null; fail(new Error('Chart.js failed to load')); };
    document.head.appendChild(s);
  });
  return chartLib;
}

// ── ink ─────────────────────────────────────────────────────────────────
/** The region's chart tokens, read off the element so a figure inside
    #abyss and one inside #chronicle each get their own viewer's ink. */
export function chartInk(el) {
  const s = getComputedStyle(el || document.documentElement);
  const v = (name, fb) => (s.getPropertyValue(name) || '').trim() || fb;
  return {
    series: [v('--ch-1', '#7FB0C4'), v('--ch-2', '#C49A52'), v('--ch-3', '#C06B62'),
             v('--ch-4', '#7A9B6E'), v('--ch-5', '#7FE0C8'), v('--ch-6', '#9A7FB0'),
             v('--ch-7', '#D9C08A'), v('--ch-8', '#8A9BA8')],
    up: v('--ch-up', '#7A9B6E'), warn: v('--ch-warn', '#C49A52'), down: v('--ch-down', '#C06B62'),
    grid: v('--ch-grid', 'rgba(201,165,84,0.12)'), ink: v('--ch-ink', '#8A8069'),
    text: v('--ch-text', '#C9BFA8'), workstation: v('--ch-surface', '#0b0d12'),
  };
}

/* Names that carry a state get the semantic ink; everything else takes the
   next categorical slot. The name still does the telling (rule 2). */
const SEMANTIC = { ok: 'up', fallback: 'down', '2xx/3xx': 'up', '4xx': 'warn', '5xx': 'down' };
function seriesColor(name, i, ink) {
  const sem = SEMANTIC[String(name).toLowerCase()] || SEMANTIC[name];
  return sem ? ink[sem] : ink.series[i % ink.series.length];
}
/** Series hue at ~14% for an area wash — never a saturated block. */
const wash = (hex) => (/^#[0-9a-f]{6}$/i.test(hex) ? hex + '24' : hex);

// ── numbers ─────────────────────────────────────────────────────────────
const compact = (n) => {
  const a = Math.abs(n);
  if (a >= 1e9) return (n / 1e9).toFixed(1).replace(/\.0$/, '') + 'B';
  if (a >= 1e6) return (n / 1e6).toFixed(1).replace(/\.0$/, '') + 'M';
  if (a >= 1e3) return (n / 1e3).toFixed(1).replace(/\.0$/, '') + 'K';
  return a >= 100 || Number.isInteger(n) ? String(Math.round(n)) : n.toFixed(a >= 10 ? 1 : 2);
};
function scaled(n, units, base) {
  let i = 0, x = Math.abs(n);
  while (x >= base && i < units.length - 1) { x /= base; i++; }
  return (n < 0 ? '-' : '') + (x >= 100 || i === 0 ? Math.round(x) : x.toFixed(1)) + ' ' + units[i];
}
/** One value in its unit — the same rendering on axis, tooltip, tile and twin. */
export function fmt(unit, v) {
  if (v === null || v === undefined || !Number.isFinite(v)) return '—';
  switch (unit) {
    case 'pct': return (v === 0 ? '0' : Math.abs(v) < 10 ? v.toFixed(1) : String(Math.round(v))) + '%';
    case 'bytes': return scaled(v, ['B', 'KiB', 'MiB', 'GiB', 'TiB'], 1024);
    case 'bps': return scaled(v, ['b/s', 'kb/s', 'Mb/s', 'Gb/s'], 1000);
    default: return compact(v);
  }
}

const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const two = (n) => String(n).padStart(2, '0');
/** A tick label fit to the window: clock inside a day, day+clock inside a
    week, calendar day beyond. */
function timeLabel(ts, window) {
  const d = new Date(ts * 1000);
  if (window === '1h' || window === '6h' || window === '24h') return `${two(d.getHours())}:${two(d.getMinutes())}`;
  if (window === '7d') return `${DAYS[d.getDay()]} ${two(d.getHours())}:00`;
  return `${MONTHS[d.getMonth()]} ${d.getDate()}`;
}
function fullTime(ts) {
  const d = new Date(ts * 1000);
  return `${DAYS[d.getDay()]} ${MONTHS[d.getMonth()]} ${d.getDate()} · ${two(d.getHours())}:${two(d.getMinutes())}`;
}

// ── framing the payload ─────────────────────────────────────────────────
/** Align every series on the union of timestamps; a missing bucket is a gap
    (null), never a zero — missing must stay missing. */
function frame(payload, ink) {
  const series = payload.series || [];
  const stamps = new Set();
  for (const s of series) for (const p of s.points) stamps.add(p[0]);
  const ts = [...stamps].sort((a, b) => a - b);
  const idx = new Map(ts.map((t, i) => [t, i]));
  const single = series.length === 1;
  const datasets = series.map((s, i) => {
    const data = new Array(ts.length).fill(null);
    for (const p of s.points) data[idx.get(p[0])] = p[1];
    const color = seriesColor(s.name, i, ink);
    return {
      label: s.name, data, borderColor: color, backgroundColor: payload.kind === 'bars' ? color + 'cc' : wash(color),
      fill: payload.kind === 'bars' ? undefined : single, borderWidth: payload.kind === 'bars' ? 0 : 1.5,
      pointRadius: 0, pointHitRadius: 8, tension: 0.25, spanGaps: false,
    };
  });
  return { ts, labels: ts.map((t) => timeLabel(t, payload.window)), datasets };
}

/* ── legend selection ──────────────────────────────────────────────────────
   Chart.js's own legend click HIDES the one series you clicked, which is the
   wrong way round for a twelve-line chart: the reader wants to see ONE, or a
   few, not lose one. So a legend click SELECTS — the clicked series stays and
   the rest step back; more clicks add to the selection; deselecting the last
   one brings everything back. The selection is remembered on the box (by
   series NAME, not index), so the 60 s redraw and a paged-away-and-back
   slide keep the reader's choice. (2026-09-02) */
function applySelection(chart, box) {
  const names = new Set(chart.data.datasets.map((d) => d.label));
  const sel = box._selected;
  if (sel) for (const n of [...sel]) if (!names.has(n)) sel.delete(n);   // a series that left the window
  const any = !!(sel && sel.size);
  chart.data.datasets.forEach((ds, i) => chart.setDatasetVisibility(i, !any || sel.has(ds.label)));
  chart.update();
}
function legendSelect(_e, item, legend) {
  const chart = legend.chart, box = chart.canvas.parentElement;
  if (!box) return;
  const sel = box._selected || (box._selected = new Set());
  const name = chart.data.datasets[item.datasetIndex]?.label;
  if (name === undefined) return;
  if (sel.has(name)) sel.delete(name); else sel.add(name);
  applySelection(chart, box);
}

function baseOptions(ink, payload, ts) {
  const mono = { size: 10, family: "'JetBrains Mono', ui-monospace, Menlo, monospace" };
  const bars = payload.kind === 'bars';
  const many = (payload.series || []).length > 1;
  return {
    responsive: true, maintainAspectRatio: false, animation: { duration: 220 },
    interaction: { mode: 'index', intersect: false },
    /* A click on the figure itself picks the NEAREST series, the same way a
       legend click does: with nothing selected it becomes the only one shown;
       with a selection up it toggles in the usual way (2026-09-02).
       `nearest` over the visible series, so a hidden line cannot be hit. */
    onClick: many ? (e, _els, chart) => {
      const hit = chart.getElementsAtEventForMode(e, 'nearest', { intersect: false }, true)[0];
      if (hit) legendSelect(e, { datasetIndex: hit.datasetIndex }, chart.legend);
    } : undefined,
    layout: { padding: { left: 4, right: 10, top: many ? 2 : 8 } },
    plugins: {
      legend: many
        ? { display: true, position: 'top', align: 'end',
            onClick: legendSelect,
            onHover: (e) => { if (e.native?.target) e.native.target.style.cursor = 'pointer'; },
            onLeave: (e) => { if (e.native?.target) e.native.target.style.cursor = ''; },
            labels: { color: ink.ink, boxWidth: 10, boxHeight: 10, padding: 10,
                      font: { size: 11, family: "'Alegreya Sans', system-ui, sans-serif" } } }
        : { display: false },
      tooltip: {
        backgroundColor: ink.surface, borderColor: ink.grid, borderWidth: 1,
        titleColor: ink.ink, bodyColor: ink.text,
        titleFont: { size: 11, weight: 'normal' }, bodyFont: { size: 12, weight: '600', family: mono.family },
        padding: 10, displayColors: true, boxWidth: 8, boxHeight: 2, caretSize: 5,
        callbacks: {
          title: (items) => (items.length ? fullTime(ts[items[0].dataIndex]) : ''),
          label: (item) => ` ${item.dataset.label}: ${fmt(payload.unit, item.parsed.y)}`,
        },
      },
    },
    scales: {
      x: { stacked: bars,
           ticks: { color: ink.ink, font: mono, maxTicksLimit: 8, maxRotation: 0, autoSkip: true },
           grid: { color: ink.grid, drawTicks: false, tickLength: 0 }, border: { color: ink.grid } },
      y: { stacked: bars, beginAtZero: true,
           ticks: { color: ink.ink, font: mono, maxTicksLimit: 6, callback: (v) => fmt(payload.unit, Number(v)) },
           grid: { color: ink.grid, drawTicks: false, tickLength: 0 }, border: { color: ink.grid } },
    },
  };
}

// ── figures that are not charts ─────────────────────────────────────────
/** A small inline sparkline for a stat tile; '' when there is nothing to show. */
function sparkSVG(points) {
  const v = (points || []).filter((p) => Number.isFinite(p?.[1]));
  if (v.length < 2) return '';
  const W = 160, H = 28, pad = 2;
  const ys = v.map((p) => p[1]);
  const min = Math.min(...ys), max = Math.max(...ys), span = (max - min) || 1;
  const t0 = v[0][0], t1 = v[v.length - 1][0];
  const x = (t) => ((t - t0) / Math.max(1, t1 - t0)) * W;
  const y = (n) => H - pad - ((n - min) / span) * (H - pad * 2);
  const line = v.map((p) => `${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join(' ');
  return `<svg class="chart-spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">` +
    `<polygon class="chart-spark-fill" points="0,${H} ${line} ${W},${H}"></polygon>` +
    `<polyline class="chart-spark-line" points="${line}"></polyline></svg>`;
}
const last = (points) => { for (let i = (points || []).length - 1; i >= 0; i--) if (Number.isFinite(points[i][1])) return points[i][1]; return null; };

/** Stat tiles: one per series — label, the number now, the window as a spark. */
function statHTML(payload) {
  const series = payload.series || [];
  if (!series.length) return note('nothing recorded in this window');
  return `<div class="chart-stats">` + series.map((s) =>
    `<div class="chart-stat"><span class="chart-stat-label">${esc(s.name)}</span>` +
    `<span class="chart-stat-now">${esc(fmt(payload.unit, last(s.points)))}</span>${sparkSVG(s.points)}</div>`
  ).join('') + `</div>`;
}

/** The table kind: label columns, the count, and a proportion bar so the
    ranking reads at a glance. An `ip` cell is a button THE NAMING DEEP can
    take — the whole reason TOP CLIENTS sits beside it. */
function tableHTML(payload) {
  const rows = payload.rows || [];
  if (!rows.length) return note('nothing recorded in this window');
  const cols = [...new Set(rows.flatMap((r) => Object.keys(r.labels || {})))];
  const top = Math.max(...rows.map((r) => r.value)) || 1;
  const cell = (k, v) => (k === 'ip'
    ? `<td><button type="button" class="chart-ip" data-ip="${esc(v)}" title="ask THE NAMING DEEP who holds this">${esc(v)}</button></td>`
    : `<td class="chart-label">${esc(v)}</td>`);
  return `<table class="chart-table"><thead><tr>${cols.map((c) => `<th>${esc(c)}</th>`).join('')}<th class="num">count</th><th></th></tr></thead><tbody>` +
    rows.map((r) => `<tr>${cols.map((c) => cell(c, r.labels?.[c] ?? '')).join('')}` +
      `<td class="num">${esc(fmt(payload.unit, r.value))}</td>` +
      `<td class="bar"><div class="chart-meter"><i style="width:${((r.value / top) * 100).toFixed(1)}%"></i></div></td></tr>`).join('') +
    `</tbody></table>`;
}

const note = (msg) => `<div class="chart-note">${esc(msg)}</div>`;

/** The numbers twin (rule 3). A table stays a table; a figure becomes one row
    per series — now, min, max, mean over the window — which is what a reader
    who cannot tell two hues apart actually needs from it. */
export function twinHTML(payload) {
  if (!payload) return note('nothing to show');
  if (payload.kind === 'table') return tableHTML(payload);
  const series = payload.series || [];
  if (!series.length) return note('nothing recorded in this window');
  const stat = (pts) => {
    const v = pts.map((p) => p[1]).filter(Number.isFinite);
    if (!v.length) return { now: null, min: null, max: null, mean: null };
    return { now: last(pts), min: Math.min(...v), max: Math.max(...v), mean: v.reduce((a, b) => a + b, 0) / v.length };
  };
  return `<table class="chart-table"><thead><tr><th>series</th><th class="num">now</th><th class="num">min</th><th class="num">max</th><th class="num">mean</th></tr></thead><tbody>` +
    series.map((s) => { const t = stat(s.points); return `<tr><td class="chart-label">${esc(s.name)}</td>` +
      ['now', 'min', 'max', 'mean'].map((k) => `<td class="num">${esc(fmt(payload.unit, t[k]))}</td>`).join('') + `</tr>`; }).join('') +
    `</tbody></table>`;
}

// ── drawing ─────────────────────────────────────────────────────────────
/** Draw `payload` into `box` (an element that already has its size). Returns
    the Chart for the canvas kinds, null for tiles and tables. The previous
    figure in the box, if any, is destroyed first. */
export async function drawChart(box, payload) {
  destroyChart(box);
  box._payload = payload;
  box.dataset.kind = payload.kind;   // the stylesheet lets a table scroll and a canvas not
  box.classList.remove('showdata');
  if (payload.kind === 'table') { box.innerHTML = tableHTML(payload); return null; }
  if (payload.kind === 'stat') { box.innerHTML = statHTML(payload); return null; }
  if (!(payload.series || []).length) { box.innerHTML = note('nothing recorded in this window'); return null; }
  const Chart = await loadChartJs();
  if (box._payload !== payload) return null;   // superseded while the library loaded
  const ink = chartInk(box);
  const canvas = document.createElement('canvas');
  canvas.setAttribute('role', 'img');
  canvas.setAttribute('aria-label', payload.title || 'a watching of the realm');
  box.replaceChildren(canvas);
  const { ts, labels, datasets } = frame(payload, ink);
  const chart = new Chart(canvas, {
    type: payload.kind === 'bars' ? 'bar' : 'line',
    data: { labels, datasets },
    options: baseOptions(ink, payload, ts),
  });
  box._chart = chart;
  if (box._selected?.size) applySelection(chart, box);   // the reader's choice outlives a redraw
  return chart;
}

export function destroyChart(box) {
  if (!box) return;
  if (box._chart) { try { box._chart.destroy(); } catch { /* already gone */ } box._chart = null; }
  box._payload = null;
  box.innerHTML = '';
  box.classList.remove('showdata');
}

/** Toggle the numbers twin over a drawn figure. */
export function toggleTwin(box, force) {
  if (!box || !box._payload) return;
  const on = force ?? !box.classList.contains('showdata');
  let twin = box.querySelector('.chart-twin');
  if (on) {
    if (!twin) { twin = document.createElement('div'); twin.className = 'chart-twin'; box.appendChild(twin); }
    twin.innerHTML = twinHTML(box._payload);
  } else if (twin) twin.remove();
  box.classList.toggle('showdata', on);
}
