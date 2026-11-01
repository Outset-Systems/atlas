/* Atlas — screen-space UI: the ivory card, THE INDEX drawer,
   the command-column flyouts, scene buttons, and toasts. */

import { A, CFG, $, esc, host, glassAttrs, zoneById, canAdminWrite, ago, FALLBACK_HUE } from './config.js';
import { chronicleItems, buildChronicle, buildAbyss } from './chronicle.js';
import { makeScene } from './scene.js';

const drawer = $('index-drawer');
const toast = $('toast');

/* ── Toast ──────────────────────────────────────────── */
let toastTimer = 0;
A.showToast = function showToast(msg) {
  toast.textContent = msg;
  toast.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove('show'), CFG.TOAST_MS);
};

/* ── THE INDEX drawer (places + services) ───────────── */
function zoneHeader(list, hue, html) {
  const head = document.createElement('div');
  head.className = 'idx-zone';
  head.style.setProperty('--zone-hue', hue);
  head.innerHTML = html;
  list.appendChild(head);
}

function buildIndex() {
  const list = $('index-list');
  list.innerHTML = '';   // rebuildable: an edit redraws the Index (see A.buildUI)
  for (const z of A.DATA.zones) {
    const nodes = A.DATA.nodes.filter(n => n.zone === z.id);
    if (!nodes.length) continue;
    zoneHeader(list, z.hue, `${esc(z.name)} <span class="sub">vlan ${esc(z.vlan)}</span>`);
    for (const n of nodes) {
      const btn = document.createElement('button');
      btn.className = 'idx-item';
      btn.dataset.search = `${n.name} ${n.role} ${z.name} ${n.ip || ''}`.toLowerCase();
      btn.innerHTML = `<span class="idx-dot" style="background:${esc(z.hue)}"></span>` +
        `<span class="idx-name">${esc(n.name)}</span>` +
        `<span class="idx-role">${esc(n.role.split('·')[0].trim())}</span>`;
      btn.addEventListener('click', () => { A.toggleDrawer(false); A.focusNode(n.id); });
      list.appendChild(btn);
    }
  }
}

/* pinned favorites (H2) — persisted in localStorage, floated to the top */
const PIN_KEY = 'atlas-pins';
const getPins = () => { try { return JSON.parse(localStorage.getItem(PIN_KEY) || '[]'); } catch { return []; } };
const setPins = (p) => { try { localStorage.setItem(PIN_KEY, JSON.stringify(p)); } catch { /* private mode */ } };
function togglePin(url) {
  const p = getPins(); const i = p.indexOf(url);
  if (i >= 0) p.splice(i, 1); else p.push(url);
  setPins(p); buildServices();
}

function svcRow(list, svc) {
  const { name, url, kuma } = svc;
  const sub = svc.group === 'CHRONICLE' ? 'a watching of the lab'
                                        : `a service of ${svc.group}`;
  const pinned = getPins().includes(url);
  const row = document.createElement('div');
  row.className = 'svc-row-wrap';
  row.dataset.search = `${name} ${url}`.toLowerCase();
  row.innerHTML =
    `<a class="svc-row" href="${esc(url)}" target="_blank" rel="noopener"` +
      `${glassAttrs(name, sub, svc.open_in)}>` +
      `<span class="svc-health"${kuma ? ` data-kuma="${esc(kuma)}"` : ''}></span>` +
      `<span class="svc-name">${esc(name)}</span>` +
      `<span class="svc-host">${esc(host(url))}</span></a>` +
    `<button class="svc-pin${pinned ? ' on' : ''}" title="${pinned ? 'Unpin' : 'Pin to top'}">${pinned ? '★' : '☆'}</button>`;
  row.querySelector('.svc-pin').addEventListener('click', (e) => { e.stopPropagation(); togglePin(url); });
  list.appendChild(row);
}

