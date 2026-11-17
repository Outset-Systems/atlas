/* NODES, the ⋯ menu (2026-11-14, its own file and one menu 2026-11-16): the
   one menu element the ⋯ of a place, of a service and of a collection all
   open. What it lists is menu-model.js (one table of actions, with no DOM);
   this file gathers the plain facts the model asks for, draws the lines,
   seats the menu under the ⋯ pressed, handles its keys, and sends a press
   on an item to what does it. There is one of each: one state (`S.menu`,
   the kind of thing and its id), one draw, one toggle, one click, one key
   handler, one lookup of the ⋯ it hangs from.

   A collection's ⋯ is in the rail. Its Rename and Remove are only started
   here: the name box and the armed Remove, with its notes and its second
   press, are the rail's own (nodes-rail.js).

   THREE MORE WAYS IN (2026-11-16). Shift+F10 or the menu key with the
   keyboard anywhere in a place's row, a service's line or a collection's
   row in the rail, and a right-click on one, open the menu its ⋯ opens,
   seated under that ⋯ (`onThingKey`, `onThingContext`; one rule finds the
   line and its ⋯, and where there is no ⋯ the browser keeps its own menu).
   Escape puts the keyboard back where it was when the menu came out, when
   that is still in the same line, else on the ⋯. On a phone a card's ⋯
   opens the same menu as a sheet along the screen's foot, over a dim
   (`.nv-menu-sheet`, `.nv-menu-dim`), and it lists only what changes
   nothing (menu-model's read-only way), for whoever is signed in.

   THE ENGINES (2026-11-17). A place's and a service's menu opens with who
   watches it and, read once from `GET api/v2/checks/<key>` (kept a few
   seconds), what its check last answered and how long ago. Check… opens
   the check's own fields in the scope bar (nodes-forms.js). Check now asks
   `POST api/v2/admin/checks/run` and says "Asking…", then the answer or
   why it was refused, in a line in the thing's row (`S.asked`), which goes
   on the first redraw after the next feed, or after a short while.

   WHERE DOES IT BREAK, AND THE CANVAS (2026-11-17). "Where does it
   break?" asks `POST api/v2/admin/diagnose` for a place and says
   "Asking…" as Check now does (a refusal is said the same way); the
   chain it answers is listed under the place's name (`S.dx`, `.nv-dx`),
   one line per step and a summary, until Close, Escape in it, or another
   place is asked; the keyboard goes to its summary as it lands and back
   to the row's ⋯ when it goes. Its "Show on the canvas" hands the answer
   to the TOPOLOGY view (`A.showDiagnosis`, topology-diagnose.js), which
   lights the chain as far as the step that failed. "Show in topology"
   opens the view on the place (`A.openTopology`; a service's: its place).
   After a write the keyboard goes back to the thing's ⋯ (`focusMore`),
   and is put back there on any redraw in the next few seconds that took
   it away (`payOwed`): the bells' redraw after a save drew the table
   again and left it on the page.

   Five of NODES' parts import each other in circles, which is safe because
   none of them calls another while it loads. */

import { A, esc, WRITE_HEADERS } from './config.js';
import * as R from './roster-model.js';
import * as M from './menu-model.js';
import * as AM from './alerts-model.js';
import * as AlertStore from './alert-store.js';
import Editor from './editor/store.js';
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

/* ── a check's last answer (2026-11-17) ──────────────────────────────────── */

/** How long a read answer is kept: a menu opened again soon reads no more. */
const CHECK_KEEP = 20000;
/** How long Check now's answer stays in its row, at most. */
const ASKED_FOR = 15000;
/** {key: {at, ok, status, body}}: the last read of each check, a 404 too. */
const checkReads = new Map();
const checkInflight = new Map();

/** The route for one key: a service key may hold a slash, a space or a `#`,
    so each part is encoded on its own. */
const checkPath = (key) => `api/v2/checks/${String(key).split('/').map(encodeURIComponent).join('/')}`;

const freshRead = (key) => {
  const had = checkReads.get(key);
  return had && Date.now() - had.at < CHECK_KEEP ? had : null;
};

/** Read one check's last answer (once, then kept briefly). Never throws: a
    read that fails is kept as one with no answer. */
