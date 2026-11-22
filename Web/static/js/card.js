
import { A, CFG, $, esc, host, glassAttrs, svcKey, zoneById, nodeById, FALLBACK_HUE, canAdminWrite, themeText } from './config.js';
import { say } from './words.js';
import { calendarPointerHTML } from './calendar.js';
import * as M from './card-model.js';
import { serviceWeb } from './world-model.js';
import { checkWhere } from './watch-model.js';
import { favouriteOf, favouriteOps, tileFor } from './favourite-model.js';

const card = $('card');

const HEALTH_LABEL = { healthy: 'answering', degraded: 'faltering', down: 'gone dark', maintenance: 'under repair', slumbering: 'slumbering' };
const cap = (s) => String(s).charAt(0).toUpperCase() + String(s).slice(1);

const ICON = {
  chev: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M6 3l5 5-5 5"/></svg>',
  back: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M10 3L5 8l5 5"/></svg>',
  split: '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="1.6"/><circle cx="3" cy="4" r="1.2"/><circle cx="13" cy="4" r="1.2"/><circle cx="3" cy="12" r="1.2"/><circle cx="13" cy="12" r="1.2"/></svg>',
  note: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 2.5h7.5a1.5 1.5 0 0 1 1.5 1.5v9.5H5.5A1.5 1.5 0 0 1 4 12V2.5z"/><path d="M4 12a1.5 1.5 0 0 1 1.5-1.5H13M6.5 5.5h4M6.5 8h3"/></svg>',
  copy: '<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="5" y="5" width="8" height="9" rx="1"/><path d="M3 11V3a1 1 0 0 1 1-1h6"/></svg>',
  out: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M9 3h4v4M13 3L7 9M11 9v4H3V5h4"/></svg>',
  topo: '<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="6" y="2" width="4" height="3"/><rect x="2" y="11" width="4" height="3"/><rect x="10" y="11" width="4" height="3"/><path d="M8 5v3M4 11V8h8v3"/></svg>',
  wire: '<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="1.5" y="5" width="4.5" height="6" rx="1"/><rect x="10" y="5" width="4.5" height="6" rx="1"/><path d="M6 8h4"/></svg>',
  route: '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="3.5" cy="12.5" r="1.5"/><circle cx="12.5" cy="3.5" r="1.5"/><path d="M5 12.5h4a2.5 2.5 0 0 0 0-5H7a2.5 2.5 0 0 1 0-5h4"/></svg>',
  lock: '<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="3" y="7" width="10" height="7" rx="1"/><path d="M5.5 7V5a2.5 2.5 0 0 1 5 0v2"/></svg>',
};

function sparkHTML(label, series, nowVal) {
  const w = 160, h = 40;
  const line = M.sparkPoints(series, w, h);
  let svg = '';
  if (line) {
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
    const ta = document.createElement('textarea');
    ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.appendChild(ta); ta.select();
    try { document.execCommand('copy'); } finally { ta.remove(); }
  }
  A.showToast('The scroll’s path is copied to your clipboard.');
}

const obsidianHref = (scroll) => M.obsidianHref(scroll, String(CFG.SCROLL_ROOT || ''));

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

A.nodeLogo = nodeLogo;

function setPortrait(n) {
  const slug = nodeLogo(n) || 'waypoints';
  $('card-portrait').innerHTML = `<img class="portrait-logo" src="static/icons/${slug}.svg" alt="">`;
}

const PANES = { services: 'card-links', pulse: 'card-vitals', details: 'card-data', schedule: 'card-forge' };
const TAB_LABEL = { services: 'SERVICES', pulse: 'PULSE', details: 'DETAILS', schedule: 'SCHEDULE' };
const drawer = { tabs: [], counts: {}, open: null };

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

function sizeDrawer() {
  const want = drawer.open ? paneHeight(drawer.open) : 0;
  const h = Math.min(want, roomPx || want);
  card.style.setProperty('--drawer-h', `${h}px`);
}

function paneHeight(id) {
  for (const [pid, el] of Object.entries(PANES)) $(el).hidden = pid !== id;
  return id ? $(PANES[id]).offsetHeight + 2 : 0;
}

