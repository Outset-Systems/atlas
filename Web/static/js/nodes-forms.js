/* NODES, the forms and the writes (2026-11-16): the message line, the bulk
   bar and its forms, the scope bar for one place, collection or service,
   maintenance windows and mode, unmanaged, adding to and taking out of a
   collection, and the path every write takes (ready, busy, applyOps,
   conflict). Cut out of nodes.js. Five of its parts import each other in
   circles, which is safe because none of them calls another while it loads;
   what they need from nodes.js itself they reach through `hooks`
   (nodes-state.js). */

import { A, esc } from './config.js';
import * as R from './roster-model.js';
import * as M from './menu-model.js';
import { serviceKey } from './alerts-model.js';
import Editor, { EditorError } from './editor/store.js';
import { inputToIso, isoToInput, numberValue } from './editor/form-model.js';
import { t } from './nodes-text.js';
import { REPEATS, S, el, shared, hooks, phone, mayWrite } from './nodes-state.js';
import { drawResults } from './nodes-table.js';
import { drawRail, ruleCollectionIds } from './nodes-rail.js';
import { setServiceCollection } from './nodes-services.js';
import { closeMenu, focusMore, forgetCheck } from './nodes-menu.js';

/* ── messages ────────────────────────────────────────────────────────────── */

export function tell(textOrErr, kind = 'info') {
  if (textOrErr instanceof Error) {
    const problems = (textOrErr.problems || []).filter((p) => p !== textOrErr.message);
    S.msg = { kind: 'bad', text: textOrErr.message || 'That could not be saved.', problems };
  } else {
    S.msg = textOrErr ? { kind, text: textOrErr, problems: [] } : null;
  }
  drawMessage();
}

export function drawMessage() {
  if (!el.msg) return;
  const m = S.msg;
  el.msg.innerHTML = !m ? '' : `<div class="dsk-notice dsk-notice-${m.kind}">${esc(m.text)}` +
    (m.problems?.length ? `<ul class="dsk-problems">${m.problems.map((p) => `<li>${esc(p)}</li>`).join('')}</ul>` : '') +
    '</div>';
}

/* ── the bulk actions (an admin, a wide screen) ──────────────────────────── */

export function button(cls, label, onClick) {
  const b = document.createElement('button');
  b.type = 'button';
  b.className = cls;
  b.textContent = label;
  b.addEventListener('click', onClick);
  return b;
}

function selectedIds() { return S.shown.filter((id) => S.selected.has(id)); }

export function drawBulk() {
  const bar = el.bulk;
  bar.innerHTML = '';
  bar.className = 'nv-bulk';
  if (!mayWrite()) { bar.hidden = true; return; }
  if (phone()) {
    bar.hidden = false;
    bar.classList.add('nv-bulk-note');
    bar.textContent = t('nodes_phone_bulk');
    return;
  }
  if (S.scope && S.scope.kind === 'place' && !rowOf(S.scope.id)) S.scope = null;   // it left the table
  if (S.scope) { drawScope(bar); return; }
  const ids = selectedIds();
  bar.hidden = !ids.length;
  if (!ids.length) { S.form = ''; shared.formEl = null; shared.formFor = ''; return; }

  const row = document.createElement('div');
  row.className = 'nv-bulk-row';
  const count = document.createElement('span');
  count.className = 'nv-bulk-n';
  count.textContent = t('nodes_selected', { n: ids.length });
  row.append(count);

  const armed = S.arm.armed;
  const review = button(`dsk-btn dsk-btn-sm nv-review${armed ? ' dsk-btn-go' : ''}`,
    armed ? (armed.length === 1 ? t('nodes_armed_one') : t('nodes_armed_many', { n: armed.length })) : t('nodes_bulk_review'),
    () => markChecked());
  row.append(review);
  for (const [form, key] of [['maint', 'nodes_bulk_maint'], ['col-add', 'nodes_bulk_col_add'],
    ['col-out', 'nodes_bulk_col_out'], ['hide', 'nodes_bulk_hide'], ['needs', 'nodes_bulk_needs'],
    ['mode', 'nodes_bulk_mode'], ['unmanaged', 'nodes_bulk_unmanaged']]) {
    const b = button(`dsk-btn dsk-btn-sm${S.form === form ? ' on' : ''}`, t(key), () => {
      S.form = S.form === form ? '' : form;
      S.arm.disarm();
      drawBulk();
      bar.querySelector('.nv-form input, .nv-form select')?.focus();
    });
    b.setAttribute('aria-expanded', String(S.form === form));
    row.append(b);
  }
  row.append(button('dsk-btn dsk-btn-sm nv-bulk-clear', t('nodes_clear_sel'), () => {
    S.selected.clear(); S.arm.disarm(); S.form = ''; drawResults();
  }));
  bar.append(row);
  for (const b of bar.querySelectorAll('button')) b.disabled = S.busy;

  // the open form survives a redraw (a tick, a search, a refresh) so nothing
  // typed into it is lost; a new one is built only when another is picked
  if (S.form !== shared.formFor) { shared.formEl = FORMS[S.form]?.(ids) || null; shared.formFor = S.form; }
  if (shared.formEl) {
    for (const b of shared.formEl.querySelectorAll('button')) b.disabled = S.busy;
    bar.append(shared.formEl);
  }
}

