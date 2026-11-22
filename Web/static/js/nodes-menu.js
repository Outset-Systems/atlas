
import { A, esc, WRITE_HEADERS, readJSON } from './config.js';
import * as R from './roster-model.js';
import * as M from './menu-model.js';
import * as AM from './alerts-model.js';
import * as AlertStore from './alert-store.js';
import Editor from './editor/store.js';
import { mayLocate, setLocation } from './location-set.js';
import { t } from './nodes-text.js';
import { S, el, phone, mayWrite, menuOn } from './nodes-state.js';
import { mayAlert, pressBell, stateOf, watcherWords } from './nodes-cells.js';
import { showRow, openCard } from './nodes-table.js';
import { drawRail, startRename, armRemove } from './nodes-rail.js';
import {
  repairs, rowOf, ensureRepairs, unmanagedVia, openScope, openCheck, setMode, setUnmanaged, collectionLabel,
  collectionUnmanaged,
} from './nodes-forms.js';
import { serviceOf, linkOf, holding, setServiceUnmanaged, serviceWatcherWords } from './nodes-services.js';


const CHECK_KEEP = 20000;
const ASKED_FOR = 15000;
const checkReads = new Map();
const checkInflight = new Map();

const checkPath = (key) => `api/v2/checks/${String(key).split('/').map(encodeURIComponent).join('/')}`;

const freshRead = (key) => {
  const had = checkReads.get(key);
  return had && Date.now() - had.at < CHECK_KEEP ? had : null;
};

function readCheck(key) {
  const had = freshRead(key);
  if (had) return Promise.resolve(had);
  if (checkInflight.has(key)) return checkInflight.get(key);
  const p = (async () => {
    let entry;
    try {
      const res = await fetch(checkPath(key), { cache: 'no-store' });
      const body = await readJSON(res);
      entry = { at: Date.now(), ok: res.ok, status: res.status, body: res.ok ? body : null };
    } catch {
      entry = { at: Date.now(), ok: false, status: 0, body: null };
    }
    checkReads.set(key, entry);
    checkInflight.delete(key);
    return entry;
  })();
  checkInflight.set(key, p);
  return p;
}

function hasCheck(kind, id) {
  let unmanaged = false;
  if (kind === 'place') {
    const row = rowOf(id);
    if (!row) return false;
    const own = (Editor.data?.nodes || []).find((x) => x.id === row.id)?.unmanaged === true;
    unmanaged = own || Boolean(row.unmanaged) || unmanagedVia(row).length > 0;
  } else if (kind === 'service') {
    const svc = serviceOf(id);
    if (!svc) return false;
    unmanaged = linkOf(svc)?.unmanaged === true || holding(svc.id).some((c) => c.unmanaged === true)
      || Boolean(rowOf(svc.place)?.unmanaged);
  } else {
    return false;
  }
  return M.checkAsk(kind, A.DATA, id, { unmanaged }) === true;
}

export function forgetCheck(key) { checkReads.delete(key); }

function checkFacts(key) {
  const read = checkReads.get(key);
  const body = read?.ok && read.body && typeof read.body === 'object' ? read.body : null;
  const heard = body ? Date.parse(body.heard_at) : NaN;
  const last = body && body.said && !Number.isNaN(heard) ? { state: body.said, secs: Math.max(0, (Date.now() - heard) / 1000) } : null;
  const on = typeof body?.on === 'boolean' ? body.on : typeof S.shadow?.asking === 'boolean' ? S.shadow.asking : undefined;
  return { last, on };
}

function silentWhy() {
  const b = AlertStore.ALERTS.body;
  if (!b) return '';
  if (AM.onOff(b.status).off) return 'off';
  return b.doc.destinations.length ? '' : 'nowhere';
}

const READS = new Set(['open', 'topology']);

const HOOK = { place: 'data-rowmenu', service: 'data-svcmenu', collection: 'data-menu' };
const TARGET = { place: 'nodes', service: 'services', collection: 'collections' };

