/* ALERTS (2026-11-13, the views' stage 4) — rules and destinations, an admin's.

   A view under ATLAS (views.js shows `#view-alerts` in the map's place, and
   only to an admin; the routes refuse anyone else regardless). It is not an
   engine: a rule says, in one sentence, "when this place, set or network
   goes to this state and stays there this long, send to this destination",
   and the server reads the state changes the ANNALS already records, at the
   annals' own poll, and sends. This file draws four things into the view:

   - DESTINATIONS: where word goes (ntfy, Gotify, a JSON webhook), on a host
     the operator listed in ATLAS_ALERT_HOSTS. A destination NAMES its secret;
     the server reads ATLAS_ALERT_SECRET_<NAME> or its _FILE. No secret's value
     is ever asked for, shown or posted here. "Send a test" shows only the
     outcome word and the server's short why.
   - RULES: each one a sentence, with a switch, and a form that builds the
     sentence as you pick (the target from the map the browser already holds).
   - THE DAILY DIGEST: an hour, a destination and four conditions.
   - DELIVERIES: the log, newest first, in plain sentences.

   While alerts are off (no ATLAS_ALERTS, or no host listed) the view says how
   to turn them on and offers no form at all. The poll being off, or no public
   URL, is a note on the status strip, with the forms still there.

   Every save posts the WHOLE document with the stamp it was read under, with
   the Desk's write proof (WRITE_HEADERS): 409 reads it again and says so in
   a plain line, 422 lists the server's problems by the field. The page
   checks what it can first (alerts-model.js), so the common mistakes are
   said before anything is posted. A form survives the 60-second refresh:
   only the status strip and the log are redrawn under it.

   Every phrase is alerts-model.js's ALERTS_TEXT, through the theme. The look
   is views.css. */

import { A, $, esc, themeText, WRITE_HEADERS } from './config.js';
import * as M from './alerts-model.js';

const API = 'api/v2/admin/alerts';
const POLL_MS = 60000;

/** One phrase: the theme's, else the plain one, with `{name}` filled in. */
const t = (key, vars = {}) => M.fill(themeText(key, M.ALERTS_TEXT[key] || ''), vars);

const S = {
  body: null,          // {doc, stamp, status, states} as last read
  error: '',
  deliveries: null,    // the log, as last read
  delError: '',
  form: null,          // the open add/edit form: {kind: 'dest'|'rule', index, el}
  digestEl: null,      // the digest's form, built per document read
  digestDirty: false,
  msg: null,           // {kind: info|warn|bad, text, problems}
  busy: false,
  tests: {},           // destination id -> {text, tone} | {pending: true}
  armed: '',           // 'dest:<id>' or 'rule:<id>', one press from removal
};

let root = null;
let el = {};
let timer = 0;
let dataTimer = 0;

const shown = () => A.VIEW === 'alerts';
const clone = (v) => JSON.parse(JSON.stringify(v ?? null));
const list = (v) => (Array.isArray(v) ? v : []);
const clock = (ms) => new Date(ms).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
const stamp = (ms) => {
  const d = new Date(ms);
  return `${d.toLocaleDateString([], { month: 'short', day: 'numeric' })} ${clock(ms)}`;
};

/* ── the data ────────────────────────────────────────────────────────────── */

function normalise(body) {
  const b = body && typeof body === 'object' ? body : {};
  const doc = b.doc && typeof b.doc === 'object' ? b.doc : {};
  return {
    ...b,
    doc: {
      ...doc,
      rules: list(doc.rules).filter((r) => r && typeof r === 'object'),
      destinations: list(doc.destinations).filter((d) => d && typeof d === 'object'),
      digest: doc.digest && typeof doc.digest === 'object' ? doc.digest : {},
    },
    stamp: b.stamp ?? null,
    status: b.status && typeof b.status === 'object' ? b.status : {},
    states: M.stateList(b.states),
  };
}

async function getJSON(url) {
  const res = await fetch(url, { cache: 'no-store' });
  let body = null;
  try { body = await res.json(); } catch { /* an empty or non-JSON answer */ }
  if (!res.ok) throw new Error(body?.error || `${res.status} ${res.statusText}`);
  return body;
}

async function postJSON(url, payload) {
  const res = await fetch(url, { method: 'POST', headers: WRITE_HEADERS, body: JSON.stringify(payload ?? {}) });
  let body = null;
  try { body = await res.json(); } catch { /* an empty or non-JSON answer */ }
  return { ok: res.ok, status: res.status, body, why: body?.error || `${res.status} ${res.statusText}` };
}

