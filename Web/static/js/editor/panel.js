/* THE SURVEYOR'S DESK — where the map is written.

   One panel, twelve sections, all rendered from the field catalogue. The
   sidebar lists the sections plus the two things that aren't sections: THE
   SURVEY (devices found on the wire, waiting to be charted) and THE CHRONICLE
   OF CHANGES (who altered what, and the way back).

   Nothing here knows what a rack slot or a rite *is*. If it looks like it
   handles twelve kinds of thing, it handles one kind of thing twelve times.

   This file is the chrome, the table, the form and the routing. THE SURVEY is
   survey.js, the change log is changes.js, the backdrop gallery and the region
   rectangle are form-extras.js, and what they all share — notices, the save
   wrapper, and the `desk` handle they reach this panel through — is
   desk-kit.js. */

import { A, $, esc } from '../config.js';
import { say } from '../words.js';
import Editor from './store.js';
import { buildForm, makeEl as el } from './form.js';
import { standing, sentence, waiting } from './standing.js';
import { VIRTUAL, desk, iconBtn, notice, problemList, run } from './desk-kit.js';
import { drawSurvey } from './survey.js';
import { drawChanges } from './changes.js';
import { drawMapArt, seatRegionView } from './form-extras.js';

let root, sideEl, bodyEl, titleEl, subEl;
let booted = false;

/* What the panel's other files reach it through (desk-kit.js): the head, the
   router and the way in. The body element joins them in buildDesk. */
Object.assign(desk, { setHead, show, open: openDesk });

/* ── chrome ───────────────────────────────────────────────────────────── */

function setHead(label, lore) {
  titleEl.textContent = say(label);
  subEl.textContent = say(lore || '');
}

function drawSidebar() {
  sideEl.innerHTML = '';
  for (const key of Editor.sectionKeys()) {
    const section = Editor.section(key);
    const count = section.kind === 'object' ? '' : String(Editor.entries(key).length);
    const btn = el('button', `dsk-nav${key === desk.active ? ' on' : ''}`,
      `<span class="dsk-nav-name">${esc(section.plural.toUpperCase())}</span>` +
      `<span class="dsk-nav-n">${count}</span>`);
    btn.addEventListener('click', () => show(key));
    sideEl.append(btn);
  }
  sideEl.append(el('div', 'dsk-nav-rule'));
  for (const [key, meta] of Object.entries(VIRTUAL)) {
    const btn = el('button', `dsk-nav${key === desk.active ? ' on' : ''}`,
      `<span class="dsk-nav-name">${esc(meta.label)}</span><span class="dsk-nav-n" ` +
      `id="dsk-n-${key}"></span>`);
    btn.addEventListener('click', () => show(key));
    sideEl.append(btn);
  }
}

/* ── the table ────────────────────────────────────────────────────────── */

/** The four or five fields worth a column, chosen from the catalogue.
    Positions, lore and nested lists are all real fields and all useless in a
    table — the identity, the name and the next few scalars are what you scan
    a list for. */
function columnsFor(section) {
  const skip = new Set(['objects', 'longtext', 'json', 'percent', 'strings']);
  const preferred = [section.id_field, section.title_field].filter(Boolean);
  const rest = section.fields
    .filter((f) => !skip.has(f.type) && !preferred.includes(f.name))
    .map((f) => f.name);
  return [...new Set([...preferred, ...rest])].slice(0, 5)
    .map((name) => section.fields.find((f) => f.name === name))
    .filter(Boolean);
}

function cellText(field, value) {
  if (value === undefined || value === null || value === '') return '—';
  if (field.type === 'bool') return value ? 'yes' : '—';
  if (Array.isArray(value)) return value.join(', ');
  return String(value);
}

