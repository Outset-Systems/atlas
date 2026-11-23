
import { A, $, esc, canAdminWrite } from './config.js';
import {
  LEVELS, boxesOn, crumbLabel, crumbs, descend, hashWithPremise, hiddenAt, leaveTo, lineage, ownHolders,
  planSpots, premiseFromHash, premiseIndex, premiseOf, premiseOfPlan, schematic, under,
} from './premises-model.js';

const SCOPE_KEY = 'atlas.premise';
const bar = $('premise-bar');
const sheet = $('premise-sheet');
const announce = $('premise-announce');

let scope = '';
try { scope = localStorage.getItem(SCOPE_KEY) || ''; } catch {   }
let menuOpen = false;


let read = { data: null, ix: null, where: null, own: null };
function tree() {
  if (read.data !== A.DATA) {
    const ix = premiseIndex(A.DATA);
    const where = premiseOf(A.DATA, ix);
    read = { data: A.DATA, ix, where, own: ownHolders(where) };
  }
  return read;
}

export function premiseScope() {
  const { ix } = tree();
  return scope && ix?.byId.has(scope) ? scope : '';
}

export function hiddenByPremise(n) {
  const { ix, where } = tree();
  return ix.size ? hiddenAt(ix, where, n, premiseScope()) : false;
}

const stateOf = (id) => A.signalsFeed?.nodes?.[id]?.state || null;


export function openPremise(id, { exact = false, quiet = false } = {}) {
  const { ix, own } = tree();
  let to = id && ix.byId.has(id) ? id : '';
  if (to && !exact) to = descend(ix, own, to);
  const changed = to !== premiseScope();
  if (changed) planImages = null;
  scope = to;
  try { if (to) localStorage.setItem(SCOPE_KEY, to); else localStorage.removeItem(SCOPE_KEY); } catch {   }
  writeHash(to);
  menuOpen = false;
  paint();
  if (changed) {
    followPlan(to);
    A.buildWorld?.();
    A.repaintSignals?.();
    dispatchEvent(new CustomEvent('atlas:premise', { detail: { id: to } }));
    if (!quiet && announce) {
      const p = ix.byId.get(to);
      announce.textContent = p ? `${p.name}, ${p.level}. Escape goes back out.` : 'Every premise.';
    }
  }
}

export function leavePremise() {
  const { ix, own } = tree();
  const at = premiseScope();
  if (!at) return false;
  openPremise(leaveTo(ix, own, at) || '', { exact: true });
  return true;
}

function writeHash(id) {
  const next = hashWithPremise(location.hash, id || null);
  const url = `${location.pathname}${location.search}${next ? `#${next}` : ''}`;
  try { history.replaceState(history.state, '', url); } catch {   }
}


let openRegion = () => {};
let regionOpen = () => '';
export function useRegions(doors) {
  openRegion = doors.open;
  regionOpen = doors.current;
}

function planAbove(id) {
  const { ix } = tree();
  for (const pid of lineage(ix, id).reverse()) {
    const region = premisePlan(pid);
    if (region) return { region, owner: pid };
  }
  return null;
}

let following = false;
function followPlan(id) {
  const want = planAbove(id);
  const open = regionOpen();
  const go = (region) => {
    following = true;
    Promise.resolve(openRegion(region)).finally(() => { following = false; paint(); });
  };
  if (want) { if (open !== want.region) go(want.region); return; }
  if (open && premiseOfPlan(tree().ix, open)) go(null);
}

export function planFor(regionId, pins) {
  const { ix, where } = tree();
  const owner = ix.size ? premiseOfPlan(ix, regionId) : '';
  if (!owner) return null;
  return planSpots(ix, where, A.DATA?.nodes, owner, pins, (n) => Boolean(n._realOff ?? n.off_map));
}

export function regionChanged(entered, left) {
  const { ix, own } = tree();
  if (!ix.size) return;
  const at = premiseScope();
  if (entered) {
    const owner = premiseOfPlan(ix, entered);
    if (owner && !under(ix, at, owner)) setScopeQuietly(owner);
    else paint();
    return;
  }
  if (following) { paint(); return; }
  const owner = premiseOfPlan(ix, left);
  if (owner && at && under(ix, at, owner)) {
    const to = leaveTo(ix, own, owner) || '';
    setScopeQuietly(to);
    if (to && planAbove(to)) setTimeout(() => { if (premiseScope() === to && !regionOpen()) followPlan(to); }, 700);
  } else paint();
}