function pullTab(id) {
  drawer.open = drawer.open === id ? null : id;
  paintTabs();
  if (drawer.open) stand.panes[drawer.open] = paneHeight(drawer.open);
  standFor(drawer.open);
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

let roomPx = 0;
const stand = { panes: {}, shut: 0, topMin: 0, rest: 0 };
const RESTING_PANE = 'details';
const narrow = () => window.matchMedia('(max-width: 720px)').matches;
const BOTTOM = 24, MIN_ROOM = 140;

function measurePanes() {
  const heights = {};
  for (const id of drawer.tabs) heights[id] = paneHeight(id);
  return heights;
}

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
  if (card.classList.contains('svc-open')) return;
  const cs = getComputedStyle(card);
  const clear = parseFloat(cs.getPropertyValue('--card-clear')) || 174;
  const over = parseFloat(cs.getPropertyValue('--medal-over')) || 0;
  stand.panes = measurePanes();
  const tallest = Math.max(0, ...Object.values(stand.panes));
  const was = cs.getPropertyValue('--drawer-h');
  card.style.setProperty('--drawer-h', '0px');
  const shut = card.offsetHeight;
  card.style.setProperty('--drawer-h', was);
  if (narrow()) {
    card.classList.remove('anchored');
    roomPx = Math.max(MIN_ROOM, Math.min(tallest, window.innerHeight - clear - over - shut));
  } else {
    stand.shut = shut;
    stand.topMin = clear - 60 + over;
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
document.fonts?.ready?.then(() => { if (A.cardOpen()) layoutCard(); });
document.fonts?.addEventListener?.('loadingdone', () => { if (A.cardOpen()) layoutCard(); });

function fillHead(n, zone) {
  const hue = zone ? zone.hue : FALLBACK_HUE;
  card.style.setProperty('--card-hue', hue);
  setPortrait(n);
  drawer.tabs = []; drawer.counts = {}; drawer.open = null;

  $('card-name').textContent = n.name;
  $('card-lore').textContent = n.lore || '';

  const parentBtn = $('card-parent');
  const parent = n.parent ? nodeById(n.parent) : null;
  parentBtn.hidden = !parent;
  if (parent) {
    parentBtn.innerHTML = `${esc(cap(say('vassal')))} of <b>${esc(parent.name)}</b>${ICON.chev}`;
    parentBtn.onclick = (e) => { e.stopPropagation(); A.focusNode(parent.id); };
  }
}

function fillStrip(info) {
  const cells = [];
  if (info?.state) {
    cells.push(['State', `<span class="svc-health ${A.svcHealthClass?.[info.state] || ''}"></span>` +
      esc(cap(HEALTH_LABEL[info.state] || info.state)), '']);
  }
  if (typeof info?.uptime_30d === 'number') cells.push(['30 days', `${info.uptime_30d.toFixed(2)}%`, 'mono']);
  let patchLine = '';
  if (info && info.patches_pending != null) {
    const age = info.patch_surveyed ? (Date.now() / 1000 - info.patch_surveyed) / 86400 : null;
    const stale = age != null && age > 8;
    const warn = info.patches_security > 0 || info.reboot_required > 0;
    const short = `${info.patches_pending}${info.patches_security > 0 ? ` · ${info.patches_security} security` : ''}`;
    cells.push(['Updates', esc(short), `${warn ? 'warn' : ''}${stale ? ' stale' : ''}`]);
    const bits = [`${info.patches_pending} waiting`];
    if (info.patches_security > 0) bits.push(`${info.patches_security} of them security`);
    if (info.reboot_required > 0) bits.push('asks for a rebirth');
    patchLine = `<dt>Updates</dt><dd class="${warn ? 'warn' : ''}${stale ? ' stale' : ''}"` +
      ` title="weekly patch survey${age != null ? ` · surveyed ${Math.round(age)}d ago` : ''}">` +
      `${esc(bits.join(', '))}${stale ? ' — the survey is stale' : ''}</dd>`;
  }
  $('card-strip').innerHTML = cells.map(([label, value, cls]) =>
    `<div class="cs-cell"><span class="cs-label">${esc(label)}</span>` +
    `<span class="cs-value ${cls}">${value}</span></div>`).join('');

  const cause = $('card-cause');
  cause.hidden = !info?.cause;
  if (info?.cause) {
    const causeNode = nodeById(info.cause);
    const viaNode = info.via && info.via !== info.cause ? nodeById(info.via) : null;
    cause.innerHTML = `${info.planned ? 'Closed for work' : 'Unreachable'} behind ` +
      `<strong>${esc(causeNode ? causeNode.name : info.cause)}</strong>` +
      (viaNode ? ` (via ${esc(viaNode.name)})` : '');
  }
  return patchLine;
}

function fillFromView(n) {
  const line = $('card-from-view');
  if (!line) return;
  const away = document.body.classList.contains('deck');
  const toMap = away && !A.PHONE;
  const toDesk = away && canAdminWrite() && A.editorReady?.() && typeof A.editPlace === 'function';
  line.hidden = !(toMap || toDesk);
  line.innerHTML =
    (toMap ? `<button type="button" class="cfv-map">${esc(themeText('show_on_map', 'Show on the map ›'))}</button>` : '') +
    (toDesk ? `<button type="button" class="cfv-edit">${esc(themeText('edit_place', 'Edit ›'))}</button>` : '');
  line.querySelector('.cfv-map')?.addEventListener('click', (e) => {
    e.stopPropagation();
    A.setView('map', { remember: true });
    A.focusNode(n.id);
  });
  line.querySelector('.cfv-edit')?.addEventListener('click', (e) => {
    e.stopPropagation();
    A.editPlace(n.id);
  });
}

function fillActions(n, entries) {
  let actions = '';
  if (entries.length) {
    actions += `<button class="card-split" id="btn-card-split" title="Draw each service as its own dot, with the routes it uses">` +
      `${ICON.split}<span class="cs-off">Split into services</span><span class="cs-on">Gather its services</span></button>`;
  }
  if (n.scroll) {
    actions += `<span class="card-scroll">` +
      `<a href="${esc(obsidianHref(n.scroll))}" title="Open the scroll in Obsidian">${ICON.note}Scroll</a>` +
      `<button type="button" id="btn-card-scroll-copy" title="Copy the scroll's path" aria-label="Copy the scroll's path">${ICON.copy}</button></span>`;
  }
  $('card-actions').innerHTML = actions;
  $('btn-card-split')?.addEventListener('click', (e) => { e.stopPropagation(); A.toggleConstellation?.(n.id); });
  $('btn-card-scroll-copy')?.addEventListener('click', (e) => { e.stopPropagation(); copyText(n.scroll); });
}

function fillServices(n, entries) {
  const links = n.links || [];
  const vassals = A.DATA.nodes.filter((x) => x.parent === n.id);
  const crossing = entries.filter((en) => en.passing);
  const row = (attrs, dot, label, meta, heart = '') =>
    `<li${heart ? ' class="cd-has-fav"' : ''}><button class="cd-row" ${attrs}>${dot}<span class="cd-label">${label}</span>` +
    `${meta ? `<span class="cd-meta">${meta}</span>` : ''}${ICON.chev}</button>${heart}</li>`;
  const metaFor = (url) => esc(M.serviceMeta(host(url), n));
  const metaOf = (l) => (l.url ? metaFor(l.url) : esc(checkWhere(l, n)));
  let svcHTML = '';
  if (vassals.length) {
    svcHTML += `<p class="cd-sub">${say('its vassals')}</p><ul class="cd-rows">` +
      vassals.map((v) => row(`data-go="${esc(v.id)}"`, `<span class="svc-health" data-node="${esc(v.id)}"></span>`,
        esc(v.name), esc(v.ip && v.ip !== '—' ? v.ip : ''))).join('') + '</ul>';
  }
  if (links.length) {
    svcHTML += `<p class="cp-head">Services<span class="n">${links.length}</span></p><ul class="cd-rows">` +
      links.map((l, i) => row(`data-svc="${i}"`,
        `<span class="svc-health" data-kuma="${esc(svcKey(l, n.id))}"></span>`,
        esc(l.label), metaOf(l), heartHTML(l, `data-fav-svc="${i}"`, ' cd-fav'))).join('') + '</ul>';
  }
  if (crossing.length) {
    svcHTML += `<p class="cd-sub">what crosses here</p><ul class="cd-rows">` +
      crossing.map((en, i) => row(`data-cross="${i}"`,
        `<span class="svc-health" data-kuma="${esc(svcKey(en.link, en.host.id))}"></span>`,
        esc(en.link.label), esc(en.host.name),
        heartHTML(en.link, `data-fav-cross="${i}"`, ' cd-fav'))).join('') + '</ul>';
  }
  const linksEl = $('card-links');
  linksEl.innerHTML = svcHTML;
  if (svcHTML) addTab('services', links.length);
  for (const btn of linksEl.querySelectorAll('[data-go]')) {
    btn.addEventListener('click', (e) => { e.stopPropagation(); A.focusNode(btn.dataset.go); });
  }
  const nodeFeed = A.signalsFeed?.nodes || {};
  for (const dot of linksEl.querySelectorAll('.svc-health[data-node]')) {
    const st = nodeFeed[dot.dataset.node]?.state;
    if (st) dot.classList.add(A.svcHealthClass[st] || '');
  }
  for (const btn of linksEl.querySelectorAll('[data-svc]')) {
    btn.addEventListener('click', (e) => { e.stopPropagation(); showServiceDetail(n, links[Number(btn.dataset.svc)]); });
  }
  for (const btn of linksEl.querySelectorAll('[data-cross]')) {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const en = crossing[Number(btn.dataset.cross)];
      if (en) showServiceDetail(en.host, en.link);
    });
  }
  for (const btn of linksEl.querySelectorAll('[data-fav-svc]')) {
    btn.addEventListener('click', (e) => { e.stopPropagation(); pressHeart(btn, n, links[Number(btn.dataset.favSvc)]); });
  }
  for (const btn of linksEl.querySelectorAll('[data-fav-cross]')) {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const en = crossing[Number(btn.dataset.favCross)];
      if (en) pressHeart(btn, en.host, en.link);
    });
  }
  A.paintServiceHealth?.(card);
}