function field(labelText, control) {
  const label = document.createElement('label');
  label.className = 'nv-field';
  const span = document.createElement('span');
  span.className = 'nv-label';
  span.textContent = labelText;
  label.append(span, control);
  return label;
}

function input(type, value = '', cls = 'dsk-input') {
  const i = document.createElement('input');
  i.type = type;
  i.className = cls;
  i.value = value;
  return i;
}

function select(options, value = '') {
  const s = document.createElement('select');
  s.className = 'dsk-input';
  s.innerHTML = options.map(([v, label]) => `<option value="${esc(v)}">${esc(label)}</option>`).join('');
  s.value = value;
  return s;
}

function formBox(fields, goLabel, onGo, note) {
  const box = document.createElement('form');
  box.className = 'nv-form';
  box.append(...fields);
  if (note) {
    const p = document.createElement('p');
    p.className = 'nv-form-note';
    p.textContent = note;
    box.append(p);
  }
  const bar = document.createElement('div');
  bar.className = 'nv-form-bar';
  const go = button('dsk-btn dsk-btn-sm dsk-btn-go', goLabel, () => {});
  go.type = 'submit';
  go.disabled = S.busy;
  // Cancel and Escape put the form away, and a scope with it (stage 3)
  bar.append(button('dsk-btn dsk-btn-sm', t('nodes_cancel'), () => { if (S.scope) closeScope(); else { S.form = ''; drawBulk(); } }), go);
  box.append(bar);
  box.addEventListener('submit', (e) => { e.preventDefault(); if (!S.busy) onGo(); });
  box.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    e.stopPropagation();
    if (S.scope) closeScope(); else { S.form = ''; drawBulk(); }
  });
  return box;
}

