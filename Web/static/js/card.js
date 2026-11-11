/* Atlas — the ivory card: the panel a marker opens.

   THE PULL-TAB CARD (2026-11-11, designed on the Atlas Node Cards canvas):
   one sheet of parchment with the place's emblem riding its top edge, its
   name, lore and a strip of vitals on the sheet, Split / Scroll right above
   its drawer, and its sections — SERVICES, PULSE, DETAILS and, only for a
   place the calendar asks, SCHEDULE — hanging from its foot as pull tabs. A
   tab pulls its section down; the drawer opens to exactly its pane's height
   and the card keeps its place (it is pinned by its top, with the room for its
   tallest pane reserved below). A section the data cannot fill gets no tab.

   Lifted out of ui.js whole; everything outside reaches
   it through `A`: openCard, closeCard, cardOpen, setCardSide,
   showServiceDetail. Registered in atlas.js after ui.js. */

import { A, CFG, $, esc, host, glassAttrs, zoneById, nodeById, FALLBACK_HUE } from './config.js';
import { say } from './words.js';
import { calendarPointerHTML } from './calendar.js';

const card = $('card');

/* the state of a whole host, read from the live feed */
const HEALTH_LABEL = { healthy: 'answering', degraded: 'faltering', down: 'gone dark', maintenance: 'under repair', slumbering: 'slumbering' };
const cap = (s) => String(s).charAt(0).toUpperCase() + String(s).slice(1);

/* inline stroke glyphs — the card's chrome is drawn, not typed */
const ICON = {
  chev: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M6 3l5 5-5 5"/></svg>',
  back: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M10 3L5 8l5 5"/></svg>',
  split: '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="1.6"/><circle cx="3" cy="4" r="1.2"/><circle cx="13" cy="4" r="1.2"/><circle cx="3" cy="12" r="1.2"/><circle cx="13" cy="12" r="1.2"/></svg>',
  note: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 2.5h7.5a1.5 1.5 0 0 1 1.5 1.5v9.5H5.5A1.5 1.5 0 0 1 4 12V2.5z"/><path d="M4 12a1.5 1.5 0 0 1 1.5-1.5H13M6.5 5.5h4M6.5 8h3"/></svg>',
  copy: '<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="5" y="5" width="8" height="9" rx="1"/><path d="M3 11V3a1 1 0 0 1 1-1h6"/></svg>',
  out: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M9 3h4v4M13 3L7 9M11 9v4H3V5h4"/></svg>',
  topo: '<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="6" y="2" width="4" height="3"/><rect x="2" y="11" width="4" height="3"/><rect x="10" y="11" width="4" height="3"/><path d="M8 5v3M4 11V8h8v3"/></svg>',
  route: '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="3.5" cy="12.5" r="1.5"/><circle cx="12.5" cy="3.5" r="1.5"/><path d="M5 12.5h4a2.5 2.5 0 0 0 0-5H7a2.5 2.5 0 0 1 0-5h4"/></svg>',
  lock: '<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="3" y="7" width="10" height="7" rx="1"/><path d="M5.5 7V5a2.5 2.5 0 0 1 5 0v2"/></svg>',
};

/* One vital as parchment ink: label, the number now, and a week of history as
   an inline SVG sparkline. SVG over canvas so the strokes stay crisp at any
   zoom and the colours come from the stylesheet (`.cv-spark-line` etc.). Values
   clamp to 0–100: these are percentages, and one bad sample must not rescale
   the week. */
function sparkHTML(label, series, nowVal) {
  const pts = (series || []).filter((p) => Number.isFinite(p?.[1]));
  let svg = '';
  if (pts.length > 1) {
    const w = 160, h = 40;
    const t0 = pts[0][0], t1 = pts[pts.length - 1][0];
    const xs = (t) => ((t - t0) / Math.max(1, t1 - t0)) * w;
    const ys = (v) => h - (Math.min(100, Math.max(0, v)) / 100) * h;
    const line = pts.map((p) => `${xs(p[0]).toFixed(1)},${ys(p[1]).toFixed(1)}`).join(' ');
    svg = `<svg class="cv-spark-svg" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true">` +
      `<polygon class="cv-spark-fill" points="0,${h} ${line} ${w},${h}"></polygon>` +
      `<polyline class="cv-spark-line" points="${line}"></polyline></svg>`;
  }
  const num = Number.isFinite(nowVal) ? `${Math.round(nowVal)}<em>%</em>` : '—';
  return `<div class="cv-spark" title="${esc(label)} over the last week">` +
    `<span class="cv-spark-label">${esc(label)}</span>` +
    `<span class="cv-spark-now">${num}</span>${svg}</div>`;
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    // insecure-context fallback (plain http over the LAN)
    const ta = document.createElement('textarea');
    ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.appendChild(ta); ta.select();
    try { document.execCommand('copy'); } finally { ta.remove(); }
  }
  A.showToast('The scroll’s path is copied to your clipboard.');
}