function drawTable(key) {
  const section = Editor.section(key);
  setHead(section.plural.toUpperCase(), section.lore);
  bodyEl.innerHTML = '';

  if (section.kind === 'object') return drawObjectForm(key, section);

  const bar = el('div', 'dsk-bar');
  bar.append(el('span', 'dsk-bar-sub', esc(section.subtitle)));
  const search = el('input', 'dsk-input dsk-search');
  search.type = 'search';
  search.placeholder = `Search ${section.plural}…`;
  const add = el('button', 'dsk-btn dsk-btn-go', `+ new ${esc(section.singular)}`);
  add.addEventListener('click', () => drawForm(key, null, null));
  bar.append(search, add);
  bodyEl.append(bar);

  const entries = Editor.entries(key);
  if (!entries.length) {
    bodyEl.append(notice(`No ${section.plural} yet. Add the first one.`));
    return;
  }

  const columns = columnsFor(section);
  const overridden = new Set(Editor.overridden[key] || []);
  const table = el('table', 'dsk-table');
  table.innerHTML =
    `<thead><tr>${columns.map((c) => `<th>${esc(c.label)}</th>`).join('')}` +
    `<th class="dsk-th-act"></th></tr></thead>`;
  const tbody = el('tbody');

  entries.forEach((entry, index) => {
    const id = section.id_field ? entry[section.id_field] : null;
    const tr = el('tr');
    tr.dataset.find = JSON.stringify(entry).toLowerCase();
    for (const column of columns) {
      const td = el('td', column.type === 'color' ? 'dsk-td-color' : '');
      if (column.type === 'color' && entry[column.name]) {
        td.innerHTML = `<span class="dsk-dot" style="background:${esc(entry[column.name])}"></span>` +
                       `<code>${esc(entry[column.name])}</code>`;
      } else {
        td.innerHTML = `<span${['ip', 'cidr', 'slug'].includes(column.type) ? ' class="dsk-mono"' : ''}>` +
                       `${esc(cellText(column, entry[column.name]))}</span>`;
      }
      tr.append(td);
    }
    const act = el('td', 'dsk-td-act');
    const ref = section.id_field ? { id } : { index };
    act.append(
      iconBtn('✎', 'Edit', () => drawForm(key, entry, ref)),
      iconBtn('⧉', 'Duplicate', () => duplicate(key, entry)),
      iconBtn('✕', `Remove this ${section.singular}`, () => confirmDelete(key, entry, ref), 'warn'));
    tr.append(act);
    if (key === 'nodes') {
      // has a person checked this place? (the server's stamp, read back)
      const state = standing(entry);
      tr.dataset.standing = state;
      tr.dataset.id = id;
      tr.title = sentence(entry);
      if (state !== 'checked') {
        tr.classList.add(`dsk-p-${state}`);
        act.prepend(iconBtn('✓', 'Mark as checked: you have looked at this and it is right',
          () => markChecked([id])));
      }
    }
    if (entry.state) tr.classList.add(`dsk-w-${entry.state}`);
    if (section.id_field && overridden.has(id)) {
      tr.classList.add('dsk-overridden');
      tr.title = 'The map is drawing this somewhere else — a saved layout overrides it.';
    }
    tbody.append(tr);
  });

  table.append(tbody);
  if (key === 'nodes') {
    const waitingFor = reviewNotice(entries, section, tbody);
    if (waitingFor) bodyEl.append(waitingFor);
  }
  bodyEl.append(table);

  search.addEventListener('input', () => {
    const q = search.value.trim().toLowerCase();
    for (const tr of tbody.children) tr.hidden = q && !tr.dataset.find.includes(q);
  });
}

/* ── checked by a person ──────────────────────────────────────────────── */

/** The store takes 500 changes in one save. */
const REVIEW_BATCH = 400;

/** Say "I have looked at these and they are right". Nothing on a place changes
    but its stamp, which the server writes (provenance.py). */
async function markChecked(ids) {
  let done = 0;
  try {
    for (let i = 0; i < ids.length; i += REVIEW_BATCH) {
      const ops = ids.slice(i, i + REVIEW_BATCH).map((id) => ({ op: 'review', section: 'nodes', id }));
      const result = await run(() => Editor.apply(ops, 'marked as checked'), false);
      if (!result) return;          // someone else saved first: run() reloaded and redrew
      done += ops.length;
    }
  } catch (err) {
    A.showToast?.(err.message || 'That could not be saved.');
    return;
  }
  A.showToast?.(done === 1 ? 'Marked as checked.' : `${done} marked as checked.`);
  show('nodes');
}