/** flat list of every service {name, url, kuma, open_in, group, gsub, ghue} */
function allServices() {
  const out = [];
  for (const c of chronicleItems()) {
    // open_in rides along like the node loop below — a watching marked `tab`
    // in the Desk must refuse the glass from THE INDEX too, not just from its
    // own slide and flyout (the hand-copied-shape trap glassAttrs exists for)
    out.push({ ghue: 'var(--gilt)', group: 'CHRONICLE', gsub: 'reports',
      name: c.title, url: c.url, open_in: c.open_in });
  }
  for (const n of A.DATA.nodes) {
    if (!n.links?.length) continue;
    const zone = zoneById(n.zone);
    for (const l of n.links) {
      out.push({ ghue: zone ? zone.hue : FALLBACK_HUE, group: n.name,
        gsub: n.ip !== '—' ? n.ip : '', name: l.label, url: l.url, kuma: l.kuma,
        open_in: l.open_in });
    }
  }
  return out;
}

function buildServices() {
  const list = $('services-list');
  list.innerHTML = '';
  const svcs = allServices();
  const pins = getPins();

  const pinned = svcs.filter(s => pins.includes(s.url));
  if (pinned.length) {
    zoneHeader(list, 'var(--gilt)', `PINNED <span class="sub">favorites</span>`);   // the app's gold, per scheme
    for (const s of pinned) svcRow(list, s);
  }

  let group = null;
  for (const s of svcs) {
    if (s.group !== group) {
      group = s.group;
      zoneHeader(list, s.ghue, `${esc(s.group)} <span class="sub">${esc(s.gsub || '')}</span>`);
    }
    svcRow(list, s);
  }
  A.paintServiceHealth?.(list);   // K4 — colour dots from the current feed
  A.applyIndexSearch?.();         // keep an active filter after a rebuild (e.g. pin)
}

/* ☰ IS THE INDEX BUTTON, AND AN INDEX BUTTON MUST OPEN AN INDEX (the owner,
   2026-08-26). Since 2026-09-04 that is all it CAN open: settings left the
   drawer for a scene of its own (the ⚙ beside ☰ in the band), so the drawer
   is PLACES and SERVICES and nothing else, and the rule that ☰ must never
   land on settings is met by there being no settings here to land on.

   Which of the two it shows is the reader's last choice, remembered — the
   Index is a thing you return to, and returning it to the section you were
   working in is the whole point. localStorage because it is a per-reader
   convenience, not app state — and wrapped, because a private window makes it
   throw rather than return null. Applied once the search wiring below exists
   (selectDrawerTab touches it). */
const LIST_TABS = ['places', 'services'];
const LAST_TAB_KEY = 'atlas-drawer-tab';
let lastListTab = 'places';
try {
  const saved = localStorage.getItem(LAST_TAB_KEY);
  if (LIST_TABS.includes(saved)) lastListTab = saved;
} catch { /* no storage: the default stands */ }

A.toggleDrawer = function toggleDrawer(open) {
  const willOpen = open ?? !drawer.classList.contains('open');
  drawer.classList.toggle('open', willOpen);
  drawer.setAttribute('aria-hidden', String(!willOpen));
  // A right-hand card sits under the Index (which docks right), so drawer-open
  // shoves it clear; a left-hand card already clears the drawer and stays put.
  // Toggling the body class is all that's needed — the :not(.card-left) rule in
  // atlas.css decides which cards actually move.
  document.body.classList.toggle('drawer-open', willOpen);
};

/* ☰ opens the panel and ☰ closes it (2026-08-15). The head's own » is gone:
   the drawer hangs from this button, so this button is the control that acts
   on it — Esc and a click on the map still close it too. */
$('btn-menu').addEventListener('click', () => A.toggleDrawer());

/* One drawer, two sections. (Three from 2026-08-10, with settings folded in;
   the scenes left for their own band 2026-08-15; settings left for a scene of
   its own 2026-09-04 — see the SETTINGS scene below.) */