/** Read the document and the status. `whole` takes the document even under
    an open form (after a save, or a 409); otherwise a form or an unsaved
    digest keeps the document it was opened on, and only the status moves. */
async function load({ whole = false } = {}) {
  let body = null;
  try { body = normalise(await getJSON(API)); S.error = ''; } catch (err) { S.error = err.message || String(err); }
  if (!body) return false;
  const editing = Boolean(S.form) || S.digestDirty;
  const changed = !S.body || body.stamp !== S.body.stamp || body.status.enabled !== S.body.status.enabled;
  if (!S.body || whole || !editing) {
    S.body = body;
    // a digest with unsaved edits keeps them through another save
    if ((changed || whole) && !S.digestDirty) S.digestEl = null;
  } else {
    S.body = { ...S.body, status: body.status };
  }
  return changed;
}

async function loadDeliveries() {
  try {
    const body = await getJSON(`${API}/deliveries?limit=50`);
    S.deliveries = M.newestFirst(Array.isArray(body) ? body : body?.deliveries);
    S.delError = '';
  } catch (err) { S.delError = err.message || String(err); }
}

/* ── the frame: built once ───────────────────────────────────────────────── */

function build() {
  root = $('view-alerts');
  if (!root || el.sheet) return Boolean(root);
  root.innerHTML = `
    <div class="al-sheet">
      <header class="al-head">
        <h2 class="al-title">${esc(themeText('view_alerts', 'ALERTS'))}</h2>
        <p class="al-sub">${esc(t('alerts_sub'))}</p>
      </header>
      <div class="al-strip" aria-live="polite"></div>
      <div class="al-msg" aria-live="polite"></div>
      <div class="al-main"></div>
    </div>`;
  el = {
    sheet: root.querySelector('.al-sheet'),
    strip: root.querySelector('.al-strip'),
    msg: root.querySelector('.al-msg'),
    main: root.querySelector('.al-main'),
  };
  el.main.addEventListener('click', onClick);
  el.main.addEventListener('change', onChange);
  return true;
}

/* ── messages ────────────────────────────────────────────────────────────── */

function tell(text, kind = 'info', problems = []) {
  S.msg = text ? { kind, text, problems } : null;
  drawMessage();
}

function drawMessage() {
  if (!el.msg) return;
  const m = S.msg;
  el.msg.innerHTML = !m ? '' : `<div class="dsk-notice dsk-notice-${m.kind}">${esc(m.text)}` +
    (m.problems?.length ? `<ul class="dsk-problems">${m.problems.map((p) => `<li>${esc(p)}</li>`).join('')}</ul>` : '') +
    '</div>';
}

/* ── drawing ─────────────────────────────────────────────────────────────── */

function drawStrip() {
  if (!el.strip) return;
  if (!S.body) { el.strip.innerHTML = ''; return; }
  const status = S.body.status;
  const state = M.onOff(status, t);
  const bits = M.statusBits(status, clock, t);
  el.strip.innerHTML = `
    <div class="al-status">
      <span class="al-onoff ${state.off ? 'al-is-off' : 'al-is-on'}">
        <span class="svc-health ${state.off ? '' : 'h-up'}" aria-hidden="true"></span>${esc(state.off ? t('alerts_off') : t('alerts_on'))}</span>
      ${bits.map((b, i) => `<span class="al-bit${i === 0 && list(status.hosts).length ? ' al-mono' : ''}">${esc(b)}</span>`).join('')}
    </div>
    ${state.notes.length && !state.off ? `<ul class="al-notes">${state.notes.map((n) => `<li>${esc(n)}</li>`).join('')}</ul>` : ''}`;
}