const FORMS = {
  maint() {
    const now = new Date();
    now.setUTCSeconds(0, 0);
    const reason = input('text');
    reason.maxLength = 200;
    const start = input('datetime-local', isoToInput(now.toISOString()));
    const end = input('datetime-local', isoToInput(new Date(now.getTime() + 3600000).toISOString()));
    const repeat = select(REPEATS.map((r) => [r, t(`nodes_r_${r}`)]), 'none');
    return formBox([field(t('nodes_m_reason'), reason), field(t('nodes_m_start'), start),
      field(t('nodes_m_end'), end), field(t('nodes_m_repeat'), repeat)], t('nodes_m_go'),
    () => openWindow(S.scope ? scopeTarget() : { nodes: selectedIds() },
      { reason: reason.value.trim(), start: start.value, end: end.value, repeat: repeat.value }));
  },
  mode() {
    const pick = select([['on', t('nodes_bm_on')], ['off', t('nodes_bm_off')]], 'on');
    return formBox([field(t('nodes_bm_label'), pick)], t('nodes_b_go'),
      () => setMode({ nodes: selectedIds() }, pick.value === 'on', placesLabel(selectedIds())), t('nodes_mode_note'));
  },
  unmanaged() {
    const pick = select([['on', t('nodes_bu_on')], ['off', t('nodes_bu_off')]], 'on');
    return formBox([field(t('nodes_bm_label'), pick)], t('nodes_b_go'),
      () => setUnmanaged('nodes', selectedIds(), pick.value === 'on', placesLabel(selectedIds())), t('nodes_unmanaged_note'));
  },
  'svc-col'() {
    const options = (S.roster?.collections || []).map((c) => [c.id, c.name || c.id]);
    if (!options.length) {
      const box = document.createElement('div');
      box.className = 'nv-form';
      const p = document.createElement('p');
      p.className = 'nv-form-note';
      p.textContent = t('nodes_sc_none');
      box.append(p);
      return box;
    }
    const pick = select(options, options[0][0]);
    const how = select([['add', t('nodes_sc_add')], ['out', t('nodes_sc_out')]], 'add');
    return formBox([field(t('nodes_sc_label'), pick), field('', how)], t('nodes_b_go'),
      () => setServiceCollection(S.scope.id, pick.value, how.value === 'add', S.scope.name));
  },
  check() { return checkForm(S.scope); },
  'col-add'() { return collectionForm(true); },
  'col-out'() { return collectionForm(false); },
  hide() {
    const group = input('text');
    group.placeholder = t('nodes_h_placeholder');
    group.maxLength = 120;
    return formBox([field(t('nodes_h_label'), group)], t('nodes_h_go'),
      () => hide(selectedIds(), group.value.trim()), t('nodes_stamps'));
  },
  needs(ids) {
    const chosen = new Set(ids);
    const places = R.sortRows(S.roster?.rows || [], 'name', 'asc')
      .filter((r) => !(chosen.size === 1 && chosen.has(r.id)));
    const pick = select(places.map((r) => [r.id, r.name || r.id]));
    pick.multiple = true;
    pick.size = Math.min(8, Math.max(3, places.length));
    return formBox([field(t('nodes_n_label'), pick)], t('nodes_n_go'),
      () => needs(selectedIds(), [...pick.selectedOptions].map((o) => o.value)), t('nodes_stamps'));
  },
};

function collectionForm(adding) {
  const options = (S.roster?.collections || []).map((s) => [s.id, s.name || s.id]);
  if (adding) options.push(['', t('nodes_s_new_opt')]);
  const fields = [];
  if (!options.length) {
    const p = document.createElement('p');
    p.className = 'nv-form-note';
    p.textContent = t('nodes_s_none');
    const box = document.createElement('div');
    box.className = 'nv-form';
    box.append(p);
    return box;
  }
  const pick = select(options, options[0][0]);
  const name = input('text');
  name.maxLength = 80;
  const nameField = field(t('nodes_s_new'), name);
  nameField.hidden = pick.value !== '';
  pick.addEventListener('change', () => { nameField.hidden = pick.value !== ''; if (!nameField.hidden) name.focus(); });
  fields.push(field(t('nodes_s_pick'), pick));
  if (adding) fields.push(nameField);
  return formBox(fields, adding ? t('nodes_s_add_go') : t('nodes_s_out_go'),
    () => (adding ? addToCollection(selectedIds(), pick.value, name.value.trim())
      : takeOutOfCollection(selectedIds(), pick.value)));
}

/* ── the writes ──────────────────────────────────────────────────────────── */

/** Open the editor's store (once), read the dataset fresh, and refuse to
    write over a table drawn from an older map: the roster's `stamp` is the
    dataset's, so a difference means somebody saved since this was drawn. */
export async function ready() {
  try {
    if (!Editor.loaded) await Editor.load(); else await Editor.reload();
  } catch (err) {
    tell(t('nodes_editor_failed', { why: err.message || String(err) }), 'bad');
    return false;
  }
  if (!Editor.writable()) { tell(t('nodes_readonly'), 'warn'); return false; }
  if (S.roster?.stamp && Editor.stamp && S.roster.stamp !== Editor.stamp) {
    S.arm.disarm();
    collectionsChanged();    // another admin may have changed the collections
    await hooks.refresh();
    tell(t('nodes_stale_table'), 'warn');
    return false;
  }
  return true;
}

/** Someone else saved first (409): say so, read everything again, stop.
    The same three steps desk-kit.js `run()` takes, without redrawing the Desk. */