function subject({ kind, id }) {
  const readonly = phone();
  if (kind === 'place') {
    const row = rowOf(id);
    if (!row) return null;
    const uvia = unmanagedVia(row);
    const { last, on } = checkFacts(row.id);
    const topology = typeof A.openTopology === 'function';
    if (readonly) {
      return {
        name: row.name || row.id,
        facts: {
          readonly,
          state: stateOf(row),
          watched: watcherWords(row.confirmed_by),
          last,
          mode: { via: R.modeVia(repairs(), row.collections).map(collectionLabel) },
          unmanaged: { via: uvia.map(collectionLabel) },
          topology,
        },
      };
    }
    const unmanaged = {
      own: (Editor.data?.nodes || []).find((x) => x.id === row.id)?.unmanaged === true || Boolean(row.unmanaged && !uvia.length),
      via: uvia.map(collectionLabel),
    };
    return {
      name: row.name || row.id,
      facts: {
        watched: watcherWords(row.confirmed_by),
        last,
        mode: { own: R.inMode(repairs(), 'place', row.id), via: R.modeVia(repairs(), row.collections).map(collectionLabel) },
        unmanaged,
        check: true,
        ask: M.checkAsk('place', A.DATA, row.id, {
          unmanaged: Boolean(unmanaged.own || unmanaged.via.length || row.unmanaged), on,
        }),
        diagnose: M.diagnoseAsk(A.DATA, row.id, {
          unmanaged: Boolean(unmanaged.own || unmanaged.via.length || row.unmanaged), on,
        }),
        topology,
        alerts: mayAlert(),
        silent: silentWhy(),
        locate: mayLocate(),
        edit: typeof A.editPlace === 'function',
        remove: typeof A.removePlace === 'function',
      },
    };
  }
  if (kind === 'service') {
    const svc = serviceOf(id);
    if (!svc) return null;
    const row = rowOf(svc.place);
    const held = holding(svc.id);
    const label = (c) => c.name || c.id;
    const unmanaged = {
      own: linkOf(svc)?.unmanaged === true,
      via: held.filter((c) => c.unmanaged === true).map(label),
      place: Boolean(row?.unmanaged),
    };
    const { last, on } = checkFacts(svc.id);
    return {
      name: svc.name,
      svc,
      facts: {
        readonly,
        watched: serviceWatcherWords(svc),
        last,
        mode: {
          own: R.inMode(repairs(), 'service', svc.id),
          via: held.filter((c) => R.inMode(repairs(), 'collection', c.id)).map(label),
          place: Boolean(row?.maintenance?.now),
        },
        unmanaged,
        check: true,
        ask: M.checkAsk('service', A.DATA, svc.id, {
          unmanaged: Boolean(unmanaged.own || unmanaged.via.length || unmanaged.place), on,
        }),
        topology: typeof A.openTopology === 'function' && Boolean(svc.place),
        alerts: mayAlert(),
        silent: silentWhy(),
      },
    };
  }
  if (kind === 'collection') {
    if (!(S.roster?.collections || []).some((c) => c.id === id)) return null;
    return {
      name: collectionLabel(id),
      facts: {
        readonly,
        mode: { own: R.inMode(repairs(), 'collection', id) },
        unmanaged: { own: collectionUnmanaged(id) },
        edit: true,
        remove: true,
      },
    };
  }
  return null;
}

function anchorOf(menu) {
  if (!menu) return null;
  const within = menu.kind === 'collection' ? el.rail : el.results;
  return within?.querySelector(`[${HOOK[menu.kind]}="${CSS.escape(menu.id)}"]`) || null;
}

const itemWords = (item) => M.wordsOf(item, t);