function draw() {
  if (!el.sheet) return;
  drawStrip();
  drawMessage();
  if (!S.body) {
    el.main.innerHTML = S.error
      ? `<div class="dsk-notice dsk-notice-bad">${esc(t('alerts_failed', { why: S.error }))}</div>`
      : `<div class="dsk-notice">${esc(t('alerts_loading'))}</div>`;
    return;
  }
  const state = M.onOff(S.body.status, t);
  if (state.off) {
    S.form = null;
    el.main.innerHTML = `
      <div class="al-off">
        <p class="al-off-title">${esc(state.title)}</p>
        ${state.lines.map((l) => `<p class="al-off-line">${esc(l)}</p>`).join('')}
        ${state.notes.length ? `<ul class="al-off-notes">${state.notes.map((n) => `<li>${esc(n)}</li>`).join('')}</ul>` : ''}
      </div>`;
    return;
  }
  const stale = S.error ? `<div class="dsk-notice dsk-notice-warn">${esc(t('alerts_failed', { why: S.error }))}</div>` : '';
  el.main.innerHTML = `${stale}
    ${section('destinations', 'alerts_t_destinations', 'add-dest', 'alerts_add_destination', destinationsHTML())}
    ${section('rules', 'alerts_t_rules', 'add-rule', 'alerts_add_rule', rulesHTML())}
    ${section('digest', 'alerts_t_digest', '', '', '')}
    ${section('deliveries', 'alerts_t_deliveries', '', '', '<div class="al-log-slot"></div>')}`;
  // the open form and the digest are elements kept across redraws, so nothing
  // typed into them is lost: put them back into their seats
  if (S.form?.el) el.main.querySelector(`[data-sec="${S.form.kind === 'dest' ? 'destinations' : 'rules'}"] .al-slot`)?.append(S.form.el);
  if (!S.digestEl) S.digestEl = digestForm();
  el.main.querySelector('[data-sec="digest"] .al-slot')?.append(S.digestEl);
  for (const b of el.main.querySelectorAll('[data-act="add-dest"], [data-act="add-rule"]')) {
    b.disabled = S.busy || Boolean(S.form);
  }
  drawDeliveries();
}

function section(key, titleKey, act, actKey, inner) {
  return `<section class="al-sec" data-sec="${key}" aria-label="${esc(t(titleKey))}">
      <header class="al-sec-head"><h3 class="al-sec-title">${esc(t(titleKey))}</h3>
        ${act ? `<button type="button" class="dsk-btn dsk-btn-sm" data-act="${act}">${esc(t(actKey))}</button>` : ''}</header>
      ${inner}
      <div class="al-slot"></div>
    </section>`;
}

function rowActs(kind, id) {
  const armed = S.armed === `${kind}:${id}`;
  return `<span class="al-acts">
      ${kind === 'dest' ? `<button type="button" class="dsk-btn dsk-btn-sm" data-act="test" data-id="${esc(id)}"${S.tests[id]?.pending ? ' disabled' : ''}>${esc(S.tests[id]?.pending ? t('alerts_testing') : t('alerts_test'))}</button>` : ''}
      <button type="button" class="dsk-btn dsk-btn-sm" data-act="edit-${kind}" data-id="${esc(id)}">${esc(t('alerts_edit'))}</button>
      <button type="button" class="dsk-btn dsk-btn-sm${armed ? ' dsk-btn-warn' : ''}" data-act="remove-${kind}" data-id="${esc(id)}">${esc(armed ? t('alerts_remove_sure') : t('alerts_remove'))}</button>
    </span>`;
}

function secretPhrase(d) {
  const name = M.secretName(d.secret);
  if (!name) return t('alerts_secret_none');
  return d.secret_bound === false ? t('alerts_secret_unbound', { name }) : t('alerts_secret_bound', { name });
}

function destinationsHTML() {
  const dests = S.body.doc.destinations;
  if (!dests.length) return `<p class="al-empty">${esc(t('alerts_dest_none'))}</p>`;
  return `<ul class="al-list">${dests.map((d, i) => {
    const test = S.tests[d.id];
    const editing = S.form?.kind === 'dest' && S.form.index === i;
    return `<li class="al-row${editing ? ' al-editing' : ''}" data-dest="${esc(d.id)}">
        <div class="al-row-head">
          <span class="al-name">${esc(d.name || d.id)}</span>
          <span class="al-kind">${esc(M.ALERTS_TEXT[`alerts_kind_${d.kind}`] ? t(`alerts_kind_${d.kind}`) : d.kind || '')}</span>
          ${rowActs('dest', d.id)}
        </div>
        <span class="al-mono al-url">${esc(M.shownAddress(d.url))}</span>
        <span class="al-quiet${d.secret && d.secret_bound === false ? ' al-warn' : ''}">${esc(secretPhrase(d))}</span>
        ${test && !test.pending ? `<span class="al-test al-tone-${test.tone}" role="status">${esc(test.text)}</span>` : ''}
      </li>`;
  }).join('')}</ul>`;
}