function setScopeQuietly(id) {
  scope = id;
  try { if (id) localStorage.setItem(SCOPE_KEY, id); else localStorage.removeItem(SCOPE_KEY); } catch {   }
  writeHash(id);
  paint();
  dispatchEvent(new CustomEvent('atlas:premise', { detail: { id } }));
}

export function premiseBoxes(regionId) {
  const { ix } = tree();
  const owner = ix.size && regionId ? premiseOfPlan(ix, regionId) : '';
  if (!owner) return [];
  return boxesOn(ix, owner).map(({ p, box, auto }) => {
    const el = document.createElement('div');
    el.className = `rg-frame pm-box${auto ? ' pm-box-auto' : ''}`;
    el.dataset.premise = p.id;
    el.style.left = box.x + '%';
    el.style.top = box.y + '%';
    el.style.width = box.w + '%';
    el.style.height = box.h + '%';
    el.innerHTML = `<button class="rg-tab" type="button" aria-label="Open ${esc(p.name || p.id)}">` +
      `<span class="rg-name">${esc(p.name || p.id)}</span></button>`;
    el.querySelector('.rg-tab').addEventListener('click', (e) => { e.stopPropagation(); openPremise(p.id); });
    return el;
  });
}

export function paintPremiseBoxes(container) {
  const { ix, where } = tree();
  if (!ix.size || !container) return;
  const RANK = ['down', 'degraded', 'maintenance', 'healthy'];
  for (const el of container.querySelectorAll('.pm-box')) {
    const id = el.dataset.premise;
    const states = (A.DATA?.nodes || []).filter((n) => n && under(ix, where.get(n.id), id)).map((n) => stateOf(n.id));
    const worst = RANK.find((st) => states.includes(st));
    if (worst) el.dataset.state = worst; else delete el.dataset.state;
    el.classList.toggle('pm-box-here', id === premiseScope());
  }
}


const LEVEL_WORD = { site: 'Site', building: 'Building', floor: 'Floor', room: 'Room', desk: 'Desk' };

function treeRows(ix) {
  const out = [];
  const walk = (list, depth) => {
    for (const p of list) {
      if (p.level === 'desk' || depth > 8) continue;
      out.push({ p, depth });
      walk(ix.children.get(p.id) || [], depth + 1);
    }
  };
  walk(ix.tops, 0);
  return out;
}

function paintBar() {
  if (!bar) return;
  const { ix, own } = tree();
  const on = Boolean(ix.size) && A.VIEW === 'map' && !A.PHONE;
  bar.hidden = !on;
  if (!on) return;
  const at = premiseScope();
  const trail = at ? crumbs(ix, own, at) : [];
  const crumbHtml = trail.map((c, i) => {
    const last = i === trail.length - 1;
    const skipped = c.skipped.length
      ? ` title="${esc(`Opened through ${c.skipped.map((s) => s.name).join(', ')}`)}"` : '';
    return '<span class="rl-sep" aria-hidden="true">›</span>' + (last
      ? `<span class="rl-crumb rl-here" aria-current="location"${skipped}>${esc(crumbLabel(c))}</span>`
      : `<button type="button" class="rl-crumb" data-premise="${esc(c.id)}"${skipped}>${esc(crumbLabel(c))}</button>`);
  }).join('');
  const rows = treeRows(ix).map(({ p, depth }) =>
    `<button type="button" role="menuitem" class="pm-row" data-premise="${esc(p.id)}" style="--pm-depth:${depth}"` +
    `${p.id === at ? ' aria-current="true"' : ''}><span class="pm-name">${esc(p.name || p.id)}</span>` +
    `<span class="pm-level">${esc(LEVEL_WORD[p.level] || p.level || '')}</span></button>`).join('');
  bar.innerHTML =
    `<button type="button" class="rl-crumb pm-open" aria-haspopup="menu" aria-expanded="${menuOpen}" ` +
    `aria-controls="premise-menu">Premises ▾</button>${crumbHtml}` +
    (at ? '<button type="button" class="rl-crumb pm-out" data-out title="Back out (Esc)" aria-label="Back out">✕</button>' : '') +
    `<div class="pm-menu" id="premise-menu" role="menu"${menuOpen ? '' : ' hidden'}>` +
    `<button type="button" role="menuitem" class="pm-row" data-premise=""${at ? '' : ' aria-current="true"'}>` +
    '<span class="pm-name">Every premise</span></button>' + rows + '</div>';
}

