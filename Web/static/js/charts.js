
import { esc } from './config.js';
import { say } from './words.js';

let chartLib = null;

function loadChartJs() {
  if (window.Chart) return Promise.resolve(window.Chart);
  if (chartLib) return chartLib;
  let v = '';
  try { v = JSON.parse(document.getElementById('atlas-config')?.textContent || '{}').version || ''; } catch {   }
  chartLib = new Promise((ok, fail) => {
    const s = document.createElement('script');
    s.src = 'static/js/vendor/chart.umd.min.js' + (v ? `?v=${encodeURIComponent(v)}` : '');
    s.onload = () => (window.Chart ? ok(window.Chart) : fail(new Error('Chart.js loaded but defined nothing')));
    s.onerror = () => { chartLib = null; fail(new Error('Chart.js failed to load')); };
    document.head.appendChild(s);
  });
  return chartLib;
}

function chartInk(el) {
  const s = getComputedStyle(el || document.documentElement);
  const v = (name, fb) => (s.getPropertyValue(name) || '').trim() || fb;
  return {
    series: [v('--ch-1', '#7FB0C4'), v('--ch-2', '#C49A52'), v('--ch-3', '#C06B62'),
             v('--ch-4', '#7A9B6E'), v('--ch-5', '#7FE0C8'), v('--ch-6', '#9A7FB0'),
             v('--ch-7', '#D9C08A'), v('--ch-8', '#8A9BA8')],
    up: v('--ch-up', '#7A9B6E'), warn: v('--ch-warn', '#C49A52'), down: v('--ch-down', '#C06B62'),
    grid: v('--ch-grid', 'rgba(201,165,84,0.12)'), ink: v('--ch-ink', '#8A8069'),
    text: v('--ch-text', '#C9BFA8'), surface: v('--ch-surface', '#0b0d12'),
  };
}

const SEMANTIC = { ok: 'up', fallback: 'down', '2xx/3xx': 'up', '4xx': 'warn', '5xx': 'down' };
function seriesColor(name, i, ink) {
  const sem = SEMANTIC[String(name).toLowerCase()] || SEMANTIC[name];
  return sem ? ink[sem] : ink.series[i % ink.series.length];
}
const wash = (hex) => (/^#[0-9a-f]{6}$/i.test(hex) ? hex + '24' : hex);

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
function fmt(unit, v) {
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

function applySelection(chart, box) {
  const names = new Set(chart.data.datasets.map((d) => d.label));
  const sel = box._selected;
  if (sel) for (const n of [...sel]) if (!names.has(n)) sel.delete(n);
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

function statHTML(payload) {
  const series = payload.series || [];
  if (!series.length) return note('nothing recorded in this window');
  return `<div class="chart-stats">` + series.map((s) =>
    `<div class="chart-stat"><span class="chart-stat-label">${esc(s.name)}</span>` +
    `<span class="chart-stat-now">${esc(fmt(payload.unit, last(s.points)))}</span>${sparkSVG(s.points)}</div>`
  ).join('') + `</div>`;
}

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

function twinHTML(payload) {
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

export async function drawChart(box, payload) {
  destroyChart(box);
  box._payload = payload;
  box.dataset.kind = payload.kind;
  box.classList.remove('showdata');
  if (payload.kind === 'table') { box.innerHTML = tableHTML(payload); return null; }
  if (payload.kind === 'stat') { box.innerHTML = statHTML(payload); return null; }
  if (!(payload.series || []).length) { box.innerHTML = note('nothing recorded in this window'); return null; }
  const Chart = await loadChartJs();
  if (box._payload !== payload) return null;
  const ink = chartInk(box);
  const canvas = document.createElement('canvas');
  canvas.setAttribute('role', 'img');
  canvas.setAttribute('aria-label', payload.title || say('a watching of the lab'));
  box.replaceChildren(canvas);
  const { ts, labels, datasets } = frame(payload, ink);
  const chart = new Chart(canvas, {
    type: payload.kind === 'bars' ? 'bar' : 'line',
    data: { labels, datasets },
    options: baseOptions(ink, payload, ts),
  });
  box._chart = chart;
  if (box._selected?.size) applySelection(chart, box);
  return chart;
}

export function destroyChart(box) {
  if (!box) return;
  if (box._chart) { try { box._chart.destroy(); } catch {   } box._chart = null; }
  box._payload = null;
  box.innerHTML = '';
  box.classList.remove('showdata');
}

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