function drawMenu() {
  const what = S.menu && subject(S.menu);
  const items = what ? M.menuItems(S.menu.kind, what.facts) : [];
  if (!items.length) { closeMenu(false); return; }
  el.menu.innerHTML = items.map((item) => (item.act
    ? `<button type="button" role="menuitem" class="nv-menu-item${item.held ? ' nv-menu-held' : ''}" data-mact="${item.act}"` +
      `${item.held ? ' aria-disabled="true"' : ''}>${esc(itemWords(item))}</button>`
    : `<p class="nv-menu-note">${esc(itemWords(item))}</p>`)).join('');
  for (const b of el.menu.querySelectorAll('button')) b.disabled = S.busy && !READS.has(b.dataset.mact);
  el.menu.setAttribute('aria-label', t(S.menu.kind === 'collection' ? 'nodes_rail_menu' : 'nodes_menu', { name: what.name }));
  const sheet = phone();
  el.menu.classList.toggle('nv-menu-sheet', sheet);
  if (el.menuDim) el.menuDim.hidden = !sheet;
  el.menu.hidden = false;
  placeMenu();
}

export function placeMenu() {
  paintAsked();
  paintDiagnose();
  payOwed();
  if (!S.menu || !el.menu) return;
  const more = anchorOf(S.menu);
  const sheet = el.menu.classList.contains('nv-menu-sheet');
  if (!more || sheet !== phone()) { closeMenu(false); return; }
  more.setAttribute('aria-expanded', 'true');
  if (sheet) { el.menu.style.left = ''; el.menu.style.top = ''; return; }
  const at = more.getBoundingClientRect();
  const box = el.menu.getBoundingClientRect();
  el.menu.style.left = `${Math.max(8, Math.min(at.left, innerWidth - box.width - 8))}px`;
  el.menu.style.top = `${at.bottom + 4 + box.height > innerHeight ? Math.max(8, at.top - box.height - 4) : at.bottom + 4}px`;
}

export async function toggleMenu(kind, id) {
  if (menuOn(kind, id)) { closeMenu(true); return; }
  await openMenu(kind, id);
}

export async function openMenu(kind, id, back = null) {
  if (menuOn(kind, id)) { refocusMenu(''); return; }
  closeMenu(false);
  if (phone() && A.cardPlace?.()) A.closeCard?.();
  S.menu = { kind, id, back };
  drawMenu();
  if (!menuOn(kind, id)) return;
  el.menu.querySelector(PRESSABLE)?.focus({ preventScroll: true });
  const reads = [];
  if (!Editor.repairs && mayWrite()) reads.push(ensureRepairs());
  if (hasCheck(kind, id) && !freshRead(id)) reads.push(readCheck(id));
  if (reads.length) {
    await Promise.all(reads);
    if (menuOn(kind, id)) { const at = focusKeyOfMenu(); drawMenu(); refocusMenu(at); }
  }
}

const PRESSABLE = 'button:not(:disabled):not([aria-disabled="true"])';

const focusKeyOfMenu = () => (el.menu.contains(document.activeElement) ? document.activeElement.dataset?.mact || '' : '');
function refocusMenu(act) {
  const same = act ? el.menu.querySelector(`button[data-mact="${CSS.escape(act)}"]`) : null;
  (same || el.menu.querySelector(PRESSABLE) || el.menu.querySelector('button'))?.focus();
}

export function closeMenu(focusBack = true) {
  const had = S.menu;
  const more = anchorOf(had);
  S.menu = null;
  if (el.menu) { el.menu.hidden = true; el.menu.innerHTML = ''; el.menu.classList.remove('nv-menu-sheet'); }
  if (el.menuDim) el.menuDim.hidden = true;
  if (!had) return;
  more?.setAttribute('aria-expanded', 'false');
  if (focusBack) (had.back?.isConnected ? had.back : more)?.focus();
}

export function focusMore(kind, id) {
  if (kind === 'collection') {
    S.railFocus = `[${HOOK.collection}="${CSS.escape(id)}"]`;
    drawRail();
    return;
  }
  showRow(kind === 'service' ? serviceOf(id)?.place : id);
  owed = { kind, id, until: Date.now() + OWED_FOR };
  el.results.querySelector(`[${HOOK[kind]}="${CSS.escape(id)}"]`)?.focus();
}

const OWED_FOR = 6000;
let owed = null;