/** The line above the places: how many nobody has checked, and the two ways on. */
function reviewNotice(entries, section, tbody) {
  const line = waiting(entries, section.plural);
  if (!line) return null;
  const box = el('div', 'dsk-notice dsk-notice-warn dsk-review');
  box.append(el('div', 'dsk-review-text',
    `${esc(line)} Open one and save it, press ✓ on its row, or mark several at once.`));
  const only = el('button', 'dsk-btn', 'Show only these');
  const all = el('button', 'dsk-btn', 'Mark the ones shown as checked');
  only.addEventListener('click', () => {
    const on = tbody.classList.toggle('dsk-only-pending');
    only.textContent = on ? `Show every ${section.singular}` : 'Show only these';
    disarm();
  });
  // Two presses: the first counts what is on screen and says so, the second writes.
  let armed = null;
  function disarm() {
    armed = null;
    all.textContent = 'Mark the ones shown as checked';
    all.classList.remove('dsk-btn-go');
  }
  all.addEventListener('click', async () => {
    if (armed) {
      const ids = armed;
      all.disabled = true;
      await markChecked(ids);
      all.disabled = false;
      disarm();
      return;
    }
    const ids = [...tbody.children]
      .filter((tr) => !tr.hidden && tr.dataset.standing !== 'checked')
      .map((tr) => tr.dataset.id);
    if (!ids.length) return;
    armed = ids;
    all.textContent = `Yes, I have checked ${ids.length === 1 ? 'this one' : `these ${ids.length}`}`;
    all.classList.add('dsk-btn-go');
  });
  const bar = el('div', 'dsk-review-bar');
  bar.append(only, all);
  box.append(bar);
  return box;
}

/* ── the form ─────────────────────────────────────────────────────────── */

function drawForm(key, entry, ref) {
  const section = Editor.section(key);
  const editing = Boolean(ref);
  setHead(`${editing ? 'EDIT' : 'NEW'} ${section.singular.toUpperCase()}`, section.subtitle);
  bodyEl.innerHTML = '';

  const form = buildForm(key, entry);
  const errors = el('div', 'dsk-form-errors');

  if (editing && section.id_field && (Editor.overridden[key] || []).includes(entry[section.id_field])) {
    bodyEl.append(notice(
      'A saved layout is currently placing this somewhere other than the position below. ' +
      'Changing the position here will clear that override.', 'warn'));
  }

  if (editing && key === 'nodes') {
    // who charted it and whether anyone has checked it; Save is how you check it
    const checked = standing(entry) === 'checked';
    bodyEl.append(notice(
      sentence(entry) + (checked ? '' : ' Saving it here, changed or not, marks it as checked.'),
      checked ? 'info' : 'warn'));
  }
  bodyEl.append(errors, form.el);
  if (key === 'regions') seatRegionView(form);

  const bar = el('div', 'dsk-formbar');
  const cancel = el('button', 'dsk-btn', 'Cancel');
  cancel.addEventListener('click', () => show(key));
  const save = el('button', 'dsk-btn dsk-btn-go', editing ? 'Save' : `Add ${esc(section.singular)}`);
  save.addEventListener('click', async () => {
    errors.innerHTML = '';
    let body;
    try {
      body = form.read();
    } catch (err) {
      errors.append(notice(err.message, 'bad'));
      return;
    }
    save.disabled = true;
    try {
      await run(() => Editor.saveEntry(key, editing ? ref : null, body));
      show(key);
    } catch (err) {
      errors.append(problemList(err));
    } finally {
      save.disabled = false;
    }
  });
  bar.append(cancel, save);
  bodyEl.append(bar);
  form.focus();
}

function drawObjectForm(key, section) {
  const form = buildForm(key, Editor.data?.[key] || {});
  const errors = el('div', 'dsk-form-errors');
  bodyEl.append(el('div', 'dsk-bar', `<span class="dsk-bar-sub">${esc(section.subtitle)}</span>`),
                errors, form.el);
  const bar = el('div', 'dsk-formbar');
  const save = el('button', 'dsk-btn dsk-btn-go', 'Save');
  save.addEventListener('click', async () => {
    errors.innerHTML = '';
    let body;
    try { body = form.read(); } catch (err) { errors.append(notice(err.message, 'bad')); return; }
    try {
      await run(() => Editor.upsert(key, null, body));
      show(key);
    } catch (err) { errors.append(problemList(err)); }
  });
  bar.append(save);
  bodyEl.append(bar);
  // The realm's own settings are where the backdrop belongs: picking one is
  // setting `meta.map_image`, and doing it from a gallery beats typing a
  // filename you have to remember exactly.
  if (key === 'meta') drawMapArt(form);
}

async function duplicate(key, entry) {
  const section = Editor.section(key);
  const copy = JSON.parse(JSON.stringify(entry));
  if (section.id_field) {
    const taken = new Set(Editor.entries(key).map((e) => e[section.id_field]));
    let candidate = `${copy[section.id_field]}-copy`;
    let n = 2;
    while (taken.has(candidate)) candidate = `${copy[section.id_field]}-copy-${n++}`;
    copy[section.id_field] = candidate;
  }
  if (copy.name) copy.name = `${copy.name} (COPY)`;
  drawForm(key, copy, null);
}