/* An Obsidian link for a scroll. The vault is the folder ATLAS_SCROLL_ROOT
   names (Obsidian calls a vault by its folder's name: /srv/docs/ → the suite)
   and the note is the rest of the path, without `.md`. With no root
   configured, ask Obsidian to find the note by its absolute path instead —
   which works only where the vault is registered at that same path. */
function obsidianHref(scroll) {
  const root = String(CFG.SCROLL_ROOT || '');
  if (root && scroll.toLowerCase().startsWith(root.toLowerCase())) {
    const vault = root.replace(/[\\/]+$/, '').split(/[\\/]/).pop();
    const file = scroll.slice(root.length).replace(/^[\\/]+/, '').replace(/\\/g, '/').replace(/\.md$/i, '');
    if (vault && file) return `obsidian://open?vault=${encodeURIComponent(vault)}&file=${encodeURIComponent(file)}`;
  }
  return `obsidian://open?path=${encodeURIComponent(scroll)}`;
}

/* ── the emblem ──────────────────────────────────────────────────────────── */
/* -> static/icons/<slug>.svg, drawn ivory on a disc in the zone's ink. A map
   style's own `logos` come first: a place wears what that picture gives it
   (table.js sets A.styleLogos). Then the place's own `logo` in the dataset,
   then the THEME's map (v1.48.0: `node_logos`, keyed by node id). A theme
   emblem listed in its `scenery_logos` belongs to the theme's own map, so on
   another style it stands down (2026-11-02: the sigil is the lab's, not the
   Seven Kingdoms'). */
const LOGO_SLUG = /^[a-z0-9][a-z0-9-]{0,39}$/;
const nodeLogo = (n) => {
  const styled = String(A.styleLogos?.[n.id] || '');
  if (LOGO_SLUG.test(styled)) return styled;
  const own = String(n.logo || '');
  if (LOGO_SLUG.test(own)) return own;
  const themed = CFG.THEME.nodeLogos?.[n.id] || '';
  const onStyle = document.body.classList.contains('on-style');
  return onStyle && (CFG.THEME.sceneryLogos || []).includes(themed) ? '' : themed;
};

function setPortrait(n) {
  const slug = nodeLogo(n) || 'waypoints';   // waypoints = generic fallback
  $('card-portrait').innerHTML = `<img class="portrait-logo" src="static/icons/${slug}.svg" alt="">`;
}

/* ── the drawer and its tabs ─────────────────────────────────────────────── */
const PANES = { services: 'card-links', pulse: 'card-vitals', details: 'card-data', schedule: 'card-forge' };
const TAB_LABEL = { services: 'SERVICES', pulse: 'PULSE', details: 'DETAILS', schedule: 'SCHEDULE' };
const drawer = { tabs: [], counts: {}, open: null };   // open = the pulled tab's id, or null

function paintTabs() {
  const row = $('card-tabs');
  row.innerHTML = drawer.tabs.map((id) => {
    const on = drawer.open === id;
    const n = drawer.counts[id];
    return `<button class="card-tab" role="tab" data-tab="${id}" aria-selected="${on}" ` +
      `aria-expanded="${on}" aria-controls="card-panel" title="${on ? 'Push it back up' : 'Pull it down'}">` +
      `${TAB_LABEL[id]}${n ? ` <span class="n">${n}</span>` : ''}</button>`;
  }).join('');
  card.classList.toggle('no-tabs', !drawer.tabs.length);
}

/* The drawer opens to exactly its pane — measured, not guessed — capped by the
   room the card reserved below its sheet (layoutCard). */