async function conflict(err) {
  A.showToast?.(err.message);
  collectionsChanged();
  try { await Editor.reload(); } catch { /* the next press loads it again */ }
  await hooks.refresh();
  tell(err.message, 'warn');
}

/** Run one write with the table held still, then draw it once from the server. */
export async function busy(work) {
  if (S.busy) return;
  S.busy = true;
  drawBulk();
  drawRail();
  try {
    await work();
  } catch (err) {
    if (err instanceof EditorError && err.status === 409) await conflict(err);
    else tell(err);
  } finally {
    S.busy = false;
    if (shared.pendingWhileBusy) shared.pendingWhileBusy = false;
    await hooks.refresh();
  }
}

/** Ops through the editor's store in saves of at most 400. A 409 part-way
    stops the run; the parts already saved stay saved. */
export async function applyOps(ops, note) {
  // the map and the editor's copy are read again once, after the last part,
  // not after each (2026-11-15, stage 5: 2,000 places checked was five full
  // reloads and redraws); a run that stops part-way reads them once there
  let sent = 0;
  let behind = false;   // parts saved that the copies have not read yet
  try {
    return await R.inBatches(ops, async (part) => {
      sent += part.length;
      const last = sent >= ops.length;
      try {
        const out = await Editor.apply(part, note, '', { refresh: last });
        behind = !last;
        return out;
      } catch (err) {
        if (err instanceof EditorError && err.status === 409) { await conflict(err); return null; }
        throw err;
      }
    });
  } finally {
    if (behind) {
      // never in place of the run's own answer or error: the next refresh mends it
      try { await Editor.reload(); } catch { /* ready() reads it before the next write */ }
      try { await A.refreshData?.(); } catch (err) { console.warn('the map could not be read again', err); }
    }
  }
}

async function markChecked() {
  const step = S.arm.press(selectedIds);
  if (step.armed) { drawBulk(); el.bulk.querySelector('.nv-review')?.focus(); return; }
  if (!step.write) return;
  const ids = step.write;
  await busy(async () => {
    if (!(await ready())) return;
    const { done, stopped } = await applyOps(R.reviewOps(ids), 'marked as checked');
    if (stopped) return;
    const line = done === 1 ? t('nodes_marked_one') : t('nodes_marked_many', { n: done });
    A.showToast?.(line);
    tell(line);
  });
}

async function openWindow(target, w) {
  if (!w.reason || !w.start || !w.end) { tell(t('nodes_m_need'), 'warn'); return; }
  const starts = inputToIso(w.start);
  const ends = inputToIso(w.end);
  if (!(Date.parse(ends) > Date.parse(starts))) { tell(t('nodes_m_order'), 'warn'); return; }
  await busy(async () => {
    if (!(await ready())) return;
    // the repairs have their own stamp: read them now, so the list sent is
    // the list on disk with one window more, and a writer between is a 409
    await Editor.loadRepairs();
    const taken = Editor.entries('maintenance').map((x) => x.id);
    const entry = {
      id: R.slugFor(w.reason, taken, 'window'),
      reason: w.reason, starts, ends,
      repeat: REPEATS.includes(w.repeat) ? w.repeat : 'none',
      ...(target.nodes?.length ? { nodes: target.nodes } : {}),
      ...(target.collections?.length ? { collections: target.collections } : {}),
      ...(target.services?.length ? { services: target.services } : {}),
    };
    try {
      await Editor.saveEntry('maintenance', null, entry);
    } catch (err) {
      if (err instanceof EditorError && err.status === 409) {
        try { await Editor.loadRepairs(); } catch { /* the next press reads them again */ }
      }
      throw err;
    }
    S.form = '';
    S.scope = null;
    const n = (target.nodes?.length || 0) + (target.collections?.length || 0) + (target.services?.length || 0);
    const line = n === 1 ? t('nodes_m_done_one') : t('nodes_m_done_many', { n });
    A.showToast?.(line);
    tell(line);
  });
}

export const onDiskCollections = () => (Array.isArray(Editor.data?.collections) ? Editor.data.collections : []);

