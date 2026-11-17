/* NODES, the table (2026-11-16): drawing the results (a table, a long table
   through a window of rows, or a phone's cards), keeping the keyboard on its
   row across a redraw, the select-all box, a row's card, and the presses and
   ticks inside the results. A phone's card has a ⋯ of its own (2026-11-16):
   the one menu, as a sheet that only reads. The keys and the right-click
   that open a row's menu are nodes-menu.js's. Cut out of nodes.js. Five of its parts import
   each other in circles, which is safe because none of them calls another
   while it loads; what they need from nodes.js itself they reach through
   `hooks` (nodes-state.js), never by importing it. */

import { A, esc } from './config.js';
import * as R from './roster-model.js';
import * as W from './window-model.js';
import { t } from './nodes-text.js';
import { DOT, COLUMNS, store, S, el, hooks, phone, mayWrite, menuOn } from './nodes-state.js';
import {
  mayAlert, alertsCell, pressBell, stateOf, stateCell, reviewedCell, maintenanceCell, certCell,
  collectionsCell, text, watchedCell, kindCell, addressCell, servicesLine,
} from './nodes-cells.js';
import { drawRail } from './nodes-rail.js';
import { drawMessage, drawBulk } from './nodes-forms.js';
import { servicesCell, servicesRow, drawThings, toggleServices } from './nodes-services.js';
import { placeMenu, toggleMenu } from './nodes-menu.js';

/* ── the table, or the phone's cards ─────────────────────────────────────── */

function drawCount(shown, total) {
  el.count.textContent = !S.roster ? ''
    : shown === total ? (total === 1 ? t('nodes_count_one') : t('nodes_count_all', { total }))
      : t('nodes_count', { shown, total });
}

export function drawResults() {
  if (!el.sheet) return;
  // the table on screen, read before anything here writes (stage 5: a read
  // after the rail's redraw would lay the whole page out for it)
  const oldBody = el.results.querySelector('.nv-table tbody');
  // (only a windowed one: a short table has nothing to hold and needs no layout read)
  const pre = oldBody && S.win ? readDrawn(oldBody) : null;
  el.clear.hidden = R.isEmptyFilter(S.filter);
  // the two checks about a place's review say nothing about a container
  for (const box of [el.unchecked, el.stale]) { const l = box.closest('label'); if (l) l.hidden = Boolean(S.filter.things); }
  hooks.drawSaved();
  drawRail();
  drawMessage();

  if (!S.roster) {
    S.win = null;
    el.results.innerHTML = S.error
      ? `<div class="dsk-notice dsk-notice-bad">${esc(t('nodes_failed', { why: S.error }))}</div>`
      : `<div class="dsk-notice">${esc(t('nodes_loading'))}</div>`;
    drawCount(0, 0);
    drawBulk();
    return;
  }
  if (S.filter.things) { drawThings(); return; }
  const now = Date.now();
  const all = S.roster.rows;
  const rows = R.sortRows(R.filterRows(all, S.filter, now), S.sort.key, S.sort.dir, S.roster.collections);
  S.shown = rows.map((r) => r.id);
  // a selection only ever holds rows on screen: what a bulk action writes is what you can see
  const onScreen = new Set(S.shown);
  let dropped = false;
  for (const id of [...S.selected]) if (!onScreen.has(id)) { S.selected.delete(id); dropped = true; }
  if (dropped) S.arm.disarm();
  drawCount(rows.length, all.length);

  if (!all.length) el.results.innerHTML = `<div class="dsk-notice">${esc(t('nodes_empty'))}</div>`;
  else if (!rows.length) el.results.innerHTML = `<div class="dsk-notice">${esc(t('nodes_none'))}</div>`;
  else if (phone()) el.results.innerHTML = cardsHTML(rows.slice(0, S.cards)) + (rows.length > S.cards
    ? `<button type="button" class="dsk-btn dsk-btn-sm nv-more-cards" data-morecards>${esc(t('nodes_more_cards', { n: Math.min(CARDS, rows.length - S.cards), left: rows.length - S.cards }))}</button>` : '');
  const warn = S.error ? `<div class="dsk-notice dsk-notice-warn">${esc(t('nodes_failed', { why: S.error }))}</div>` : '';
  const windowed = !phone() && rows.length >= W.WINDOW_MIN;
  if (windowed) drawWindowed(rows, now, pre, warn);   // the notice goes in before the row on screen is held still
  else if (rows.length && !phone()) el.results.innerHTML = tableHTML(rows, now);
  if (!windowed) S.win = null;
  placeMenu();
  el.addPlace.hidden = !(mayWrite() && !phone() && typeof A.newPlace === 'function');
  if (warn && !windowed) el.results.insertAdjacentHTML('afterbegin', warn);
  syncSelectAll();
  drawBulk();
  hooks.drawSummary();
  hooks.drawRecent();
}