const DRAWER_SECTIONS = { places: 'index-list', services: 'services-list' };
function selectDrawerTab(name) {
  if (LIST_TABS.includes(name)) {
    lastListTab = name;
    try { localStorage.setItem(LAST_TAB_KEY, name); } catch { /* not worth failing over */ }
  }
  document.querySelectorAll('.dtab').forEach(t => t.classList.toggle('active', t.dataset.tab === name));
  for (const [key, id] of Object.entries(DRAWER_SECTIONS)) {
    const el = $(id);
    if (el) el.hidden = key !== name;
  }
  updateSeekRow();   // the DEGOOG row rides with the search box
}

document.querySelectorAll('.dtab').forEach(tab => {
  tab.addEventListener('click', () => selectDrawerTab(tab.dataset.tab));
});

/* ── Index search — filters PLACES + SERVICES live (H1 sibling) ──────────
   Rows carry data-search; a zone/group header stays if it matches OR any of
   its rows survive, so results keep their heading. */
function filterList(listEl, q) {
  let header = null, headerMatch = false, shown = 0;
  const flush = () => { if (header) header.hidden = shown === 0 && !headerMatch; };
  for (const el of listEl.children) {
    if (el.classList.contains('idx-zone')) {
      flush();
      header = el; shown = 0;
      headerMatch = Boolean(q) && el.textContent.toLowerCase().includes(q);
      continue;
    }
    const hay = el.dataset.search || el.textContent.toLowerCase();
    const match = !q || headerMatch || hay.includes(q);
    el.hidden = !match;
    if (match) shown++;
  }
  flush();
}

const idxSearch = $('idx-search'), idxClear = $('idx-search-clear');
A.applyIndexSearch = function applyIndexSearch() {
  const q = idxSearch.value.trim().toLowerCase();
  idxClear.hidden = !q;
  filterList($('index-list'), q);
  filterList($('services-list'), q);
  updateSeekRow();
};

/* ── THE SEEKING — hand the query to DEGOOG (H1's outward sibling) ────────
   The filter above answers "where is it on the map"; this row answers "it is
   not on the map" by offering the same words to the realm's own metasearch.
   Opt-in from settings (THE SEEKING), remembered per browser, and drawn only
   while a query is typed — an empty search has nothing to seek. The service
   is found in the dataset rather than configured here, so the row simply does
   not exist on an Atlas that charts no Degoog. */
const DEGOOG_KEY = 'atlas-degoog';
const degoogOn = () => { try { return localStorage.getItem(DEGOOG_KEY) === '1'; } catch { return false; } };
const setDegoogOn = (on) => { try { localStorage.setItem(DEGOOG_KEY, on ? '1' : '0'); } catch { /* private mode */ } };
function degoogService() {
  for (const n of A.DATA?.nodes || []) {
    for (const l of n.links || []) {
      if (l.container === 'degoog' || /degoog/i.test(l.label || '')) return l;
    }
  }
  return null;
}
function updateSeekRow() {
  const row = $('idx-seek');
  if (!row) return;
  const q = idxSearch.value.trim();
  row.hidden = !(degoogOn() && q && degoogService());
}
$('idx-seek')?.addEventListener('click', () => {
  const svc = degoogService();
  const q = idxSearch.value.trim();
  if (!svc || !q) return;
  // a search-results page in the glass would be a browser inside a browser —
  // the seeking leaves for a real tab, and the map is still here on return
  window.open(svc.url.replace(/\/+$/, '') + '/search?q=' + encodeURIComponent(q),
    '_blank', 'noopener');
});
idxSearch.addEventListener('input', A.applyIndexSearch);
idxSearch.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') { e.stopPropagation(); if (idxSearch.value) { idxSearch.value = ''; A.applyIndexSearch(); } else idxSearch.blur(); }
});
idxClear.addEventListener('click', () => { idxSearch.value = ''; A.applyIndexSearch(); idxSearch.focus(); });
if (lastListTab !== 'places') selectDrawerTab(lastListTab);   // the remembered tab (see LIST_TABS)