/* ── stage 3 (2026-11-14): the place menu, the scope bar, the ways out ────
   The owner's Q4: three ways out of the watch, from a place's menu, a
   collection's menu or the bulk bar. SCHEDULE is the window form (the bulk
   bar's, for one place or one collection: the "scope"); MAINTENANCE MODE is
   a window marked `open` (roster-model modeChange); UNMANAGED is a field on
   the place or the collection (`unmanaged`). A place in either through a
   collection says so, and its own switch is not offered. */

export const repairs = () => (Editor.repairs ? Editor.entries('maintenance') : []);
export const rowOf = (id) => (S.roster?.rows || []).find((r) => r.id === id) || null;
const placesLabel = (ids) => (ids.length === 1 ? (rowOf(ids[0])?.name || ids[0]) : t('nodes_n_places', { n: ids.length }));
export const collectionUnmanaged = (id) => onDiskCollections().find((c) => c.id === id)?.unmanaged === true
  || (S.roster?.collections || []).find((c) => c.id === id)?.unmanaged === true;

export async function ensureRepairs() {
  if (Editor.repairs) return;
  try { await Editor.loadRepairs(); } catch { /* an admin route: shown as off until it reads */ }
}

/** The collections a place is unmanaged through (marked so themselves). */
export function unmanagedVia(row) {
  const marked = new Set((S.roster?.collections || []).filter((c) => c.unmanaged === true).map((c) => c.id));
  return (row?.collections || []).filter((c) => marked.has(c));
}

const scopeTarget = () => (S.scope?.kind === 'collection' ? { collections: [S.scope.id] }
  : S.scope?.kind === 'service' ? { services: [S.scope.id] } : { nodes: [S.scope.id] });

/** Put the scope bar away: its form goes with it (a kept form would come
    back aimed at the ticked rows; stage 3 review), and the keyboard goes
    back to what opened it: the ⋯ of the place, the service or the
    collection (2026-11-16: a collection's Schedule… is in its ⋯ too). */
function closeScope() {
  const was = S.scope;
  S.scope = null;
  S.form = '';
  shared.formFor = '';
  shared.formEl = null;
  drawBulk();
  if (!was) return;
  // a place's or service's row may have left the window while the bar was
  // up (its form took the keyboard and scrolled to the top): bring it back
  focusMore(was.kind, was.id);
}

/** The bar for one thing: its schedule form (stage 3). */
export function openScope(scope) {
  closeMenu(false);
  S.scope = scope;
  S.form = scope.form || 'maint';
  shared.formFor = '';
  drawBulk();
  el.bulk.querySelector('.nv-form input, .nv-form select')?.focus();
}

function drawScope(bar) {
  bar.hidden = false;
  const row = document.createElement('div');
  row.className = 'nv-bulk-row';
  const what = document.createElement('span');
  what.className = 'nv-bulk-n';
  what.textContent = t(S.scope.form === 'svc-col' ? 'nodes_scope_col' : S.scope.form === 'check' ? 'nodes_scope_check'
    : 'nodes_scope_for', { name: S.scope.name });
  row.append(what, button('dsk-btn dsk-btn-sm nv-bulk-clear', t('nodes_scope_close'), closeScope));
  bar.append(row);
  // another action cleared the shared form (a mode toggle elsewhere): the
  // scope keeps its own (stage 3b review: FORMS[''] threw on every redraw)
  if (!FORMS[S.form]) S.form = S.scope.form || 'maint';
  const key = `scope:${S.scope.kind}:${S.scope.id}:${S.form}`;
  if (shared.formFor !== key) { shared.formEl = FORMS[S.form]([]); shared.formFor = key; }
  for (const b of [...bar.querySelectorAll('button'), ...shared.formEl.querySelectorAll('button')]) b.disabled = S.busy;
  bar.append(shared.formEl);
}

/** Maintenance mode on or off for {nodes, collections}, one save of the
    repairs (their own stamp: a writer between is a 409). */
export async function setMode(targets, on, label) {
  await busy(async () => {
    if (!(await ready())) return;
    await Editor.loadRepairs();
    const now = new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
    const next = R.modeChange(repairs(), targets, on, { now, reason: t('nodes_mode_reason') });
    if (!next) { tell(on ? t('nodes_already') : throughLine('nodes_mode_through', targets, (row) => R.modeVia(repairs(), row.collections)), 'warn'); return; }
    try {
      await Editor.saveRepairs(next);
    } catch (err) {
      if (err instanceof EditorError && err.status === 409) {
        try { await Editor.loadRepairs(); } catch { /* the next press reads them again */ }
      }
      throw err;
    }
    S.form = '';
    const line = t(on ? 'nodes_mode_on_done' : 'nodes_mode_off_done', { name: label });
    A.showToast?.(line);
    tell(line);
  });
}

