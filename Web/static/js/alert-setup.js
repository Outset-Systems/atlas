
import { A, $, esc } from './config.js';
import * as M from './alerts-model.js';
import * as Store from './alert-store.js';
import {
  t, tOr, list, clock, stamp, field, input, select, check, toggle, showProblems, byFieldOf, formBox,
  noticeHTML, offHTML, answerNotice, keepFocus, focusKey, refocus, sameEntry,
} from './alert-forms.js';

const POLL_MS = 60000;

const S = {
  deliveries: null,
  delError: '',
  form: null,
  digestEl: null,
  digestDirty: false,
  digestWas: null,
  msg: null,
  busy: false,
  tests: {},
  armed: '',
  armedRule: '',
};

let sec = null;
let el = {};
let timer = 0;
let open = false;

const body = () => Store.ALERTS.body;
const unfolded = () => Boolean(sec && !sec.hidden && !sec.classList.contains('closed'));


function frame() {
  sec = $('sp-alerts');
  if (!sec) return false;
  sec.hidden = !A.MAY_ALERTS;
  if (sec.hidden) return false;
  if (el.main && sec.contains(el.main)) return true;
  sec.innerHTML = `
    <button class="sp-sub" type="button">${esc(t('alerts_setup_title'))} <span class="sp-sub-plain">· ${esc(t('alerts_setup_sub'))}</span></button>
    <div class="sp-sec-body al-setup">
      <p class="acct-note">${esc(t('alerts_setup_note'))}</p>
      <div class="al-strip" aria-live="polite"></div>
      <div class="al-msg" aria-live="polite"></div>
      <div class="al-main"></div>
    </div>`;
  el = {
    strip: sec.querySelector('.al-strip'),
    msg: sec.querySelector('.al-msg'),
    main: sec.querySelector('.al-main'),
  };
  el.main.addEventListener('click', onClick);
  A.applySettingsFolds?.();
  return true;
}


function tell(text, kind = 'info', problems = []) {
  S.msg = text ? { kind, text, problems } : null;
  if (el.msg) el.msg.innerHTML = noticeHTML(S.msg);
}

function drawStrip() {
  if (!el.strip) return;
  const b = body();
  if (!b) { el.strip.innerHTML = ''; return; }
  const state = M.onOff(b.status, t);
  const bits = M.statusBits(b.status, clock, t);
  el.strip.innerHTML = `
    <div class="al-status">
      <span class="al-onoff ${state.off ? 'al-is-off' : 'al-is-on'}">
        <span class="svc-health ${state.off ? '' : 'h-up'}" aria-hidden="true"></span>${esc(state.off ? t('alerts_off') : t('alerts_on'))}</span>
      ${bits.map((x, i) => `<span class="al-bit${i === 0 && list(b.status.hosts).length ? ' al-mono' : ''}">${esc(x)}</span>`).join('')}
    </div>
    ${state.notes.length && !state.off ? `<ul class="al-notes">${state.notes.map((n) => `<li>${esc(n)}</li>`).join('')}</ul>` : ''}`;
}

