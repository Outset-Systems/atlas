
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


function drawCount(shown, total) {
  el.count.textContent = !S.roster ? ''
    : shown === total ? (total === 1 ? t('nodes_count_one') : t('nodes_count_all', { total }))
      : t('nodes_count', { shown, total });
}

export function drawResults() {
  if (!el.sheet) return;
  const oldBody = el.results.querySelector('.nv-table tbody');
  const pre = oldBody && S.win ? readDrawn(oldBody) : null;
  el.clear.hidden = R.isEmptyFilter(S.filter);
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
  if (windowed) drawWindowed(rows, now, pre, warn);
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
  return `<div class="nv-scroll"><table class="dsk-table nv-table"${count ? ` aria-rowcount="${count + 1}" tabindex="-1"` : ''}>` +
    `<thead><tr${count ? ' aria-rowindex="1"' : ''}>${p.pickHead}${p.head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

function tableParts(now) {
  const admin = mayWrite();
  const alerting = mayAlert();
  const span = COLUMNS.length + (admin ? 1 : 0) + (alerting ? 1 : 0);
  const head = COLUMNS.map(([key, label]) => {
    const on = S.sort.key === key;
    const sort = on ? (S.sort.dir === 'desc' ? 'descending' : 'ascending') : 'none';
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


export const CARDS = 200;
const heights = new Map();
const hkey = (row) => `${row.id}|${S.expanded.has(row.id) ? 1 : 0}`;
const scroller = () => document.getElementById('view-nodes') || el.sheet?.closest('[id^="view-"]') || null;
let watching = null;

function drawWindowed(rows, now, pre = null, lead = '') {
  const p = tableParts(now);
  const same = Boolean(S.win && pre?.anchor && S.win.rows.length === rows.length
    && S.win.rows[0]?.id === rows[0]?.id && S.win.rows.at(-1)?.id === rows.at(-1)?.id);
  S.win = { rows, p, start: 0, end: 0, widths: [] };
  const total = W.rowWindow({ count: rows.length, heights: rows.map((r) => heights.get(hkey(r))) }).total;
  const extra = rows.reduce((k, r) => k + (S.expanded.has(r.id) ? 1 : 0), 0);
  el.results.innerHTML = lead + tableShell(p, `<tr class="nv-gap" data-gap="before" aria-hidden="true"><td colspan="${p.span}"></td></tr>`, rows.length + extra);
  el.results.querySelector('[data-gap="before"] td').style.height = `${total}px`;
  const sc = scroller();
  if (sc && watching !== sc) {
    sc.addEventListener('scroll', () => { if (S.win) paintWindow(false); }, { passive: true });
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
  const seen = pre || readDrawn(tbody);
  const cols = pre ? null : [...el.results.querySelectorAll('.nv-table thead th')].map((th) => Math.ceil(th.getBoundingClientRect().width));
  const n = w.rows.length;
  const want = W.rowWindow({ count: n, heights: w.rows.map((r) => heights.get(hkey(r))), ...seen.view });
  const redraw = force || W.needsRedraw(w, want, n);
  const key = redraw ? rowFocusKey() : null;
  growColumns(w, cols);
  if (!redraw) return;
  const gap = (where) => `<tr class="nv-gap" data-gap="${where}" aria-hidden="true"><td colspan="${w.p.span}"></td></tr>`;
  let index = 2;
  for (let k = 0; k < want.start; k++) index += S.expanded.has(w.rows[k].id) ? 2 : 1;
  tbody.innerHTML = gap('before') +
    w.rows.slice(want.start, want.end).map((row) => {
      const html = w.p.rowHTML(row, index);
      index += S.expanded.has(row.id) ? 2 : 1;
      return html;
    }).join('') +
    gap('after');
  tbody.querySelector('[data-gap="before"] td').style.height = `${want.before}px`;
  tbody.querySelector('[data-gap="after"] td').style.height = `${want.after}px`;
  w.start = want.start;
  w.end = want.end;
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

function growColumns(w, px) {
  if (!px) return;
  const ths = el.results.querySelectorAll('.nv-table thead th');
  px.forEach((v, i) => {
    if (v > (w.widths[i] || 0) && ths[i]) { w.widths[i] = v; ths[i].style.minWidth = `${v}px`; }
  });
}

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
  return '.nv-table';
}

function restoreRowFocus(key) {
  if (!key) return;
  const now = document.activeElement;
  if (now && now !== document.body && el.results.contains(now)) return;
  (el.results.querySelector(key) || el.results.querySelector('.nv-table'))?.focus({ preventScroll: true });
}

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
  if (bell) { pressBell(bell.dataset.alerts, bell.dataset.id); return; }
  if (e.target.closest('.nv-svc-row')) return;
  const more = e.target.closest('[data-rowmenu]');
  if (more) { toggleMenu('place', more.dataset.rowmenu); return; }
  if (e.target.closest('input, label, a, .dsk-td-pick')) return;
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