/** Nothing to turn off on the places themselves: say which collections
    hold them (their own switch is there), or that it is already so. */
function throughLine(key, targets, via) {
  const names = [...new Set((targets.nodes || []).flatMap((id) => via(rowOf(id) || {})))].map(collectionLabel);
  return names.length ? t(key, { names: names.join(', ') }) : t('nodes_already');
}

/** Unmanaged on or off: the field on places (`nodes`) or collections. */
export async function setUnmanaged(section, ids, on, label) {
  await busy(async () => {
    if (!(await ready())) return;
    const onDisk = new Map((section === 'nodes' ? (Editor.data?.nodes || []) : onDiskCollections()).map((x) => [x.id, x]));
    const ops = ids.filter((id) => onDisk.has(id) && (onDisk.get(id).unmanaged === true) !== on)
      .map((id) => ({ op: 'upsert', section, id, body: { unmanaged: on } }));
    if (!ops.length) {
      tell(on || section !== 'nodes' ? t('nodes_already')
        : throughLine('nodes_unmanaged_through', { nodes: ids }, unmanagedVia), 'warn');
      return;
    }
    const { stopped } = await applyOps(ops, on ? 'marked unmanaged' : 'watched again');
    if (stopped) return;
    S.form = '';
    const line = t(on ? 'nodes_unmanaged_on_done' : 'nodes_unmanaged_off_done', { name: label });
    A.showToast?.(line);
    tell(line);
  });
}

export function collectionLabel(id) {
  const s = (S.roster?.collections || []).find((x) => x.id === id) || onDiskCollections().find((x) => x.id === id);
  return s?.name || id;
}

/** Say a write worked, in the toast and above the table. */
export function done(line) {
  A.showToast?.(line);
  tell(line);
}

async function addToCollection(ids, collectionId, newName) {
  if (!collectionId && !newName) { tell(t('nodes_s_name_needed'), 'warn'); return; }
  await busy(async () => {
    if (!(await ready())) return;
    const list = onDiskCollections();
    let op;
    let label;
    if (collectionId) {
      const entry = list.find((s) => s.id === collectionId);
      if (!entry) {
        // removed in the rail since the form was drawn: say so and draw it again
        shared.formFor = '';
        drawBulk();
        tell(t('nodes_s_gone'), 'warn');
        return;
      }
      const before = R.memberList(entry?.places);
      const places = [...before, ...ids.filter((id) => !before.includes(id))];
      label = collectionLabel(collectionId);
      if (places.length === before.length) { tell(t('nodes_s_unchanged', { name: label })); return; }
      op = { op: 'upsert', section: 'collections', id: collectionId, body: { places } };
    } else {
      const id = R.slugFor(newName, [...list.map((s) => s.id), ...(await ruleCollectionIds())], 'collection');
      label = newName;
      op = { op: 'insert', section: 'collections', body: { id, name: newName, places: ids } };
    }
    const { stopped } = await applyOps([op], 'added to a collection');
    if (stopped) return;
    S.form = '';
    done(t('nodes_s_added', { name: label }));
  });
}

async function takeOutOfCollection(ids, collectionId) {
  await busy(async () => {
    if (!(await ready())) return;
    const entry = onDiskCollections().find((s) => s.id === collectionId);
    if (!entry) {
      // removed since the form was drawn (another admin, or the rail)
      shared.formFor = '';
      drawBulk();
      tell(t('nodes_s_gone'), 'warn');
      return;
    }
    const before = R.memberList(entry?.places);
    const places = before.filter((id) => !ids.includes(id));
    const label = collectionLabel(collectionId);
    if (!entry || places.length === before.length) { tell(t('nodes_s_unchanged', { name: label })); return; }
    const { stopped } = await applyOps([{ op: 'upsert', section: 'collections', id: collectionId, body: { places } }],
      'taken out of a collection');
    if (stopped) return;
    S.form = '';
    done(t('nodes_s_removed', { name: label }));
  });
}