function draw() {
  if (!el.main) return;
  drawStrip();
  if (el.msg) el.msg.innerHTML = noticeHTML(S.msg);
  const b = body();
  if (!b) {
    el.main.innerHTML = Store.ALERTS.error
      ? `<div class="dsk-notice dsk-notice-bad">${esc(t('alerts_failed', { why: Store.ALERTS.error }))}</div>`
      : `<div class="dsk-notice">${esc(t('alerts_loading'))}</div>`;
    return;
  }
  const state = M.onOff(b.status, t);
  if (state.off) { S.form = null; el.main.innerHTML = offHTML(state); return; }
  const stale = Store.ALERTS.error ? `<div class="dsk-notice dsk-notice-warn">${esc(t('alerts_failed', { why: Store.ALERTS.error }))}</div>` : '';
  el.main.innerHTML = `${stale}
    ${section('destinations', 'alerts_t_destinations', 'add-dest', 'alerts_add_destination', destinationsHTML())}
    ${orphansHTML()}
    ${section('digest', 'alerts_t_digest', '', '', '')}
    ${section('deliveries', 'alerts_t_deliveries', '', '', '<div class="al-log-slot"></div>')}`;
  if (S.form?.el) el.main.querySelector('[data-sec="destinations"] .al-slot')?.append(S.form.el);
  if (!S.digestEl) S.digestEl = digestForm();
  el.main.querySelector('[data-sec="digest"] .al-slot')?.append(S.digestEl);
  for (const x of el.main.querySelectorAll('[data-act="add-dest"]')) x.disabled = S.busy || Boolean(S.form);
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

function secretPhrase(d) {
  const name = M.secretName(d.secret);
  if (!name) return t('alerts_secret_none');
  return d.secret_bound === false ? t('alerts_secret_unbound', { name }) : t('alerts_secret_bound', { name });
}

function destinationsHTML() {
  const dests = body().doc.destinations;
  if (!dests.length) return `<p class="al-empty">${esc(t('alerts_dest_none'))}</p>`;
  return `<ul class="al-list">${dests.map((d) => {
    const test = S.tests[d.id];
    const editing = S.form?.id === d.id;
    const armed = S.armed === d.id;
    return `<li class="al-row${editing ? ' al-editing' : ''}" data-dest="${esc(d.id)}">
        <div class="al-row-head">
          <span class="al-name">${esc(d.name || d.id)}</span>
          <span class="al-kind">${esc(kindWord(d.kind))}</span>
          <span class="al-acts">
            <button type="button" class="dsk-btn dsk-btn-sm" data-act="test" data-id="${esc(d.id)}"${test?.pending ? ' disabled' : ''}>${esc(test?.pending ? t('alerts_testing') : t('alerts_test'))}</button>
            <button type="button" class="dsk-btn dsk-btn-sm" data-act="edit" data-id="${esc(d.id)}">${esc(t('alerts_edit'))}</button>
            <button type="button" class="dsk-btn dsk-btn-sm${armed ? ' dsk-btn-warn' : ''}" data-act="remove" data-id="${esc(d.id)}">${esc(armed ? t('alerts_remove_sure') : t('alerts_remove'))}</button>
          </span>
        </div>
        <span class="al-mono al-url">${esc(M.shownAddress(d.url))}</span>
        <span class="al-quiet${d.secret && d.secret_bound === false ? ' al-warn' : ''}">${esc(secretPhrase(d))}</span>
        ${test && !test.pending ? `<span class="al-test al-tone-${test.tone}" role="status">${esc(test.text)}</span>` : ''}
      </li>`;
  }).join('')}</ul>`;
}

function orphansHTML() {
  const lost = M.unreachableRules(body().doc.rules, A.DATA);
  if (!lost || !lost.length) return '';
  const ctx = { data: A.DATA, destinations: body().doc.destinations };
  const inner = `<p class="al-quiet">${esc(t('alerts_orphans_note'))}</p><ul class="al-list">${lost.map((r) => {
    const id = typeof r.id === 'string' ? r.id : '';
    const armed = id && S.armedRule === id;
    return `<li class="al-row${M.ruleOn(r) ? '' : ' al-paused'}">
        <div class="al-row-head">
          <span class="al-name">${esc(r.name || r.id || '')}</span>
          ${id ? `<span class="al-acts"><button type="button" class="dsk-btn dsk-btn-sm${armed ? ' dsk-btn-warn' : ''}" data-act="remove-rule" data-id="${esc(id)}">${esc(armed ? t('alerts_remove_sure') : t('alerts_remove'))}</button></span>` : ''}
        </div>
        <p class="al-sentence">${esc(M.ruleSentence(r, ctx, t))}</p>
      </li>`;
  }).join('')}</ul>`;
  return section('orphans', 'alerts_t_orphans', '', '', inner);
}

async function removeOrphan(id) {
  if (S.armedRule !== id) {
    S.armedRule = id;
    draw();
    el.main.querySelector(`[data-act="remove-rule"][data-id="${CSS.escape(id)}"]`)?.focus();
    return;
  }
  S.armedRule = '';
  await saveChange((doc) => { doc.rules = doc.rules.filter((r) => !(r && r.id === id)); },
    {}, () => {}, ['[data-act="remove-rule"]', '[data-act="add-dest"]']);
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
  const ctx = { rules: body()?.doc.rules, destinations: body()?.doc.destinations };
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


const kinds = () => M.kindList(body()?.kinds);
const kindWord = (kind) => tOr(`alerts_kind_${kind}`, kinds().find((k) => k.kind === kind)?.label || kind || '');

function control(f, value) {
  if (f.type === 'select') {
    return select(list(f.options).filter(Array.isArray).map(([v, plain, key]) => [v, tOr(key, plain || v)]), value ?? '');
  }
  if (f.type === 'url') {
    const box = input('url', value, 'dsk-input dsk-mono al-wide');
    box.placeholder = f.placeholder || '';
    box.spellcheck = false;
    return box;
  }
  if (f.type === 'secret-name') {
    const box = input('text', value || '', 'dsk-input dsk-mono');
    box.placeholder = f.placeholder || '';
    box.maxLength = 40;
    box.spellcheck = false;
    box.autocomplete = 'off';
    return box;
  }
  const box = input('text', value);
  if (f.placeholder) box.placeholder = f.placeholder;
  return box;
}

function destinationForm(was = {}) {
  const editing = Boolean(was.id);
  const offered = kinds();
  const name = input('text', was.name);
  name.maxLength = 60;
  const kind = select(offered.map((k) => [k.kind, kindWord(k.kind)]), was.kind || offered[0]?.kind || '');
  const fieldsOf = (k) => (offered.find((x) => x.kind === k) || offered[0] || { fields: [] }).fields;
  const unbound = editing && M.secretName(was.secret) && was.secret_bound === false;
  const bind = check(false);
  const bindField = unbound ? toggle('bind', t('alerts_f_bind', { name: M.secretName(was.secret) }), bind) : null;
  const boxes = {};
  let fields = [];
  let seats = [];
  const shape = (fs) => fs.map((f) => `${f.name}:${f.type}:${f.label || ''}:${f.hint || ''}`).join(',');
  const draw = (fs) => {
    const typed = Object.fromEntries(Object.entries(boxes).map(([n, b]) => [n, b.value]));
    for (const n of Object.keys(boxes)) delete boxes[n];
    seats = fs.map((f) => {
      boxes[f.name] = control(f, f.name in typed ? typed[f.name] : was[f.name]);
      return field(f.name, tOr(f.label, f.text), boxes[f.name], f.hint ? tOr(f.hint, f.hint_text) : '');
    });
    if (bindField && boxes.secret) seats.push(bindField);
    fields = fs;
  };
  draw(fieldsOf(kind.value));
  const kindField = field('kind', t('alerts_f_kind'), kind);
  kind.addEventListener('change', () => {
    const next = fieldsOf(kind.value);
    if (shape(next) === shape(fields)) {
      for (const f of next) if (boxes[f.name] && 'placeholder' in boxes[f.name]) boxes[f.name].placeholder = f.placeholder || '';
      fields = next;
      return;
    }
    const gone = seats;
    draw(next);
    kindField.after(...seats);
    for (const s of gone) if (!seats.includes(s)) s.remove();
  });
  const hosts = list(body().status.hosts);
  const note = document.createElement('p');
  note.className = 'nv-form-note';
  note.textContent = hosts.length ? t('alerts_hosts_hint', { hosts: hosts.join(', ') }) : '';
  return formBox('al-form-dest', [
    field('name', t('alerts_f_name'), name),
    kindField,
    ...seats,
  ], t('alerts_save'), () => saveDestination(was.id || '', {
    name: name.value.trim(), kind: kind.value, ...M.destinationValues(fields, (n) => boxes[n]?.value),
    ...(unbound && bind.checked && boxes.secret ? { bind: true } : {}),
  }), closeForm, [note], () => S.busy);
}

function digestForm() {
  const b = body();
  const doc = b.doc;
  S.digestWas = Store.clone(doc.digest);
  const g = { hour: 8, cert_days: 30, review_days: 90, drift: true, uncharted: false, ...doc.digest };
  const enabled = check(g.enabled);
  const hour = select(Array.from({ length: 24 }, (_, h) => [String(h), `${String(h).padStart(2, '0')}:00`]), String(Number(g.hour) || 0));
  const dest = select([['', t('alerts_pick')], ...doc.destinations.map((d) => [d.id, d.name || d.id])], g.destination || '');
  const cert = input('number', String(g.cert_days ?? 30), 'dsk-input dsk-mono al-num');
  const review = input('number', String(g.review_days ?? 90), 'dsk-input dsk-mono al-num');
  cert.min = '1'; cert.max = '365'; cert.step = '1';
  review.min = '1'; review.max = '3650'; review.step = '1';
  const drift = check(g.drift);
  const support = M.unchartedSupport(b, t);
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
  ], t('alerts_save'), () => saveDigest(read()), null, [sentence], () => S.busy);
  box.addEventListener('input', () => { S.digestDirty = true; preview(); });
  box.addEventListener('change', () => { S.digestDirty = true; preview(); });
  return box;
}

