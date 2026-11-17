/* The alerts' form pieces (2026-11-14), shared by Settings › Alerts
   (alert-setup.js) and the rules inside NODES (alert-rules.js). Moved out of
   the ALERTS view (alerts.js, 2026-11-13) unchanged in what they draw: a
   labelled field with a seat for its problems, the filter bar's toggle, and
   a form with Cancel and Save that never posts while one is in flight.

   Every phrase is alerts-model.js's ALERTS_TEXT, through the theme. */

import { esc, themeText } from './config.js';
import * as M from './alerts-model.js';

/** One phrase: the theme's, else the plain one, with `{name}` filled in. */
export const t = (key, vars = {}) => M.fill(themeText(key, M.ALERTS_TEXT[key] || ''), vars);
/** The same, for words a kind of destination declares (2026-11-16): the
    theme's, else ours, else the kind's own `plain` words. */
export const tOr = (key, plain, vars = {}) => M.fill(themeText(key, M.ALERTS_TEXT[key] || plain || ''), vars);

export const list = (v) => (Array.isArray(v) ? v : []);
export const clock = (ms) => new Date(ms).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
export const stamp = (ms) => {
  const d = new Date(ms);
  return `${d.toLocaleDateString([], { month: 'short', day: 'numeric' })} ${clock(ms)}`;
};

export function button(cls, label, onClick, type = 'button') {
  const b = document.createElement('button');
  b.type = type;
  b.className = cls;
  b.textContent = label;
  if (onClick) b.addEventListener('click', onClick);
  return b;
}

/** A labelled field with a seat for its problems (`data-for`). */
export function field(name, labelText, control, hint = '') {
  const label = document.createElement('label');
  label.className = 'nv-field al-field';
  label.dataset.field = name;
  const span = document.createElement('span');
  span.className = 'nv-label';
  span.textContent = labelText;
  label.append(span, control);
  if (hint) {
    const h = document.createElement('span');
    h.className = 'al-hint';
    h.textContent = hint;
    label.append(h);
  }
  const p = document.createElement('span');
  p.className = 'al-problem';
  p.dataset.for = name;
  p.setAttribute('role', 'alert');
  label.append(p);
  return label;
}

export function input(type, value = '', cls = 'dsk-input') {
  const i = document.createElement('input');
  i.type = type;
  i.className = cls;
  i.value = value ?? '';
  return i;
}

export function select(options, value = '') {
  const s = document.createElement('select');
  s.className = 'dsk-input';
  s.innerHTML = options.map(([v, label]) => `<option value="${esc(v)}">${esc(label)}</option>`).join('');
  s.value = value ?? '';
  return s;
}

export function check(checked, cls = 'dsk-check') {
  const c = document.createElement('input');
  c.type = 'checkbox';
  c.className = cls;
  c.checked = Boolean(checked);
  return c;
}

/** A box beside its words, the filter bar's toggle. */
export function toggle(name, labelText, box) {
  const label = document.createElement('label');
  label.className = 'nv-toggle al-toggle';
  label.dataset.field = name;
  label.append(box, document.createTextNode(` ${labelText}`));
  return label;
}

/** Put problems beside their fields; what has no field goes in the general line. */
export function showProblems(form, byField, general = []) {
  if (!form) return;
  for (const p of form.querySelectorAll('.al-problem')) p.textContent = '';
  const left = [...general];
  for (const [name, texts] of Object.entries(byField)) {
    const seat = form.querySelector(`.al-problem[data-for="${CSS.escape(name)}"]`);
    if (seat) seat.textContent = texts.join(' ');
    else left.push(...texts);
  }
  const seat = form.querySelector('.al-form-problems');
  if (seat) {
    seat.innerHTML = left.length ? `<ul class="dsk-problems">${left.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>` : '';
  }
  (form.querySelector('.al-problem:not(:empty)')?.closest('label')?.querySelector('input, select') || null)?.focus();
}

export const byFieldOf = (checks) => checks.reduce((acc, c) => { (acc[c.field] = acc[c.field] || []).push(c.text); return acc; }, {});

/** A form: its fields, a seat for the problems no field owns, then Cancel
    (when there is one) and the go button. `isBusy()` holds a second submit
    while a save is in flight. */
