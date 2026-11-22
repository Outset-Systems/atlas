
import { A, CFG, $, esc, glassAttrs, isMixed } from './config.js';
import { say } from './words.js';
import { drawChart, destroyChart, toggleTwin } from './charts.js';

function resolved(url) {
  try { return new URL(url, document.baseURI).href; } catch { return url; }
}


export const chronicleItems = () => (A.DATA?.chronicle?.length ? A.DATA.chronicle : []);
const abyssItems = () => (A.DATA?.abyss || []);

const chartIndex = () => A.CHARTS || {};
function chartFor(c) {
  if (!c) return null;
  const idx = chartIndex();
  if (c.chart) return idx[c.chart] ? c.chart : null;
  const m = /\/d-solo\/([^/?#]+)\/[^?#]*\?([^#]*)/.exec(c.embed || '');
  if (!m) return null;
  const panel = new URLSearchParams(m[2]).get('panelId');
  if (!panel) return null;
  for (const e of Object.values(idx)) {
    if (e.grafana?.uid === m[1] && String(e.grafana.panel) === String(panel)) return e.key;
  }
  return null;
}
const chartRange = (c) => (c?.range || CFG.CHART_RANGE || '');
const rangeLabel = (r) => {
  const m = /^(?:now-)?(\d+)([hdy])$/.exec(String(r || ''));
  if (!m) return String(r || '');
  const n = Number(m[1]), u = m[2];
  if (u === 'y') return `${n}Y`;
  if (u === 'd') return n % 7 === 0 && n > 7 ? `${n / 7}W` : `${n}D`;
  return `${n}H`;
};

const chartCache = new Map();
async function chartData(key, range) {
  const ck = `${key}|${range}`;
  const hit = chartCache.get(ck);
  if (hit && Date.now() - hit.at < CFG.CHART_STALE_MS) return hit.payload;
  const res = await fetch(`api/v2/charts/${encodeURIComponent(key)}?range=${encodeURIComponent(range)}`, { cache: 'no-store' });
  if (!res.ok) throw new Error(`chart ${key} ${res.status}`);
  const payload = await res.json();
  chartCache.set(ck, { at: Date.now(), payload });
  return payload;
}

async function wakeNatives(slide) {
  const boxes = [...slide.querySelectorAll('.chron-native')];
  if (!boxes.length) return;
  const fresh = boxes.filter((b) => !b.dataset.at || Date.now() - Number(b.dataset.at) > CFG.CHART_STALE_MS);
  if (!fresh.length) return;
  if (!slide.classList.contains('scried')) slide.classList.add('scrying');
  await Promise.all(fresh.map(async (box) => {
    const stamp = String(Date.now());
    box.dataset.pending = stamp;
    try {
      const payload = await chartData(box.dataset.chart, box.dataset.range);
      if (box.dataset.pending !== stamp || !box.isConnected) return;
      await drawChart(box, payload);
      box.dataset.at = String(Date.now());
    } catch (e) {
      if (box.dataset.pending !== stamp || !box.isConnected) return;
      destroyChart(box);
      box.innerHTML = `<div class="chart-note">${say('the scribe is not answering')}</div>`;
      box.dataset.at = String(Date.now() - CFG.CHART_STALE_MS + 15000);
      console.warn('chronicle: native watching failed', box.dataset.chart, e);
    }
  }));
  if (!slide.isConnected) return;
  slide.classList.add('scried');
  slide.classList.remove('scrying');
  const drawn = boxes[0]._payload?.window, rng = slide.querySelector('.chron-range');
  if (drawn && rng) rng.textContent = rangeLabel(drawn);
}
function parkNatives(slide) {
  for (const box of slide.querySelectorAll('.chron-native')) {
    if (!box.dataset.at && !box.dataset.pending) continue;
    delete box.dataset.pending;
    delete box.dataset.at;
    destroyChart(box);
  }
}
const hasNatives = (slide) => !!slide.querySelector('.chron-native');


function slideHTML(c, i) {
  const asksWhois = c.whois && CFG.WHOIS;
  const whoisPane = asksWhois
    ? `<div class="aw-side">` +
      `<div class="aw-head">THE NAMING DEEP</div>` +
      `<div class="aw-sub">ask who holds one of those names — whois, from below</div>` +
      `<form class="aw-form">` +
        `<span class="aw-glyph" aria-hidden="true">☍</span>` +
        `<input class="aw-input" type="text" autocomplete="off" spellcheck="false"` +
        ` placeholder="203.0.113.7 · example.net" aria-label="Whois — a domain or IP address">` +
        `<button class="aw-go" type="submit">ASK</button>` +
      `</form>` +
      `<pre class="aw-out" hidden></pre>` +
      `</div>`
    : '';
  const paneHTML = (w) => {
    const key = chartFor(w);
    return key
      ? `<div class="chron-native" data-chart="${esc(key)}" data-range="${esc(chartRange(w))}"></div>`
      : `<iframe class="chron-frame" data-src="${esc(w.embed)}" title="${esc(w.title)}"></iframe>`;
  };
  const members = c.panels || [c];
  const native = members.every((w) => !!chartFor(w));
  const inner = c.panels
    ? `<div class="chron-grid">` + c.panels.map((p) =>
        `<div class="chron-cell"><div class="chron-cell-cap">${esc(p.title)}</div>${paneHTML(p)}</div>`
      ).join('') + `</div>`
    : asksWhois
      ? `<div class="aw-duo">` + paneHTML(c) + whoisPane + `</div>`
      : paneHTML(c);
  return `<div class="chron-slide${c.solo ? ' solo' : ''}" data-i="${i}">` +
    `<div class="chron-slide-head"><span class="chron-title">${esc(c.title)}</span>` +
    `<span class="chron-head-actions">` +
      (c.about ? `<button class="chron-info" title="What am I looking at?">ⓘ</button>` : '') +
      (members.some((w) => chartFor(w))
        ? `<button class="chron-range" title="Three weeks ⇄ all time" aria-pressed="false">${esc(rangeLabel(chartRange(members.find((w) => chartFor(w)))))}</button>` +
          `<button class="chron-twin" title="The numbers behind it">☷</button>`
        : '') +
      (c.panels ? '' : `<button class="chron-fs" title="Full screen">⛶</button>`) +
      (c.url
        ? `<a class="chron-open" href="${esc(c.url)}" target="_blank" rel="noopener"` +
          `${glassAttrs(c.title, say('a watching of the lab'), c.open_in)}>open ›</a>`
        : '') +
    `</span></div>` +
    (c.about ? `<div class="chron-about" hidden>${esc(c.about)}</div>` : '') +
    `<div class="chron-pane${native ? ' native' : ''}">` +
      `<div class="chron-scrying" aria-hidden="true"><span></span><span></span><span></span>` +
        `<em>${say('scrying')} ${esc(c.title.toLowerCase())}…</em></div>` +
      inner +
    `</div></div>`;
}

function settleScry(frame, target = frame) {
  if (!frame.src || frame.src === 'about:blank') return;
  setTimeout(() => {
    if (frame.isConnected && frame.src && frame.src !== 'about:blank') {
      target.classList.add('scried');
      target.classList.remove('scrying');
    }
  }, CFG.EMBED_SETTLE_MS);
}

function buildButtons(items, bwrap) {
  if (!bwrap) return;
  bwrap.innerHTML = items.filter((c) => c.url).map((c) => {
    const note = c.note || c.about || '';
    return `<div class="chron-btn-wrap">` +
      `<a class="chron-btn${c.broken ? ' broken' : ''}" href="${esc(c.url)}"` +
        ` target="_blank" rel="noopener"` +
        `${glassAttrs(c.title, say('a watching of the lab'), c.open_in)}>${esc(c.title)}</a>` +
      (note
        ? `<div class="chron-fly-pop" role="tooltip">` +
          `<div class="cfp-note">${c.broken ? '⚠ ' : ''}${esc(note)}</div></div>`
        : '') +
      `</div>`;
  }).join('');
}

function makeCarousel(p) {
  const stage = $(p.stage), dots = $(p.dots), viewer = document.querySelector(p.viewer);
  let idx = 0, timer = 0, n = 0, items = [], arrowsWired = false;
  const inWarmWindow = (slideIdx) => {
    if (n <= 1) return true;
    const d = Math.abs(slideIdx - idx);
    return Math.min(d, n - d) <= CFG.CHRONICLE_WARM;
  };

  function show(i, byUser) {
    if (!n) return;
    idx = (i + n) % n;
    stage.style.transform = `translateX(${-idx * 100}%)`;
    for (const slide of stage.children) {
      slide.querySelector('.chron-pane')?.classList.remove('awake');
      const warm = inWarmWindow(Number(slide.dataset.i));
      if (hasNatives(slide)) {
        if (warm) wakeNatives(slide);
        else { parkNatives(slide); if (!slide.querySelector('iframe')) slide.classList.remove('scried', 'scrying'); }
      }
      for (const f of slide.querySelectorAll('iframe')) {
        if (f.dataset.focused) continue;
        if (warm) {
          if (f.src !== resolved(f.dataset.src)) { f.src = f.dataset.src; slide.classList.add('scrying'); }
        } else if (f.src && f.src !== 'about:blank') {
          f.src = 'about:blank';
          delete f.dataset.loaded;
          slide.classList.remove('scried', 'scrying');
        }
      }
    }
    for (const d of dots.children) d.classList.toggle('active', Number(d.dataset.i) === idx);
    if (byUser) auto();
  }

  if (stage) stage.addEventListener('load', (e) => {
    if (e.target?.tagName !== 'IFRAME') return;
    const slide = e.target.closest('.chron-slide') ?? e.target;
    e.target.dataset.loaded = '1';
    const frames = slide.querySelectorAll ? [...slide.querySelectorAll('iframe')] : [e.target];
    if (frames.every((f) => f.dataset.loaded)) settleScry(e.target, slide);
  }, true);
  function auto() { clearInterval(timer); if (n > 1) timer = setInterval(() => show(idx + 1), CFG.CHRONICLE_ROTATE_MS); }
  if (stage) stage.addEventListener('click', (e) => {
    const pane = e.target.closest('.chron-pane');
    const ip = e.target.closest('.chart-ip');
    if (ip) {
      e.preventDefault(); e.stopPropagation();
      const slide = ip.closest('.aw-duo, .chron-slide') || document;
      const input = slide.querySelector('.aw-input') || document.querySelector('.aw-input');
      if (input) { input.value = ip.dataset.ip || ''; input.focus(); input.closest('.aw-form')?.requestSubmit?.(); }
      return;
    }
    if (pane && pane.classList.contains('native')) {
      e.stopPropagation();
      return;
    }
    if (pane && !pane.classList.contains('awake')) {
      e.stopPropagation();
      pane.classList.add('awake');
      return;
    }
    const rng = e.target.closest('.chron-range');
    if (rng) {
      e.preventDefault(); e.stopPropagation();
      const slide = rng.closest('.chron-slide');
      const boxes = [...(slide?.querySelectorAll('.chron-native') || [])];
      if (!boxes.length) return;
      const all = rng.getAttribute('aria-pressed') !== 'true';
      rng.setAttribute('aria-pressed', all ? 'true' : 'false');
      for (const b of boxes) {
        if (!b.dataset.rangeHome) b.dataset.rangeHome = b.dataset.range;
        b.dataset.range = all ? CFG.CHART_RANGE_ALL : b.dataset.rangeHome;
        delete b.dataset.at;
      }
      rng.textContent = rangeLabel(boxes[0].dataset.range);
      wakeNatives(slide).then(() => {
        const drawn = boxes[0]._payload?.window;
        if (drawn && rng.isConnected) rng.textContent = rangeLabel(drawn);
      });
      return;
    }
    const twin = e.target.closest('.chron-twin');
    if (twin) {
      e.preventDefault(); e.stopPropagation();
      const boxes = twin.closest('.chron-slide')?.querySelectorAll('.chron-native') || [];
      const on = ![...boxes].some((b) => b.classList.contains('showdata'));
      for (const b of boxes) toggleTwin(b, on);
      return;
    }
    const info = e.target.closest('.chron-info');
    if (info) {
      e.preventDefault(); e.stopPropagation();
      const about = info.closest('.chron-slide')?.querySelector('.chron-about');
      if (about) about.hidden = !about.hidden;
      return;
    }
    const fs = e.target.closest('.chron-fs');
    if (!fs) return;
    e.preventDefault(); e.stopPropagation();
    const slide = fs.closest('.chron-slide');
    const frame = slide?.querySelector('iframe');
    const at = Number(slide?.dataset.i ?? idx);
    if (chartFor(items[at])) { maximizeEmbed(null, items, at); return; }
    maximizeEmbed(frame?.src && frame.src !== 'about:blank' ? frame.src : items[idx]?.embed,
                    items, at);
  });
  setInterval(() => {
    const visible = stage?.children[idx];
    if (visible && hasNatives(visible) && !document.hidden) wakeNatives(visible);
  }, CFG.CHART_STALE_MS);
  function render(embeds) {
    items = embeds; n = embeds.length;
    if (!stage) return;
    if (!n) { if (viewer) viewer.hidden = true; if (dots) dots.hidden = true; return; }
    if (viewer) viewer.hidden = false;
    if (dots) dots.hidden = false;
    for (const box of stage.querySelectorAll('.chron-native')) destroyChart(box);
    stage.innerHTML = embeds.map((c, i) => slideHTML(c, i)).join('');
    dots.innerHTML = embeds.map((_, i) => `<button class="chron-dot" data-i="${i}" aria-label="watching ${i + 1}"></button>`).join('');
    for (const d of dots.children) d.addEventListener('click', (e) => { e.stopPropagation(); show(Number(d.dataset.i), true); });
    for (const s of stage.children)
      s.addEventListener('pointerleave', () => s.querySelector('.chron-pane')?.classList.remove('awake'));
    if (!arrowsWired) {
      arrowsWired = true;
      $(p.prev).addEventListener('click', (e) => { e.stopPropagation(); show(idx - 1, true); });
      $(p.next).addEventListener('click', (e) => { e.stopPropagation(); show(idx + 1, true); });
    }
    show(0); auto();
  }
  function showByTitle(sub) {
    const hay = (c) => ((c.title || '') + ' ' + (c.panels || []).map((p) => p.title).join(' ')).toUpperCase();
    const i = items.findIndex(c => hay(c).includes(sub.toUpperCase()));
    if (i >= 0) show(i, true);
  }
  function focusEmbed(titleSub, extraQuery, newTitle) {
    const i = items.findIndex(c => (c.title || '').toUpperCase().includes(titleSub.toUpperCase()));
    if (i < 0) { showByTitle(titleSub); return; }
    const slide = stage.children[i], frame = slide?.querySelector('iframe');
    if (frame) {
      const base = items[i].embed;
      frame.dataset.focused = '1';
      frame.src = base + (base.includes('?') ? '&' : '?') + extraQuery;
      const t = slide.querySelector('.chron-title');
      if (t && newTitle) t.textContent = newTitle;
    }
    show(i, true);
  }
  return { render, showByTitle, focusEmbed };
}

const chronCarousel = makeCarousel({ stage: 'chron-stage', dots: 'chron-dots', prev: 'chron-prev', next: 'chron-next', viewer: '#chronicle .chron-viewer' });
const abyssCarousel = makeCarousel({ stage: 'abyss-stage', dots: 'abyss-dots', prev: 'abyss-prev', next: 'abyss-next', viewer: '#abyss .chron-viewer' });

let maxItems = [], maxIdx = 0;
function maxSrc(src) {
  const f = $('embed-max-frame'), n = $('embed-max-native');
  if (n) { n.hidden = true; for (const b of n.querySelectorAll('.chron-native')) destroyChart(b); n.innerHTML = ''; }
  if (!f) return;
  f.hidden = false;
  if (f.src === resolved(src)) return;
  $('embed-max')?.classList.remove('scried');
  f.src = src;
}
async function maxChart(c) {
  const f = $('embed-max-frame'), n = $('embed-max-native'), m = $('embed-max');
  if (!n || !m) return;
  if (f) { f.hidden = true; if (f.src && f.src !== 'about:blank') f.src = 'about:blank'; }
  m.classList.remove('scried');
  for (const b of n.querySelectorAll('.chron-native')) destroyChart(b);
  n.innerHTML = `<div class="chron-native" data-chart="${esc(chartFor(c))}" data-range="${esc(chartRange(c))}"></div>`;
  n.hidden = false;
  const box = n.firstElementChild;
  try {
    const payload = await chartData(box.dataset.chart, box.dataset.range);
    if (!box.isConnected) return;
    await drawChart(box, payload);
  } catch (e) {
    if (!box.isConnected) return;
    box.innerHTML = `<div class="chart-note">${say('the scribe is not answering')}</div>`;
    console.warn('chronicle: maximised watching failed', box.dataset.chart, e);
  }
  if (box.isConnected) m.classList.add('scried');
}
function maxShow(i) {
  if (!maxItems.length) return;
  maxIdx = (i + maxItems.length) % maxItems.length;
  const c = maxItems[maxIdx];
  if (chartFor(c)) maxChart(c);
  else maxSrc(c.embed);
  const t = $('embed-max-title');
  if (t) t.textContent = c.title || '';
}
function maximizeEmbed(src, items = [], idx = 0) {
  const m = $('embed-max');
  if (!m) return;
  maxItems = items.filter(c => c.embed || chartFor(c));
  maxIdx = Math.max(0, maxItems.indexOf(items[idx]));
  const c = items[idx] || maxItems[maxIdx];
  if (c && chartFor(c)) maxChart(c);
  else maxSrc(src || maxItems[maxIdx]?.embed || 'about:blank');
  const t = $('embed-max-title');
  if (t) t.textContent = c?.title || '';
  const nav = maxItems.length > 1;
  const prev = $('embed-max-prev'), next = $('embed-max-next');
  if (prev) prev.hidden = !nav;
  if (next) next.hidden = !nav;
  m.hidden = false;
}
A.closeMax = function closeMax() {
  const m = $('embed-max');
  if (!m || m.hidden) return;
  m.hidden = true;
  m.classList.remove('scried');
  $('embed-max-frame').src = 'about:blank';
  const n = $('embed-max-native');
  if (n) { for (const b of n.querySelectorAll('.chron-native')) destroyChart(b); n.innerHTML = ''; n.hidden = true; }
};
$('embed-max-frame')?.addEventListener('load', (e) => {
  const m = $('embed-max');
  if (m) settleScry(e.target, m);
});
$('embed-max-close')?.addEventListener('click', (e) => { e.stopPropagation(); A.closeMax(); });
$('embed-max-prev')?.addEventListener('click', (e) => { e.stopPropagation(); maxShow(maxIdx - 1); });
$('embed-max-next')?.addEventListener('click', (e) => { e.stopPropagation(); maxShow(maxIdx + 1); });
$('embed-max')?.addEventListener('click', (e) => { if (e.target.id === 'embed-max') A.closeMax(); });



function groupPanes(embeds) {
  const out = [], groups = new Map();
  for (const c of embeds) {
    const g = c.pane_group;
    if (!g) { out.push(c); continue; }
    let item = groups.get(g);
    if (!item) {
      item = { title: g.toUpperCase(), panels: [], url: c.url, range: c.range };
      groups.set(g, item);
      out.push(item);
    }
    item.panels.push(c);
  }
  for (const item of groups.values()) {
    if (item.panels.length === 1) out[out.indexOf(item)] = item.panels[0];
    else {
      item.about = item.panels.filter(p => p.about)
        .map(p => `${p.title} — ${p.about}`).join('\n\n');
      item.solo = item.panels.every(p => p.solo);
    }
  }
  return out;
}

const mixedEmbed = (c) => isMixed(c.embed);

function splitReports(items) {
  const embeds = items.filter(c => !c.broken &&
    (chartFor(c) || (CFG.CHRONICLE_EMBEDS && c.embed && !mixedEmbed(c))));
  const buttons = items.filter(c => !embeds.includes(c));
  return { embeds: groupPanes(embeds), buttons };
}
export function buildChronicle() {
  const { embeds, buttons } = splitReports(chronicleItems());
  chronCarousel.render(embeds);
  buildButtons(buttons, $('chron-buttons'));
}
export function buildAbyss() {
  const { embeds, buttons } = splitReports(abyssItems());
  abyssCarousel.render(embeds);
  buildButtons(buttons, $('abyss-buttons'));
}