/** The rail changed the collections: an open bulk form is drawn again, so
    its picker lists what is there now. */
export function collectionsChanged() {
  // only the collection forms list collections: a typed maintenance reason,
  // access group or needs pick is never wiped (round 14)
  if (S.form === 'col-add' || S.form === 'col-out') shared.formFor = '';
}

async function hide(ids, group) {
  if (!group) { tell(t('nodes_h_needed'), 'warn'); return; }
  await busy(async () => {
    if (!(await ready())) return;
    const ops = ids.map((id) => ({ op: 'upsert', section: 'nodes', id, body: { require_group: group } }));
    const { stopped } = await applyOps(ops, 'hidden from everyone outside an access group');
    if (stopped) return;
    S.form = '';
    const line = t('nodes_h_done', { group });
    A.showToast?.(line);
    tell(line);
  });
}

async function needs(ids, picks) {
  if (!picks.length) { tell(t('nodes_n_needed'), 'warn'); return; }
  await busy(async () => {
    if (!(await ready())) return;
    const onDisk = new Map((Editor.data?.nodes || []).map((n) => [n.id, n]));
    const ops = [];
    for (const id of ids) {
      const before = onDisk.get(id)?.depends_on;
      const merged = R.mergeNeeds(id, before, picks);
      const same = Array.isArray(before) && before.length === merged.length && merged.every((v, i) => v === before[i]);
      if (!same && merged.length) ops.push({ op: 'upsert', section: 'nodes', id, body: { depends_on: merged } });
    }
    if (!ops.length) { tell(t('nodes_n_unchanged')); return; }
    const { done, stopped } = await applyOps(ops, 'said what these places need');
    if (stopped) return;
    S.form = '';
    const line = done === 1 ? t('nodes_n_done_one') : t('nodes_n_done_many', { n: done });
    A.showToast?.(line);
    tell(line);
  });
}

/* ── Check… (2026-11-17): a check's own fields, in the scope bar ──────────
   A place's or a service's menu opens its check's fields here: the Desk
   form's own (menu-model CHECK_FIELDS: type, address, port, expects,
   every), with their labels, options, limits and help read from the
   schema the editor's store loads, so they are written once, in
   schema.py. Saved through the ops path every NODES write takes (undo,
   revisions and the conflict rule come with it); a place's fields are a
   patch on the place, a service's are laid on its link and its place's
   `links` written whole, as unmanaged is. What the server refuses is said
   inside the form, which stays open. */

/** The schema's fields for a place's check, or a service link's. */
function checkSchema(kind) {
  const fields = Editor.section('nodes')?.fields || [];
  const list = kind === 'service' ? (fields.find((f) => f.name === 'links')?.of || []) : fields;
  return M.CHECK_FIELDS.map((name) => list.find((f) => f && f.name === name)).filter(Boolean);
}

/** The place, or the service's link, as it is on disk; null when gone.
    A service is found by its key on its place (`scope.place`). */
function checkEntry(scope) {
  const nodes = Array.isArray(Editor.data?.nodes) ? Editor.data.nodes : [];
  if (scope.kind === 'place') return { node: nodes.find((n) => n && n.id === scope.id) || null, index: -1 };
  const node = nodes.find((n) => n && n.id === scope.place) || null;
  const links = Array.isArray(node?.links) ? node.links : [];
  const index = links.findIndex((l) => l && typeof l === 'object' && serviceKey(node.id, l) === scope.id);
  return { node: index < 0 ? null : node, index };
}

/** Open the Check… form for one place or service: the editor's store (its
    schema and the map on disk) is read first, since the form is built from
    them. */
export async function openCheck(scope) {
  if (!Editor.loaded) {
    try { await Editor.load(); } catch (err) {
      tell(t('nodes_editor_failed', { why: err.message || String(err) }), 'bad');
      return;
    }
  }
  openScope({ ...scope, form: 'check' });
}

function noteBox(text) {
  const box = document.createElement('div');
  box.className = 'nv-form';
  const p = document.createElement('p');
  p.className = 'nv-form-note';
  p.textContent = text;
  box.append(p);
  return box;
}