/* ── The sky ascent ─────────────────────────────────── */
/* the sky button rises to the Upper Deck (where the Chronicle lives) —
   the mirror of the Depths button that descends south */
$('btn-sky').addEventListener('click', () => A.ascend());

/* Scenes: clicking a scene selects it; clicking the ACTIVE scene again
   deselects — back to the atlas. THE PATH merged into THE LEDGER (2026-07-11).
   The ◆ button that used to carry the `lit` mark is gone (2026-08-10), so ☰
   wears it instead: with the drawer shut, that lamp is the only thing telling
   you a scene is open over the map. */
function setSceneActive(name) {
  // `[data-scene]`, not `.scene`: the ⚙ in the band is the SETTINGS scene's
  // button with a glyph instead of a word (2026-09-04), and it wears the
  // same `.active` — the CSS styles it in its own chrome dress.
  document.querySelectorAll('[data-scene]').forEach(b => b.classList.toggle('active', b.dataset.scene === name));
  $('btn-menu')?.classList.toggle('lit', name !== 'atlas');
  document.querySelector(`.scene[data-scene="${name}"]`)?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  /* `body.scene-open` lifts the scene band above the overlays and firms up its
     fill (atlas.css) — the switcher is the one control you still want while a
     scene is up, and at z-960 under an `inset: 0` z-985 overlay it was buried,
     so changing scenes meant closing the one you were in first. Same condition
     the ☰ lamp already used; it just needed to be readable from CSS. */
  document.body.classList.toggle('scene-open', name !== 'atlas');
  /* Read by THE ATLAS's own click handler to decide which of its two jobs is
     on offer. Kept on `A` rather than re-read from the DOM so the answer is
     the same one `setSceneActive` just decided. */
  A.sceneOpen = name !== 'atlas';
}
A.setSceneActive = setSceneActive;

/* Every route home closes the lot: the band's own THE ATLAS button, and now
   ⚙ under ☰, which must leave a scene before it opens the drawer underneath
   one. Stated once so a scene added to the band cannot be closed by one route
   and not the other. */
function closeAllScenes() {
  A.closeReliquary?.(); A.closeTribute?.(); A.closeLedger?.(); A.closePath?.();
  A.closeCalendar?.(); A.closeSeals?.(); A.closeStones?.(); A.closeAnnals?.();
  A.closeAccounts?.(); A.closeTrust?.(); A.closeSettings?.();
}
A.closeAllScenes = closeAllScenes;   // the Escape chain (camera.js) reads this list rather than keeping its own
A.showAtlas = function showAtlas() {
  closeAllScenes();
  setSceneActive('atlas');
};

/* ACCOUNTS is the one scene whose data is admin-only, so it is the one button
   that is not always there. The roster is stripped server-side for anyone not
   cleared (redaction.py), which means a non-admin who opened it would meet an
   empty scene reading "nothing charted yet" — a lie by omission, and exactly
   the "drawing calm over a gap" this app refuses elsewhere. Offer the door
   only to someone who can walk through it; the strip is the actual control.
   ONE spelling of the question (`canAdminWrite`), the same one the ✎ chrome
   and the provisioner rows use. */
if (canAdminWrite()) $('scene-accounts')?.removeAttribute('hidden');
/* THE TRUST is admin-only for the same reason ACCOUNTS is, one step
   sharper: it is the shortest description of where to aim a forged
   header. The endpoint refuses non-admins on its own — this only
   declines to offer a door that would answer 403. */
if (canAdminWrite()) $('scene-trust')?.removeAttribute('hidden');

