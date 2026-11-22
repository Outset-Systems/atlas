
import { A, noticeHTML } from './config.js';
import { button, input, select } from './alert-forms.js';
import * as R from './roster-model.js';
import Editor, { EditorError } from './editor/store.js';
import { inputToIso, isoToInput } from './editor/form-model.js';
import { t } from './nodes-text.js';
import { REPEATS, S, el, shared, hooks, phone, mayWrite } from './nodes-state.js';
import { drawResults } from './nodes-table.js';
import { drawRail, ruleCollectionIds } from './nodes-rail.js';
import { setServiceCollection } from './nodes-services.js';
import { closeMenu, focusMore } from './nodes-menu.js';
import { checkForm, openCheck } from './nodes-check.js';

export { openCheck };


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
  el.msg.innerHTML = noticeHTML(S.msg);
}


export { button };

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
  if (S.scope && S.scope.kind === 'place' && !rowOf(S.scope.id)) S.scope = null;
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

  if (S.form !== shared.formFor) { shared.formEl = FORMS[S.form]?.(ids) || null; shared.formFor = S.form; }
  if (shared.formEl) {
    for (const b of shared.formEl.querySelectorAll('button')) b.disabled = S.busy;
    bar.append(shared.formEl);
  }
}

export function field(labelText, control) {
  const label = document.createElement('label');
  label.className = 'nv-field';
  const span = document.createElement('span');
  span.className = 'nv-label';
  span.textContent = labelText;
  label.append(span, control);
  return label;
}

export function formBox(fields, goLabel, onGo, note) {
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
    if (!options.length) return noteBox(t('nodes_sc_none'));
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
  if (!options.length) return noteBox(t('nodes_s_none'));
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
    collectionsChanged();
    await hooks.refresh();
    tell(t('nodes_stale_table'), 'warn');
    return false;
  }
  return true;
}

async function conflict(err) {
  A.showToast?.(err.message);
  collectionsChanged();
  try { await Editor.reload(); } catch {   }
  await hooks.refresh();
  tell(err.message, 'warn');
}

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

export async function applyOps(ops, note) {
  let sent = 0;
  let behind = false;
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
      try { await Editor.reload(); } catch {   }
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
        try { await Editor.loadRepairs(); } catch {   }
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


export const repairs = () => (Editor.repairs ? Editor.entries('maintenance') : []);
export const rowOf = (id) => (S.roster?.rows || []).find((r) => r.id === id) || null;
const placesLabel = (ids) => (ids.length === 1 ? (rowOf(ids[0])?.name || ids[0]) : t('nodes_n_places', { n: ids.length }));
export const collectionUnmanaged = (id) => onDiskCollections().find((c) => c.id === id)?.unmanaged === true
  || (S.roster?.collections || []).find((c) => c.id === id)?.unmanaged === true;

export async function ensureRepairs() {
  if (Editor.repairs) return;
  try { await Editor.loadRepairs(); } catch {   }
}

export function unmanagedVia(row) {
  const marked = new Set((S.roster?.collections || []).filter((c) => c.unmanaged === true).map((c) => c.id));
  return (row?.collections || []).filter((c) => marked.has(c));
}

const scopeTarget = () => (S.scope?.kind === 'collection' ? { collections: [S.scope.id] }
  : S.scope?.kind === 'service' ? { services: [S.scope.id] } : { nodes: [S.scope.id] });

function closeScope() {
  const was = S.scope;
  S.scope = null;
  S.form = '';
  shared.formFor = '';
  shared.formEl = null;
  drawBulk();
  if (!was) return;
  focusMore(was.kind, was.id);
}

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
  if (!FORMS[S.form]) S.form = S.scope.form || 'maint';
  const key = `scope:${S.scope.kind}:${S.scope.id}:${S.form}`;
  if (shared.formFor !== key) { shared.formEl = FORMS[S.form]([]); shared.formFor = key; }
  for (const b of [...bar.querySelectorAll('button'), ...shared.formEl.querySelectorAll('button')]) b.disabled = S.busy;
  bar.append(shared.formEl);
}

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
        try { await Editor.loadRepairs(); } catch {   }
      }
      throw err;
    }
    S.form = '';
    const line = t(on ? 'nodes_mode_on_done' : 'nodes_mode_off_done', { name: label });
    A.showToast?.(line);
    tell(line);
  });
}

function throughLine(key, targets, via) {
  const names = [...new Set((targets.nodes || []).flatMap((id) => via(rowOf(id) || {})))].map(collectionLabel);
  return names.length ? t(key, { names: names.join(', ') }) : t('nodes_already');
}

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

export function collectionsChanged() {
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

export function noteBox(text) {
  const box = document.createElement('div');
  box.className = 'nv-form';
  const p = document.createElement('p');
  p.className = 'nv-form-note';
  p.textContent = text;
  box.append(p);
  return box;
}