function rulesHTML() {
  const rules = S.body.doc.rules;
  if (!rules.length) return `<p class="al-empty">${esc(t('alerts_rules_none'))}</p>`;
  const ctx = { data: A.DATA, destinations: S.body.doc.destinations };
  const held = M.suspendedIds(S.body);
  return `<ul class="al-list">${rules.map((r, i) => {
    const editing = S.form?.kind === 'rule' && S.form.index === i;
    const on = r.enabled !== false;
    return `<li class="al-row${on ? '' : ' al-paused'}${editing ? ' al-editing' : ''}" data-rule="${esc(r.id)}">
        <div class="al-row-head">
          <input type="checkbox" class="dsk-check" data-act="toggle" data-id="${esc(r.id)}"${on ? ' checked' : ''}${S.busy ? ' disabled' : ''}
            aria-label="${esc(`${t('alerts_rule_on')}: ${r.name || r.id}`)}" title="${esc(t('alerts_rule_on'))}">
          <span class="al-name">${esc(r.name || r.id)}</span>
          ${on ? '' : `<span class="al-tag">${esc(t('alerts_rule_paused'))}</span>`}
          ${rowActs('rule', r.id)}
        </div>
        <p class="al-sentence">${esc(M.ruleSentence(r, ctx, t))}</p>
        ${r.note ? `<p class="al-quiet al-note">${esc(r.note)}</p>` : ''}
        ${held.has(String(r.id)) ? `<p class="al-warn al-note">${esc(t('alerts_suspended'))}</p>` : ''}
      </li>`;
  }).join('')}</ul>`;
}

function drawDeliveries() {
  const slot = el.main?.querySelector('.al-log-slot');
  if (!slot) return;
  if (!S.deliveries) {
    slot.innerHTML = S.delError
      ? `<p class="al-empty">${esc(t('alerts_deliveries_failed', { why: S.delError }))}</p>`
      : `<p class="al-empty">${esc(t('alerts_loading'))}</p>`;
    return;
  }
  const ctx = { rules: S.body?.doc.rules, destinations: S.body?.doc.destinations };
  const warn = S.delError ? `<p class="al-empty">${esc(t('alerts_deliveries_failed', { why: S.delError }))}</p>` : '';
  if (!S.deliveries.length) { slot.innerHTML = `${warn}<p class="al-empty">${esc(t('alerts_deliveries_none'))}</p>`; return; }
  const DOT = { up: 'h-up', warn: 'h-degraded', down: 'h-down' };
  slot.innerHTML = `${warn}<ul class="al-log">${S.deliveries.map((row) => {
    const at = M.toMs(row.at);
    return `<li class="al-log-row">
        <span class="al-mono al-when"${row.at ? ` title="${esc(String(row.at))}"` : ''}>${esc(at === null ? '' : stamp(at))}</span>
        <span class="al-log-line"><span class="svc-health ${DOT[M.outcomeTone(row.outcome)]}" aria-hidden="true"></span>${esc(M.deliveryLine(row, ctx, t))}</span>
      </li>`;
  }).join('')}</ul>`;
}

/* ── the forms ───────────────────────────────────────────────────────────── */

function button(cls, label, onClick, type = 'button') {
  const b = document.createElement('button');
  b.type = type;
  b.className = cls;
  b.textContent = label;
  if (onClick) b.addEventListener('click', onClick);
  return b;
}