function sizeDrawer() {
  const want = drawer.open ? paneHeight(drawer.open) : 0;
  const h = Math.min(want, roomPx || want);
  card.style.setProperty('--drawer-h', `${h}px`);
}

/** Show one pane (null = none) and say how tall it wants to be. The pane's own
    box is asked, not the panel's scroll height: the panel is as tall as the
    drawer was a moment ago, and answers with that. */
function paneHeight(id) {
  for (const [pid, el] of Object.entries(PANES)) $(el).hidden = pid !== id;
  return id ? $(PANES[id]).offsetHeight + 2 : 0;   // + the panel's hairline and a pixel of air
}

function pullTab(id) {
  drawer.open = drawer.open === id ? null : id;
  paintTabs();
  if (drawer.open) stand.panes[drawer.open] = paneHeight(drawer.open);   // as it is now, not as first measured
  standFor(drawer.open);   // a pane taller than the room below slides the card up to make it
  sizeDrawer();
}

$('card-tabs').addEventListener('click', (e) => {
  const tab = e.target.closest('.card-tab');
  if (!tab) return;
  e.stopPropagation();
  pullTab(tab.dataset.tab);
});

function addTab(id, count) {
  if (!drawer.tabs.includes(id)) {
    const order = Object.keys(PANES);
    drawer.tabs.push(id);
    drawer.tabs.sort((a, b) => order.indexOf(a) - order.indexOf(b));
  }
  if (count) drawer.counts[id] = count;
  paintTabs();
}

/* ── where the card stands ───────────────────────────────────────────────────
   Pinned by its TOP on a desktop window, with the drawer SHUT and room below
   for the DETAILS pane and no more (owner, 2026-11-11): the card stands low,
   and Details opens downward into space that was already the card's. A taller
   pane (Services, on a busy place) slides the card up by what it lacks, and
   shutting it lets the card back down. The top never rises past the chrome
   above it (`--card-clear`, per side, plus the emblem's rise); past that the
   pane scrolls. The ≤720px bottom sheet stays bottom-pinned and its drawer
   grows upward. */
let roomPx = 0;
/* what layoutCard measured, for standFor to stand the card by */
const stand = { panes: {}, shut: 0, topMin: 0, rest: 0 };
/** The pane the card keeps room for while its drawer is shut. */
const RESTING_PANE = 'details';
const narrow = () => window.matchMedia('(max-width: 720px)').matches;
/* the pinned card may stand lower than the bottom-pinned one did (60px): its
   foot only ever meets the empty map, and every pixel goes to the drawer */
const BOTTOM = 24, MIN_ROOM = 140;

/** Every tab's pane, as tall as it wants to be: {tab id: px}. */
function measurePanes() {
  const heights = {};
  for (const id of drawer.tabs) heights[id] = paneHeight(id);
  return heights;
}

/** Stand the card for the pane `id` (null = drawer shut): at rest unless that
    pane needs more room than rest leaves, then as far up as it needs. */
function standFor(id) {
  if (narrow() || !card.classList.contains('anchored')) return;
  const need = id ? stand.panes[id] || 0 : 0;
  const top = Math.max(stand.topMin, Math.min(stand.rest, window.innerHeight - BOTTOM - stand.shut - need));
  roomPx = Math.max(MIN_ROOM, Math.floor(window.innerHeight - BOTTOM - top - stand.shut) - 2);
  card.style.setProperty('--card-top', `${Math.round(top)}px`);
  card.style.setProperty('--drawer-room', `${Math.round(roomPx)}px`);
}

function layoutCard() {
  if (!card.classList.contains('visible') && card.getAttribute('aria-hidden') === 'true') return;
  // only the full node view is the box to measure: a service pane would set
  // the top from the wrong height (re-run on Back)
  if (card.classList.contains('svc-open')) return;
  const cs = getComputedStyle(card);
  const clear = parseFloat(cs.getPropertyValue('--card-clear')) || 174;
  const over = parseFloat(cs.getPropertyValue('--medal-over')) || 0;
  stand.panes = measurePanes();
  const tallest = Math.max(0, ...Object.values(stand.panes));
  // the sheet + tabs with the drawer shut
  const was = cs.getPropertyValue('--drawer-h');
  card.style.setProperty('--drawer-h', '0px');
  const shut = card.offsetHeight;
  card.style.setProperty('--drawer-h', was);
  if (narrow()) {
    card.classList.remove('anchored');
    roomPx = Math.max(MIN_ROOM, Math.min(tallest, window.innerHeight - clear - over - shut));
  } else {
    stand.shut = shut;
    stand.topMin = clear - 60 + over;   // the chrome above, as --card-clear has always measured it (from a 60px foot)
    stand.rest = Math.max(stand.topMin,
      window.innerHeight - BOTTOM - shut - (stand.panes[RESTING_PANE] || 0));
    card.classList.add('anchored');
    standFor(drawer.open);
  }
  if (narrow()) card.style.setProperty('--drawer-room', `${Math.round(roomPx)}px`);
  sizeDrawer();
}

