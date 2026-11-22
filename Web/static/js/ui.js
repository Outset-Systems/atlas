
import { A, CFG, $, esc, host, glassAttrs, svcKey, zoneById, canAdminWrite, ago, FALLBACK_HUE } from './config.js';
import { say } from './words.js';
import { chronicleItems, buildChronicle, buildAbyss } from './chronicle.js';
import { makeScene } from './scene.js';
import { sceneChanged } from './scheme.js';

const drawer = $('index-drawer');
const toast = $('toast');

let toastTimer = 0;
A.showToast = function showToast(msg) {
  toast.textContent = msg;
  toast.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove('show'), CFG.TOAST_MS);
};

function zoneHeader(list, hue, html) {
  const head = document.createElement('div');
  head.className = 'idx-zone';
  head.style.setProperty('--zone-hue', hue);
  head.innerHTML = html;
  list.appendChild(head);
}

function buildIndex() {
  const list = $('index-list');
  list.innerHTML = '';
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

const PIN_KEY = 'atlas-pins';
const getPins = () => { try { return JSON.parse(localStorage.getItem(PIN_KEY) || '[]'); } catch { return []; } };
const setPins = (p) => { try { localStorage.setItem(PIN_KEY, JSON.stringify(p)); } catch {   } };
function togglePin(url) {
  const p = getPins(); const i = p.indexOf(url);
  if (i >= 0) p.splice(i, 1); else p.push(url);
  setPins(p); buildServices();
}

function svcRow(list, svc) {
  const { name, url, kuma } = svc;
  const sub = svc.group === 'CHRONICLE' ? say('a watching of the lab')
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

function allServices() {
  const out = [];
  for (const c of chronicleItems()) {
    out.push({ ghue: 'var(--gilt)', group: 'CHRONICLE', gsub: 'reports',
      name: c.title, url: c.url, open_in: c.open_in });
  }
  for (const n of A.DATA.nodes) {
    if (!n.links?.length) continue;
    const zone = zoneById(n.zone);
    for (const l of n.links) {
      if (!l?.url) continue;
      out.push({ ghue: zone ? zone.hue : FALLBACK_HUE, group: n.name,
        gsub: n.ip !== '—' ? n.ip : '', name: l.label, url: l.url, kuma: svcKey(l, n.id),
        open_in: l.open_in });
    }
  }
  return out;
}

let applyIndexSearch;

function buildServices() {
  const list = $('services-list');
  list.innerHTML = '';
  const svcs = allServices();
  const pins = getPins();

  const pinned = svcs.filter(s => pins.includes(s.url));
  if (pinned.length) {
    zoneHeader(list, 'var(--gilt)', `PINNED <span class="sub">favorites</span>`);
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
  A.paintServiceHealth?.(list);
  applyIndexSearch?.();
}

const LIST_TABS = ['places', 'services'];
const LAST_TAB_KEY = 'atlas-drawer-tab';
let lastListTab = 'places';
try {
  const saved = localStorage.getItem(LAST_TAB_KEY);
  if (LIST_TABS.includes(saved)) lastListTab = saved;
} catch {   }

const ROLLUP_MS = 4000;
const mouse = (e) => e.pointerType === 'mouse';
const working = (panel) => {
  const el = document.activeElement;
  return !!el && panel.contains(el) && (el.matches('input, textarea, select') || el.matches(':focus-visible'));
};
function idleRollup(panel, parts, { isUp, rollUp, after = ROLLUP_MS }) {
  let timer = null;
  let fade = null;
  let inside = false;
  const wake = () => {
    clearTimeout(timer); clearTimeout(fade); timer = null;
    panel.classList.remove('idle');
  };
  const later = () => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      if (inside || !isUp()) return;
      if (working(panel)) return;
      panel.classList.remove('idle');
      rollUp();
    }, after);
  };
  const leave = () => {
    inside = false;
    if (!isUp()) return;
    clearTimeout(fade);
    fade = setTimeout(() => { if (!inside && isUp()) panel.classList.add('idle'); }, Math.min(160, after / 4));
    later();
  };
  for (const el of parts) {
    el.addEventListener('pointerenter', (e) => { if (mouse(e)) { inside = true; wake(); } });
    el.addEventListener('pointerleave', (e) => { if (mouse(e)) leave(); });
  }
  panel.addEventListener('focusin', () => { if (working(panel)) wake(); });
  panel.addEventListener('focusout', (e) => {
    if (panel.contains(e.relatedTarget) || inside || !isUp()) return;
    if (panel.classList.contains('idle') || timer) { panel.classList.add('idle'); later(); }
  });
  return { wake, leave };
}