function payOwed() {
  if (!owed) return;
  if (Date.now() > owed.until || !el.results) { owed = null; return; }
  const want = el.results.querySelector(`[${HOOK[owed.kind]}="${CSS.escape(owed.id)}"]`);
  const now = document.activeElement;
  if (want && now === want) return;
  if (now && now !== document.body) { owed = null; return; }
  want?.focus({ preventScroll: true });
}

export function onMenuClick(e) {
  const b = e.target.closest('[data-mact]');
  if (!b || b.disabled || b.getAttribute('aria-disabled') === 'true' || (S.busy && !READS.has(b.dataset.mact)) || !S.menu) return;
  const { kind, id } = S.menu;
  const what = subject(S.menu);
  if (!what) { closeMenu(false); return; }
  const { name } = what;
  const act = b.dataset.mact;
  const on = act.endsWith('-on');
  switch (act) {
    case 'schedule': openScope({ kind, id, name }); break;
    case 'collections': openScope({ kind, id, name, form: 'svc-col' }); break;
    case 'mode-on': case 'mode-off':
      closeMenu(true);
      setMode({ [TARGET[kind]]: [id] }, on, name).then(() => focusMore(kind, id));
      break;
    case 'unmanaged-on': case 'unmanaged-off':
      closeMenu(true);
      (kind === 'service' ? setServiceUnmanaged(what.svc, on) : setUnmanaged(TARGET[kind], [id], on, name))
        .then(() => focusMore(kind, id));
      break;
    case 'check':
      closeMenu(false);
      openCheck({ kind, id, name, ...(kind === 'service' ? { place: what.svc.place } : {}) });
      break;
    case 'check-now': closeMenu(false); focusMore(kind, id); askNow(kind, id); break;
    case 'diagnose': closeMenu(false); focusMore(kind, id); diagnose(id, name); break;
    case 'topology': closeMenu(false); A.openTopology?.(kind === 'service' ? what.svc.place : id); break;
    case 'alerts': closeMenu(false); pressBell(kind, id); break;
    case 'location': closeMenu(false); focusMore(kind, id); setLocation({ node: id }); break;
    case 'edit': closeMenu(false); A.editPlace?.(id); break;
    case 'rename': closeMenu(false); startRename(id); break;
    case 'remove':
      closeMenu(false);
      if (kind === 'collection') armRemove(id); else A.removePlace?.(id);
      break;
    case 'open': closeMenu(true); openCard(id); break;
    default: break;
  }
}


let askedTimer = 0;

function askedHost(kind, id) {
  if (!el.results) return null;
  if (kind === 'place') return el.results.querySelector(`tr[data-id="${CSS.escape(id)}"] .nv-name-cell`)?.parentElement || null;
  return el.results.querySelector(`[data-svcmenu="${CSS.escape(id)}"]`)?.closest('.nv-svc') || null;
}

function paintAsked() {
  const a = S.asked;
  if (a && !a.pending && (Date.now() > a.until || A.signalsFeed !== a.feed)) S.asked = null;
  const mark = S.asked ? `${S.asked.kind}:${S.asked.id}` : '';
  for (const old of el.results?.querySelectorAll('.nv-asked') || []) if (old.dataset.for !== mark) old.remove();
  if (!S.asked) return;
  const host = askedHost(S.asked.kind, S.asked.id);
  if (!host) return;
  let line = host.querySelector(':scope > .nv-asked');
  if (!line) {
    line = document.createElement('span');
    line.setAttribute('role', 'status');
    line.dataset.for = mark;
    host.append(line);
  }
  line.className = `nv-asked${S.asked.pending ? ' nv-asking' : ''}${S.asked.tone ? ` nv-asked-${S.asked.tone}` : ''}`;
  if (line.textContent !== S.asked.text) line.textContent = S.asked.text;
}

