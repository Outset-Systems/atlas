
import { A, esc } from './config.js';
import * as M from './alerts-model.js';
import * as Store from './alert-store.js';
import {
  t, list, field, input, select, check, toggle, showProblems, byFieldOf, formBox, noticeHTML, offHTML, answerNotice,
  keepFocus, focusKey, refocus, sameEntry,
} from './alert-forms.js';

const S = {
  target: null,
  form: null,
  armed: '',
  msg: null,
  busy: false,
};

let host = null;
let onShut = () => {};
let onMoved = () => {};

const body = () => Store.ALERTS.body;
const same = (a, b) => Boolean(a && b && a.kind === b.kind && a.id === b.id);
const heldPlace = (id) => list(body()?.status?.held).includes(id);
function unmanagedPlace(id) {
  const node = list(A.DATA?.nodes).find((n) => n && n.id === id);
  if (node?.unmanaged === true) return true;
  const members = (v) => (typeof v === 'string' ? [v] : list(v));
  return list(A.DATA?.collections).some((c) => c && c.unmanaged === true && members(c.places).includes(id));
}

export function mount(el, { shut, moved } = {}) {
  host = el;
  if (shut) onShut = shut;
  if (moved) onMoved = moved;
  host.addEventListener('click', onClick);
  host.addEventListener('change', onChange);
  host.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && S.target && !S.form) { e.stopPropagation(); close(); }
  });
}

export const current = () => S.target;

export function openFor(target) {
  if (same(S.target, target)) { close(); return false; }
  S.target = { kind: target.kind, id: target.id };
  S.form = null;
  S.armed = '';
  S.msg = null;
  draw();
  if (!body()) Store.read();
  host?.querySelector('.al-panel-title')?.focus();
  onMoved(S.target);
  return true;
}

function stillThere(target) {
  if (!A.DATA) return true;
  return M.unreachableRules([{ target }], A.DATA).length === 0;
}

export function close() {
  const was = S.target;
  S.target = null;
  S.form = null;
  S.armed = '';
  S.msg = null;
  draw();
  onShut(was);
}


function tell(text, kind = 'info', problems = []) {
  S.msg = text ? { kind, text, problems } : null;
  host?.querySelector('.al-panel-msg')?.replaceChildren();
  const seat = host?.querySelector('.al-panel-msg');
  if (seat) seat.innerHTML = noticeHTML(S.msg);
}

export function draw() {
  if (!host) return;
  if (!S.target) { host.innerHTML = ''; host.hidden = true; return; }
  if (!stillThere(S.target)) { close(); return; }
  host.hidden = false;
  const b = body();
  const phrase = M.targetPhrase(S.target, A.DATA, t);
  const head = `<header class="al-panel-head">
      <h3 class="al-panel-title" tabindex="-1">${esc(t('alerts_panel_title', { target: phrase }))}</h3>
      <button type="button" class="dsk-btn dsk-btn-sm" data-act="shut" title="${esc(t('alerts_panel_shut'))}">${esc(t('alerts_panel_shut'))}</button>
    </header>`;
  if (!b) {
    host.innerHTML = `<section class="al-panel" aria-label="${esc(phrase)}">${head}` +
      (Store.ALERTS.error
        ? `<div class="dsk-notice dsk-notice-bad">${esc(t('alerts_failed', { why: Store.ALERTS.error }))}</div>`
        : `<div class="dsk-notice">${esc(t('alerts_loading'))}</div>`) + '</section>';
    return;
  }
  const state = M.onOff(b.status, t);
  if (state.off) {
    S.form = null;
    host.innerHTML = `<section class="al-panel" aria-label="${esc(phrase)}">${head}${offHTML(state)}` +
      `<p class="al-quiet">${esc(t('alerts_panel_setup'))}</p></section>`;
    return;
  }
  const rules = M.rulesOn(b.doc.rules, S.target.kind, S.target.id);
  const noDest = !b.doc.destinations.length;
  const unmanaged = S.target.kind === 'place' && unmanagedPlace(S.target.id);
  const held = S.target.kind === 'place' && (unmanaged || heldPlace(S.target.id));
  const foot = held ? `<p class="al-warn al-note">${esc(t(unmanaged ? 'alerts_panel_unmanaged' : 'alerts_panel_held'))}</p>`
    : `<div class="al-panel-foot">
        <button type="button" class="dsk-btn dsk-btn-sm" data-act="add"${S.form || S.busy || noDest ? ' disabled' : ''}>${esc(t('alerts_add_rule'))}</button>
        ${noDest ? `<span class="al-quiet">${esc(t('alerts_panel_no_dest'))}</span>
          <button type="button" class="dsk-btn dsk-btn-sm" data-act="setup">${esc(t('alerts_panel_to_setup'))}</button>` : ''}
      </div>`;
  host.innerHTML = `<section class="al-panel" aria-label="${esc(phrase)}">${head}
      <div class="al-panel-msg" aria-live="polite">${noticeHTML(S.msg)}</div>
      ${rules.length ? `<ul class="al-list">${rules.map(ruleHTML).join('')}</ul>`
        : held ? '' : `<p class="al-empty">${esc(t('alerts_panel_none'))}</p>`}
      ${S.target.kind === 'place' && !held ? alsoHTML() : S.target.kind === 'service' ? alsoServiceHTML() : ''}
      <div class="al-slot"></div>
      ${foot}
    </section>`;
  if (S.form?.el) host.querySelector('.al-slot')?.append(S.form.el);
}