function checkForm(scope) {
  const fields = scope ? checkSchema(scope.kind) : [];
  if (!fields.length) return noteBox(t('nodes_check_none'));
  const { node, index } = checkEntry(scope);
  const entry = scope.kind === 'place' ? node : node?.links?.[index];
  if (!entry) return noteBox(t('nodes_check_gone'));
  const read = {};
  const parts = fields.map((fld) => {
    const had = entry[fld.name];
    let control;
    if (fld.type === 'select') {
      const options = (fld.options || []).map((o) => [o, o || t('nodes_check_default')]);
      // a hand edit's value the list does not offer stays, so a save of
      // another field never quietly changes it
      if (typeof had === 'string' && had && !(fld.options || []).includes(had)) options.unshift([had, had]);
      control = select(options, had ?? '');
      read[fld.name] = () => control.value;
    } else if (fld.type === 'int' || fld.type === 'number') {
      control = input('number', had ?? '', 'dsk-input dsk-num');
      control.step = fld.type === 'int' ? '1' : 'any';
      if (fld.min !== undefined) control.min = fld.min;
      if (fld.max !== undefined) control.max = fld.max;
      read[fld.name] = () => numberValue(control.value);
    } else {
      control = input('text', typeof had === 'string' ? had : (had ?? ''));
      control.maxLength = 500;
      read[fld.name] = () => control.value.trim();
    }
    if (fld.help) control.title = fld.help;
    return field(fld.label || fld.name, control);
  });
  const problems = document.createElement('div');
  problems.className = 'nv-form-problems';
  problems.setAttribute('aria-live', 'polite');
  const typeHelp = fields.find((f) => f.name === 'check')?.help || '';
  const box = formBox(parts, t('nodes_check_go'), () => {
    const values = Object.fromEntries(Object.entries(read).map(([name, fn]) => [name, fn()]));
    saveCheck(scope, values, problems);
  }, typeHelp);
  box.insertBefore(problems, box.querySelector('.nv-form-bar'));
  return box;
}

/** What the server refused, inside the form: its words, and each problem. */
function showProblems(host, err) {
  if (!err) { host.innerHTML = ''; return; }
  const problems = (err.problems || []).filter((p) => p && p !== err.message);
  host.innerHTML = `<div class="dsk-notice dsk-notice-bad">${esc(err.message || '')}` +
    (problems.length ? `<ul class="dsk-problems">${problems.map((p) => `<li>${esc(p)}</li>`).join('')}</ul>` : '') +
    '</div>';
}

async function saveCheck(scope, values, problems) {
  showProblems(problems, null);
  let saved = false;
  let refused = false;
  await busy(async () => {
    if (!(await ready())) return;
    // read again under the fresh stamp: the patch is from what is on disk now
    const { node, index } = checkEntry(scope);
    if (!node) { tell(t('nodes_check_gone'), 'warn'); return; }
    let ops;
    if (scope.kind === 'place') {
      const patch = M.checkPatch(node, values);
      if (!Object.keys(patch).length) { tell(t('nodes_already')); return; }
      ops = [{ op: 'upsert', section: 'nodes', id: node.id, body: patch }];
    } else {
      const patch = M.checkPatch(node.links[index], values);
      if (!Object.keys(patch).length) { tell(t('nodes_already')); return; }
      const links = node.links.map((l, i) => (i === index ? M.patched(l, patch) : l));
      ops = [{ op: 'upsert', section: 'nodes', id: node.id, body: { links } }];
    }
    try {
      const { stopped } = await applyOps(ops, scope.kind === 'place' ? 'changed a check' : "changed a service's check");
      if (stopped) return;
    } catch (err) {
      // the server's words for a value it will not take, in the form
      if (err instanceof EditorError && (err.status === 400 || err.status === 422)) {
        showProblems(problems, err);
        refused = true;
        return;
      }
      throw err;
    }
    saved = true;
    S.form = '';
    S.scope = null;
    shared.formEl = null;
    shared.formFor = '';
    forgetCheck(scope.id);
    done(t('nodes_check_saved', { name: scope.name }));
  });
  if (saved) focusMore(scope.kind, scope.id);
  else if (refused) problems.closest('form')?.querySelector('input, select')?.focus();
}