async function askNow(kind, id) {
  if (S.asked?.pending && S.asked.kind === kind && S.asked.id === id) return;
  clearTimeout(askedTimer);
  S.asked = { kind, id, text: t('nodes_asking'), tone: '', pending: true };
  paintAsked();
  let res = null;
  let body = null;
  try {
    res = await fetch('api/v2/admin/checks/run', { method: 'POST', headers: WRITE_HEADERS, body: JSON.stringify({ key: id }) });
    body = await readJSON(res);
  } catch {   }
  let text;
  let tone;
  if (res?.ok && body && typeof body === 'object') {
    checkReads.set(id, { at: Date.now(), ok: true, status: res.status, body });
    const line = M.answerLine(body);
    text = line.parts.map(itemWords).join(' · ');
    tone = line.tone;
  } else {
    text = itemWords(M.refusalLine(res ? res.status : 0, body));
    tone = 'warn';
  }
  if (S.asked?.kind !== kind || S.asked.id !== id) return;
  sayAsked(kind, id, text, tone);
}

function sayAsked(kind, id, text, tone, extra = {}) {
  S.asked = { kind, id, text, tone, pending: false, feed: A.signalsFeed, until: Date.now() + ASKED_FOR, ...extra };
  paintAsked();
  clearTimeout(askedTimer);
  askedTimer = setTimeout(() => {
    if (S.asked && !S.asked.pending && S.asked.kind === kind && S.asked.id === id) { S.asked = null; paintAsked(); }
  }, ASKED_FOR + 50);
}


let dxSeq = 0;

async function askDiagnose(id) {
  try {
    const res = await fetch('api/v2/admin/diagnose', { method: 'POST', headers: WRITE_HEADERS, body: JSON.stringify({ id }) });
    const body = await readJSON(res);
    return { status: res.status, ok: res.ok, body };
  } catch {
    return { status: 0, ok: false, body: null };
  }
}
A.askDiagnose = askDiagnose;

async function diagnose(id, name) {
  if (S.asked?.pending && S.asked.kind === 'place' && S.asked.id === id) return;
  const seq = ++dxSeq;
  if (S.dx) { S.dx = null; paintDiagnose(); }
  clearTimeout(askedTimer);
  S.asked = { kind: 'place', id, text: t('nodes_asking'), tone: '', pending: true, dx: true };
  paintAsked();
  const { status, ok, body } = await askDiagnose(id);
  if (seq !== dxSeq) return;
  const ours = S.asked?.dx === true && S.asked.id === id;
  if (ok && body && typeof body === 'object' && Array.isArray(body.steps)) {
    if (ours) { S.asked = null; paintAsked(); }
    S.dx = { id, name: typeof body.name === 'string' && body.name ? body.name : name, answer: body, focus: 'summary', land: true };
    paintDiagnose();
    payOwed();
    return;
  }
  if (ours) sayAsked('place', id, itemWords(M.diagnoseRefusal(status, body)), 'warn', { dx: true });
}

function closeDiagnose(focusBack) {
  const was = S.dx;
  S.dx = null;
  paintDiagnose();
  if (was && focusBack) focusMore('place', was.id);
}