document.querySelectorAll('[data-scene]').forEach(btn => {
  btn.addEventListener('click', () => {
    /* The scenes live in their own band at the top of the screen now
       (2026-08-15), so a scene click no longer involves the drawer at all —
       which settles v1.10.13's close-it/keep-it-open question by removing it.
       An open drawer stays open; the scene overlays already inset themselves
       past it (body.drawer-open in atlas.css), so nothing is covered. */
    // THE REPAIRS was retired as a scene 2026-08-04. The maintenance windows
    // themselves are untouched — they still suppress alarms server-side and are
    // still edited from the Desk; only the read-only viewer is gone.
    const scenes = { rack: A.openReliquary, tribute: A.openTribute, ledger: A.openLedger,
                     path: A.openPath, calendar: A.openCalendar,
                     seals: A.openSeals, stones: A.openStones, annals: A.openAnnals,
                     accounts: A.openAccounts, trust: A.openTrust,
                     settings: A.openSettings };
    const deselect = btn.classList.contains('active');
    /* THE ATLAS is the home button (owner, 2026-11-01): it closes whatever is
       up and brings the whole map back to centre. A.home and not A.recenter,
       because from the Depths home is the map, not the middle of the Depths. */
    if (btn.dataset.scene === 'atlas') {
      closeAllScenes();
      setSceneActive('atlas');
      A.closeCard?.();
      A.home(true);
      return;
    }
    closeAllScenes();
    if (deselect) { setSceneActive('atlas'); return; }
    setSceneActive(btn.dataset.scene);
    scenes[btn.dataset.scene]?.();
  });
});

/* ── Chrome buttons wired to camera/world ───────────── */
// the recenter (✦) button was removed; recenter still lives on the card ×,
// the Home key, and clicking a selected marker again (2026-07-12)
$('btn-zoom-in').addEventListener('click', () => A.zoomAt(innerWidth / 2, innerHeight / 2, CFG.ZOOM_BTN));
$('btn-zoom-out').addEventListener('click', () => A.zoomAt(innerWidth / 2, innerHeight / 2, 1 / CFG.ZOOM_BTN));
$('btn-depths').addEventListener('click', () => A.descend());
$('btn-net').addEventListener('click', () => A.toggleNet());

/* The map tools drop down from THE ATLAS (owner, 2026-11-01), a column beside
   the zoom column: sky, depths, tripwires. Not `:hover`, because the cluster
   is not a descendant of the band (see `.atlas-tools` in atlas.css). The close is
   delayed so the pointer can cross the gap and reach the column it just opened.
   A touch screen has no hover, so atlas.css keeps the column out there. */
function hoverReveal(anchor, cluster, delay = 220) {
  if (!anchor || !cluster) return;
  let timer = null;
  const peek = (on) => {
    clearTimeout(timer);
    if (on) { cluster.classList.add('peek'); return; }
    timer = setTimeout(() => cluster.classList.remove('peek'), delay);
  };
  [anchor, cluster].forEach(el => {
    el.addEventListener('mouseenter', () => peek(true));
    el.addEventListener('mouseleave', () => peek(false));
    el.addEventListener('focusin', () => peek(true));
    el.addEventListener('focusout', () => peek(false));
  });
}
hoverReveal($('scene-home'), $('atlas-tools'));

/* The band's labels scroll in their own strip. `.over` brings out ‹ › only while
   something is out of reach; they are dimmed at the end they have reached. */
const labels = $('band-labels');
function paintBandArrows() {
  const room = labels.scrollWidth - labels.clientWidth;
  $('scenes-list').classList.toggle('over', room > 1);
  $('band-prev').disabled = labels.scrollLeft <= 1;
  $('band-next').disabled = labels.scrollLeft >= room - 1;
}
const slideBand = (by) => labels.scrollBy({ left: by, behavior: 'smooth' });
$('band-prev').addEventListener('click', () => slideBand(-240));
$('band-next').addEventListener('click', () => slideBand(240));
labels.addEventListener('scroll', paintBandArrows, { passive: true });
labels.addEventListener('wheel', (e) => {
  if (!e.deltaY || labels.scrollWidth <= labels.clientWidth) return;
  e.preventDefault();
  labels.scrollLeft += e.deltaY;
}, { passive: false });
new ResizeObserver(paintBandArrows).observe(labels);

