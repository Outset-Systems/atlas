/* Forms rendered from the field catalogue.

   Every editor in the Atlas — places, realms, prefixes, roads, ports, the
   rack, the vassals, the rites, the watchings — is this one function reading
   `Web/schema.py`. Adding a field to the map is an entry in the catalogue,
   not a new form here and a new validator there.

   The contract with the server: `read()` returns only what the human actually
   set. A field left blank that was blank before is simply absent; a field
   cleared that had a value comes back as `null`, which is how `dataset.py`
   is told to remove a key. That distinction is what keeps a save from
   sprinkling `"hue": ""` through a hand-written dataset. */

import { esc } from '../config.js';
import Editor from './store.js';

const el = (tag, cls, html) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (html !== undefined) node.innerHTML = html;
  return node;
};

/** Options for a reference field: every entry of the target section. */
function refOptions(target) {
  const section = Editor.section(target);
  const idField = section?.id_field || 'id';
  const titleField = section?.title_field;
  return Editor.entries(target).map((entry) => {
    const value = entry[idField];
    const title = titleField && entry[titleField];
    return { value, label: title && title !== value ? `${value} — ${title}` : String(value ?? '') };
  }).filter((o) => o.value !== undefined && o.value !== null);
}

function selectEl(options, value, allowBlank) {
  const node = el('select', 'dsk-input');
  const list = allowBlank ? [{ value: '', label: '—' }, ...options] : options;
  node.innerHTML = list.map((o) =>
    `<option value="${esc(o.value)}"${String(o.value) === String(value ?? '') ? ' selected' : ''}>` +
    `${esc(o.label ?? o.value)}</option>`).join('');
  return node;
}

/* ── One widget per field type ─────────────────────────────────────────── */

function buildWidget(field, value) {
  const type = field.type;

  if (type === 'bool') {
    const node = el('input', 'dsk-check');
    node.type = 'checkbox';
    node.checked = value === true;
    return { node, read: () => node.checked };
  }

  if (type === 'longtext') {
    const node = el('textarea', 'dsk-input dsk-area');
    node.rows = 3;
    node.value = value ?? '';
    return { node, read: () => node.value.trim() };
  }

  if (type === 'select') {
    const options = (field.options || []).map((o) => ({ value: o, label: o || '—' }));
    const node = selectEl(options, value, !field.required && !(field.options || []).includes(''));
    return { node, read: () => node.value };
  }

  if (type === 'ref') {
    const node = selectEl(refOptions(field.ref), value, !field.required);
    // A reference to something no longer charted must stay visible, or saving
    // an unrelated field would quietly repoint it at the first entry.
    if (value && ![...node.options].some((o) => o.value === String(value))) {
      node.insertAdjacentHTML('afterbegin',
        `<option value="${esc(value)}" selected>${esc(value)} — no longer charted</option>`);
    }
    return { node, read: () => node.value };
  }

  if (type === 'color') {
    const wrap = el('div', 'dsk-color');
    const swatch = el('input', 'dsk-swatch');
    swatch.type = 'color';
    swatch.value = /^#[0-9a-f]{6}$/i.test(value || '') ? value : '#c49a52';   // the design notes's gold zone hue
    const text = el('input', 'dsk-input dsk-color-text');
    text.type = 'text';
    text.placeholder = '#C49A52';
    text.value = value ?? '';
    swatch.addEventListener('input', () => { text.value = swatch.value.toUpperCase(); });
    text.addEventListener('input', () => {
      if (/^#[0-9a-f]{6}$/i.test(text.value)) swatch.value = text.value;
    });
    wrap.append(swatch, text);
    return { node: wrap, read: () => text.value.trim() };
  }

  if (type === 'datetime') {
    // <input type=datetime-local> speaks "YYYY-MM-DDTHH:MM" with no zone. The
    // server stores UTC, so convert both ways rather than letting the browser's
    // zone silently decide when a maintenance window opens.
    const node = el('input', 'dsk-input dsk-mono');
    node.type = 'datetime-local';
    if (value) {
      const d = new Date(value);
      if (!Number.isNaN(d.getTime())) node.value = d.toISOString().slice(0, 16);
    }
    return {
      node,
      read: () => (node.value ? new Date(node.value + 'Z').toISOString()
        .replace(/\.\d{3}Z$/, 'Z') : ''),
    };
  }

  // a calendar day, stored as YYYY-MM-DD (a canary token's `expires`, v1.52.0)
  if (type === 'date') {
    const node = el('input', 'dsk-input');
    const ok = typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value);
    // a stored value the date picker cannot show stays visible as text, so
    // opening the form never quietly erases it (validation names it on save)
    node.type = ok || !value ? 'date' : 'text';
    node.value = value ?? '';
    return { node, read: () => node.value.trim() };
  }

  if (type === 'int' || type === 'number' || type === 'percent') {
    const node = el('input', 'dsk-input dsk-num');
    node.type = 'number';
    node.step = type === 'int' ? '1' : 'any';
    if (field.min !== undefined) node.min = field.min;
    if (field.max !== undefined) node.max = field.max;
    node.value = value ?? '';
    return {
      node,
      read: () => {
        if (node.value.trim() === '') return '';
        const n = Number(node.value);
        return Number.isNaN(n) ? node.value : n;
      },
    };
  }

  if (type === 'strings') {
    return buildStringList(field, value);
  }

  if (type === 'objects') {
    return buildObjectList(field, value);
  }

  if (type === 'object') {
    return buildObjectGroup(field, value);
  }

  if (type === 'json') {
    const node = el('textarea', 'dsk-input dsk-area dsk-mono');
    node.rows = 4;
    node.value = value === undefined || value === null ? '' : JSON.stringify(value, null, 1);
    return {
      node,
      read: () => {
        const raw = node.value.trim();
        if (!raw) return '';
        try { return JSON.parse(raw); } catch { throw new Error(`${field.label}: that is not valid JSON`); }
      },
    };
  }

  // text · slug · path · url · link · ip · cidr · scalar
  const node = el('input', `dsk-input${['ip', 'cidr', 'slug', 'path'].includes(type) ? ' dsk-mono' : ''}`);
  node.type = 'text';
  node.spellcheck = false;
  node.value = value ?? '';
  if (field.placeholder) node.placeholder = field.placeholder;
  if (type === 'scalar') {
    // text *or* a number (a VLAN is `4` or `—`): a typed whole number goes back
    // as a number, so saving a realm never turns the dataset's `4` into "4"
    return {
      node,
      read: () => {
        const raw = node.value.trim();
        return /^-?\d+$/.test(raw) ? Number(raw) : raw;
      },
    };
  }
  return { node, read: () => (typeof node.value === 'string' ? node.value.trim() : node.value) };
}