let drawerIdle = null;
A.toggleDrawer = function toggleDrawer(open) {
  const willOpen = open ?? !drawer.classList.contains('open');
  if (willOpen && listsStale) buildLists();
  if (!willOpen) drawerIdle?.wake();
  drawer.classList.toggle('open', willOpen);
  drawer.setAttribute('aria-hidden', String(!willOpen));
  document.body.classList.toggle('drawer-open', willOpen);
};

$('btn-menu').addEventListener('click', () => A.toggleDrawer());
drawerIdle = idleRollup(drawer, [drawer, $('btn-menu')], {
  isUp: () => drawer.classList.contains('open'),
  rollUp: () => A.toggleDrawer(false),
});

const DRAWER_SECTIONS = { places: 'index-list', services: 'services-list' };
function selectDrawerTab(name) {
  if (LIST_TABS.includes(name)) {
    lastListTab = name;
    try { localStorage.setItem(LAST_TAB_KEY, name); } catch {   }
  }
  document.querySelectorAll('.dtab').forEach(t => t.classList.toggle('active', t.dataset.tab === name));
  for (const [key, id] of Object.entries(DRAWER_SECTIONS)) {
    const el = $(id);
    if (el) el.hidden = key !== name;
  }
  updateSeekRow();
}

document.querySelectorAll('.dtab').forEach(tab => {
  tab.addEventListener('click', () => selectDrawerTab(tab.dataset.tab));
});

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
applyIndexSearch = function () {
  const q = idxSearch.value.trim().toLowerCase();
  idxClear.hidden = !q;
  filterList($('index-list'), q);
  filterList($('services-list'), q);
  updateSeekRow();
};

const SEARXNG_KEY = 'atlas-searxng';
const searxngOn = () => { try { return localStorage.getItem(SEARXNG_KEY) === '1'; } catch { return false; } };
const setSearXNGOn = (on) => { try { localStorage.setItem(SEARXNG_KEY, on ? '1' : '0'); } catch {   } };
function searxngService() {
  for (const n of A.DATA?.nodes || []) {
    for (const l of n.links || []) {
      if (l.url && (l.container === 'searxng' || /searxng/i.test(l.label || ''))) return l;
    }
  }
  return null;
}
function updateSeekRow() {
  const row = $('idx-seek');
  if (!row) return;
  const q = idxSearch.value.trim();
  row.hidden = !(searxngOn() && q && searxngService());
}
$('idx-seek')?.addEventListener('click', () => {
  const svc = searxngService();
  const q = idxSearch.value.trim();
  if (!svc || !q) return;
  window.open(svc.url.replace(/\/+$/, '') + '/search?q=' + encodeURIComponent(q),
    '_blank', 'noopener');
});
idxSearch.addEventListener('input', applyIndexSearch);
idxSearch.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') { e.stopPropagation(); if (idxSearch.value) { idxSearch.value = ''; applyIndexSearch(); } else idxSearch.blur(); }
});
idxClear.addEventListener('click', () => { idxSearch.value = ''; applyIndexSearch(); idxSearch.focus(); });
if (lastListTab !== 'places') selectDrawerTab(lastListTab);


function setSceneActive(name) {
  document.querySelectorAll('[data-scene]').forEach(b => b.classList.toggle('active', b.dataset.scene === name));
  document.querySelector(`.scene[data-scene="${name}"]`)?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  document.body.classList.toggle('scene-open', name !== 'atlas');
  sceneChanged(name !== 'atlas');
  A.sceneOpen = name !== 'atlas';
}
A.setSceneActive = setSceneActive;

function closeAllScenes() {
  A.closeReliquary?.(); A.closeTribute?.(); A.closeLedger?.(); A.closePath?.();
  A.closeCalendar?.(); A.closeSeals?.(); A.closeStones?.(); A.closeAnnals?.();
  A.closeAccounts?.(); A.closeTrust?.(); A.closeSettings?.();
  if (A.sceneOpen) setSceneActive('atlas');
}
A.closeAllScenes = closeAllScenes;