/* ── SETTINGS is a scene (2026-09-04) ──────────────────────────────
   It was the drawer's tabless third section, and that shape cost a rule per
   release: ☰ must not open onto it, the search must hide over it, the title
   must rename itself, ⚙ must come home from a scene before opening a drawer
   that sits UNDER the scenes. As a scene it inherits all of that from the one
   shell every other scene uses (scene.js) — the ⚙ in the band is a scene
   button with a glyph instead of a word and goes through the click handler
   above, so THE ATLAS, Escape (camera.js → closeAllScenes) and the × all
   leave it the same way. `build` runs on every open: the account and admin
   sections re-render from the live posture, the render list is a cheap fetch,
   and THE WATCHERS' clock starts here and stops in `onClose` — it must not
   tick against a panel nobody can see. */
const settingsScene = makeScene({
  id: 'settings', closeId: 'set-close',
  build: () => {
    A.renderSettingsSections();
    renderSources();
    clearInterval(sourcesTimer);
    sourcesTimer = setInterval(renderSources, 5000);
    A.buildCartographer?.();   // the render list is a cheap fetch, fresh per open
  },
  onClose: () => clearInterval(sourcesTimer),
});
A.openSettings = settingsScene.open;
A.closeSettings = settingsScene.close;
settingsScene.mount();

/* ── Settings — the sections' own wiring: THE WATCHERS, THE SURVEY, THE SEEKING ── */

/* Which signal sources are reporting (and how stale). A silent Kuma degrades the
   map to its static self by design — quietly — so without this the only way to
   tell "everything is healthy" from "nothing is reporting" was to curl the API. */
function renderSources() {
  const el = $('sp-sources');
  if (!el) return;
  const src = A.signalsSources;
  if (!src) {
    el.innerHTML = '<span class="sp-src sp-src-silent">no feed: nothing is reporting</span>';
    return;
  }
  const names = Object.keys(src);
  if (!names.length) {
    el.innerHTML = '<span class="sp-src sp-src-silent">no sources configured</span>';
    return;
  }
  const age = A.signalsAt ? ago(Date.now() - A.signalsAt) : '';
  el.innerHTML =
    names.map((n) => `<span class="sp-src sp-src-${src[n] === 'ok' ? 'ok' : 'silent'}">${esc(n)}</span>`).join('') +
    (age ? `<span class="sp-src-age">read ${age}</span>` : '');
}

/* Started by the SETTINGS scene's `build` and stopped by its `onClose` (the
   scene is declared a hundred lines above). Declared with `var` on purpose:
   the scene's hooks touch this, and a `let` here would leave it in the
   temporal dead zone if anything ever opened the scene during module
   evaluation rather than on a click. */
var sourcesTimer = 0;   // eslint-disable-line no-var

/* ── Folding sections (2026-08-15) ─────────────────────────────────
   Settings grew from one checkbox to five sections — account, directory,
   survey tools, the seeking, the watchers — and an admin on an accounts
   instance scrolled past the eight-field AD form to reach "Move the dots".
   Every `.sp-sub` is a button now: it folds its own section, and the folds
   are remembered per browser. Delegated from the panel because the account
   and directory sections re-render their headers on every open. */
const FOLD_KEY = 'atlas-sp-folds';
const getFolds = () => { try { return JSON.parse(localStorage.getItem(FOLD_KEY) || '{}'); } catch { return {}; } };
/* Sections you have not touched start CLOSED (2026-08-16) — settings
   used to greet you with every section standing open, a wall where the one
   thing you came for was somewhere in the middle. ACCOUNT alone defaults
   open: who you are is the panel's first answer, and it is three lines tall.
   A fold you HAVE set (either way) is remembered over the default, so this
   changes nothing for a section you already arranged. */