function ruleHTML(r) {
  const b = body();
  const on = M.ruleOn(r);
  const armed = S.armed === r.id;
  const editing = S.form?.id === r.id;
  const held = M.suspendedIds(b).has(String(r.id));
  return `<li class="al-row${on ? '' : ' al-paused'}${editing ? ' al-editing' : ''}" data-rule="${esc(r.id)}">
      <div class="al-row-head">
        <input type="checkbox" class="dsk-check" data-act="toggle" data-id="${esc(r.id)}"${on ? ' checked' : ''}${S.busy ? ' disabled' : ''}
          aria-label="${esc(`${t('alerts_rule_on')}: ${r.name || r.id}`)}" title="${esc(t('alerts_rule_on'))}">
        <span class="al-name">${esc(r.name || r.id)}</span>
        ${on ? '' : `<span class="al-tag">${esc(t('alerts_rule_paused'))}</span>`}
        <span class="al-acts">
          <button type="button" class="dsk-btn dsk-btn-sm" data-act="edit" data-id="${esc(r.id)}">${esc(t('alerts_edit'))}</button>
          <button type="button" class="dsk-btn dsk-btn-sm${armed ? ' dsk-btn-warn' : ''}" data-act="remove" data-id="${esc(r.id)}">${esc(armed ? t('alerts_remove_sure') : t('alerts_remove'))}</button>
        </span>
      </div>
      <p class="al-sentence">${esc(M.ruleSentence(r, { data: A.DATA, destinations: b.doc.destinations }, t))}</p>
      ${r.note ? `<p class="al-quiet al-note">${esc(r.note)}</p>` : ''}
      ${held ? `<p class="al-warn al-note">${esc(t('alerts_suspended'))}</p>` : ''}
    </li>`;
}

function alsoServiceHTML() {
  const rules = body().doc.rules;
  const doors = list(A.DATA?.collections)
    .filter((c) => c && typeof c.id === 'string' && list(c.services).includes(S.target.id))
    .map((c) => ({ kind: 'collection', id: c.id, n: M.rulesOn(rules, 'collection', c.id).length }))
    .filter((d) => d.n);
  if (!doors.length) return '';
  return `<div class="al-also"><p class="al-quiet">${esc(t('alerts_panel_also'))}</p><ul class="al-also-list">${doors.map((d) =>
    `<li><button type="button" class="dsk-btn dsk-btn-sm" data-act="go" data-kind="${d.kind}" data-id="${esc(d.id)}">` +
    `${esc(M.targetPhrase(d, A.DATA, t))} · ${esc(d.n === 1 ? t('alerts_panel_one') : t('alerts_panel_many', { n: d.n }))}</button></li>`).join('')}</ul></div>`;
}