function fillDetails(n, zone, patchLine) {
  const facts = [];
  if (n.ip && n.ip !== '—') facts.push(`<dt>Address</dt><dd class="mono">${esc(n.ip)}</dd>`);
  if (n.hw) facts.push(`<dt>Hardware</dt><dd>${esc(n.hw)}</dd>`);
  if (patchLine) facts.push(patchLine);
  if (n.scroll) {
    const root = CFG.SCROLL_ROOT.toLowerCase();
    const shown = (M.scrollTail(n.scroll, root) ?? n.scroll).replace(/\.md$/i, '');
    facts.push(`<dt>Scroll</dt><dd class="mono">${esc(shown)}</dd>`);
  }
  const zoneLine = zone ? `${zone.name} · ${n.role || ''}`.replace(/ · $/, '') : (n.role || '');
  $('card-data').innerHTML = `<p class="cp-head">Details</p>` +
    (zoneLine ? `<p class="cd-zone">${esc(zoneLine)}</p>` : '') +
    (facts.length ? `<dl class="cd-facts">${facts.join('')}</dl>` : '');
  addTab('details');
}

function fillSchedule(n) {
  const forge = $('card-forge');
  const pointer = calendarPointerHTML(n, A.DATA.rites || []);
  forge.innerHTML = pointer;
  if (pointer) {
    addTab('schedule');
    $('btn-card-forge')?.addEventListener('click', () => {
      A.closeAllScenes?.(); A.setSceneActive?.('calendar'); A.openCalendar?.();
    });
  }
}