let resizeTimer = 0;
window.addEventListener('resize', () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => { if (A.cardOpen()) layoutCard(); }, 120);
});
/* the card's three faces load with `font-display: swap` and nothing else on
   the page uses them, so the first card of a visit can be measured in the
   fallback type — measure again once they have arrived */
document.fonts?.ready?.then(() => { if (A.cardOpen()) layoutCard(); });
document.fonts?.addEventListener?.('loadingdone', () => { if (A.cardOpen()) layoutCard(); });

/* ── the card ────────────────────────────────────────────────────────────── */
A.openCard = function openCard(n) {
  const zone = zoneById(n.zone);
  const hue = zone ? zone.hue : FALLBACK_HUE;
  card.style.setProperty('--card-hue', hue);
  setPortrait(n);
  drawer.tabs = []; drawer.counts = {}; drawer.open = null;   // the drawer is shut until a tab is pulled

  $('card-name').textContent = n.name;
  $('card-lore').textContent = n.lore || '';

  // its host, when it is a guest on one (NetBox's virtualization model)
  const parentBtn = $('card-parent');
  const parent = n.parent ? nodeById(n.parent) : null;
  parentBtn.hidden = !parent;
  if (parent) {
    parentBtn.innerHTML = `${esc(cap(say('vassal')))} of <b>${esc(parent.name)}</b>${ICON.chev}`;
    parentBtn.onclick = (e) => { e.stopPropagation(); A.focusNode(parent.id); };
  }

  /* THE STRIP — only what the feed can vouch for: no cell for a number nobody
     reported, and no strip at all when the watchers are silent. */
  const info = A.signalsFeed?.nodes?.[n.id];
  const cells = [];
  if (info?.state) {
    cells.push(['State', `<span class="svc-health ${A.svcHealthClass?.[info.state] || ''}"></span>` +
      esc(cap(HEALTH_LABEL[info.state] || info.state)), '']);
  }
  // K5 — "faith of the realm": 30-day uptime
  if (typeof info?.uptime_30d === 'number') cells.push(['30 days', `${info.uptime_30d.toFixed(2)}%`, 'mono']);
  // the patch survey (weekly, via Prometheus) — absent when the watchers can't see it
  const pi = info;
  let patchLine = '';
  if (pi && pi.patches_pending != null) {
    const age = pi.patch_surveyed ? (Date.now() / 1000 - pi.patch_surveyed) / 86400 : null;
    const stale = age != null && age > 8;
    const warn = pi.patches_security > 0 || pi.reboot_required > 0;
    const short = `${pi.patches_pending}${pi.patches_security > 0 ? ` · ${pi.patches_security} security` : ''}`;
    cells.push(['Updates', esc(short), `${warn ? 'warn' : ''}${stale ? ' stale' : ''}`]);
    const bits = [`${pi.patches_pending} waiting`];
    if (pi.patches_security > 0) bits.push(`${pi.patches_security} of them security`);
    if (pi.reboot_required > 0) bits.push('asks for a rebirth');
    patchLine = `<dt>Updates</dt><dd class="${warn ? 'warn' : ''}${stale ? ' stale' : ''}"` +
      ` title="weekly patch survey${age != null ? ` · surveyed ${Math.round(age)}d ago` : ''}">` +
      `${esc(bits.join(', '))}${stale ? ' — the survey is stale' : ''}</dd>`;
  }
  $('card-strip').innerHTML = cells.map(([label, value, cls]) =>
    `<div class="cs-cell"><span class="cs-label">${esc(label)}</span>` +
    `<span class="cs-value ${cls}">${value}</span></div>`).join('');

  // If this place is dark because something it depends on is dark, say so —
  // "it is down" is true but useless; "it is behind the hypervisor" is the
  // thing you act on (see Web/dependencies.py).
  const cause = $('card-cause');
  cause.hidden = !info?.cause;
  if (info?.cause) {
    const causeNode = nodeById(info.cause);
    const viaNode = info.via && info.via !== info.cause ? nodeById(info.via) : null;
    cause.innerHTML = `${info.planned ? 'Closed for work' : 'Unreachable'} behind ` +
      `<strong>${esc(causeNode ? causeNode.name : info.cause)}</strong>` +
      (viaNode ? ` (via ${esc(viaNode.name)})` : '');
  }

  /* SPLIT / SCROLL, right above the drawer.
     ⁘ THE CONSTELLATION — scatter this place's services onto the map as their
     own dots so each one's roads can be read separately (2026-07-31).
     Both labels are rendered; body.constellation in CSS decides which shows,
     so neither this card nor world.js ever redraws the button to flip it.
     Existence = own links + pass-throughs (A.serviceEntriesFor — the same list
     the split rings), so a pure transit place like PANGOLIN still offers ⁘. */
  const entries = A.serviceEntriesFor?.(n.id) || [];
  let actions = '';
  if (entries.length) {
    actions += `<button class="card-split" id="btn-card-split" title="Draw each service as its own dot, with the routes it uses">` +
      `${ICON.split}<span class="cs-off">Split into services</span><span class="cs-on">Gather its services</span></button>`;
  }
  /* The scroll: an Obsidian link — its own URI scheme opens the note in the
     desktop app — with the path one click away for a machine without it. */
  if (n.scroll) {
    actions += `<span class="card-scroll">` +
      `<a href="${esc(obsidianHref(n.scroll))}" title="Open the scroll in Obsidian">${ICON.note}Scroll</a>` +
      `<button type="button" id="btn-card-scroll-copy" title="Copy the scroll's path" aria-label="Copy the scroll's path">${ICON.copy}</button></span>`;
  }
  $('card-actions').innerHTML = actions;
  $('btn-card-split')?.addEventListener('click', (e) => { e.stopPropagation(); A.toggleConstellation?.(n.id); });
  $('btn-card-scroll-copy')?.addEventListener('click', (e) => { e.stopPropagation(); copyText(n.scroll); });

  /* ── SERVICES: guests first, then its own stalls, then what only passes ── */
  const links = n.links || [];
  // vassals: nodes that name this place as parent (the hypervisor's VMs) — clicking
  // one flies to it (2026-07-11)
  const vassals = A.DATA.nodes.filter((x) => x.parent === n.id);
  // what crosses here — a road is known by its traffic. Each row names its true
  // host: the thing lives there, it only *passes* through here (2026-08-03).
  const crossing = entries.filter((en) => en.passing);
  const row = (attrs, dot, label, meta) =>
    `<li><button class="cd-row" ${attrs}>${dot}<span class="cd-label">${label}</span>` +
    `${meta ? `<span class="cd-meta">${meta}</span>` : ''}${ICON.chev}</button></li>`;
  /* the row's quiet second word: just the port when the service answers on this
     place itself (by its address or its own name), else the host it answers at */
  const metaFor = (url) => {
    const h = host(url).replace(/\/.*$/, '');
    const [name, port] = h.split(':');
    const own = name === n.ip || name.split('.')[0].toLowerCase() === String(n.id).toLowerCase();
    return esc(own ? (port ? `:${port}` : '') : h);
  };
  let svcHTML = '';
  if (vassals.length) {
    svcHTML += `<p class="cd-sub">${say('its vassals')}</p><ul class="cd-rows">` +
      vassals.map((v) => row(`data-go="${esc(v.id)}"`, `<span class="svc-health" data-node="${esc(v.id)}"></span>`,
        esc(v.name), esc(v.ip && v.ip !== '—' ? v.ip : ''))).join('') + '</ul>';
  }
  if (links.length) {
    svcHTML += `<p class="cp-head">Services<span class="n">${links.length}</span></p><ul class="cd-rows">` +
      links.map((l, i) => row(`data-svc="${i}"`,
        `<span class="svc-health"${l.kuma ? ` data-kuma="${esc(l.kuma)}"` : ''}></span>`,
        esc(l.label), metaFor(l.url))).join('') + '</ul>';
  }
  if (crossing.length) {
    svcHTML += `<p class="cd-sub">what crosses here</p><ul class="cd-rows">` +
      crossing.map((en, i) => row(`data-cross="${i}"`,
        `<span class="svc-health"${en.link.kuma ? ` data-kuma="${esc(en.link.kuma)}"` : ''}></span>`,
        esc(en.link.label), esc(en.host.name))).join('') + '</ul>';
  }
  const linksEl = $('card-links');
  linksEl.innerHTML = svcHTML;
  // the tab counts what its heading counts: this place's own services
  if (svcHTML) addTab('services', links.length);
  for (const btn of linksEl.querySelectorAll('[data-go]')) {
    btn.addEventListener('click', (e) => { e.stopPropagation(); A.focusNode(btn.dataset.go); });
  }
  // vassal dots take the HOST feed (data-node), not the service feed
  const nodeFeed = A.signalsFeed?.nodes || {};
  for (const dot of linksEl.querySelectorAll('.svc-health[data-node]')) {
    const st = nodeFeed[dot.dataset.node]?.state;
    if (st) dot.classList.add(A.svcHealthClass[st] || '');
  }
  for (const btn of linksEl.querySelectorAll('[data-svc]')) {
    btn.addEventListener('click', (e) => { e.stopPropagation(); showServiceDetail(n, links[Number(btn.dataset.svc)]); });
  }
  // a pass-through flips to the service on its OWN host, not on this crossing —
  // the detail pane's "a service of X" has to name where the thing actually is
  for (const btn of linksEl.querySelectorAll('[data-cross]')) {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const en = crossing[Number(btn.dataset.cross)];
      if (en) showServiceDetail(en.host, en.link);
    });
  }
  A.paintServiceHealth?.(card);   // K4 — colour the new dots from the current feed

  /* ── DETAILS: the zone line, then the ledger of facts ── */
  const facts = [];
  if (n.ip && n.ip !== '—') facts.push(`<dt>Address</dt><dd class="mono">${esc(n.ip)}</dd>`);
  if (n.hw) facts.push(`<dt>Hardware</dt><dd>${esc(n.hw)}</dd>`);
  if (patchLine) facts.push(patchLine);
  if (n.scroll) {
    // trim the display (drop the configured vault root + the .md) — the link
    // and the copy keep the full path. The root is a deployment value
    // (ATLAS_SCROLL_ROOT), not a constant.
    const root = CFG.SCROLL_ROOT.toLowerCase();
    const shown = (root && n.scroll.toLowerCase().startsWith(root) ? n.scroll.slice(root.length) : n.scroll)
      .replace(/\.md$/i, '');
    facts.push(`<dt>Scroll</dt><dd class="mono">${esc(shown)}</dd>`);
  }
  const zoneLine = zone ? `${zone.name} · ${n.role || ''}`.replace(/ · $/, '') : (n.role || '');
  $('card-data').innerHTML = `<p class="cp-head">Details</p>` +
    (zoneLine ? `<p class="cd-zone">${esc(zoneLine)}</p>` : '') +
    (facts.length ? `<dl class="cd-facts">${facts.join('')}</dl>` : '');
  addTab('details');

  /* ── SCHEDULE: THE FORGE'S DAY (v1.40.0 → part of THE CALENDAR in v1.45.0).
     A place other rites ask for its model — the GPU box — says what turns next and
     offers the door to THE CALENDAR. Every other place gets no tab at all.
     Intent only (the dataset's clocks), never the beats. */
  const forge = $('card-forge');
  const pointer = calendarPointerHTML(n, A.DATA.rites || []);
  forge.innerHTML = pointer;
  if (pointer) {
    addTab('schedule');
    $('btn-card-forge')?.addEventListener('click', () => {
      A.closeAllScenes?.(); A.setSceneActive?.('calendar'); A.openCalendar?.();
    });
  }

  /* ── PULSE: the card draws its OWN pulse (v1.34.0) — the server asks
     Prometheus (`/api/v2/vitals`, ATLAS_PROM_URL) and the card paints
     sparklines. No pulse (endpoint absent, host unknown to Prometheus, scribe
     down) is a quiet absence: no tab, never a fake calm and never an error. */
  const vitals = $('card-vitals');
  vitals.innerHTML = '';
  if (n.spark) {
    vitals.dataset.node = n.id;   // a slow answer must never paint a different card
    fetch(`api/v2/vitals/${encodeURIComponent(n.id)}`, { cache: 'no-store' })
      .then((r) => (r.ok ? r.json() : null))
      .then((v) => {
        if (!v || vitals.dataset.node !== n.id || !A.cardOpen()) return;
        if (v.now?.cpu == null && v.now?.ram == null) return;
        vitals.innerHTML = `<p class="cp-head">Pulse · this week</p>` +
          `<div class="cv-row">${sparkHTML('CPU', v.cpu, v.now?.cpu)}${sparkHTML('Memory', v.ram, v.now?.ram)}</div>` +
          (typeof info?.uptime_30d === 'number'
            ? `<p class="cv-note">Answered for <span class="mono">${info.uptime_30d.toFixed(2)}%</span> of the last 30 days.</p>` : '');
        addTab('pulse');
        layoutCard();
      })
      .catch(() => {});
  }

  paintTabs();
  $('card-svc').hidden = true;   // always land on the node view
  card.classList.remove('svc-open');
  card.classList.add('visible');
  card.setAttribute('aria-hidden', 'false');
  layoutCard();
};