function alsoHTML() {
  const row = placeRow(S.target.id);
  if (!row) return '';
  const cover = M.rulesCovering(body().doc.rules, row);
  const doors = [
    ...cover.collections.map((c) => ({ kind: 'collection', id: c.id, n: c.rules.length })),
    ...(cover.network.length ? [{ kind: 'network', id: row.zone, n: cover.network.length }] : []),
  ];
  if (!doors.length) return '';
  return `<div class="al-also"><p class="al-quiet">${esc(t('alerts_panel_also'))}</p><ul class="al-also-list">${doors.map((d) =>
    `<li><button type="button" class="dsk-btn dsk-btn-sm" data-act="go" data-kind="${d.kind}" data-id="${esc(d.id)}">` +
    `${esc(M.targetPhrase(d, A.DATA, t))} · ${esc(d.n === 1 ? t('alerts_panel_one') : t('alerts_panel_many', { n: d.n }))}</button></li>`).join('')}</ul></div>`;
}

function placeRow(id) {
  const node = list(A.DATA?.nodes).find((n) => n && n.id === id);
  if (!node) return null;
  const members = (v) => (typeof v === 'string' ? [v] : list(v));
  const collections = list(A.DATA?.collections)
    .filter((c) => c && typeof c.id === 'string' && members(c.places).includes(id)).map((c) => c.id);
  return { id, zone: typeof node.zone === 'string' ? node.zone : '', collections };
}


function ruleForm(was) {
  const b = body();
  const doc = b.doc;
  const name = input('text', was.name);
  name.maxLength = 80;
  const note = input('text', was.note || '', 'dsk-input al-wide');
  note.maxLength = 300;

  const states = document.createElement('div');
  states.className = 'al-states';
  const chosen = new Set(list(was.to));
  for (const s of b.states) {
    const box = check(chosen.has(s));
    box.value = s;
    const lab = document.createElement('label');
    lab.className = 'nv-toggle';
    lab.append(box, document.createTextNode(` ${M.stateLabel(s, t)}`));
    states.append(lab);
  }
  const statesField = document.createElement('fieldset');
  statesField.className = 'nv-field al-field al-fieldset';
  statesField.dataset.field = 'to';
  const legend = document.createElement('legend');
  legend.className = 'nv-label';
  legend.textContent = t('alerts_f_states');
  const statesProblem = document.createElement('span');
  statesProblem.className = 'al-problem';
  statesProblem.dataset.for = 'to';
  statesField.append(legend, states, statesProblem);

  const minutes = input('number', String(was.for_minutes ?? 0), 'dsk-input dsk-mono al-num');
  minutes.min = '0';
  minutes.max = '1440';
  minutes.step = '1';
  const dest = select([['', t('alerts_pick')], ...doc.destinations.map((d) => [d.id, d.name || d.id])], was.destination || '');
  const enabled = check(M.ruleOn(was));

  const sentence = document.createElement('p');
  sentence.className = 'al-sentence al-preview';
  sentence.setAttribute('aria-live', 'polite');
  const resolution = document.createElement('p');
  resolution.className = 'nv-form-note';
  resolution.textContent = M.pollRunning(b.status) ? t('alerts_resolution', { n: Number(b.status.poll_seconds) }) : t('alerts_resolution_off');

  const target = { ...S.target };
  const read = () => ({
    ...was,
    name: name.value.trim(),
    note: note.value.trim(),
    enabled: enabled.checked,
    target,
    to: [...states.querySelectorAll('input:checked')].map((x) => x.value),
    for_minutes: minutes.value === '' ? '' : Number(minutes.value),
    destination: dest.value,
  });
  const preview = () => { sentence.textContent = M.ruleSentence(read(), { data: A.DATA, destinations: doc.destinations }, t); };
  preview();

  const box = formBox('al-form-rule', [
    field('name', t('alerts_f_rule_name'), name),
    field('note', t('alerts_f_note'), note),
    statesField,
    field('for_minutes', t('alerts_f_minutes'), minutes),
    field('destination', t('alerts_f_dest'), dest),
    toggle('enabled', t('alerts_f_enabled'), enabled),
  ], t('alerts_save'), () => saveRule(was.id || '', read()), closeForm, [sentence, resolution], () => S.busy);
  box.addEventListener('input', preview);
  box.addEventListener('change', preview);
  return box;
}