bar?.addEventListener('click', (e) => {
  if (e.target.closest('.pm-open')) {
    menuOpen = !menuOpen;
    paintBar();
    if (menuOpen) bar.querySelector('.pm-menu [aria-current="true"], .pm-menu .pm-row')?.focus();
    return;
  }
  if (e.target.closest('[data-out]')) { leavePremise(); return; }
  const row = e.target.closest('[data-premise]');
  if (!row) return;
  openPremise(row.dataset.premise, { exact: row.classList.contains('rl-crumb') });
});
bar?.addEventListener('keydown', (e) => {
  if (!menuOpen) return;
  const items = [...bar.querySelectorAll('.pm-menu .pm-row')];
  const i = items.indexOf(document.activeElement);
  if (e.key === 'ArrowDown') { e.preventDefault(); items[Math.min(items.length - 1, i + 1)]?.focus(); }
  else if (e.key === 'ArrowUp') { e.preventDefault(); items[Math.max(0, i - 1)]?.focus(); }
  else if (e.key === 'Escape') { e.stopPropagation(); menuOpen = false; paintBar(); bar.querySelector('.pm-open')?.focus(); }
});
addEventListener('pointerdown', (e) => {
  if (menuOpen && bar && !bar.contains(e.target)) { menuOpen = false; paintBar(); }
});


const DOT = { down: 'h-down', degraded: 'h-degraded', healthy: 'h-up', maintenance: 'h-maint' };

export function premisePlan(id) {
  const p = tree().ix.byId.get(id);
  const region = p && typeof p.region === 'string' ? p.region : '';
  return region && (A.DATA?.regions || []).some((r) => r && r.id === region) ? region : '';
}

function paintSheet() {
  if (!sheet) return;
  const at = premiseScope();
  const plan = at ? planAbove(at) : null;
  const on = Boolean(at) && A.VIEW === 'map' && !(plan && regionOpen() === plan.region);
  sheet.hidden = !on;
  document.body.classList.toggle('premise-sheet-open', on);
  if (!on) return;
  const { ix, where } = tree();
  const p = ix.byId.get(at);
  const { kids, here } = schematic(ix, where, A.DATA?.nodes, at, stateOf);
  const tiles = kids.map((k) => {
    const dot = k.worst ? `<span class="svc-health ${DOT[k.worst]}" aria-hidden="true"></span>` : '';
    const trouble = k.trouble ? ` · ${k.trouble} in trouble` : '';
    return `<button type="button" class="pm-tile" data-premise="${esc(k.id)}">` +
      `<span class="pm-tile-level">${esc(LEVEL_WORD[k.level] || k.level)}${k.kind ? ` · ${esc(k.kind)}` : ''}</span>` +
      `<span class="pm-tile-name">${dot}${esc(k.name)}</span>` +
      `<span class="pm-tile-n">${k.count} ${k.count === 1 ? 'place' : 'places'}${esc(trouble)}</span></button>`;
  }).join('');
  const places = here.map((n) => {
    const st = stateOf(n.id);
    const dot = st && DOT[st] ? `<span class="svc-health ${DOT[st]}" aria-hidden="true"></span>` : '<span class="pm-dot-none" aria-hidden="true"></span>';
    return `<li><button type="button" class="pm-place" data-node="${esc(n.id)}">${dot}` +
      `<span class="pm-place-name">${esc(n.name || n.id)}</span>` +
      `<span class="pm-place-what">${esc(n.device || n.role || '')}</span></button></li>`;
  }).join('');
  const levelAt = LEVELS.indexOf(p.level);
  sheet.innerHTML =
    `<header class="pm-head"><span class="pm-head-level">${esc(LEVEL_WORD[p.level] || p.level)}${p.kind ? ` · ${esc(p.kind)}` : ''}</span>` +
    `<h2 class="pm-head-name">${esc(p.name || p.id)}</h2>` +
    (p.address ? `<p class="pm-head-note">${esc(p.address)}</p>` : '') +
    (canAdminWrite() && A.editorReady?.() ? planDoor() : '') + '</header>' +
    (kids.length ? `<div class="pm-tiles">${tiles}</div>` : '') +
    (here.length ? `<h3 class="pm-sub">${levelAt >= 2 ? 'Standing here' : 'Standing here, in no room'}</h3><ul class="pm-places">${places}</ul>` : '') +
    (!kids.length && !here.length ? '<p class="pm-empty">Nothing stands here yet.</p>' : '');
}