/** A list of plain strings — or, when the field points at a section, a list
    of references picked from what exists. */
function buildStringList(field, value) {
  const wrap = el('div', 'dsk-list');
  const chips = el('div', 'dsk-chips');
  let items = Array.isArray(value) ? [...value] : [];

  const draw = () => {
    chips.innerHTML = items.map((item, i) =>
      `<span class="dsk-chip">${esc(item)}<button type="button" class="dsk-chip-x" ` +
      `data-i="${i}" title="Remove">×</button></span>`).join('') ||
      '<span class="dsk-chips-empty">none</span>';
    chips.querySelectorAll('.dsk-chip-x').forEach((btn) => {
      btn.addEventListener('click', () => { items.splice(Number(btn.dataset.i), 1); draw(); });
    });
  };

  const row = el('div', 'dsk-list-add');
  let input;
  if (field.ref) {
    input = selectEl(refOptions(field.ref), '', true);
  } else {
    input = el('input', 'dsk-input');
    input.type = 'text';
  }
  const add = el('button', 'dsk-btn dsk-btn-sm', 'Add');
  add.type = 'button';
  add.addEventListener('click', () => {
    const raw = String(input.value || '').trim();
    if (raw && !items.includes(raw)) { items.push(raw); draw(); }
    input.value = '';
  });
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); add.click(); }
  });
  row.append(input, add);
  wrap.append(chips, row);
  draw();
  return { node: wrap, read: () => items };
}

/** A list of sub-objects — a node's services, a prefix's ranges. */
function buildObjectList(field, value) {
  const wrap = el('div', 'dsk-sublist');
  const body = el('div', 'dsk-sublist-body');
  let rows = (Array.isArray(value) ? value : []).map((entry) => ({ entry }));

  const draw = () => {
    body.innerHTML = '';
    if (!rows.length) body.append(el('div', 'dsk-chips-empty', 'none yet'));
    rows.forEach((row, i) => {
      const card = el('div', 'dsk-subcard');
      const head = el('div', 'dsk-subcard-head');
      head.append(el('span', 'dsk-subcard-n', `${field.label} ${i + 1}`));
      const drop = el('button', 'dsk-chip-x', '×');
      drop.type = 'button';
      drop.title = 'Remove';
      drop.addEventListener('click', () => { rows.splice(i, 1); draw(); });
      head.append(drop);
      card.append(head);
      row.widgets = {};
      for (const sub of field.of || []) {
        const widget = buildWidget(sub, row.entry?.[sub.name]);
        row.widgets[sub.name] = { field: sub, widget };
        card.append(fieldRow(sub, widget.node));
      }
      body.append(card);
    });
  };

  const add = el('button', 'dsk-btn dsk-btn-sm', `+ add`);
  add.type = 'button';
  add.addEventListener('click', () => {
    // Keep what's typed in the existing rows when a new one appears.
    rows = rows.map((r) => ({ entry: collectSub(field, r) }));
    rows.push({ entry: {} });
    draw();
  });

  wrap.append(body, add);
  draw();
  return { node: wrap, read: () => rows.map((r) => collectSub(field, r)) };
}