export function formBox(cls, fields, goLabel, onGo, onCancel, extra = [], isBusy = () => false) {
  const box = document.createElement('form');
  box.className = `nv-form al-form ${cls}`;
  box.noValidate = true;
  box.append(...fields, ...extra);
  const problems = document.createElement('div');
  problems.className = 'al-form-problems';
  problems.setAttribute('role', 'alert');
  box.append(problems);
  const bar = document.createElement('div');
  bar.className = 'nv-form-bar';
  if (onCancel) bar.append(button('dsk-btn dsk-btn-sm', t('alerts_cancel'), onCancel));
  bar.append(button('dsk-btn dsk-btn-sm dsk-btn-go', goLabel, null, 'submit'));
  box.append(bar);
  box.addEventListener('submit', (e) => { e.preventDefault(); if (!isBusy()) onGo(); });
  if (onCancel) box.addEventListener('keydown', (e) => { if (e.key === 'Escape') { e.stopPropagation(); onCancel(); } });
  return box;
}

/** Run `redraw`, which rebuilds part of `root`, and put the keyboard back on
    the same control if it was on one inside: found again by what it does
    (`data-act`, `data-alerts`, `data-menu`, `data-toggle`, `data-sort`,
    `data-saved`) and what it is for (`data-id`). A read that lands while
    someone is on a button must not drop them to the page. */
export function keepFocus(root, redraw, ...fallbacks) {
  const key = focusKey(root);
  redraw();
  refocus(root, key, ...fallbacks);
}

/** Where the keyboard is inside `root`, as a selector that finds the same
    control after a redraw; '' when it is inside on something with no such
    mark (a form's Save); null when it is not inside at all. Take it BEFORE
    disabling buttons: a disabled button gives up the focus. */
export function focusKey(root) {
  const was = document.activeElement;
  if (!root || !was || was === document.body || !root.contains(was)) return null;
  for (const attr of ['data-act', 'data-alerts', 'data-menu', 'data-toggle', 'data-sort', 'data-saved']) {
    const v = was.getAttribute(attr);
    if (v === null) continue;
    const id = was.getAttribute('data-id');
    return `[${attr}="${CSS.escape(v)}"]${id !== null ? `[data-id="${CSS.escape(id)}"]` : ''}`;
  }
  return '';
}

/** Put the keyboard back after a redraw: on the control `key` names, else on
    the first of `fallbacks` that is there and enabled. Nothing when the
    keyboard was not inside (`key` null) or is still inside. */
export function refocus(root, key, ...fallbacks) {
  if (key === null || key === undefined || !root) return;
  const now = document.activeElement;
  if (now && now !== document.body && root.contains(now)) return;
  for (const sel of [key, ...fallbacks]) {
    const el = sel ? root.querySelector(sel) : null;
    if (el && !el.disabled) { el.focus({ preventScroll: true }); return; }
  }
}

/** True when two entries say the same, whatever the order of their keys: a
    form's entry as it was opened against the same entry in the latest read. */
export function sameEntry(a, b) {
  const norm = (v) => (Array.isArray(v) ? v.map(norm)
    : v && typeof v === 'object' ? Object.fromEntries(Object.keys(v).sort().map((k) => [k, norm(v[k])])) : v);
  return JSON.stringify(norm(a ?? null)) === JSON.stringify(norm(b ?? null));
}

/** A notice line, with the server's problems under it. */
export const noticeHTML = (m) => (!m ? '' : `<div class="dsk-notice dsk-notice-${m.kind}">${esc(m.text)}` +
  (m.problems?.length ? `<ul class="dsk-problems">${m.problems.map((p) => `<li>${esc(p)}</li>`).join('')}</ul>` : '') +
  '</div>');

/** The how-to-turn-it-on page, when alerts are off. */
export function offHTML(state) {
  return `<div class="al-off">
      <p class="al-off-title">${esc(state.title)}</p>
      ${state.lines.map((l) => `<p class="al-off-line">${esc(l)}</p>`).join('')}
      ${state.notes.length ? `<ul class="al-off-notes">${state.notes.map((n) => `<li>${esc(n)}</li>`).join('')}</ul>` : ''}
    </div>`;
}

/** What a save's answer says, as a notice and the problems for a form. A
    422's problems are put beside the fields of `form`. */
export function answerNotice(r, { form = null, prefix = '', label = '' } = {}) {
  if (r.ok) {
    const notes = list(r.body?.notes).map(String);
    return { kind: notes.length ? 'warn' : 'info', text: t('alerts_saved'), problems: notes };
  }
  if (r.status === 409) return { kind: 'warn', text: t('alerts_stale') };
  if (r.status === 422) {
    const { byField, general, mine } = M.sortProblems(r.body?.problems || [r.why], prefix, label);
    if (form) showProblems(form, byField, mine);
    const all = [...general, ...mine, ...Object.values(byField).flat()];
    const listed = form ? general : all;
    return { kind: 'bad', text: t(listed.length ? 'alerts_fix' : 'alerts_fix_form'), problems: listed };
  }
  return { kind: 'bad', text: t('alerts_refused', { why: r.why }) };
}