function openForm(id) {
  S.armed = '';
  S.msg = null;
  const was = id ? body().doc.destinations.find((d) => d.id === id) : {};
  if (!was) return;
  S.form = { id, was: Store.clone(was), el: destinationForm(was) };
  draw();
  S.form.el.querySelector('input, select')?.focus();
}

function closeForm() {
  S.form = null;
  S.msg = null;
  draw();
  el.main.querySelector('[data-act="add-dest"]')?.focus({ preventScroll: true });
}


async function busy(fn, fallbacks = []) {
  const key = focusKey(el.main);
  S.busy = true;
  for (const b of el.main.querySelectorAll('button')) b.disabled = true;
  try { return await fn(); } finally {
    S.busy = false;
    for (const b of el.main.querySelectorAll('button')) b.disabled = false;
    draw();
    const bad = [S.form?.el, S.digestEl].map((f) => f?.querySelector('.al-problem:not(:empty)')
      ?.closest('label, fieldset')?.querySelector('input, select')).find(Boolean);
    if (key !== null && bad) bad.focus();
    else refocus(el.main, key, ...fallbacks);
  }
}

async function saveChange(change, where = {}, after = () => {}, fallbacks = []) {
  return busy(async () => {
    tell(t('alerts_saving'));
    const r = await Store.save(change);
    if (r.unchanged) { tell(''); after(true); return true; }
    const m = answerNotice(r, where);
    if (r.status === 409 || r.status === 403) { S.form = null; S.digestEl = null; S.digestDirty = false; }
    else if (r.ok && !S.digestDirty) S.digestEl = null;
    after(r.ok);
    S.msg = { kind: m.kind, text: m.text, problems: m.problems || [] };
    return r.ok;
  }, fallbacks);
}