/** A single nested group of settings — `meta.tribute`, not a list. */
function buildObjectGroup(field, value) {
  const card = el('div', 'dsk-subcard');
  const widgets = {};
  for (const sub of field.of || []) {
    const widget = buildWidget(sub, (value || {})[sub.name]);
    widgets[sub.name] = { field: sub, widget };
    card.append(fieldRow(sub, widget.node));
  }
  return { node: card, read: () => collectSub(field, { widgets }) };
}

function collectSub(field, row) {
  const out = {};
  for (const [name, { field: sub, widget }] of Object.entries(row.widgets || {})) {
    const raw = widget.read();
    if (raw === '' || raw === undefined) continue;
    if (Array.isArray(raw) && !raw.length) continue;
    if (sub.type === 'bool' && raw === false) continue;
    out[name] = raw;
  }
  return out;
}

function fieldRow(field, widget) {
  const row = el('label', `dsk-field dsk-field-${field.type}`);
  const label = el('span', 'dsk-label');
  label.innerHTML = esc(field.label) + (field.required ? '<i class="dsk-req">*</i>' : '');
  row.append(label, widget);
  if (field.help) row.append(el('span', 'dsk-help', esc(field.help)));
  return row;
}

/**
 * Build a form for one entry of a section.
 * @param {{only?: string[]}} [opts] `only`: show and read just these fields
 *   (the first survey asks for the few a newcomer needs). Everything else is
 *   left untouched: `read()` never mentions it, so an upsert merges around it.
 * @returns {{el: HTMLElement, read: () => object, focus: () => void}}
 *   `read()` throws an Error with a human message if a required field is blank.
 */
export function buildForm(sectionKey, entry, opts = {}) {
  const section = Editor.section(sectionKey);
  const original = entry || {};
  const form = el('div', 'dsk-form');
  const widgets = {};
  const only = opts.only ? new Set(opts.only) : null;
  const fields = only ? section.fields.filter((f) => only.has(f.name)) : section.fields;

  const rows = {};
  for (const field of fields) {
    const widget = buildWidget(field, original[field.name]);
    widgets[field.name] = { field, widget };
    rows[field.name] = fieldRow(field, widget.node);
    form.append(rows[field.name]);
  }

  // Keys the catalogue doesn't model are shown, read-only, rather than hidden:
  // the dataset is allowed to be richer than the form, and a field you cannot
  // see is a field you will accidentally destroy. A trimmed form hides fields
  // on purpose and never writes them, so it has nothing to warn about.
  const unmodelled = only ? [] : Object.keys(original).filter(
    (k) => !section.fields.some((f) => f.name === k));
  if (unmodelled.length) {
    form.append(el('div', 'dsk-extra',
      `<span class="dsk-extra-head">also on file, kept as-is</span>` +
      unmodelled.map((k) => `<code>${esc(k)}</code>`).join(' ')));
  }

  return {
    el: form,
    focus() { form.querySelector('input,select,textarea')?.focus(); },
    /** Read one field's current value, and write one back.

        Added for THE BACKDROP, where picking a render from the gallery has to
        put its filename into `map_image` so the single Save still writes it.
        Exposed as a pair of methods rather than letting callers query the DOM:
        the widgets deliberately carry no `name` attribute, so a selector-based
        reach-in would be matching on markup that isn't a contract — it would
        have failed silently the first time a widget changed shape. */
    get(name) { return widgets[name]?.widget.read(); },
    set(name, value) {
      const widget = widgets[name]?.widget;
      if (!widget) return false;
      widget.node.value = value ?? '';
      return true;
    },
    /** The row a field sits in, so a helper can be seated beside it (the
        region rectangle's "use the current view"). Null for a field this
        form does not show. */
    row(name) { return rows[name] || null; },
    read() {
      const out = {};
      const missing = [];
      for (const [name, { field, widget }] of Object.entries(widgets)) {
        let value = widget.read();
        const had = Object.prototype.hasOwnProperty.call(original, name);

        if (field.type === 'bool') {
          if (value === true) out[name] = true;
          else if (had && original[name] === true) out[name] = null;
          continue;
        }
        const blank = value === '' || value === undefined ||
                      (Array.isArray(value) && value.length === 0);
        if (blank) {
          if (field.required) missing.push(field.label);
          else if (had) out[name] = null;   // an explicit clear
          continue;
        }
        out[name] = value;
      }
      if (missing.length) {
        throw new Error(`${missing.join(', ')} ${missing.length === 1 ? 'is' : 'are'} required`);
      }
      return out;
    },
  };
}

export { el as makeEl };