/** flip the card to a single service's detail — its parent host, live status,
    its route and the outward jump. Back returns to the host. (When THE
    CONSTELLATION is open, highlightService finds the service's own scattered
    dot itself — the card never carries map geometry.) */
function showServiceDetail(node, link) {
  if (!link) return;
  const svc = $('card-svc');
  const svcState = A.signalsFeed?.services?.[link.kuma]?.state;
  const hostState = A.signalsFeed?.nodes?.[node.id]?.state;
  const st = svcState || hostState;
  const badge = st
    ? `<span class="csv-chip"><span class="svc-health ${A.svcHealthClass[st] || ''}"></span>${esc(cap(HEALTH_LABEL[st] || st))}</span>`
    : `<span class="csv-chip dim">status unknown</span>`;
  const group = link.require_group
    ? `<span class="csv-chip" title="Only this group may open it">${ICON.lock}${esc(link.require_group)} only</span>` : '';
  const roleShort = (node.role || '').split('·')[0].trim();
  const zone = zoneById(node.zone);
  const where = node.ip && node.ip !== '—' ? node.ip : (node.hw || 'the map');
  /* What this service actually IS, when the dataset says so; a service with no
     description keeps the generated sentence rather than an empty pane —
     charting a new link should never require prose before it reads sensibly. */
  const desc = (link.desc || '').trim();
  // the road out, as stops — the same precedence highlightService uses
  const stops = (link.path || []).map((id) => nodeById(id)?.name || id);
  const facts = [`<dt>Address</dt><dd>${esc(host(link.url))}</dd>`];
  if (link.container) facts.push(`<dt>Container</dt><dd>${esc(link.container)}</dd>`);
  svc.innerHTML =
    `<button class="csv-back" id="csv-back" title="Back to ${esc(node.name)}">${ICON.back}Back to <b>${esc(node.name)}</b></button>` +
    `<div><p class="csv-epi">A service of ${esc(node.name)}${zone ? ' · ' + esc(zone.name) : ''}</p>` +
    `<h3 class="csv-name"><span class="ldot" style="background:${esc(link.hue)}"></span>${esc(link.label)}</h3></div>` +
    `<div class="csv-state">${badge}${group}</div>` +
    `<p class="csv-desc">${desc
      ? esc(desc)
      : `Hosted on <strong>${esc(node.name)}</strong>${roleShort ? ` — ${esc(roleShort)}` : ''}, ` +
        `answering at ${esc(where)}. Follow the routes to its live metrics, or open it directly.`}</p>` +
    (stops.length
      ? `<div class="csv-route"><h4>Its route · ${stops.length} ${stops.length === 1 ? 'stop' : 'stops'}</h4>` +
        `<ol>${stops.map((s) => `<li>${esc(String(s).toUpperCase())}</li>`).join('')}</ol></div>`
      : '') +
    `<dl class="csv-facts">${facts.join('')}</dl>` +
    `<div class="csv-actions">` +
      `<a class="csv-open" href="${esc(link.url)}" target="_blank" rel="noopener"` +
        `${glassAttrs(link.label, `a service of ${node.name}`, link.open_in)}>Open ${esc(link.label)}${ICON.out}</a>` +
      `<div class="csv-twin">` +
      `<button class="csv-metrics" id="csv-path" title="Show it in TOPOLOGY — the tier diagram">${ICON.topo}Topology</button>` +
      // the map-side twin of TOPOLOGY: the same road, drawn where you already
      // are instead of in the tier diagram (2026-08-11)
      `<button class="csv-metrics" id="csv-road" title="Follow its route on the map">${ICON.route}Draw route</button>` +
      `</div></div>`;
  svc.querySelector('#csv-back').addEventListener('click', (e) => {
    e.stopPropagation();
    svc.hidden = true;
    card.classList.remove('svc-open');   // the node view takes its room back
    layoutCard();
  });
  svc.querySelector('#csv-path').addEventListener('click', (e) => {
    e.stopPropagation();
    A.closeCard?.();
    A.setSceneActive?.('path');
    // THE PATH, with this service's host haloed and its reach web lit; the
    // road out wins over the unordered set, same precedence highlightService
    // uses — the two views must not disagree about what this service touches
    A.openPath?.(node.id, link.path || link.connects || node.reaches || [], link.label);
  });
  svc.querySelector('#csv-road').addEventListener('click', (e) => {
    e.stopPropagation();
    A.highlightService?.(node, link);   // draw it, now that it was asked for
  });
  svc.hidden = false;
  /* the pane is a FLOW child: this class folds the node view away so the card
     is exactly as tall as the SERVICE's content (2026-08-16). Nothing is
     drawn on the map by opening a service (2026-08-11): the road is one
     gesture away — Draw route, or clicking a drawn road. */
  card.classList.add('svc-open');
  card.querySelector('.card-inner').scrollTop = 0;
}
/* the constellation's dots flip the card the same way its buttons do */
A.showServiceDetail = showServiceDetail;