/** A labelled field with a seat for its problems (`data-for`). */
function field(name, labelText, control, hint = '') {
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

function input(type, value = '', cls = 'dsk-input') {
  const i = document.createElement('input');
  i.type = type;
  i.className = cls;
  i.value = value ?? '';
  return i;
}

function select(options, value = '') {
  const s = document.createElement('select');
  s.className = 'dsk-input';
  s.innerHTML = options.map(([v, label]) => `<option value="${esc(v)}">${esc(label)}</option>`).join('');
  s.value = value ?? '';
  return s;
}

function check(checked, cls = 'dsk-check') {
  const c = document.createElement('input');
  c.type = 'checkbox';
  c.className = cls;
  c.checked = Boolean(checked);
  return c;
}

/** A box beside its words, the filter bar's toggle. */
function toggle(name, labelText, box) {
  const label = document.createElement('label');
  label.className = 'nv-toggle al-toggle';
  label.dataset.field = name;
  label.append(box, document.createTextNode(` ${labelText}`));
  return label;
}

/** Put problems beside their fields; what has no field goes in the general line. */
function showProblems(form, byField, general = []) {
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

const byFieldOf = (checks) => checks.reduce((acc, c) => { (acc[c.field] = acc[c.field] || []).push(c.text); return acc; }, {});

function formBox(cls, fields, goLabel, onGo, onCancel, extra = []) {
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
  box.addEventListener('submit', (e) => { e.preventDefault(); if (!S.busy) onGo(); });
  if (onCancel) box.addEventListener('keydown', (e) => { if (e.key === 'Escape') { e.stopPropagation(); onCancel(); } });
  return box;
}

const PLACEHOLDER = { ntfy: 'https://ntfy.example/lab-alerts', gotify: 'https://gotify.example', webhook: 'https://hooks.example/atlas' };

function destinationForm(index) {
  const doc = S.body.doc;
  const was = index >= 0 ? doc.destinations[index] : {};
  const name = input('text', was.name);
  name.maxLength = 60;
  const kind = select(M.KINDS.map((k) => [k, t(`alerts_kind_${k}`)]), was.kind || 'ntfy');
  const url = input('url', was.url, 'dsk-input dsk-mono al-wide');
  url.placeholder = PLACEHOLDER[kind.value] || '';
  url.spellcheck = false;
  kind.addEventListener('change', () => { url.placeholder = PLACEHOLDER[kind.value] || ''; });
  const secret = input('text', was.secret || '', 'dsk-input dsk-mono');
  secret.placeholder = 'NTFY_LAB';
  secret.maxLength = 40;
  secret.spellcheck = false;
  secret.autocomplete = 'off';
  // the server binds a secret only when the admin names it; after the
  // address moved, naming the same one again is this box (`bind: true`)
  const unbound = index >= 0 && M.secretName(was.secret) && was.secret_bound === false;
  const bind = check(false);
  const bindField = unbound ? [toggle('bind', t('alerts_f_bind', { name: M.secretName(was.secret) }), bind)] : [];
  const hosts = list(S.body.status.hosts);
  const note = document.createElement('p');
  note.className = 'nv-form-note';
  note.textContent = hosts.length ? t('alerts_hosts_hint', { hosts: hosts.join(', ') }) : '';
  return formBox('al-form-dest', [
    field('name', t('alerts_f_name'), name),
    field('kind', t('alerts_f_kind'), kind),
    field('url', t('alerts_f_url'), url),
    field('secret', t('alerts_f_secret'), secret, t('alerts_secret_hint')),
    ...bindField,
  ], t('alerts_save'), () => saveDestination(index, {
    name: name.value.trim(), kind: kind.value, url: url.value.trim(), secret: M.secretName(secret.value),
    ...(unbound && bind.checked ? { bind: true } : {}),
  }), closeForm, [note]);
}

function ruleForm(index) {
  const doc = S.body.doc;
  const was = index >= 0 ? doc.rules[index] : { enabled: true, to: ['down'], for_minutes: 5, target: { kind: 'place' } };
  const name = input('text', was.name);
  name.maxLength = 80;
  const note = input('text', was.note || '', 'dsk-input al-wide');
  note.maxLength = 300;
  const kind = select(M.TARGETS.map((k) => [k, t(`alerts_kind_${k}`)]), was.target?.kind || 'place');
  const target = document.createElement('select');
  target.className = 'dsk-input al-target';
  const fillTargets = (keep) => {
    const opts = M.targetOptions(A.DATA, kind.value);
    // a rule on something the map no longer shows keeps its id, said plainly
    if (keep && !opts.some(([v]) => v === keep)) opts.unshift([keep, M.targetPhrase({ kind: kind.value, id: keep }, A.DATA, t)]);
    target.innerHTML = `<option value="">${esc(t('alerts_pick'))}</option>` +
      opts.map(([v, label]) => `<option value="${esc(v)}">${esc(label)}</option>`).join('');
    target.value = keep || '';
  };
  fillTargets(was.target?.kind === kind.value ? was.target?.id : '');
  kind.addEventListener('change', () => { fillTargets(''); preview(); });

  const states = document.createElement('div');
  states.className = 'al-states';
  const chosen = new Set(list(was.to));
  for (const s of S.body.states) {
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
  const enabled = check(was.enabled !== false);

  const sentence = document.createElement('p');
  sentence.className = 'al-sentence al-preview';
  sentence.setAttribute('aria-live', 'polite');
  const poll = Number(S.body.status.poll_seconds);
  const resolution = document.createElement('p');
  resolution.className = 'nv-form-note';
  resolution.textContent = M.pollRunning(S.body.status) ? t('alerts_resolution', { n: poll }) : t('alerts_resolution_off');

  const read = () => ({
    ...was,
    name: name.value.trim(),
    note: note.value.trim(),
    enabled: enabled.checked,
    target: { kind: kind.value, id: target.value },
    to: [...states.querySelectorAll('input:checked')].map((b) => b.value),
    for_minutes: minutes.value === '' ? '' : Number(minutes.value),
    destination: dest.value,
  });
  const preview = () => {
    sentence.textContent = M.ruleSentence(read(), { data: A.DATA, destinations: doc.destinations }, t);
  };
  preview();

  const box = formBox('al-form-rule', [
    field('name', t('alerts_f_rule_name'), name),
    field('note', t('alerts_f_note'), note),
    field('kind', t('alerts_f_watch'), kind),
    field('target', t('alerts_f_target'), target),
    statesField,
    field('for_minutes', t('alerts_f_minutes'), minutes),
    field('destination', t('alerts_f_dest'), dest),
    toggle('enabled', t('alerts_f_enabled'), enabled),
  ], t('alerts_save'), () => saveRule(index, read()), closeForm, [sentence, resolution]);
  box.addEventListener('input', preview);
  box.addEventListener('change', preview);
  return box;
}

function digestForm() {
  const doc = S.body.doc;
  const g = { hour: 8, cert_days: 30, review_days: 90, drift: true, uncharted: false, ...doc.digest };
  const enabled = check(g.enabled);
  const hour = select(Array.from({ length: 24 }, (_, h) => [String(h), `${String(h).padStart(2, '0')}:00`]), String(Number(g.hour) || 0));
  const dest = select([['', t('alerts_pick')], ...doc.destinations.map((d) => [d.id, d.name || d.id])], g.destination || '');
  const cert = input('number', String(g.cert_days ?? 30), 'dsk-input dsk-mono al-num');
  const review = input('number', String(g.review_days ?? 90), 'dsk-input dsk-mono al-num');
  cert.min = '1'; cert.max = '365'; cert.step = '1';
  review.min = '1'; review.max = '3650'; review.step = '1';
  const drift = check(g.drift);
  const support = M.unchartedSupport(S.body, t);
  const uncharted = check(support.ok && g.uncharted);
  uncharted.disabled = !support.ok;
  const unchartedLabel = toggle('uncharted', t('alerts_f_uncharted'), uncharted);
  if (!support.ok) {
    const why = document.createElement('span');
    why.className = 'al-hint';
    why.textContent = ` (${support.why})`;
    unchartedLabel.append(why);
    unchartedLabel.classList.add('al-off-choice');
  }
  const sentence = document.createElement('p');
  sentence.className = 'al-sentence al-preview';
  sentence.setAttribute('aria-live', 'polite');
  const read = () => ({
    ...doc.digest,
    enabled: enabled.checked,
    hour: Number(hour.value),
    destination: dest.value,
    cert_days: cert.value === '' ? '' : Number(cert.value),
    review_days: review.value === '' ? '' : Number(review.value),
    drift: drift.checked,
    // what the server cannot do yet is posted as it was read, never switched on here
    uncharted: support.ok ? uncharted.checked : Boolean(doc.digest.uncharted),
  });
  const preview = () => { sentence.textContent = M.digestSentence(read(), { destinations: doc.destinations }, t); };
  preview();
  const box = formBox('al-form-digest', [
    toggle('enabled', t('alerts_f_digest_on'), enabled),
    field('hour', t('alerts_f_hour'), hour),
    field('destination', t('alerts_f_dest'), dest),
    field('cert_days', t('alerts_f_cert_days'), cert),
    field('review_days', t('alerts_f_review_days'), review),
    toggle('drift', t('alerts_f_drift'), drift),
    unchartedLabel,
  ], t('alerts_save'), () => saveDigest(read()), null, [sentence]);
  box.addEventListener('input', () => { S.digestDirty = true; preview(); });
  box.addEventListener('change', () => { S.digestDirty = true; preview(); });
  return box;
}

function openForm(kind, index) {
  S.armed = '';
  S.msg = null;
  S.form = { kind, index, el: kind === 'dest' ? destinationForm(index) : ruleForm(index) };
  draw();
  S.form.el.querySelector('input, select')?.focus();
}

function closeForm() {
  const kind = S.form?.kind;
  S.form = null;
  S.msg = null;
  draw();
  el.main.querySelector(`[data-act="add-${kind === 'dest' ? 'dest' : 'rule'}"]`)?.focus({ preventScroll: true });
}

/* ── saving ──────────────────────────────────────────────────────────────── */

/** What the server computes is not posted back: a destination's binding. */
function outgoing(doc) {
  const out = clone(doc);
  out.destinations = list(out.destinations).map(({ secret_bound: _bound, ...d }) => d);
  return out;
}

async function busy(fn) {
  S.busy = true;
  for (const b of el.main.querySelectorAll('button, input[data-act]')) b.disabled = true;
  try { return await fn(); } finally {
    S.busy = false;
    for (const b of el.main.querySelectorAll('button, input[data-act]')) b.disabled = false;
    for (const b of el.main.querySelectorAll('[data-act="add-dest"], [data-act="add-rule"]')) b.disabled = Boolean(S.form);
  }
}

/** Post the whole document under the stamp it was read with. `form` and
    `prefix` say where a 422's problems belong. True when it saved. */
async function saveDoc(doc, { form = null, prefix = '', label = '' } = {}) {
  return busy(async () => {
    tell(t('alerts_saving'));
    const r = await postJSON(API, { doc: outgoing(doc), expect: S.body.stamp });
    if (r.ok) {
      if (r.body?.stamp) S.body.stamp = r.body.stamp;
      await load({ whole: true });
      const notes = list(r.body?.notes).map(String);
      tell(t('alerts_saved'), notes.length ? 'warn' : 'info', notes);
      return true;
    }
    if (r.status === 409) {
      S.form = null;
      await load({ whole: true });
      draw();
      tell(t('alerts_stale'), 'warn');
      return false;
    }
    if (r.status === 422) {
      const { byField, general, mine } = M.sortProblems(r.body?.problems || [r.why], prefix, label);
      if (form) showProblems(form, byField, mine);
      const all = [...general, ...mine, ...Object.values(byField).flat()];
      const listed = form ? general : all;
      tell(t(listed.length ? 'alerts_fix' : 'alerts_fix_form'), 'bad', listed);
      return false;
    }
    if (r.status === 403) { S.form = null; await load({ whole: true }); draw(); }
    tell(t('alerts_refused', { why: r.why }), 'bad');
    return false;
  });
}

async function saveDestination(index, entry) {
  const form = S.form?.el;
  const checks = M.checkDestination(entry, { hosts: S.body.status.hosts }, t);
  if (checks.length) { showProblems(form, byFieldOf(checks)); tell(t('alerts_fix'), 'warn'); return; }
  const doc = clone(S.body.doc);
  let i = index;
  if (index >= 0) doc.destinations[index] = { ...doc.destinations[index], ...entry };
  else {
    const id = M.slugFor(entry.name, doc.destinations.map((d) => d.id), 'destination');
    i = doc.destinations.push({ id, ...entry }) - 1;
  }
  if (await saveDoc(doc, { form, prefix: `destinations[${i}]`, label: `destination ${doc.destinations[i].id}` })) { S.form = null; draw(); }
}

async function saveRule(index, entry) {
  const form = S.form?.el;
  const checks = M.checkRule(entry, { destinations: S.body.doc.destinations }, t);
  if (checks.length) { showProblems(form, byFieldOf(checks)); tell(t('alerts_fix'), 'warn'); return; }
  const doc = clone(S.body.doc);
  const rule = { ...entry, for_minutes: Number(entry.for_minutes) || 0 };
  let i = index;
  if (index >= 0) doc.rules[index] = rule;
  else {
    rule.id = M.slugFor(entry.name, doc.rules.map((r) => r.id), 'rule');
    i = doc.rules.push(rule) - 1;
  }
  if (await saveDoc(doc, { form, prefix: `rules[${i}]`, label: `rule ${doc.rules[i].id}` })) { S.form = null; draw(); }
}

async function saveDigest(digest) {
  const form = S.digestEl;
  const checks = M.checkDigest(digest, { destinations: S.body.doc.destinations }, t);
  if (checks.length) { showProblems(form, byFieldOf(checks)); tell(t('alerts_fix'), 'warn'); return; }
  const doc = clone(S.body.doc);
  doc.digest = { ...digest, destination: digest.destination || null };
  if (await saveDoc(doc, { form, prefix: 'digest', label: 'digest' })) { S.digestDirty = false; S.digestEl = null; draw(); }
}

async function toggleRule(id, on) {
  const doc = clone(S.body.doc);
  const rule = doc.rules.find((r) => r.id === id);
  if (!rule) return;
  rule.enabled = on;
  await saveDoc(doc);
  draw();
}

async function remove(kind, id) {
  if (S.armed !== `${kind}:${id}`) { S.armed = `${kind}:${id}`; draw(); return; }
  S.armed = '';
  const doc = clone(S.body.doc);
  if (kind === 'dest') {
    const users = doc.rules.filter((r) => r.destination === id).map((r) => r.name || r.id);
    if (doc.digest?.enabled && doc.digest.destination === id) users.push(t('alerts_t_digest'));
    if (users.length) { draw(); tell(t('alerts_in_use', { names: users.join(', ') }), 'warn'); return; }
    doc.destinations = doc.destinations.filter((d) => d.id !== id);
    if (doc.digest?.destination === id) doc.digest.destination = null;
  } else {
    doc.rules = doc.rules.filter((r) => r.id !== id);
  }
  await saveDoc(doc);
  draw();
}

/** "Send a test": the same path a rule's message takes, a fixed message. Only
    the outcome word and the short why are shown. */
async function sendTest(id) {
  S.tests[id] = { pending: true };
  draw();
  const r = await postJSON(`${API}/destinations/${encodeURIComponent(id)}/test`, {});
  S.tests[id] = r.ok && r.body?.outcome
    ? { text: M.testLine(r.body, t), tone: M.outcomeTone(r.body.outcome) }
    : { text: r.why, tone: 'down' };
  draw();
  await loadDeliveries();
  drawDeliveries();
}

function onClick(e) {
  const b = e.target.closest('[data-act]');
  if (!b || b.disabled || S.busy) return;
  const id = b.dataset.id;
  const act = b.dataset.act;
  if (act !== 'remove-dest' && act !== 'remove-rule' && S.armed) { S.armed = ''; }
  if (act === 'add-dest') openForm('dest', -1);
  else if (act === 'add-rule') openForm('rule', -1);
  else if (act === 'edit-dest') openForm('dest', S.body.doc.destinations.findIndex((d) => d.id === id));
  else if (act === 'edit-rule') openForm('rule', S.body.doc.rules.findIndex((r) => r.id === id));
  else if (act === 'remove-dest') remove('dest', id);
  else if (act === 'remove-rule') remove('rule', id);
  else if (act === 'test') sendTest(id);
}

function onChange(e) {
  const box = e.target.closest('[data-act="toggle"]');
  if (box && !S.busy) toggleRule(box.dataset.id, box.checked);
}

/* ── showing ─────────────────────────────────────────────────────────────── */

async function tick() {
  if (!shown()) { stop(); return; }
  if (document.hidden) return;   // a tab nobody is looking at reads nothing
  const changed = await load();
  await loadDeliveries();
  if (!shown()) return;
  // under a form only the strip and the log move; otherwise everything
  if (changed && !S.form && !S.digestDirty) draw();
  else { drawStrip(); drawDeliveries(); }
}

function stop() {
  clearInterval(timer);
  clearTimeout(dataTimer);
  timer = 0;
}

/** The view came up: draw what is known, then read it fresh, and every
    minute after while it stays up. */
async function show() {
  if (!A.MAY_ALERTS || !build()) return;
  draw();
  clearInterval(timer);
  timer = setInterval(tick, POLL_MS);
  await Promise.all([load(), loadDeliveries()]);
  if (!shown()) return;
  draw();
  // the targets' names come from the map, which may not be read yet on a page
  // that opens here: draw again once it is
  const waitForMap = (n = 0) => {
    clearTimeout(dataTimer);
    if (A.DATA || n > 40) { if (A.DATA && shown() && !S.form) draw(); return; }
    dataTimer = setTimeout(() => waitForMap(n + 1), 500);
  };
  if (!A.DATA) waitForMap();
}

addEventListener('atlas:view', (e) => {
  if (e.detail?.view === 'alerts') show();
  else if (e.detail?.prev === 'alerts') stop();
});
document.addEventListener('visibilitychange', () => { if (!document.hidden && shown() && timer) tick(); });
// the first view is chosen at import, before this file listens (views.js)
if (A.VIEW === 'alerts' || document.body.dataset.view === 'alerts') show();
