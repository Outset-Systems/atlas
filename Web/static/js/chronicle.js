/* Atlas — THE UPPER DECK' Chronicle + THE DEPTHS' Abyss: the two
   carousels of live watchings (Grafana embeds, staged reports), their button
   rows, and the ⛶ maximised frame.

   Lived inside ui.js from the first version (≈360 of its 1700 lines, the
   single largest subsystem in the file, flagged for extraction on 2026-08-12
   and left because of the Grafana-timing code it carries). Moved out whole on
   2026-08-21, behaviour unchanged except the sleeping frames below. The rest of
   ui.js reaches it through exactly three names — `settleScry` (the card's
   vitals fade in the same way a slide does), `chronicleItems` (THE INDEX lists
   the sky's watchings) and `buildChronicle`/`buildAbyss` (buildUI) — and
   nothing else in the app touches it except `A.closeMax` from the Escape chain. */

import { A, CFG, $, esc, glassAttrs, isMixed } from './config.js';
import { say } from './words.js';
import { drawChart, destroyChart, toggleTwin } from './charts.js';

/* CHRONICLE (sky) + ABYSS (depths) — the realm's live watchings, sourced from the
   data file (lab-data.json → "chronicle" / "abyss"): adding a dashboard is a data
   edit. Each region has a CAROUSEL of watchings — drawn NATIVELY when the server's
   chart catalogue knows the panel (v1.35.0, below), else an embeddable dashboard
   in an iframe (`embed`; `solo` = a single Grafana panel) — plus a row of BUTTON
   cards (link-only, or `broken` = flagged dark, or everything while embedding is
   off). Shared machinery, two instances. */
export const chronicleItems = () => (A.DATA?.chronicle?.length ? A.DATA.chronicle : []);
const abyssItems = () => (A.DATA?.abyss || []);

/* ── Native watchings (v1.35.0) ─────────────────────────────────────────────
   `A.CHARTS` is the server's catalogue (api/v2/charts, loaded beside the
   dataset in atlas.js): key → {kind, unit, grafana:{uid,panel}} for every
   panel the Atlas can draw itself, from Prometheus/Loki, in its own ink. A
   watching is native when its `chart` names a key — or, with no dataset edit
   at all, when its `embed` URL points at a Grafana panel the catalogue
   replaces. A key the catalogue does not list (or lists as unavailable: that
   source is not configured on this deployment) falls back to the iframe, so
   every watching still shows SOMETHING and Grafana keeps the ones the Atlas
   cannot yet draw. */
const chartIndex = () => A.CHARTS || {};
export function chartFor(c) {
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
/** The window a native watching asks for: its own `range`, else three weeks
    (CFG.CHART_RANGE). ⧗ on the slide swaps in CFG.CHART_RANGE_ALL — "all
    time" — remembered per slide until the page is rebuilt. */
const chartRange = (c) => (c?.range || CFG.CHART_RANGE || '');
const rangeLabel = (r) => {
  const m = /^(?:now-)?(\d+)([hdy])$/.exec(String(r || ''));
  if (!m) return String(r || '');
  const n = Number(m[1]), u = m[2];
  if (u === 'y') return `${n}Y`;
  if (u === 'd') return n % 7 === 0 && n > 7 ? `${n / 7}W` : `${n}D`;
  return `${n}H`;
};

/* One answer per (key, window), held CHART_STALE_MS: paging back to a slide
   inside a minute redraws from memory — the server caches too, but a fetch
   is still a round trip the reader can see. */
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

/** Draw (or redraw, when stale) every native figure in a slide, then mark the
    slide scried the way a frame's `load` would. A figure that fails says so
    in its own pane — the slide is never left at "scrying…" forever. */
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
      if (box.dataset.pending !== stamp || !box.isConnected) return;   // paged away, or redrawn since
      await drawChart(box, payload);
      box.dataset.at = String(Date.now());
    } catch (e) {
      if (box.dataset.pending !== stamp || !box.isConnected) return;
      destroyChart(box);
      box.innerHTML = `<div class="chart-note">${say('the scribe is not answering')}</div>`;
      box.dataset.at = String(Date.now() - CFG.CHART_STALE_MS + 15000);   // ask again soon, not at once
      console.warn('chronicle: native watching failed', box.dataset.chart, e);
    }
  }));
  if (!slide.isConnected) return;
  slide.classList.add('scried');
  slide.classList.remove('scrying');
  // ⧗ reads the window actually DRAWN — a capped chart (TOP PROBES, 24h) says
  // so from its first paint, not only after a toggle
  const drawn = boxes[0]._payload?.window, rng = slide.querySelector('.chron-range');
  if (drawn && rng) rng.textContent = rangeLabel(drawn);
}
/** A slide leaving the warm window gives its figures back, like a parked frame. */
function parkNatives(slide) {
  for (const box of slide.querySelectorAll('.chron-native')) {
    if (!box.dataset.at && !box.dataset.pending) continue;
    delete box.dataset.pending;
    delete box.dataset.at;
    destroyChart(box);
  }
}
const hasNatives = (slide) => !!slide.querySelector('.chron-native');