async function saveDestination(id, entry) {
  const form = S.form?.el;
  const checks = M.checkDestination(entry, { hosts: body().status.hosts, kinds: kinds() }, t);
  if (checks.length) { showProblems(form, byFieldOf(checks)); tell(t('alerts_fix'), 'warn'); return; }
  const dests = body().doc.destinations;
  const at = id ? dests.findIndex((d) => d.id === id) : dests.length;
  const label = id || M.slugFor(entry.name, dests.map((d) => d.id), 'destination');
  const was = S.form?.was;
  await saveChange((doc) => {
    const i = id ? doc.destinations.findIndex((d) => d.id === id) : -1;
    if (id && (i < 0 || !sameEntry(doc.destinations[i], was))) return Store.CONFLICT;
    if (i >= 0) doc.destinations[i] = { ...doc.destinations[i], ...entry };
    else doc.destinations.push({ id: M.slugFor(entry.name, doc.destinations.map((d) => d.id), 'destination'), ...entry });
    return true;
  }, { form, prefix: `destinations[${Math.max(at, 0)}]`, label: `destination ${label}` },
  (ok) => { if (ok) S.form = null; }, ['[data-act="add-dest"]']);
}

async function saveDigest(digest) {
  const form = S.digestEl;
  const checks = M.checkDigest(digest, { destinations: body().doc.destinations }, t);
  if (checks.length) { showProblems(form, byFieldOf(checks)); tell(t('alerts_fix'), 'warn'); return; }
  const was = S.digestWas;
  await saveChange((doc) => {
    if (!sameEntry(doc.digest, was)) return Store.CONFLICT;
    doc.digest = { ...digest, destination: digest.destination || null };
    return true;
  }, { form, prefix: 'digest', label: 'digest' },
  (ok) => { if (ok) { S.digestDirty = false; S.digestEl = null; } }, ['.al-form-digest .dsk-btn-go']);
}