function openForm(id) {
  S.armed = '';
  S.msg = null;
  const was = id ? body().doc.rules.find((r) => r.id === id)
    : { enabled: true, to: ['down'], for_minutes: 5, target: { ...S.target } };
  if (!was) return;
  S.form = { id, was: Store.clone(was), el: ruleForm(was) };
  draw();
  S.form.el.querySelector('input, select')?.focus();
}

function closeForm() {
  S.form = null;
  S.msg = null;
  draw();
  host.querySelector('[data-act="add"]')?.focus({ preventScroll: true });
}


async function busy(fn) {
  const key = focusKey(host);
  S.busy = true;
  for (const x of host.querySelectorAll('button, input[data-act]')) x.disabled = true;
  try { return await fn(); } finally {
    S.busy = false;
    for (const x of S.form?.el?.querySelectorAll('button') || []) x.disabled = false;
    settle(key);
  }
}

function settle(key) {
  draw();
  const bad = S.form?.el?.querySelector('.al-problem:not(:empty)')?.closest('label, fieldset')?.querySelector('input, select');
  if (key !== null && bad) { bad.focus(); return; }
  refocus(host, key, '[data-act="add"]', '.al-panel-title');
}

async function saveChange(change, where = {}) {
  return busy(async () => {
    tell(t('alerts_saving'));
    const r = await Store.save(change);
    if (r.unchanged) { S.msg = null; return true; }
    const m = answerNotice(r, where);
    if (r.status === 409 || r.status === 403) S.form = null;
    S.msg = { kind: m.kind, text: m.text, problems: m.problems || [] };
    return r.ok;
  });
}

async function saveRule(id, entry) {
  const form = S.form?.el;
  const checks = M.checkRule(entry, { destinations: body().doc.destinations }, t);
  if (checks.length) { showProblems(form, byFieldOf(checks)); tell(t('alerts_fix'), 'warn'); return; }
  const rules = body().doc.rules;
  const at = id ? rules.findIndex((r) => r.id === id) : rules.length;
  const newId = id || M.slugFor(entry.name, rules.map((r) => r.id), 'rule');
  const was = S.form?.was;
  const key = focusKey(host);
  const ok = await saveChange((doc) => {
    const rule = { ...entry, for_minutes: Number(entry.for_minutes) || 0 };
    const i = id ? doc.rules.findIndex((r) => r.id === id) : -1;
    if (id && (i < 0 || !sameEntry(doc.rules[i], was))) return Store.CONFLICT;
    if (i >= 0) doc.rules[i] = rule;
    else { rule.id = M.slugFor(entry.name, doc.rules.map((r) => r.id), 'rule'); doc.rules.push(rule); }
    return true;
  }, { form, prefix: `rules[${Math.max(at, 0)}]`, label: `rule ${newId}` });
  if (ok) S.form = null;
  settle(key);
}

async function toggleRule(id, on) {
  await saveChange((doc) => {
    const rule = doc.rules.find((r) => r.id === id);
    if (!rule) return false;
    rule.enabled = on;
    return true;
  });
}

async function removeRule(id) {
  if (S.armed !== id) {
    S.armed = id;
    draw();
    host.querySelector(`[data-act="remove"][data-id="${CSS.escape(id)}"]`)?.focus();
    return;
  }
  S.armed = '';
  await saveChange((doc) => { doc.rules = doc.rules.filter((r) => r.id !== id); });
}

function onClick(e) {
  const b = e.target.closest('[data-act]');
  if (!b || b.disabled || S.busy || b.dataset.act === 'toggle') return;
  const id = b.dataset.id;
  const act = b.dataset.act;
  if (act !== 'remove' && S.armed) S.armed = '';
  if (act === 'shut') close();
  else if (act === 'add') openForm('');
  else if (act === 'edit') openForm(id);
  else if (act === 'remove') removeRule(id);
  else if (act === 'go') openFor({ kind: b.dataset.kind, id });
  else if (act === 'setup') A.openSettings?.();
}

function onChange(e) {
  const box = e.target.closest('[data-act="toggle"]');
  if (box && !S.busy) toggleRule(box.dataset.id, box.checked);
}

Store.listen((changed) => {
  if ((changed || !body()) && S.target && !S.form && !S.busy) keepFocus(host, draw);
});