if (canAdminWrite()) $('scene-accounts')?.removeAttribute('hidden');
if (canAdminWrite() || CFG.DEMO_TRUST) $('scene-trust')?.removeAttribute('hidden');

if (document.body.dataset.demo === '1' && !canAdminWrite() && CFG.DEMO_LINK) {
  const invite = document.createElement('a');
  invite.id = 'first-survey';
  invite.className = 'fs-demo fs-link';
  invite.href = CFG.DEMO_LINK;
  invite.target = '_blank';
  invite.rel = 'noopener';
  invite.innerHTML = '<span class="fs-head">YOU ARE LOOKING AT THE DEMO</span>' +
    '<span class="fs-sub">get Atlas for your own lab ›</span>';
  document.body.append(invite);
}

document.querySelectorAll('[data-scene]').forEach(btn => {
  btn.addEventListener('click', () => {
    const scenes = { rack: A.openReliquary, tribute: A.openTribute, ledger: A.openLedger,
                     path: A.openPath, calendar: A.openCalendar,
                     seals: A.openSeals, stones: A.openStones, annals: A.openAnnals,
                     accounts: A.openAccounts, trust: A.openTrust,
                     settings: A.openSettings };
    const deselect = btn.classList.contains('active');
    if (btn.dataset.scene === 'atlas') {
      closeAllScenes();
      setSceneActive('atlas');
      A.closeCard?.();
      closeViewMenu(false);
      mapEditor(false);
      if (A.PHONE) { A.deckTop?.(); return; }
      if (A.VIEW !== 'map') A.setView('map', { remember: true });
      if (A.inRegion?.()) { A.leaveToMap(); return; }
      A.home(true);
      return;
    }
    if (deselect && btn.dataset.place) {
      dispatchEvent(new CustomEvent('atlas:scene-place', { detail: { scene: btn.dataset.scene, place: '' } }));
      return;
    }
    closeAllScenes();
    if (deselect) { setSceneActive('atlas'); return; }
    mapEditor(false);
    setSceneActive(btn.dataset.scene);
    scenes[btn.dataset.scene]?.();
  });
});

$('btn-zoom-in').addEventListener('click', () => A.zoomAt(innerWidth / 2, innerHeight / 2, CFG.ZOOM_BTN));
$('btn-zoom-out').addEventListener('click', () => A.zoomAt(innerWidth / 2, innerHeight / 2, 1 / CFG.ZOOM_BTN));
$('btn-net').addEventListener('click', () => A.toggleNet());

const reveals = new Set();
function hoverReveal(anchor, cluster, { delay = 220, onChange = () => {}, refuse = () => false, shut = () => {} } = {}) {
  if (!anchor || !cluster) return { close() {} };
  let timer = null;
  let over = false;
  const atOnce = (change) => {
    cluster.style.transition = 'none';
    change();
    void cluster.offsetWidth;
    cluster.style.transition = '';
  };
  const cut = () => {
    clearTimeout(timer);
    if (!cluster.classList.contains('peek') && !cluster.classList.contains('open')) return false;
    atOnce(() => { cluster.classList.remove('peek'); shut(); onChange(); });
    return true;
  };
  reveals.add(cut);
  const keyed = () => {
    const el = document.activeElement;
    return !!el && (anchor.contains(el) || cluster.contains(el)) && el.matches(':focus-visible');
  };
  const peek = (on, how) => {
    clearTimeout(timer);
    if (on) {
      if (refuse(how)) return;
      let took = false;
      for (const other of reveals) if (other !== cut && other()) took = true;
      const show = () => { cluster.classList.add('peek'); onChange(); };
      if (took) atOnce(show); else show();
      return;
    }
    timer = setTimeout(() => {
      if (how === 'pointer' ? keyed() : over) return;
      cluster.classList.remove('peek');
      if (how === 'pointer') shut();
      onChange();
    }, delay);
  };
  [anchor, cluster].forEach(el => {
    el.addEventListener('pointerenter', (e) => { if (mouse(e)) { over = true; peek(true, 'pointer'); } });
    el.addEventListener('pointerleave', (e) => { if (mouse(e)) { over = false; peek(false, 'pointer'); } });
    el.addEventListener('focusin', (e) => {
      if (e.target.matches?.(':focus-visible')) peek(true, 'focus');
    });
    el.addEventListener('focusout', (e) => {
      if (anchor.contains(e.relatedTarget) || cluster.contains(e.relatedTarget)) return;
      peek(false, 'focus');
    });
  });
  return { close() { clearTimeout(timer); cluster.classList.remove('peek'); onChange(); } };
}