/** Never delete without saying what else it takes with it. */
async function confirmDelete(key, entry, ref) {
  const section = Editor.section(key);
  const id = section.id_field ? entry[section.id_field] : null;
  const label = id || entry[section.title_field] || `#${ref.index + 1}`;

  let deps = [];
  if (id) {
    try { deps = (await Editor.dependents(key, id)).dependents || []; } catch { /* best effort */ }
  }

  bodyEl.innerHTML = '';
  setHead(`REMOVE ${String(label).toUpperCase()}`, 'this cannot be undone from here — but the chronicle remembers');
  bodyEl.append(notice(`Remove the ${section.singular} “${label}”?`, 'warn'));

  let cascade = false;
  if (deps.length) {
    const box = el('div', 'dsk-deps');
    box.append(el('div', 'dsk-deps-head',
      `${deps.length} other ${deps.length === 1 ? 'thing points' : 'things point'} at it:`));
    box.append(el('ul', 'dsk-problems', deps.map((d) => {
      const target = Editor.section(d.section);
      return `<li><strong>${esc(target ? target.noun || target.singular : d.section)} ` +
             `${esc(d.label)}</strong> <span class="dsk-dim">(${esc(d.field)})</span></li>`;
    }).join('')));
    const check = el('label', 'dsk-field dsk-field-bool');
    const input = el('input', 'dsk-check');
    input.type = 'checkbox';
    input.addEventListener('change', () => { cascade = input.checked; });
    check.append(input, el('span', 'dsk-label',
      'Also remove or unhook everything above (otherwise the removal is refused)'));
    box.append(check);
    bodyEl.append(box);
  }

  const bar = el('div', 'dsk-formbar');
  const cancel = el('button', 'dsk-btn', 'Keep it');
  cancel.addEventListener('click', () => show(key));
  const go = el('button', 'dsk-btn dsk-btn-warn', 'Remove');
  const errors = el('div', 'dsk-form-errors');
  go.addEventListener('click', async () => {
    errors.innerHTML = '';
    try {
      await run(() => Editor.removeEntry(key, ref, cascade));
      show(key);
    } catch (err) { errors.append(problemList(err)); }
  });
  bar.append(cancel, go);
  bodyEl.append(errors, bar);
}

/* ── routing ──────────────────────────────────────────────────────────── */

async function show(key) {
  desk.active = key;
  drawSidebar();
  bodyEl.scrollTop = 0;
  try {
    if (key === 'changes') return await drawChanges();
    if (key === 'survey') return await drawSurvey();
    return drawTable(key);
  } catch (err) {
    bodyEl.innerHTML = '';
    bodyEl.append(problemList(err));
  }
}

export async function openDesk(sectionKey) {
  if (!root) return;
  root.classList.add('open');
  root.setAttribute('aria-hidden', 'false');
  A.closeCard?.();
  if (!booted) {
    bodyEl.innerHTML = '<div class="dsk-notice">Opening the map editor…</div>';
    try {
      await Editor.load();
      await Editor.loadRepairs();
      booted = true;
    } catch (err) {
      bodyEl.innerHTML = '';
      bodyEl.append(problemList(err));
      return;
    }
    if (!Editor.writable()) {
      bodyEl.prepend(notice(
        Editor.ctx.read_only
          ? 'This Atlas is read-only (ATLAS_READONLY=1). You can look, but nothing here will save.'
          : 'The dataset is not writable by this process — check the mount and its permissions.',
        'warn'));
    }
  } else {
    await Editor.reload();
  }
  try {
    await Editor.loadRepairs();
  } catch { /* the repairs endpoint is admin-only and may legitimately fail */ }
  await show(sectionKey || desk.active);
}

export function closeDesk() {
  if (!root) return;
  root.classList.remove('open');
  root.setAttribute('aria-hidden', 'true');
}

export function deskOpen() {
  return root?.classList.contains('open') ?? false;
}

export function buildDesk() {
  root = $('desk');
  if (!root) return;
  sideEl = $('dsk-nav');
  bodyEl = $('dsk-body');
  desk.body = bodyEl;
  titleEl = $('dsk-title');
  subEl = $('dsk-sub');
  $('dsk-close')?.addEventListener('click', () => { closeDesk(); A.recenter?.(true); });
  root.addEventListener('pointerdown', (e) => { if (e.target === root) closeDesk(); });
}