/* (`withRange` and `withEmbedAuth` lived here until v1.36.0 — the Grafana
   from/to window and the §20c embed token. Grafana was decommissioned
   2026-09-03; an `embed` URL is now framed exactly as written.) */

function slideHTML(c, i) {
  // src is NOT set here — the carousel decides which slides carry a live iframe
  // (see `show()`: a warm window around the visible one). Every slide loading
  // and auto-refreshing offscreen was the app's biggest drain (2026-07-11).
  //
  // `loading="lazy"` is deliberately absent: the src is assigned by script, so
  // lazy adds nothing but a chance the *visible* slide is deferred.
  //
  // `c.panels` = several watchings sharing this slide (pane_group): quarter-
  // panes in a grid, each with its own caption and frame. No ⛶ on a grid —
  // there is no single dashboard to enlarge.
  // `c.whois` = THE NAMING DEEP rides in this slide (TOP CLIENTS): the panel
  // that names the busiest client IPs and the tool that asks who holds one,
  // side by side. The form's behaviour is delegated document-wide in
  // whois.js, so this re-renderable HTML carries no listeners of its own.
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
  // One watching's pane: the Atlas's own figure when the catalogue knows the
  // panel, else the frame. `data-src`/`data-chart` are both assigned by
  // `show()` — nothing here reaches for a server at parse time.
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

/* One rule for every embedded dashboard: the realm's own waiting state holds
   CFG.EMBED_SETTLE_MS past the iframe's `load` (Grafana is an SPA — its
   document lands well before it draws), then `target` is marked scried —
   unless the frame was parked or torn down while we waited. Was three
   hand-rolled copies with three different liveness guards; this one carries
   the union of them. */
export function settleScry(frame, target = frame) {
  if (!frame.src || frame.src === 'about:blank') return;
  setTimeout(() => {
    if (frame.isConnected && frame.src && frame.src !== 'about:blank') {
      target.classList.add('scried');
      target.classList.remove('scrying');
    }
  }, CFG.EMBED_SETTLE_MS);
}

/* A watching that can't paint into the carousel becomes a button here.

   It used to take a click to reveal the blurb and a SECOND click, on a link
   inside that popup, to actually open the thing — two clicks to read a report,
   and the first one told you what you already guessed from the title. Now the
   blurb is what hovering gets you and the click does the obvious thing: opens
   it, in the glass when it can be framed (the staged markdown reports are
   served for exactly that) and in a tab when `open_in` says it must be.
   (2026-08-04) */
function buildButtons(items, bwrap) {
  if (!bwrap) return;
  // the anchor IS the button now — one element, so a click cannot land on the
  // wrap and miss the link, and the glass keeps its own href/target contract
  // a watching with nowhere to go is not a button (v1.36.0: `url` became
  // optional for native watchings, whose deep dive went with Grafana)
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

/** a self-contained carousel bound to a set of element ids (one per region) */
function makeCarousel(p) {
  const stage = $(p.stage), dots = $(p.dots), viewer = document.querySelector(p.viewer);
  let idx = 0, timer = 0, n = 0, items = [], arrowsWired = false;
  /** How far from the visible slide a dashboard stays loaded.

      Loading only the visible one meant every ‹ › press and every 3-minute
      auto-advance was a **cold Grafana load** — its own spinner, every time,
      for a dashboard you had already looked at ten seconds earlier. Loading all
      of them was the 2026-07-11 drain. A window of ±CHRONICLE_WARM is the
      middle: paging is instant in both directions, and at most three of twenty
      dashboards are ever live. */
  const inWarmWindow = (slideIdx) => {
    if (n <= 1) return true;
    const d = Math.abs(slideIdx - idx);
    return Math.min(d, n - d) <= CFG.CHRONICLE_WARM;   // wraps, like the carousel
  };

  function show(i, byUser) {
    if (!n) return;
    idx = (i + n) % n;
    stage.style.transform = `translateX(${-idx * 100}%)`;
    for (const slide of stage.children) {
      slide.querySelector('.chron-pane')?.classList.remove('awake');   // paging puts every watching back to sleep
      const warm = inWarmWindow(Number(slide.dataset.i));
      // the Atlas's own figures: drawn inside the warm window, given back
      // outside it — the same rule as the frames, for the same reason
      if (hasNatives(slide)) {
        if (warm) wakeNatives(slide);
        else { parkNatives(slide); if (!slide.querySelector('iframe')) slide.classList.remove('scried', 'scrying'); }
      }
      // every frame in the slide — a pane_group slide carries several
      for (const f of slide.querySelectorAll('iframe')) {
        if (f.dataset.focused) continue;
        if (warm) {
          // `scrying` marks a pane actually reaching for a dashboard — it is the
          // only state whose waiting-dots animate (parked slides stay still)
          if (f.src !== f.dataset.src) { f.src = f.dataset.src; slide.classList.add('scrying'); }
        } else if (f.src && f.src !== 'about:blank') {
          f.src = 'about:blank';
          delete f.dataset.loaded;
          slide.classList.remove('scried', 'scrying');   // it will have to load again
        }
      }
    }
    for (const d of dots.children) d.classList.toggle('active', Number(d.dataset.i) === idx);
    if (byUser) auto();
  }

  /* Our own waiting state, so you never watch Grafana's cold spinner: the slide
     shows the realm's own "scrying…" until the dashboard has actually drawn,
     and `scried` sticks, so a slide that has already loaded never flashes
     again. One shared rule — see settleScry. */
  if (stage) stage.addEventListener('load', (e) => {
    if (e.target?.tagName !== 'IFRAME') return;
    const slide = e.target.closest('.chron-slide') ?? e.target;
    e.target.dataset.loaded = '1';
    // a pane_group slide settles when its LAST pane lands — revealing on the
    // first would trade Grafana's spinner for three of them
    const frames = slide.querySelectorAll ? [...slide.querySelectorAll('iframe')] : [e.target];
    if (frames.every((f) => f.dataset.loaded)) settleScry(e.target, slide);
  }, true);   // capture: `load` from an iframe does not bubble
  function auto() { clearInterval(timer); if (n > 1) timer = setInterval(() => show(idx + 1), CFG.CHRONICLE_ROTATE_MS); }
  // ⛶ — enlarge the dashboard under the cursor to fill the window (not OS
  // full-screen). Passes the whole carousel so the overlay keeps ‹ › paging.
  if (stage) stage.addEventListener('click', (e) => {
    /* A click on a SLEEPING pane wakes its watching. Frames sleep by default
       (`pointer-events: none`, atlas.css "the wheel travels") so the wheel and
       a drag over a dashboard move the map instead of vanishing into the
       iframe's document; the click hands the frames back their pointer until
       the pointer leaves the slide (render) or the carousel pages (show).
       Stopped here so the viewport's background click does not read a
       deliberate touch on a watching as "close the card". (2026-08-21) */
    const pane = e.target.closest('.chron-pane');
    // an address in a native table is handed to THE NAMING DEEP beside it —
    // that is the whole reason TOP CLIENTS and the whois box share a slide
    const ip = e.target.closest('.chart-ip');
    if (ip) {
      e.preventDefault(); e.stopPropagation();
      // the deep on the SAME slide, by class: another watching may carry one too
      const slide = ip.closest('.aw-duo, .chron-slide') || document;
      const input = slide.querySelector('.aw-input') || document.querySelector('.aw-input');
      if (input) { input.value = ip.dataset.ip || ''; input.focus(); input.closest('.aw-form')?.requestSubmit?.(); }
      return;
    }
    if (pane && pane.classList.contains('native')) {
      e.stopPropagation();   // a touch on a figure is not a click on the map behind it
      return;
    }
    if (pane && !pane.classList.contains('awake')) {
      e.stopPropagation();
      pane.classList.add('awake');
      return;
    }
    // ⧗ — three weeks ⇄ all time, for every figure on the slide. The button
    // reads the window actually DRAWN (the server clamps a year to Loki's
    // month and says so), so it never claims a span the chart does not show.
    const rng = e.target.closest('.chron-range');
    if (rng) {
      e.preventDefault(); e.stopPropagation();
      const slide = rng.closest('.chron-slide');
      const boxes = [...(slide?.querySelectorAll('.chron-native') || [])];
      if (!boxes.length) return;
      const all = rng.getAttribute('aria-pressed') !== 'true';
      rng.setAttribute('aria-pressed', all ? 'true' : 'false');
      for (const b of boxes) {
        if (!b.dataset.rangeHome) b.dataset.rangeHome = b.dataset.range;   // the watching's own window, to come back to
        b.dataset.range = all ? CFG.CHART_RANGE_ALL : b.dataset.rangeHome;
        delete b.dataset.at;   // stale by definition — the window changed
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
    if (chartFor(items[at])) { A.maximizeEmbed(null, items, at); return; }
    A.maximizeEmbed(frame?.src && frame.src !== 'about:blank' ? frame.src : items[idx]?.embed,
                    items, at);
  });
  // a figure on the visible slide is redrawn as it goes stale, so a slide left
  // open keeps telling the truth — one timer per carousel, never per slide
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
    // a re-render (every Desk save redraws the UI) replaces the slides — give
    // the figures back first, or each Chart.js instance stays registered
    // against a canvas nobody can reach (review, 2026-09-03)
    for (const box of stage.querySelectorAll('.chron-native')) destroyChart(box);
    stage.innerHTML = embeds.map((c, i) => slideHTML(c, i)).join('');
    dots.innerHTML = embeds.map((_, i) => `<button class="chron-dot" data-i="${i}" aria-label="watching ${i + 1}"></button>`).join('');
    for (const d of dots.children) d.addEventListener('click', (e) => { e.stopPropagation(); show(Number(d.dataset.i), true); });
    // an awake watching sleeps again when the pointer leaves its slide. Bound
    // per slide because pointerleave does not bubble; a re-render replaces the
    // slides, so nothing stacks.
    for (const s of stage.children)
      s.addEventListener('pointerleave', () => s.querySelector('.chron-pane')?.classList.remove('awake'));
    // the arrows live outside the stage, so they survive a re-render — binding
    // them here would stack a fresh listener every time an edit redraws the UI
    if (!arrowsWired) {
      arrowsWired = true;
      $(p.prev).addEventListener('click', (e) => { e.stopPropagation(); show(idx - 1, true); });
      $(p.next).addEventListener('click', (e) => { e.stopPropagation(); show(idx + 1, true); });
    }
    show(0); auto();
  }
  function showByTitle(sub) {
    // a watching folded into a pane_group slide is still findable by its own name
    const hay = (c) => ((c.title || '') + ' ' + (c.panels || []).map((p) => p.title).join(' ')).toUpperCase();
    const i = items.findIndex(c => hay(c).includes(sub.toUpperCase()));
    if (i >= 0) show(i, true);
  }
  // filter a card's embed to one service/host (e.g. &var-container=sonarr) and show it.
  // Re-derives from the clean base embed each call, so filters never stack.
  // data-focused pins the filtered src so lazy-loading doesn't blank it away.
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
  /* ⚑ `render` is the live one. `showByTitle` and `focusEmbed` are deliberate
     RE-ENTRY POINTS with no current caller — both of theirs went in 2026-07-31
     and 2026-08-15, and the two tombstone comments further down this file name
     these two by hand as the way back ("one `chronCarousel.showByTitle` away
     from being reinvented", "`focusEmbed` still knows how to narrow to one
     container"). Kept on that basis and said so HERE, at the return site,
     because a reader grepping for callers finds none and has no way to learn
     it was a decision rather than an oversight.
     `focusEmbed` also calls `showByTitle` as its own fallback, so the pair
     stands or goes together. */
  return { render, showByTitle, focusEmbed };
}

const chronCarousel = makeCarousel({ stage: 'chron-stage', dots: 'chron-dots', prev: 'chron-prev', next: 'chron-next', viewer: '#chronicle .chron-viewer' });
const abyssCarousel = makeCarousel({ stage: 'abyss-stage', dots: 'abyss-dots', prev: 'abyss-prev', next: 'abyss-next', viewer: '#abyss .chron-viewer' });

/* ⛶ — enlarge a dashboard to fill the window (not OS full-screen).
   Keeps ‹ › paging through the same carousel's watchings (2026-07-11). */
let maxItems = [], maxIdx = 0;
/** point the enlarged frame somewhere, showing the realm's own waiting state
    rather than Grafana's until it lands. Re-assigning an identical `src`
    reloads the frame in every browser, so identical is a no-op here. */
function maxSrc(src) {
  const f = $('embed-max-frame'), n = $('embed-max-native');
  if (n) { n.hidden = true; for (const b of n.querySelectorAll('.chron-native')) destroyChart(b); n.innerHTML = ''; }
  if (!f) return;
  f.hidden = false;
  if (f.src === src) return;
  $('embed-max')?.classList.remove('scried');
  f.src = src;
}
/** the enlarged pane draws a native watching itself — big, in the dark
    viewer's ink — with the frame parked, exactly as the carousel would */
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
A.maximizeEmbed = function maximizeEmbed(src, items = [], idx = 0) {
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
};
A.closeMax = function closeMax() {
  const m = $('embed-max');
  if (!m || m.hidden) return;
  m.hidden = true;
  m.classList.remove('scried');
  $('embed-max-frame').src = 'about:blank';   // stop the offscreen refresh
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

/* (`A.showChronicleCard` lived here — "rise to the Chronicle and land on a card
   by title". `showServiceMetrics` below took over and nothing has called it
   since; it was one `chronCarousel.showByTitle` away from being reinvented if
   ever needed. Removed 2026-07-31.) */

/* (`A.showServiceMetrics` lived here — "rise to the Chronicle and land on THIS
   service's container/host graph". The service pane's ↑ VIEW ITS METRICS was
   its only caller and went in the 2026-08-15 action-row shrink; the graphs
   themselves are one ☁ away in the Chronicle, and `chronCarousel.focusEmbed`
   still knows how to narrow to one container if this is ever wanted back.) */

/** Watchings sharing a `pane_group` fold into ONE slide of quarter-panes,
    titled by the group name and seated where the first member sat. A group
    of one is just a slide; abouts merge behind the group's single ⓘ. */
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
      /* The group slide inherits its members' own sizing (2026-08-15).
         The fold built a fresh object and never carried `solo`, so THE EDGE'S
         TALLY — four single panels, every one of them `solo` — came out at the
         full-dashboard height (90vh) while every neighbour in the carousel sat
         at the single-panel 76vh: the one slide that stepped down and back up
         as you paged past it. `every`, not `some`: a group holding a real
         dashboard still deserves the taller window. */
      item.solo = item.panels.every(p => p.solo);
    }
  }
  return out;
}

/* An http embed inside an https Atlas is mixed content — the browser blocks
   the iframe SILENTLY, so over the TLS door an unguarded slide
   would sit at "scrying…" forever. The glass (glass.js) already knew this
   through the shared `isMixed` (config.js, one spelling since 2026-08-21);
   the carousels were the one surface that didn't. A mixed watching takes the
   path a `broken` one takes — a button, whose click the glass routes to a
   real tab. Grafana growing TLS someday makes this guard a no-op. */
const mixedEmbed = (c) => isMixed(c.embed);

function splitReports(items) {
  // only watchings that can paint stay in the carousel; broken/link-only/mixed become buttons.
  // A native watching always can — nothing about it is framed, so the mixed-
  // content guard and the embeds switch (both about iframes) do not apply.
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

/* The stray-click dismisser that used to live here went with the click-to-open
   popup (2026-08-04): the blurb is a hover tooltip now, so it dismisses itself
   when the pointer leaves and there is no open state left to clear. */