let planImages = null;
function planDoor() {
  if (!planImages) {
    return '<div class="pm-plan"><button type="button" class="dsk-btn dsk-btn-sm" data-plan="ask">Give it a plan…</button></div>';
  }
  if (!planImages.length) return '<div class="pm-plan"><span class="pm-head-note">Upload a picture first (MAP EDITOR › Every record › Map art).</span></div>';
  return '<div class="pm-plan"><select class="dsk-input" id="pm-plan-pick" aria-label="The picture">' +
    planImages.map((n) => `<option value="${esc(n)}">${esc(n)}</option>`).join('') + '</select>' +
    '<button type="button" class="dsk-btn dsk-btn-sm dsk-btn-go" data-plan="save">Make it the plan</button>' +
    '<button type="button" class="dsk-btn dsk-btn-sm" data-plan="cancel">Cancel</button></div>';
}
async function planPress(what) {
  if (what === 'cancel') { planImages = null; paintSheet(); return; }
  const { Editor } = await import('./editor/index.js');
  if (what === 'ask') {
    try { planImages = ((await Editor.mapArt()).images || []).map((i) => i?.name).filter(Boolean); } catch { planImages = []; }
    paintSheet();
    return;
  }
  const at = premiseScope();
  const p = tree().ix.byId.get(at);
  const map = $('pm-plan-pick')?.value;
  if (!p || !map) return;
  await Editor.load();
  const taken = new Set((Editor.data?.regions || []).map((r) => r?.id));
  let id = `${at}-plan`;
  for (let n = 2; taken.has(id); n++) id = `${at}-plan-${n}`;
  try {
    await Editor.apply([
      { op: 'insert', section: 'regions', body: { id, name: p.name || at, map, standalone: true, auto: false,
        x: 0, y: 0, w: 100, h: 100 } },
      { op: 'upsert', section: 'premises', id: at, body: { region: id } },
    ], `a plan for ${p.name || at}`);
    planImages = null;
    A.showToast?.(`${p.name || at} has a plan.`);
    followPlan(at);
  } catch (err) {
    A.showToast?.(`Not saved: ${err.message || err}`);
  }
}

sheet?.addEventListener('click', (e) => {
  const plan = e.target.closest('[data-plan]');
  if (plan) { planPress(plan.dataset.plan); return; }
  const tile = e.target.closest('.pm-tile');
  if (tile) { openPremise(tile.dataset.premise); return; }
  const place = e.target.closest('.pm-place');
  if (!place) return;
  const n = (A.DATA?.nodes || []).find((x) => x && x.id === place.dataset.node);
  if (n) A.openCard?.(n);
});

function paint() {
  const open = regionOpen();
  document.body.classList.toggle('premise-plan-open', Boolean(open && tree().ix.size && premiseOfPlan(tree().ix, open)));
  paintBar();
  paintSheet();
}


addEventListener('atlas:data', () => {
  paint();
  const at = premiseScope();
  if (at && !document.body.classList.contains('pre')) followPlan(at);
});
addEventListener('atlas:view', () => { menuOpen = false; paint(); });
setInterval(() => { if (sheet && !sheet.hidden && !document.hidden) paintSheet(); }, 15000);
addEventListener('hashchange', () => {
  const asked = premiseFromHash(location.hash);
  if (asked !== null && asked !== premiseScope()) openPremise(asked);
});
addEventListener('keydown', (e) => {
  if (e.key !== 'Escape' || !premiseScope() || A.VIEW !== 'map') return;
  if (e.target.closest?.('input, textarea, select, [contenteditable="true"], .pm-menu')) return;
  if (A.sceneOpen || A.cardOpen?.() || A.glassOpen?.()) return;
  if (document.querySelector('#map-drawer.open, #index-drawer.open, #palette.open')) return;
  if (A.inRegion?.()) {
    const { ix } = tree();
    const owner = premiseOfPlan(ix, regionOpen());
    const at = premiseScope();
    if (!owner || at === owner || !under(ix, at, owner)) return;
    e.preventDefault();
    e.stopImmediatePropagation();
  }
  leavePremise();
}, true);

function first() {
  const asked = premiseFromHash(location.hash);
  if (asked) scope = asked;
  if (A.DATA) {
    writeHash(premiseScope());
    paint();
    if (premiseScope()) dispatchEvent(new CustomEvent('atlas:premise', { detail: { id: premiseScope() } }));
  }
  const lifted = () => {
    if (document.body.classList.contains('pre')) { setTimeout(lifted, 250); return; }
    if (premiseScope()) followPlan(premiseScope());
  };
  lifted();
}
addEventListener('atlas:data', function once() { removeEventListener('atlas:data', once); first(); });