function mapEditor(open) {
  dispatchEvent(new CustomEvent('atlas:map-editor', { detail: { open } }));
}

const viewMenu = $('view-menu') || document.createElement('div');
const viewMore = $('view-more') || document.createElement('button');
const sceneHome = $('scene-home');
const viewItems = () => [...viewMenu.querySelectorAll('[role="menuitem"]')].filter((b) => !b.hidden && b.getClientRects().length);
const inViewChrome = (el) => !!el && (viewMenu.contains(el) || sceneHome.contains(el));
let viewHush = false;

function paintViewMenu() {
  const shown = viewMenu.classList.contains('peek') || viewMenu.classList.contains('open');
  viewMore.setAttribute('aria-expanded', String(shown));
  if (!shown) return;
  const r = sceneHome.getBoundingClientRect();
  viewMenu.style.setProperty('--view-menu-x', `${Math.max(8, Math.round(r.left))}px`);
}
const viewReveal = hoverReveal(sceneHome, viewMenu, {
  onChange: paintViewMenu,
  refuse: (how) => A.PHONE || (how === 'focus' && viewHush),
  shut: () => viewMenu.classList.remove('open'),
});
function openViewMenu(focusFirst) {
  viewHush = false;
  viewMenu.classList.add('open');
  paintViewMenu();
  if (focusFirst) viewItems()[0]?.focus();
}
function closeViewMenu(focusOpener) {
  if (focusOpener) viewHush = true;
  viewMenu.classList.remove('open');
  viewReveal.close();
  if (focusOpener) (viewMore.getClientRects().length ? viewMore : sceneHome?.querySelector('[data-scene="atlas"]'))?.focus();
}

viewMore.addEventListener('click', (e) => {
  e.stopPropagation();
  if (viewMenu.classList.contains('open')) closeViewMenu(e.detail === 0);
  else openViewMenu(true);
});
viewMore.addEventListener('keydown', (e) => {
  if (e.key !== 'ArrowDown') return;
  e.preventDefault(); e.stopPropagation();
  openViewMenu(true);
});
sceneHome?.querySelector('[data-scene="atlas"]')?.addEventListener('keydown', (e) => {
  if (e.key !== 'ArrowDown' || A.PHONE) return;
  e.preventDefault(); e.stopPropagation();
  openViewMenu(true);
});
viewMenu.addEventListener('keydown', (e) => {
  if (e.key === 'Tab') return;
  e.stopPropagation();
  const items = viewItems();
  const at = items.indexOf(document.activeElement);
  const go = (i) => { e.preventDefault(); items[(i + items.length) % items.length]?.focus(); };
  if (e.key === 'ArrowDown') go(at + 1);
  else if (e.key === 'ArrowUp') go(at < 0 ? items.length - 1 : at - 1);
  else if (e.key === 'Home') go(0);
  else if (e.key === 'End') go(items.length - 1);
  else if (e.key === 'Escape') { e.preventDefault(); closeViewMenu(true); }
});
viewMenu.addEventListener('click', (e) => {
  if (e.target.closest('[data-act="records"]')) {
    e.stopPropagation();
    closeViewMenu(false);
    if (viewMenu.contains(document.activeElement)) document.activeElement.blur();
    dispatchEvent(new CustomEvent('atlas:records'));
    return;
  }
  const item = e.target.closest('[data-view]');
  if (!item) return;
  e.stopPropagation();
  const keyboard = e.detail === 0;
  const wasAway = A.VIEW !== 'map';
  closeAllScenes();
  setSceneActive('atlas');
  A.setView(item.dataset.view, { remember: true });
  if (item.dataset.view === 'map' && wasAway) A.home?.(true);
  closeViewMenu(keyboard);
  if (!keyboard && viewMenu.contains(document.activeElement)) document.activeElement.blur();
  if (item.dataset.view === 'map') mapEditor(wasAway ? true : undefined);
});
[viewMenu, sceneHome].forEach((el) => el.addEventListener('focusout', (e) => {
  if (inViewChrome(e.relatedTarget)) return;
  viewHush = false;
  if (viewMenu.classList.contains('open')) { viewMenu.classList.remove('open'); paintViewMenu(); }
}));
document.addEventListener('pointerdown', (e) => {
  if (!viewMenu.classList.contains('open') || inViewChrome(e.target)) return;
  closeViewMenu(false);
});

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