/* Which edge the card lands on — and, since 2026-08-25, which edge it ENTERS
   from: `--card-in` is per-side in atlas.css, so the class carries both.
   ⚑ The reflow is load-bearing: both callers set the side and then open the
   card in the SAME synchronous block, so without it a hidden card would start
   its slide from the PREVIOUS card's edge. Only when it is HIDDEN: flipping a
   card that is already up is the `right` transition sliding it across. */
A.setCardSide = (left) => {
  card.classList.toggle('card-left', !!left);
  if (!card.classList.contains('visible')) void card.offsetWidth;   // see above
  else layoutCard();   // the other side clears different chrome
};

A.closeCard = function closeCard() {
  card.classList.remove('visible');
  card.setAttribute('aria-hidden', 'true');
  drawer.open = null; sizeDrawer();
  // a hidden card must not keep its pulse alive or answer a late vitals reply
  const vitals = $('card-vitals');
  if (vitals) { vitals.innerHTML = ''; delete vitals.dataset.node; }
  for (const mk of $('markers').children) mk.classList.remove('active');
  A.clearHighlight?.();   // drops the reach web AND gathers any split — one seam
};

// Is a card on screen? The Escape chain asks, so it can recentre on close
// exactly as the × does — but only when there was actually a card to leave.
A.cardOpen = () => card.classList.contains('visible');

// closing the card with the × re-centers the survey (you were glided off-center to a node)
$('btn-card-close').addEventListener('click', (e) => { e.stopPropagation(); A.closeCard(); A.recenter?.(true); });

/* There is no minimize (owner, 2026-11-11): the pull-tab card with its drawer
   shut is already the small card, and a headline-only state was one more
   thing to get stuck in. × closes it. */

/* ⊖ — pull back WITHOUT losing the place: zooms out around the selected
   marker so its roads come into frame and it stays put. Repeatable, and it
   says so once the whole table is on screen. (2026-07-31) */
$('btn-card-out')?.addEventListener('click', (e) => {
  e.stopPropagation();
  const at = A.pullBack?.();
  if (at === 'floor') A.showToast('The whole table is already in view.');
});