function diagnoseBox(d) {
  const sum = M.diagnoseSummary(d.answer);
  const lines = M.diagnoseLines(d.answer);
  const box = document.createElement('div');
  box.className = 'nv-dx';
  box.dataset.for = d.id;
  box.setAttribute('role', 'group');
  box.setAttribute('aria-label', t('nodes_dx_label', { name: d.name }));
  const canvas = typeof A.showDiagnosis === 'function';
  box.innerHTML =
    `<p class="nv-dx-sum${sum.tone ? ` nv-dx-${sum.tone}` : ''}" tabindex="-1" data-dx="summary">${esc(itemWords(sum))}</p>` +
    `<ol class="nv-dx-steps">${lines.map((l) => `<li class="nv-dx-step${l.tone ? ` nv-dx-${l.tone}` : ' nv-dx-quiet'}` +
      `${l.broke ? ' nv-dx-broke' : ''}">${esc(l.parts.map(itemWords).join(' · '))}</li>`).join('')}</ol>` +
    '<div class="nv-dx-bar">' +
    (canvas ? `<button type="button" class="dsk-btn dsk-btn-sm" data-dx="show">${esc(t('nodes_dx_show'))}</button>` : '') +
    `<button type="button" class="dsk-btn dsk-btn-sm" data-dx="close">${esc(t('nodes_dx_close'))}</button></div>`;
  box.addEventListener('click', (e) => {
    e.stopPropagation();
    const b = e.target.closest('button[data-dx]');
    if (!b || !S.dx) return;
    if (b.dataset.dx === 'close') closeDiagnose(true);
    else if (b.dataset.dx === 'show') A.showDiagnosis?.(S.dx.answer);
  });
  box.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    e.preventDefault();
    e.stopPropagation();
    closeDiagnose(true);
  });
  box.addEventListener('focusin', (e) => { if (S.dx) S.dx.focus = e.target.closest('[data-dx]')?.dataset.dx || 'summary'; });
  box.addEventListener('focusout', (e) => {
    if (S.dx && e.relatedTarget && !box.contains(e.relatedTarget)) S.dx.focus = '';
  });
  return box;
}

function paintDiagnose() {
  const d = S.dx;
  for (const old of el.results?.querySelectorAll('.nv-dx') || []) if (!d || old.dataset.for !== d.id) old.remove();
  if (!d) return;
  const host = askedHost('place', d.id);
  if (!host || host.querySelector(':scope > .nv-dx')) return;
  const box = diagnoseBox(d);
  host.append(box);
  const now = document.activeElement;
  const free = !now || now === document.body;
  if (d.land) {
    d.land = false;
    if (free || el.results.contains(now)) { box.querySelector('[data-dx="summary"]').focus({ preventScroll: true }); owed = null; }
    else d.focus = '';
  } else if (d.focus && free) {
    box.querySelector(`[data-dx="${CSS.escape(d.focus)}"]`)?.focus({ preventScroll: true });
    owed = null;
  }
}


const MORE = '[data-rowmenu], [data-svcmenu], [data-menu]';

function thingAt(target) {
  const line = target?.closest?.('.nv-svc, tr[data-id], .nv-rail-li');
  const more = line?.querySelector(MORE);
  if (!more) return null;
  if (more.hasAttribute('data-svcmenu')) return { line, kind: 'service', id: more.dataset.svcmenu };
  if (more.hasAttribute('data-rowmenu')) return { line, kind: 'place', id: more.dataset.rowmenu };
  return { line, kind: 'collection', id: more.dataset.menu };
}

const backIn = (line) => (line.contains(document.activeElement) ? document.activeElement : null);

let keyedAt = 0;

export function onThingKey(e) {
  const shiftF10 = e.key === 'F10' && e.shiftKey && !e.ctrlKey && !e.altKey && !e.metaKey;
  if (!shiftF10 && e.key !== 'ContextMenu') return;
  if (e.target.closest?.('textarea, select, input:not([type="checkbox"])')) return;
  const at = thingAt(e.target);
  if (!at) return;
  e.preventDefault();
  keyedAt = Date.now();
  openMenu(at.kind, at.id, backIn(at.line));
}

export function onThingContext(e) {
  if (Date.now() - keyedAt < 1000) { e.preventDefault(); return; }
  if (e.target.closest?.('a, input, textarea, select, [contenteditable]')) return;
  const at = thingAt(e.target);
  if (!at) return;
  const sel = typeof getSelection === 'function' ? getSelection() : null;
  if (sel && !sel.isCollapsed && String(sel).trim() && sel.containsNode?.(at.line, true)) return;
  e.preventDefault();
  openMenu(at.kind, at.id, backIn(at.line));
}

export function onMenuContext(e) { e.preventDefault(); }

export function onMenuKey(e) {
  const items = [...el.menu.querySelectorAll('button:not(:disabled)')];
  const i = items.indexOf(document.activeElement);
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    e.preventDefault();
    const step = e.key === 'ArrowDown' ? 1 : -1;
    items[(i + step + items.length) % items.length]?.focus();
  } else if (e.key === 'Home' || e.key === 'End') {
    e.preventDefault();
    (e.key === 'Home' ? items[0] : items[items.length - 1])?.focus();
  } else if (e.key === 'Escape') {
    e.stopPropagation();
    closeMenu(true);
  } else if (e.key === 'Tab') {
    closeMenu(true);
  }
}