async function removeDestination(id) {
  if (S.armed !== id) { S.armed = id; draw(); el.main.querySelector(`[data-act="remove"][data-id="${CSS.escape(id)}"]`)?.focus(); return; }
  S.armed = '';
  const doc = body().doc;
  const users = doc.rules.filter((r) => r.destination === id).map((r) => r.name || r.id);
  if (doc.digest?.enabled && doc.digest.destination === id) users.push(t('alerts_t_digest'));
  if (users.length) { keepFocus(el.main, draw, '[data-act="add-dest"]'); tell(t('alerts_in_use', { names: users.join(', ') }), 'warn'); return; }
  await saveChange((d) => {
    d.destinations = d.destinations.filter((x) => x.id !== id);
    if (d.digest?.destination === id) d.digest.destination = null;
  }, {}, () => {}, ['[data-act="add-dest"]']);
}

async function sendTest(id) {
  S.tests[id] = { pending: true };
  draw();
  const r = await Store.postJSON(`${Store.API}/destinations/${encodeURIComponent(id)}/test`, {});
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
  if (act !== 'remove' && S.armed) S.armed = '';
  if (act !== 'remove-rule' && S.armedRule) S.armedRule = '';
  if (act === 'add-dest') openForm('');
  else if (act === 'edit') openForm(id);
  else if (act === 'remove') removeDestination(id);
  else if (act === 'remove-rule') removeOrphan(id);
  else if (act === 'test') sendTest(id);
}


async function loadDeliveries() {
  try { S.deliveries = await Store.deliveries(50); S.delError = ''; } catch (err) { S.delError = err.message || String(err); }
}

Store.listen((changed) => {
  if (!el.main || !unfolded()) return;
  if (changed && !S.form && !S.digestDirty && !S.busy) { S.digestEl = null; keepFocus(el.main, draw); } else drawStrip();
});

async function start() {
  if (!frame()) return;
  clearInterval(timer);
  timer = setInterval(tick, POLL_MS);
  draw();
  await Promise.all([Store.read(), loadDeliveries()]);
  if (open && unfolded()) draw();
}

async function tick() {
  if (!open || !unfolded()) { clearInterval(timer); timer = 0; return; }
  if (document.hidden) return;
  await Promise.all([Store.read(), loadDeliveries()]);
  drawDeliveries();
}

addEventListener('atlas:settings', (e) => {
  open = Boolean(e.detail?.open);
  if (!open) { clearInterval(timer); timer = 0; return; }
  if (!frame()) return;
  if (unfolded()) start();
});
document.addEventListener('click', (e) => {
  const head = e.target.closest?.('#sp-alerts > .sp-sub');
  if (head && open) setTimeout(() => { if (unfolded() && !timer) start(); }, 0);
});