const settingsScene = makeScene({
  id: 'settings', closeId: 'set-close',
  build: () => {
    A.renderSettingsSections();
    renderSources();
    clearInterval(sourcesTimer);
    sourcesTimer = setInterval(renderSources, 5000);
    dispatchEvent(new CustomEvent('atlas:settings', { detail: { open: true } }));
  },
  onClose: () => {
    clearInterval(sourcesTimer);
    dispatchEvent(new CustomEvent('atlas:settings', { detail: { open: false } }));
  },
});
A.openSettings = settingsScene.open;
A.closeSettings = settingsScene.close;
settingsScene.mount();


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

var sourcesTimer = 0;

const FOLD_KEY = 'atlas-sp-folds';
const getFolds = () => { try { return JSON.parse(localStorage.getItem(FOLD_KEY) || '{}'); } catch { return {}; } };
const FOLD_DEFAULT_OPEN = new Set(['account']);
const FOLD_PANELS = ['settings-panel', 'map-editor-body'];
if (A.PHONE) {
  const words = document.querySelector('#map-editor-body .sp-sec[data-sec="words"]');
  const you = document.querySelector('#settings-panel [data-group="you"]');
  if (words && you) you.append(words);
}
function applyFolds() {
  const folds = getFolds();
  for (const sec of document.querySelectorAll(':is(#settings-panel, #map-editor-body) .sp-sec')) {
    if (sec.classList.contains('sp-fixed')) continue;
    const key = sec.dataset.sec;
    const closed = Object.hasOwn(folds, key)
      ? Boolean(folds[key])
      : !(FOLD_DEFAULT_OPEN.has(key) || sec.closest('#map-editor-body'));
    sec.classList.toggle('closed', closed);
  }
}
for (const id of FOLD_PANELS) $(id)?.addEventListener('click', (e) => {
  const head = e.target.closest('.sp-sub');
  const sec = head?.closest('.sp-sec');
  if (!sec || !sec.dataset.sec || sec.classList.contains('sp-fixed')) return;
  const closed = sec.classList.toggle('closed');
  if (!closed && sec._load) { const f = sec._load; sec._load = null; f(); }
  const folds = getFolds();
  folds[sec.dataset.sec] = closed;
  try { localStorage.setItem(FOLD_KEY, JSON.stringify(folds)); } catch {   }
});
A.applySettingsFolds = applyFolds;
applyFolds();

const spSearXNG = $('sp-searxng');
if (spSearXNG) {
  spSearXNG.checked = searxngOn();
  spSearXNG.addEventListener('change', (e) => {
    setSearXNGOn(e.target.checked);
    updateSeekRow();
    if (e.target.checked && !searxngService()) {
      A.showToast('No SearXNG is charted on this map — the row will appear once one is.');
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
    const what = `${res.saved} ${res.saved === 1 ? 'spot' : 'spots'}`;
    A.showToast(!res.saved ? 'No places have been moved yet.'
      : res.style ? `Saved ${what} to ${res.style}. Everyone who views this map style sees them there.`
      : `Saved ${res.saved} ${res.saved === 1 ? 'place' : 'places'} to the map — permanent for everyone.`);
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

function nameRegionHeads() {
  const sky = A.DATA.zones?.find(z => z.id === 'upper');
  if (sky) {
    $('chronicle').querySelector('.chron-head').textContent = `THE ${sky.name.toUpperCase()}`;
    $('chronicle').querySelector('.chron-sub').textContent =
      `vlan ${sky.vlan} · ${say('over the map')}`;
  }
  const depths = A.DATA.zones?.find(z => z.id === 'lower');
  if (depths) {
    $('abyss').querySelector('.abyss-head').textContent = depths.name.toUpperCase();
  }
}

let listsStale = false;
function buildLists() {
  listsStale = false;
  buildIndex();
  buildServices();
}

A.buildUI = function buildUI() {
  if (drawer.classList.contains('open')) buildLists();
  else listsStale = true;
  buildChronicle();
  buildAbyss();
  nameRegionHeads();
};

export { hoverReveal };