function tableHTML(rows, now) {
  const p = tableParts(now);
  return tableShell(p, rows.map((row) => p.rowHTML(row)).join(''), 0);
}

function tableShell(p, body, count) {
  // a windowed table says how many rows it has, and each row its place (stage 5)
  // (and can hold the keyboard while the window moves a focused row away)
  return `<div class="nv-scroll"><table class="dsk-table nv-table"${count ? ` aria-rowcount="${count + 1}" tabindex="-1"` : ''}>` +
    `<thead><tr${count ? ' aria-rowindex="1"' : ''}>${p.pickHead}${p.head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

/** The table's head and a drawer of one row (with its open services row). */
function tableParts(now) {
  const admin = mayWrite();
  const alerting = mayAlert();
  const span = COLUMNS.length + (admin ? 1 : 0) + (alerting ? 1 : 0);   // a services row spans them all
  const head = COLUMNS.map(([key, label]) => {
    const on = S.sort.key === key;
    const sort = on ? (S.sort.dir === 'desc' ? 'descending' : 'ascending') : 'none';
    // the Alerts column stands beside the name, where its bell is seen with
    // the place it belongs to (a column at the far end scrolled out of sight)
    const alertHead = key === 'name' && alerting ? `<th scope="col" class="nv-th-alerts">${esc(t('nodes_col_alerts'))}</th>` : '';
    return `<th scope="col" aria-sort="${sort}" class="nv-th-${key}"><button type="button" class="nv-sort${on ? ' on' : ''}" ` +
      `data-sort="${key}" title="${esc(t('nodes_sort_by', { col: t(label) }))}">${esc(t(label))}</button></th>${alertHead}`;
  }).join('');
  const pickHead = admin
    ? `<th class="dsk-th-pick" scope="col"><input type="checkbox" class="dsk-check nv-all" aria-label="${esc(t('nodes_select_all'))}"></th>` : '';
  const rowHTML = (row, index = 0) => {
    const standing = R.rowStanding(row);
    const pick = admin
      ? `<td class="dsk-td-pick"><input type="checkbox" class="dsk-check nv-pick-row" data-id="${esc(row.id)}" ` +
        `${S.selected.has(row.id) ? 'checked ' : ''}aria-label="${esc(t('nodes_select', { name: row.name || row.id }))}"></td>` : '';
    return `<tr data-id="${esc(row.id)}" data-standing="${standing}"${index ? ` aria-rowindex="${index}"` : ''} class="nv-row${standing === 'checked' ? '' : ` dsk-p-${standing}`}${S.selected.has(row.id) ? ' nv-on' : ''}${row.unmanaged ? ' nv-unmanaged' : ''}">` +
      pick +
      `<td>${stateCell(row)}</td>` +
      `<td><span class="nv-name-cell"><button type="button" class="nv-name" data-open="${esc(row.id)}" title="${esc(t('nodes_open'))}">${esc(row.name || row.id)}</button>` +
      (admin && !phone() ? `<button type="button" class="nv-rail-more nv-row-more" data-rowmenu="${esc(row.id)}" aria-haspopup="menu" ` +
        `aria-expanded="${menuOn('place', row.id)}" aria-label="${esc(t('nodes_menu', { name: row.name || row.id }))}" ` +
        `title="${esc(t('nodes_menu', { name: row.name || row.id }))}">⋯</button>` : '') + '</span></td>' +
      (alerting ? `<td class="nv-td-alerts">${alertsCell(row)}</td>` : '') +
      `<td>${text(row.zone_name || row.zone)}</td>` +
      `<td>${kindCell(row)}</td>` +
      `<td>${addressCell(row)}</td>` +
      `<td class="nv-num">${servicesCell(row, admin)}</td>` +
      `<td>${watchedCell(row)}</td>` +
      `<td>${reviewedCell(row, now)}</td>` +
      `<td>${maintenanceCell(row)}</td>` +
      `<td>${certCell(row)}</td>` +
      `<td>${collectionsCell(row)}</td>` +
      '</tr>' + (S.expanded.has(row.id) ? servicesRow(row, span, index ? index + 1 : 0) : '');
  };
  return { head, pickHead, span, rowHTML };
}

/* ── the window (2026-11-15, stage 5 of the NODES plan) ──────────────────
   Past W.WINDOW_MIN rows the table draws only the rows on screen and a few
   more (window-model.js), with a spacer row above and below standing in for
   the rest. Scrolling `#view-nodes` near a drawn edge draws again, in the
   scroll handler itself (a hidden pane runs animation frames once a second).
   A row that stays drawn stays where it was on screen: the scroll is put
   right for heights that turned out other than guessed. Columns only widen
   while the window moves, so they do not jump. Find-in-page sees only the
   rows drawn; the search box sees them all. Fewer rows: drawn as before. */

export const CARDS = 200;                  // a phone's cards, drawn this many at a time
const heights = new Map();          // `<id>|<services open>` → measured px
const hkey = (row) => `${row.id}|${S.expanded.has(row.id) ? 1 : 0}`;
const scroller = () => document.getElementById('view-nodes') || el.sheet?.closest('[id^="view-"]') || null;
let watching = null;

/** `pre`: the table that was on screen, read by drawResults before it wrote
    anything (its rows' heights, where the screen is). */
function drawWindowed(rows, now, pre = null, lead = '') {
  const p = tableParts(now);
  // the same rows drawn again (a save read back, services opened, a bell):
  // the row at the screen's top stays put, as on a scroll. A keystroke that
  // changed the list skips it (and the layout it costs)
  const same = Boolean(S.win && pre?.anchor && S.win.rows.length === rows.length
    && S.win.rows[0]?.id === rows[0]?.id && S.win.rows.at(-1)?.id === rows.at(-1)?.id);
  S.win = { rows, p, start: 0, end: 0, widths: [] };
  // the shell holds one spacer the height of every row before anything is
  // measured, so the page never shrinks under the scroll (which would clamp
  // it to the top) between this redraw and the window's
  const total = W.rowWindow({ count: rows.length, heights: rows.map((r) => heights.get(hkey(r))) }).total;
  // an open services row is a row too, for the count readers hear
  const extra = rows.reduce((k, r) => k + (S.expanded.has(r.id) ? 1 : 0), 0);
  el.results.innerHTML = lead + tableShell(p, `<tr class="nv-gap" data-gap="before" aria-hidden="true"><td colspan="${p.span}"></td></tr>`, rows.length + extra);
  el.results.querySelector('[data-gap="before"] td').style.height = `${total}px`;
  const sc = scroller();
  if (sc && watching !== sc) {
    sc.addEventListener('scroll', () => { if (S.win) paintWindow(false); }, { passive: true });
    // another width wraps rows differently: measure again, and let the
    // columns narrow (the widths they were held to go)
    addEventListener('resize', () => {
      heights.clear();
      if (!S.win) return;
      S.win.widths = [];
      for (const th of el.results.querySelectorAll('.nv-table thead th')) th.style.minWidth = '';
      paintWindow(true);
    });
    watching = sc;
  }
  paintWindow(true, pre, same);
}

/* EVERY READ, THEN EVERY WRITE. A layout read after a write lays the whole
   page out again (about 25 ms at 2,000 places), so a redraw reads what it
   needs while the layout is still clean (in the scroll event, or before a
   keystroke's redraw replaces the table), then writes. A keystroke's redraw
   forces no layout at all; a scroll's forces one, to keep its anchor row
   still. */

/** What is drawn now, read while the layout is clean: each drawn row's
    height (kept, with its services row when open), where the screen is
    against the body, and the first drawn row on screen. */
function readDrawn(tbody) {
  const sc = scroller();
  const scTop = sc ? sc.getBoundingClientRect().top : 0;
  let anchor = null;
  for (const tr of tbody.querySelectorAll('tr[data-id]')) {
    const r = tr.getBoundingClientRect();
    const svc = tr.nextElementSibling?.classList.contains('nv-svc-row') ? tr.nextElementSibling : null;
    heights.set(`${tr.dataset.id}|${svc ? 1 : 0}`, r.height + (svc ? svc.getBoundingClientRect().height : 0));
    if (!anchor && r.bottom > scTop) anchor = { id: tr.dataset.id, at: r.top };
  }
  const view = { top: scTop - tbody.getBoundingClientRect().top, viewport: sc ? sc.clientHeight : innerHeight };
  return { view, anchor };
}

function paintWindow(force, pre = null, hold = false) {
  const w = S.win;
  const tbody = el.results.querySelector('.nv-table tbody');
  if (!w || !tbody) return;
  // reads
  const seen = pre || readDrawn(tbody);
  const cols = pre ? null : [...el.results.querySelectorAll('.nv-table thead th')].map((th) => Math.ceil(th.getBoundingClientRect().width));
  const n = w.rows.length;
  const want = W.rowWindow({ count: n, heights: w.rows.map((r) => heights.get(hkey(r))), ...seen.view });
  const redraw = force || W.needsRedraw(w, want, n);
  const key = redraw ? rowFocusKey() : null;
  // writes
  growColumns(w, cols);
  if (!redraw) return;
  const gap = (where) => `<tr class="nv-gap" data-gap="${where}" aria-hidden="true"><td colspan="${w.p.span}"></td></tr>`;
  // readers' row numbers: the head is 1, and an open services row counts
  let index = 2;
  for (let k = 0; k < want.start; k++) index += S.expanded.has(w.rows[k].id) ? 2 : 1;
  tbody.innerHTML = gap('before') +
    w.rows.slice(want.start, want.end).map((row) => {
      const html = w.p.rowHTML(row, index);
      index += S.expanded.has(row.id) ? 2 : 1;
      return html;
    }).join('') +
    gap('after');
  // heights through the CSSOM (the page's CSP refuses style attributes in markup)
  tbody.querySelector('[data-gap="before"] td').style.height = `${want.before}px`;
  tbody.querySelector('[data-gap="after"] td').style.height = `${want.after}px`;
  w.start = want.start;
  w.end = want.end;
  // a scroll keeps the row that was at the screen's top where it was, though
  // the rows above it turned out taller or shorter than guessed (one layout);
  // so does a redraw of the same rows (`hold`)
  const sc = scroller();
  if ((!force || hold) && sc && seen.anchor) {
    const again = tbody.querySelector(`tr[data-id="${CSS.escape(seen.anchor.id)}"]`);
    const moved = again ? again.getBoundingClientRect().top - seen.anchor.at : 0;
    if (Math.abs(moved) >= 1) sc.scrollTop += moved;
  }
  restoreRowFocus(key);
  placeMenu();
  syncSelectAll();
}

/** Columns may widen as other rows come into the window, never narrow:
    `px` are the widths read before any write. */
function growColumns(w, px) {
  if (!px) return;
  const ths = el.results.querySelectorAll('.nv-table thead th');
  px.forEach((v, i) => {
    if (v > (w.widths[i] || 0) && ths[i]) { w.widths[i] = v; ths[i].style.minWidth = `${v}px`; }
  });
}

/** The control the keyboard is on inside a row, as a selector that finds it
    after a redraw; null when the keyboard is not in the table's rows. */
function rowFocusKey() {
  const was = document.activeElement;
  if (!was || !el.results.contains(was) || !was.closest('tbody')) return null;
  for (const attr of ['data-open', 'data-rowmenu', 'data-expand', 'data-svcmenu', 'data-alerts']) {
    const v = was.getAttribute(attr);
    if (v === null) continue;
    const id = was.getAttribute('data-id');
    return `[${attr}="${CSS.escape(v)}"]${id !== null ? `[data-id="${CSS.escape(id)}"]` : ''}`;
  }
  if (was.classList.contains('nv-pick-row')) return `.nv-pick-row[data-id="${CSS.escape(was.dataset.id)}"]`;
  return '.nv-table';   // somewhere else in a row: the table holds it
}

/** The keyboard back where it was; when the window moved its row away (a
    scroll past it), on the table itself, so it does not fall to the page and
    the next Tab goes on in the rows on screen. */
function restoreRowFocus(key) {
  if (!key) return;
  const now = document.activeElement;
  if (now && now !== document.body && el.results.contains(now)) return;
  (el.results.querySelector(key) || el.results.querySelector('.nv-table'))?.focus({ preventScroll: true });
}

/** Bring a row into the window (a save that re-sorted it away; the keyboard
    going back to its ⋯ or bell) before something looks for it. */
export function showRow(id) {
  const w = S.win;
  if (!w) return;
  const i = w.rows.findIndex((r) => r.id === id);
  if (i < 0 || (i >= w.start && i < w.end)) return;
  const sc = scroller();
  const tbody = el.results.querySelector('.nv-table tbody');
  if (!sc || !tbody) return;
  const hs = w.rows.map((r) => heights.get(hkey(r)));
  const g = W.guess(hs);
  let y = 0;
  for (let k = 0; k < i; k++) y += hs[k] > 0 ? hs[k] : g;
  const bodyTop = tbody.getBoundingClientRect().top - sc.getBoundingClientRect().top + sc.scrollTop;
  sc.scrollTop = Math.max(0, bodyTop + y - sc.clientHeight / 3);
  paintWindow(true);
}

/** A phone's cards. Each has a ⋯ beside it (2026-11-16), for whoever is
    signed in: the one menu, as a sheet that only reads (nodes-menu.js). It
    carries a row's own mark (`data-rowmenu`), so it is found, pressed and
    focused as a row's ⋯ is; it cannot sit inside the card's button. */
function cardsHTML(rows) {
  return `<ul class="nv-cards">${rows.map((row) => {
    const s = stateOf(row);
    const first = (row.addresses || [])[0];
    const services = typeof row.services === 'number' ? servicesLine(row.services) : '';
    const name = row.name || row.id;
    return `<li class="nv-card-li"><button type="button" class="nv-card" data-open="${esc(row.id)}">` +
      `<span class="nv-card-top"><span class="svc-health ${DOT[s] || ''}" aria-hidden="true"></span>` +
      `<span class="nv-name-text">${esc(name)}</span>` +
      `<span class="nv-sr">${esc(t(`nodes_state_${s}`))}</span></span>` +
      `<span class="nv-card-line">${esc(row.zone_name || row.zone || '')}` +
      `${first ? ` <span class="nv-mono">${esc(first)}</span>` : ''}` +
      `${services ? ` <span class="nv-dim">${esc(services)}</span>` : ''}</span>` +
      '</button>' +
      `<button type="button" class="nv-rail-more nv-card-more" data-rowmenu="${esc(row.id)}" aria-haspopup="menu" ` +
      `aria-expanded="${menuOn('place', row.id)}" aria-label="${esc(t('nodes_menu', { name }))}" ` +
      `title="${esc(t('nodes_menu', { name }))}">⋯</button></li>`;
  }).join('')}</ul>`;
}

export function syncSelectAll() {
  const all = el.results.querySelector('.nv-all');
  if (!all) return;
  const n = S.shown.filter((id) => S.selected.has(id)).length;
  all.checked = n > 0 && n === S.shown.length;
  all.indeterminate = n > 0 && n < S.shown.length;
}

/** A row's press: its card, or (pressed again while that card is up) no card,
    the way a marker on the map behaves (2026-11-13). */
export function openCard(id) {
  if (R.rowPress(A.cardPlace?.(), id) === 'close') { A.closeCard?.(); return; }
  const node = A.DATA?.nodes?.find((n) => n.id === id);
  if (!node || typeof A.openCard !== 'function') { A.showToast?.(t('nodes_not_drawn')); return; }
  A.openCard(node);
}

export function onResultsClick(e) {
  const sort = e.target.closest('[data-sort]');
  if (sort) {
    const key = sort.dataset.sort;
    S.sort = { key, dir: S.sort.key === key && S.sort.dir === 'asc' ? 'desc' : 'asc' };
    R.writeSort(store, S.sort);
    drawResults();
    el.results.querySelector(`[data-sort="${key}"]`)?.focus();
    return;
  }
  if (e.target.closest('[data-morecards]')) {
    // a phone's next cards: the keyboard goes to the first of them
    const from = S.cards;
    S.cards += CARDS;
    drawResults();
    el.results.querySelectorAll(S.filter.things ? '.nv-things .nv-svc-host' : '.nv-card')[from]?.focus();
    return;
  }
  const expand = e.target.closest('[data-expand]');
  if (expand) { toggleServices(expand.dataset.expand); return; }
  const svcMore = e.target.closest('[data-svcmenu]');
  if (svcMore) { toggleMenu('service', svcMore.dataset.svcmenu); return; }
  const bell = e.target.closest('[data-alerts]');
  if (bell) { pressBell(bell.dataset.alerts, bell.dataset.id); return; }   // the bell opens alerts, not the card
  if (e.target.closest('.nv-svc-row')) return;   // a service's row opens no card (after its bell: review)
  const more = e.target.closest('[data-rowmenu]');
  if (more) { toggleMenu('place', more.dataset.rowmenu); return; }   // the menu, not the card
  if (e.target.closest('input, label, a, .dsk-td-pick')) return;   // a checkbox selects, it does not open
  const open = e.target.closest('[data-open]') || e.target.closest('tr[data-id]');
  if (open) openCard(open.dataset.open || open.dataset.id);
}

export function onResultsChange(e) {
  const box = e.target;
  if (box.classList.contains('nv-all')) {
    for (const id of S.shown) { if (box.checked) S.selected.add(id); else S.selected.delete(id); }
  } else if (box.classList.contains('nv-pick-row')) {
    if (box.checked) S.selected.add(box.dataset.id); else S.selected.delete(box.dataset.id);
  } else return;
  S.arm.disarm();
  for (const tr of el.results.querySelectorAll('tr[data-id]')) {
    const on = S.selected.has(tr.dataset.id);
    tr.classList.toggle('nv-on', on);
    const cb = tr.querySelector('.nv-pick-row');
    if (cb) cb.checked = on;
  }
  syncSelectAll();
  drawBulk();
}
