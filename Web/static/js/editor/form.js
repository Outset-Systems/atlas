
import { esc } from '../config.js';
import { say } from '../words.js';
import Editor from './store.js';
import { inputToIso, isoToInput, numberValue, readEntry, readSub, scalarValue } from './form-model.js';

const el = (tag, cls, html) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (html !== undefined) node.innerHTML = html;
  return node;
};

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
    swatch.value = /^#[0-9a-f]{6}$/i.test(value || '') ? value : '#c49a52';
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
    const node = el('input', 'dsk-input dsk-mono');
    node.type = 'datetime-local';
    if (value) {
      const shown = isoToInput(value);
      if (shown) node.value = shown;
    }
    return { node, read: () => inputToIso(node.value) };
  }

  if (type === 'date') {
    const node = el('input', 'dsk-input');
    const ok = typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value);
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
    return { node, read: () => numberValue(node.value) };
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

  const node = el('input', `dsk-input${['ip', 'cidr', 'slug', 'path'].includes(type) ? ' dsk-mono' : ''}`);
  node.type = 'text';
  node.spellcheck = false;
  node.value = value ?? '';
  if (field.placeholder) node.placeholder = field.placeholder;
  if (type === 'scalar') {
    return { node, read: () => scalarValue(node.value) };
  }
  return { node, read: () => (typeof node.value === 'string' ? node.value.trim() : node.value) };
}

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
      drop.addEventListener('click', () => {
        rows = rows.map((r) => ({ entry: collectSub(field, r) }));
        rows.splice(i, 1);
        draw();
      });
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
    rows = rows.map((r) => ({ entry: collectSub(field, r) }));
    rows.push({ entry: {} });
    draw();
  });

  wrap.append(body, add);
  draw();
  return { node: wrap, read: () => rows.map((r) => collectSub(field, r)) };
}

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

function valuesOf(widgets) {
  const fields = [];
  const values = {};
  for (const [name, { field, widget }] of Object.entries(widgets)) {
    fields.push(field);
    values[name] = widget.read();
  }
  return { fields, values };
}

function collectSub(field, row) {
  const { fields, values } = valuesOf(row.widgets || {});
  return readSub(fields, values);
}

function fieldRow(field, widget) {
  const row = el('label', `dsk-field dsk-field-${field.type}`);
  const label = el('span', 'dsk-label');
  label.innerHTML = esc(say(field.label)) + (field.required ? '<i class="dsk-req">*</i>' : '');
  row.append(label, widget);
  if (field.help) row.append(el('span', 'dsk-help', esc(field.help)));
  return row;
}

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

  const unmodelled = only ? [] : Object.keys(original).filter(
    (k) => k !== 'provenance' && !section.fields.some((f) => f.name === k));
  if (unmodelled.length) {
    form.append(el('div', 'dsk-extra',
      `<span class="dsk-extra-head">also on file, kept as-is</span>` +
      unmodelled.map((k) => `<code>${esc(k)}</code>`).join(' ')));
  }

  return {
    el: form,
    focus() { form.querySelector('input,select,textarea')?.focus(); },
    get(name) { return widgets[name]?.widget.read(); },
    set(name, value) {
      const widget = widgets[name]?.widget;
      if (!widget) return false;
      widget.node.value = value ?? '';
      return true;
    },
    row(name) { return rows[name] || null; },
    read() {
      const { fields: shown, values } = valuesOf(widgets);
      return readEntry(shown, original, values);
    },
  };
}

export { el as makeEl };