function readCheck(key) {
  const had = freshRead(key);
  if (had) return Promise.resolve(had);
  if (checkInflight.has(key)) return checkInflight.get(key);
  const p = (async () => {
    let entry;
    try {
      const res = await fetch(checkPath(key), { cache: 'no-store' });
      let body = null;
      try { body = await res.json(); } catch { /* an empty or non-JSON answer */ }
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

/** A save changed a check's fields: its kept answer is read again next time. */
export function forgetCheck(key) { checkReads.delete(key); }

/** What a kept read says for the menu: its last answer ({state, secs}), and
    whether the checks source is on (the read's own word, else the shadow
    summary's, an admin's; unknown is not off). */
function checkFacts(key) {
  const read = checkReads.get(key);
  const body = read?.ok && read.body && typeof read.body === 'object' ? read.body : null;
  const heard = body ? Date.parse(body.heard_at) : NaN;
  const last = body && body.said && !Number.isNaN(heard) ? { state: body.said, secs: Math.max(0, (Date.now() - heard) / 1000) } : null;
  const on = typeof body?.on === 'boolean' ? body.on : typeof S.shadow?.asking === 'boolean' ? S.shadow.asking : undefined;
  return { last, on };
}

/** Why nothing can send, for the Alerts line: alerts off, or no
    destination yet; '' when they can, or when it is not known yet. */
function silentWhy() {
  const b = AlertStore.ALERTS.body;
  if (!b) return '';
  if (AM.onOff(b.status).off) return 'off';
  return b.doc.destinations.length ? '' : 'nowhere';
}

/** The presses that only read, which a write running does not hold back:
    opening a card, and the TOPOLOGY view (2026-11-17). */
const READS = new Set(['open', 'topology']);

/** The mark on each kind's ⋯, and where a write names the kind. */
const HOOK = { place: 'data-rowmenu', service: 'data-svcmenu', collection: 'data-menu' };
const TARGET = { place: 'nodes', service: 'services', collection: 'collections' };

/** The thing a menu is for: its name and the plain facts the model lists
    its items from; null when it is not there any more. On a phone, the
    read-only way's facts (2026-11-16): nothing there writes. */
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
        // 2026-11-17: the place's chain, held as the route would refuse it
        diagnose: M.diagnoseAsk(A.DATA, row.id, {
          unmanaged: Boolean(unmanaged.own || unmanaged.via.length || row.unmanaged), on,
        }),
        topology,
        alerts: mayAlert(),
        silent: silentWhy(),
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
      // its ⋯ is drawn only for an admin who may write: the name and the
      // collection itself are theirs to change
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

/** The ⋯ the menu is out for: in the rail for a collection, in the results
    for a place or a service. */
function anchorOf(menu) {
  if (!menu) return null;
  const within = menu.kind === 'collection' ? el.rail : el.results;
  return within?.querySelector(`[${HOOK[menu.kind]}="${CSS.escape(menu.id)}"]`) || null;
}

/** One line's words: its key filled in, and any `words` (vars that are
    theme keys) as words first, filled in with the same vars ("3 minutes
    ago", 2026-11-17). */
const itemWords = (item) => M.wordsOf(item, t);

function drawMenu() {
  const what = S.menu && subject(S.menu);
  const items = what ? M.menuItems(S.menu.kind, what.facts) : [];
  if (!items.length) { closeMenu(false); return; }
  // a held item (Check now where the server would refuse it) is in the
  // arrows' path, so its reason is read out, but a press does nothing
  el.menu.innerHTML = items.map((item) => (item.act
    ? `<button type="button" role="menuitem" class="nv-menu-item${item.held ? ' nv-menu-held' : ''}" data-mact="${item.act}"` +
      `${item.held ? ' aria-disabled="true"' : ''}>${esc(itemWords(item))}</button>`
    : `<p class="nv-menu-note">${esc(itemWords(item))}</p>`)).join('');
  // a write waits while another runs; opening a card never does
  for (const b of el.menu.querySelectorAll('button')) b.disabled = S.busy && !READS.has(b.dataset.mact);
  el.menu.setAttribute('aria-label', t(S.menu.kind === 'collection' ? 'nodes_rail_menu' : 'nodes_menu', { name: what.name }));
  // a phone's is a sheet along the screen's foot, over a dim (2026-11-16)
  const sheet = phone();
  el.menu.classList.toggle('nv-menu-sheet', sheet);
  if (el.menuDim) el.menuDim.hidden = !sheet;
  el.menu.hidden = false;
  placeMenu();
}

/** Seat the menu under its ⋯ (after every redraw of the table or the rail);
    put it away when its ⋯ has gone. A phone's sheet has its seat in the
    style sheet: only its ⋯ is marked. */
export function placeMenu() {
  paintAsked();
  paintDiagnose();
  payOwed();
  if (!S.menu || !el.menu) return;
  const more = anchorOf(S.menu);
  const sheet = el.menu.classList.contains('nv-menu-sheet');
  // gone, or the screen crossed between a phone and a wide one
  if (!more || sheet !== phone()) { closeMenu(false); return; }
  more.setAttribute('aria-expanded', 'true');
  if (sheet) { el.menu.style.left = ''; el.menu.style.top = ''; return; }
  const at = more.getBoundingClientRect();
  const box = el.menu.getBoundingClientRect();
  el.menu.style.left = `${Math.max(8, Math.min(at.left, innerWidth - box.width - 8))}px`;
  el.menu.style.top = `${at.bottom + 4 + box.height > innerHeight ? Math.max(8, at.top - box.height - 4) : at.bottom + 4}px`;
}

/** A press on a ⋯: its menu out, or put away when it was out already. */
export async function toggleMenu(kind, id) {
  if (menuOn(kind, id)) { closeMenu(true); return; }
  await openMenu(kind, id);
}

/** A thing's menu out, seated under its ⋯, the keyboard on its first item.
    Already out: it stays (the keyboard and a right-click open, never shut).
    `back` is where Escape puts the keyboard, when it is still there; else
    the ⋯. */
export async function openMenu(kind, id, back = null) {
  if (menuOn(kind, id)) { refocusMenu(''); return; }
  closeMenu(false);
  // a phone's sheet stands under an open place card: the card goes first
  if (phone() && A.cardPlace?.()) A.closeCard?.();
  S.menu = { kind, id, back };
  drawMenu();
  if (!menuOn(kind, id)) return;   // nothing to list
  // (no scroll for it: any scroll puts the menu away)
  el.menu.querySelector(PRESSABLE)?.focus({ preventScroll: true });
  // its maintenance mode line reads the repairs (an admin's route), and a
  // place's or a service's last answer its check (2026-11-17): each read
  // once, then the menu drawn again
  const reads = [];
  if (!Editor.repairs && mayWrite()) reads.push(ensureRepairs());
  if (kind !== 'collection' && !freshRead(id)) reads.push(readCheck(id));
  if (reads.length) {
    await Promise.all(reads);
    if (menuOn(kind, id)) { const at = focusKeyOfMenu(); drawMenu(); refocusMenu(at); }
  }
}

/** A press that does something: not disabled while a write runs, not held. */
const PRESSABLE = 'button:not(:disabled):not([aria-disabled="true"])';

/** The item the keyboard is on, by what it does (a redraw may add lines
    above it), or '' when it is not in the menu. */
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

/** The keyboard back on a thing's ⋯. A place's or a service's row is
    brought into the drawn window first; the rail is drawn again, so a ⋯ a
    save has just replaced is the one that takes it. */
export function focusMore(kind, id) {
  if (kind === 'collection') {
    S.railFocus = `[${HOOK.collection}="${CSS.escape(id)}"]`;
    drawRail();
    return;
  }
  showRow(kind === 'service' ? serviceOf(id)?.place : id);
  // owed for a few seconds: a redraw that lands after this (the bells'
  // counts read after a save) draws the ⋯ afresh, and payOwed puts the
  // keyboard back on the new one (2026-11-17)
  owed = { kind, id, until: Date.now() + OWED_FOR };
  el.results.querySelector(`[${HOOK[kind]}="${CSS.escape(id)}"]`)?.focus();
}

/** How long a ⋯ is owed the keyboard after a write. */
const OWED_FOR = 6000;
/** {kind, id, until}: the ⋯ the keyboard was last sent back to. */
let owed = null;

/** After every redraw (placeMenu): when the keyboard fell to the page in
    the few seconds after it was sent to a ⋯, it goes back there. Once it
    is somewhere else on purpose, nothing is owed. */
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
    // the bulk bar becomes the bar for this one thing (it puts the menu away)
    case 'schedule': openScope({ kind, id, name }); break;
    case 'collections': openScope({ kind, id, name, form: 'svc-col' }); break;
    // the table and the rail are drawn again once the save is read back: the
    // keyboard goes back to this thing's ⋯ then, not to the page
    case 'mode-on': case 'mode-off':
      closeMenu(true);
      setMode({ [TARGET[kind]]: [id] }, on, name).then(() => focusMore(kind, id));
      break;
    case 'unmanaged-on': case 'unmanaged-off':
      closeMenu(true);
      (kind === 'service' ? setServiceUnmanaged(what.svc, on) : setUnmanaged(TARGET[kind], [id], on, name))
        .then(() => focusMore(kind, id));
      break;
    // the check's own fields in the scope bar; or asked now, its answer in the row
    case 'check':
      closeMenu(false);
      openCheck({ kind, id, name, ...(kind === 'service' ? { place: what.svc.place } : {}) });
      break;
    // the keyboard on the thing's ⋯, whichever way the menu was opened
    case 'check-now': closeMenu(false); focusMore(kind, id); askNow(kind, id); break;
    // the place's chain, listed under its name (2026-11-17)
    case 'diagnose': closeMenu(false); focusMore(kind, id); diagnose(id, name); break;
    // the TOPOLOGY view, centred on the place (a service's: its place)
    case 'topology': closeMenu(false); A.openTopology?.(kind === 'service' ? what.svc.place : id); break;
    case 'alerts': closeMenu(false); pressBell(kind, id); break;
    case 'edit': closeMenu(false); A.editPlace?.(id); break;
    // a collection's name box is the rail's
    case 'rename': closeMenu(false); startRename(id); break;
    // a place's remove page is the Desk's; a collection's Remove arms in the
    // rail, where its notes and its second press are
    case 'remove':
      closeMenu(false);
      if (kind === 'collection') armRemove(id); else A.removePlace?.(id);
      break;
    // a phone's sheet: what a press on the card does (the keyboard back on its ⋯ first)
    case 'open': closeMenu(true); openCard(id); break;
    default: break;
  }
}

/* ── Check now (2026-11-17) ──────────────────────────────────────────────── */

let askedTimer = 0;

/** Where a thing's Check now line goes: a place's name cell, or a
    service's line (under its place, or in the list of every one). */
function askedHost(kind, id) {
  if (!el.results) return null;
  if (kind === 'place') return el.results.querySelector(`tr[data-id="${CSS.escape(id)}"] .nv-name-cell`)?.parentElement || null;
  return el.results.querySelector(`[data-svcmenu="${CSS.escape(id)}"]`)?.closest('.nv-svc') || null;
}

/** Draw `S.asked` into its row, after every redraw (placeMenu calls this).
    "Asking…" stays through any redraw; an answer stays through a redraw of
    the same feed (a scroll of a long table), and goes on the first redraw
    after the next feed, or after ASKED_FOR. */
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

/** Ask one check now: "Asking…" in its row, then what it answered or why
    it was refused, in words. Not a write to the map, so not `busy`: the
    table stays as it is. The keyboard stays on the ⋯ the menu came from. */
async function askNow(kind, id) {
  if (S.asked?.pending && S.asked.kind === kind && S.asked.id === id) return;
  clearTimeout(askedTimer);
  S.asked = { kind, id, text: t('nodes_asking'), tone: '', pending: true };
  paintAsked();
  let res = null;
  let body = null;
  try {
    res = await fetch('api/v2/admin/checks/run', { method: 'POST', headers: WRITE_HEADERS, body: JSON.stringify({ key: id }) });
    try { body = await res.json(); } catch { /* an empty or non-JSON answer */ }
  } catch { /* no answer at all: said below */ }
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
  // another thing was asked meanwhile: that one's line is the one shown
  if (S.asked?.kind !== kind || S.asked.id !== id) return;
  sayAsked(kind, id, text, tone);
}

/** An answer, or a refusal, in a thing's row: it goes with the next feed's
    redraw or after ASKED_FOR. */
function sayAsked(kind, id, text, tone, extra = {}) {
  S.asked = { kind, id, text, tone, pending: false, feed: A.signalsFeed, until: Date.now() + ASKED_FOR, ...extra };
  paintAsked();
  clearTimeout(askedTimer);
  askedTimer = setTimeout(() => {
    if (S.asked && !S.asked.pending && S.asked.kind === kind && S.asked.id === id) { S.asked = null; paintAsked(); }
  }, ASKED_FOR + 50);
}

/* ── where does it break? (2026-11-17) ───────────────────────────────────── */

/** Which ask is the latest: an answer to an older one is not listed. */
let dxSeq = 0;

/** Ask a place's chain once: `{status, body}`, status 0 when nothing
    answered. The one place it is asked from: the TOPOLOGY canvas asks
    through it too (`A.askDiagnose`), so its parts send nothing of their
    own. An admin's POST with the write proof; it writes nothing to the map. */
async function askDiagnose(id) {
  try {
    const res = await fetch('api/v2/admin/diagnose', { method: 'POST', headers: WRITE_HEADERS, body: JSON.stringify({ id }) });
    let body = null;
    try { body = await res.json(); } catch { /* an empty or non-JSON answer */ }
    return { status: res.status, ok: res.ok, body };
  } catch {
    return { status: 0, ok: false, body: null };
  }
}
A.askDiagnose = askDiagnose;

/** Ask a place's chain: "Asking…" under its name, then the chain listed
    there (`S.dx`), or why it was refused, said as Check now says it. Not a
    write to the map, so not `busy`. Another place's list goes at once. */
async function diagnose(id, name) {
  // one ask at a time for a place: a check being asked is not written over
  if (S.asked?.pending && S.asked.kind === 'place' && S.asked.id === id) return;
  const seq = ++dxSeq;
  if (S.dx) { S.dx = null; paintDiagnose(); }
  clearTimeout(askedTimer);
  S.asked = { kind: 'place', id, text: t('nodes_asking'), tone: '', pending: true, dx: true };
  paintAsked();
  const { status, ok, body } = await askDiagnose(id);
  if (seq !== dxSeq) return;   // another was asked since
  // its "Asking…" goes, unless something else was asked in its row since
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

/** Put the list away; `focusBack`, the keyboard on the row's ⋯. */
function closeDiagnose(focusBack) {
  const was = S.dx;
  S.dx = null;
  paintDiagnose();
  if (was && focusBack) focusMore('place', was.id);
}

/** The list, as views.css draws it: the summary (where the keyboard lands),
    one line per step in order, and Show on the canvas and Close. */
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
  // its presses are its own: a press in a place's row would open its card
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
  // where the keyboard is in it, to put it back after a redraw of the table
  box.addEventListener('focusin', (e) => { if (S.dx) S.dx.focus = e.target.closest('[data-dx]')?.dataset.dx || 'summary'; });
  box.addEventListener('focusout', (e) => {
    if (S.dx && e.relatedTarget && !box.contains(e.relatedTarget)) S.dx.focus = '';
  });
  return box;
}

/** Draw `S.dx` under its place's name, after every redraw (placeMenu). A
    redraw of the table drew it afresh: the keyboard, when it was in the
    list and has fallen to the page, goes back where it was. */
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
    // it lands where the keyboard was sent (the row's ⋯), never from a box being typed in
    if (free || el.results.contains(now)) { box.querySelector('[data-dx="summary"]').focus({ preventScroll: true }); owed = null; }
    else d.focus = '';
  } else if (d.focus && free) {
    box.querySelector(`[data-dx="${CSS.escape(d.focus)}"]`)?.focus({ preventScroll: true });
    owed = null;
  }
}