const FOLD_DEFAULT_OPEN = new Set(['account']);
function applyFolds() {
  const folds = getFolds();
  for (const sec of document.querySelectorAll('#settings-panel .sp-sec')) {
    const key = sec.dataset.sec;
    const closed = Object.hasOwn(folds, key)
      ? Boolean(folds[key])
      : !FOLD_DEFAULT_OPEN.has(key);
    sec.classList.toggle('closed', closed);
  }
}
$('settings-panel')?.addEventListener('click', (e) => {
  const head = e.target.closest('.sp-sub');
  const sec = head?.closest('.sp-sec');
  if (!sec || !sec.dataset.sec) return;
  const closed = sec.classList.toggle('closed');
  // the admin ledgers load their body on first unfold (adminSection)
  if (!closed && sec._load) { const f = sec._load; sec._load = null; f(); }
  const folds = getFolds();
  folds[sec.dataset.sec] = closed;
  try { localStorage.setItem(FOLD_KEY, JSON.stringify(folds)); } catch { /* private mode */ }
});
A.applySettingsFolds = applyFolds;   // the account/directory renders call back in
applyFolds();   // the static sections; the dynamic two re-apply after render

/* THE SEEKING's switch — see updateSeekRow above for what it turns on */
const spDegoog = $('sp-degoog');
if (spDegoog) {
  spDegoog.checked = degoogOn();
  spDegoog.addEventListener('change', (e) => {
    setDegoogOn(e.target.checked);
    updateSeekRow();
    if (e.target.checked && !degoogService()) {
      A.showToast('No Degoog is charted on this map — the row will appear once one is.');
    }
  });
}

$('sp-editmode').addEventListener('change', (e) => {
  A.setEditMode(e.target.checked);
  $('sp-edit-hint').hidden = !e.target.checked;
  if (e.target.checked && !A.netOn()) A.showToast('Move the dots — drag any place to reposition it.');
});
$('sp-save').addEventListener('click', async (e) => {
  e.stopPropagation();
  try {
    const res = await A.savePositions();
    A.showToast(res.saved ? `Saved ${res.saved} ${res.saved === 1 ? 'place' : 'places'} to the map — permanent for everyone.`
                          : 'No places have been moved yet.');
  } catch (err) {
    A.showToast(`Could not save: ${err.message || err}`);
  }
});
$('sp-copy').addEventListener('click', (e) => {
  e.stopPropagation();
  const n = A.copyPositions();
  A.showToast(n ? `${n} moved ${n === 1 ? 'place' : 'places'} copied to clipboard.`
                : 'No places have been moved yet.');
});
$('sp-reset').addEventListener('click', (e) => {
  e.stopPropagation();
  A.resetPositions();
});
/* The map-click dismisser that used to hide the settings panel is gone
   (2026-08-10). Settings is a scene now (2026-09-04): its scrim, its ×,
   Escape and the band close it, exactly as they close every other scene. */
// The agent has no chrome button anymore — the watcher lives on the map, in the Lost
// Woods, reachable like any other place (2026-07-11). The colour scheme is
// scheme.js's (v1.52.0): the panels follow it, the map stays a night map.
/* (#sky-title's listener retired 2026-08-15 — see world.js by buildSkyIsland) */

/* The two region headings read their facts from the dataset (2026-08-15).
   The sky's carousel is headed by the ZONE's own name and vlan — renaming or
   re-vlan'ing it in the Desk must move this heading exactly as it moves the
   map's labels and the Index, and the template's baked text was already wrong
   for the demo dataset (its sky is vlan 10, not 4). The prose halves of the
   subtitles stay authored in the template: they are voice, not data. */
function nameRegionHeads() {
  const sky = A.DATA.zones?.find(z => z.id === 'sky');
  if (sky) {
    $('chronicle').querySelector('.chron-head').textContent = `THE ${sky.name.toUpperCase()}`;
    $('chronicle').querySelector('.chron-sub').textContent =
      `vlan ${sky.vlan} · the realm above the realm`;
  }
  const depths = A.DATA.zones?.find(z => z.id === 'depths');
  if (depths) {
    $('abyss').querySelector('.abyss-head').textContent = depths.name.toUpperCase();
  }
}

A.buildUI = function buildUI() {
  buildIndex();
  buildServices();
  buildChronicle();
  buildAbyss();
  nameRegionHeads();
};
