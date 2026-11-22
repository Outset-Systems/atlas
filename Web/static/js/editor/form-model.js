
export function numberValue(text) {
  if (text.trim() === '') return '';
  const n = Number(text);
  return Number.isNaN(n) ? text : n;
}

export function scalarValue(text) {
  const raw = text.trim();
  return /^-?\d+$/.test(raw) ? Number(raw) : raw;
}

export function isoToInput(value) {
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? '' : d.toISOString().slice(0, 16);
}

export const inputToIso = (text) => (text ? new Date(text + 'Z').toISOString()
  .replace(/\.\d{3}Z$/, 'Z') : '');

export function readSub(fields, values) {
  const out = {};
  for (const sub of fields) {
    const name = sub.name;
    const raw = values[name];
    if (raw === '' || raw === undefined) continue;
    if (Array.isArray(raw) && !raw.length) continue;
    if (sub.type === 'bool' && raw === false) continue;
    out[name] = raw;
  }
  return out;
}

export function readEntry(fields, original, values) {
  const out = {};
  const missing = [];
  for (const field of fields) {
    const name = field.name;
    let value = values[name];
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
      else if (had) out[name] = null;
      continue;
    }
    out[name] = value;
  }
  if (missing.length) {
    throw new Error(`${missing.join(', ')} ${missing.length === 1 ? 'is' : 'are'} required`);
  }
  return out;
}