/* ── the keyboard and a right-click (2026-11-16) ─────────────────────────── */

const MORE = '[data-rowmenu], [data-svcmenu], [data-menu]';

/** The thing a key or a right-click is on: its line (a place's row, a
    service's line, a collection's row in the rail) and that line's ⋯.
    A service's line is inside a row of its own, so it is found first. Null
    where the line has no ⋯ (a viewer's row, a network, a kind), and on a
    phone's card, which opens its sheet only from its ⋯ (a long press keeps
    the browser's own). */
function thingAt(target) {
  const line = target?.closest?.('.nv-svc, tr[data-id], .nv-rail-li');
  const more = line?.querySelector(MORE);
  if (!more) return null;
  if (more.hasAttribute('data-svcmenu')) return { line, kind: 'service', id: more.dataset.svcmenu };
  if (more.hasAttribute('data-rowmenu')) return { line, kind: 'place', id: more.dataset.rowmenu };
  return { line, kind: 'collection', id: more.dataset.menu };
}

/** Where Escape puts the keyboard: where it is now, when that is in the line. */
const backIn = (line) => (line.contains(document.activeElement) ? document.activeElement : null);

/** A key opened a menu just now: the context menu event the same key may
    send after it is the browser's, and is refused. */
let keyedAt = 0;

/** Shift+F10 or the menu key, inside the results or the rail. */
export function onThingKey(e) {
  const shiftF10 = e.key === 'F10' && e.shiftKey && !e.ctrlKey && !e.altKey && !e.metaKey;
  if (!shiftF10 && e.key !== 'ContextMenu') return;
  // a box being typed in keeps its own menu
  if (e.target.closest?.('textarea, select, input:not([type="checkbox"])')) return;
  const at = thingAt(e.target);
  if (!at) return;
  e.preventDefault();
  keyedAt = Date.now();
  openMenu(at.kind, at.id, backIn(at.line));
}

/** A right-click inside the results or the rail: the thing's menu, under
    its ⋯, where it has one. A link, a box, and text someone has selected
    in the line keep the browser's menu. */
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

/** The menu's own right-click (and the key's late one): never the browser's
    over it. */
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