function loadPulse(n, info) {
  const vitals = $('card-vitals');
  vitals.innerHTML = '';
  vitals.dataset.node = n.id;
  if (n.spark) {
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
}

A.openCard = function openCard(n) {
  const zone = zoneById(n.zone);
  fillHead(n, zone);
  const info = A.signalsFeed?.nodes?.[n.id];
  const patchLine = fillStrip(info);
  const entries = A.serviceEntriesFor?.(n.id) || [];
  fillFromView(n);
  fillActions(n, entries);
  fillServices(n, entries);
  fillDetails(n, zone, patchLine);
  fillSchedule(n);
  loadPulse(n, info);

  paintTabs();
  $('card-svc').hidden = true;
  card.dataset.place = n.id;
  card.classList.remove('svc-open');
  card.classList.add('visible');
  card.setAttribute('aria-hidden', 'false');
  layoutCard();
};

const HEART = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 20.3 4.6 12.9a4.9 4.9 0 0 1 6.9-6.9l.5.5.5-.5a4.9 4.9 0 0 1 6.9 6.9z"/></svg>';
const mayFavour = () => canAdminWrite() && document.body.dataset.editable === '1';
function heartRefusal() {
  const lookOnly = document.body.dataset.demo === '1' || Boolean(CFG.AUTH?.admin);
  return lookOnly
    ? `This ${document.body.dataset.demo === '1' ? 'demo' : 'Atlas'} is look-only, so a favourite can't be saved here`
    : 'Only someone who may edit the map can change a favourite';
}
function heartWords(link, tile) {
  if (!String(link.url || '').trim()) return 'It has no address, so OVERVIEW cannot list it as a favourite';
  if (!mayFavour()) return `${tile ? `A favourite on OVERVIEW (${tile})` : 'Not a favourite'}. ${heartRefusal()}`;
  return tile
    ? `A favourite: listed on OVERVIEW (${tile}). Press to take it off`
    : `Add to OVERVIEW's favourites (${tileFor(link.url)})`;
}
function heartHTML(link, attrs = 'id="csv-fav"', cls = '') {
  const tile = favouriteOf(A.DATA, link.url);
  const words = heartWords(link, tile);
  const ro = mayFavour() ? '' : ' ro';
  return `<button type="button" class="csv-fav${cls}${ro}${tile ? ' on' : ''}" ${attrs} data-url="${esc(link.url || '')}" aria-pressed="${Boolean(tile)}"` +
    `${String(link.url || '').trim() ? '' : ' disabled'}${ro ? ' aria-disabled="true"' : ''} title="${esc(words)}" aria-label="${esc(words)}">${HEART}</button>`;
}
function syncHearts(link, now) {
  const words = heartWords(link, now);
  for (const b of card.querySelectorAll('.csv-fav')) {
    if (b.dataset.url !== String(link.url || '')) continue;
    b.classList.toggle('on', Boolean(now));
    b.setAttribute('aria-pressed', String(Boolean(now)));
    b.title = words;
    b.setAttribute('aria-label', words);
  }
}
async function pressHeart(btn, node, link) {
  if (btn.disabled) return;
  if (!mayFavour()) { A.showToast?.(`${heartRefusal()}.`); return; }
  btn.disabled = true;
  try {
    const { Editor } = await import('./editor/index.js');
    await Editor.load();
    const was = favouriteOf(Editor.data, link.url);
    const ops = favouriteOps(Editor.data, node.id, link, !was);
    if (!ops.length && !was) throw new Error('the map has changed; open the service again and retry');
    if (ops.length) {
      await Editor.apply(ops, was
        ? `${link.label} is no longer a favourite (the heart on its card)`
        : `${link.label} is a favourite, ${tileFor(link.url)} (the heart on its card)`);
    }
    const now = favouriteOf(Editor.data, link.url);
    syncHearts(link, now);
    A.showToast?.(now ? `${link.label} is on OVERVIEW's ${now} favourites.` : `${link.label} is off the favourites.`);
  } catch (err) {
    A.showToast?.(`Not saved: ${err.message || err}`);
  } finally {
    btn.disabled = false;
  }
}

function showServiceDetail(node, link) {
  if (!link) return;
  const svc = $('card-svc');
  const svcState = A.signalsFeed?.services?.[svcKey(link, node.id)]?.state;
  const hostState = A.signalsFeed?.nodes?.[node.id]?.state;
  const st = svcState || hostState;
  const dot = `<span class="svc-health ${st ? A.svcHealthClass[st] || '' : ''}" ` +
    `title="${st ? esc(cap(HEALTH_LABEL[st] || st)) : 'No live state for this service'}"></span>`;
  const badge = st
    ? `<span class="csv-chip">${esc(cap(HEALTH_LABEL[st] || st))}</span>`
    : `<span class="csv-chip dim">status unknown</span>`;
  const hostInfo = A.signalsFeed?.nodes?.[node.id];
  let updates = '';
  if (hostInfo && hostInfo.patches_pending != null) {
    const n = hostInfo.patches_pending, sec = hostInfo.patches_security > 0 ? hostInfo.patches_security : 0;
    const reboot = hostInfo.reboot_required > 0;
    const words = n > 0
      ? `${n} host update${n === 1 ? '' : 's'}${sec ? ` · ${sec} security` : ''}`
      : reboot ? 'Host needs a restart' : 'Host up to date';
    const told = `From the weekly patch survey of ${node.name}` +
      `${n > 0 && reboot ? ', which also needs a restart' : ''}. ` +
      'Atlas does not yet know this service\'s own version.';
    updates = `<span class="csv-chip${n > 0 || reboot ? ' warn' : ''}" title="${esc(told)}">${esc(words)}</span>`;
  }
  const group = link.require_group && link.require_group !== '*'
    ? `<span class="csv-chip" title="Only this group may open it">${ICON.lock}${esc(link.require_group)} only</span>` : '';
  const roleShort = (node.role || '').split('·')[0].trim();
  const zone = zoneById(node.zone);
  const where = node.ip && node.ip !== '—' ? node.ip : (node.hw || 'the map');
  const desc = (link.desc || '').trim();
  const stops = (link.path || []).map((id) => nodeById(id)?.name || id);
  const facts = [`<dt>Address</dt><dd>${esc(link.url ? host(link.url) : checkWhere(link, node))}</dd>`];
  if (link.container) facts.push(`<dt>Container</dt><dd>${esc(link.container)}</dd>`);
  svc.innerHTML =
    `<button class="csv-back" id="csv-back" title="Back to ${esc(node.name)}">${ICON.back}Back to <b>${esc(node.name)}</b></button>` +
    `<div><p class="csv-epi">A service of ${esc(node.name)}${zone ? ' · ' + esc(zone.name) : ''}</p>` +
    `<h3 class="csv-name">${dot}<span class="csv-name-t">${esc(link.label)}</span>${heartHTML(link)}</h3></div>` +
    `<div class="csv-state">${badge}${updates}${group}</div>` +
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
      (link.url
        ? `<a class="csv-open" href="${esc(link.url)}" target="_blank" rel="noopener"` +
          `${glassAttrs(link.label, `a service of ${node.name}`, link.open_in)}>Open ${esc(link.label)}${ICON.out}</a>`
        : '') +
      `<div class="csv-twin">` +
      `<button class="csv-metrics" id="csv-path" title="Show it in TOPOLOGY — the tier diagram">${ICON.topo}Topology</button>` +
      `<button class="csv-metrics" id="csv-road" title="Follow its route on the map">${ICON.route}Draw route</button>` +
      `</div>` +
      `<button class="csv-metrics" id="csv-wiring" title="Show its place in WIRING, lit from the head down">${ICON.wire}Wiring</button>` +
      `</div>`;
  svc.querySelector('#csv-fav')?.addEventListener('click', (e) => { e.stopPropagation(); pressHeart(e.currentTarget, node, link); });
  svc.querySelector('#csv-back').addEventListener('click', (e) => {
    e.stopPropagation();
    svc.hidden = true;
    card.classList.remove('svc-open');
    layoutCard();
  });
  svc.querySelector('#csv-path').addEventListener('click', (e) => {
    e.stopPropagation();
    A.closeCard?.();
    A.setSceneActive?.('path');
    const web = serviceWeb(node, link, A.DATA.routes);
    A.openPath?.(node.id, web.chain.length ? web.chain : [...web.ids], link.label);
  });
  svc.querySelector('#csv-wiring').addEventListener('click', (e) => {
    e.stopPropagation();
    A.closeCard?.();
    A.openTopology?.(node.id);
  });
  svc.querySelector('#csv-road').addEventListener('click', (e) => {
    e.stopPropagation();
    A.highlightService?.(node, link);
  });
  svc.hidden = false;
  card.classList.add('svc-open');
  card.querySelector('.card-inner').scrollTop = 0;
}
A.showServiceDetail = showServiceDetail;

A.setCardSide = (left) => {
  card.classList.toggle('card-left', !!left);
  if (!card.classList.contains('visible')) void card.offsetWidth;
  else layoutCard();
};

A.closeCard = function closeCard() {
  card.classList.remove('visible');
  card.setAttribute('aria-hidden', 'true');
  delete card.dataset.place;
  drawer.open = null; sizeDrawer();
  const vitals = $('card-vitals');
  if (vitals) { vitals.innerHTML = ''; delete vitals.dataset.node; }
  for (const mk of $('markers').children) mk.classList.remove('active');
  A.clearHighlight?.();
};

A.cardOpen = () => card.classList.contains('visible');
A.cardPlace = () => (A.cardOpen() ? card.dataset.place || null : null);

$('btn-card-close').addEventListener('click', (e) => { e.stopPropagation(); A.closeCard(); A.recenter?.(true); });


$('btn-card-out')?.addEventListener('click', (e) => {
  e.stopPropagation();
  const at = A.pullBack?.();
  if (at === 'floor') A.showToast('The whole table is already in view.');
});
