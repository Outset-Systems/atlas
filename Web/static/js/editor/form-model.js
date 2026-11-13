/* The save contract of a form, with no DOM.

   form.js builds the widgets; this decides what their values become in the
   body that is sent. The rules, which `dataset.py` relies on:

   * A field left blank that was blank before is absent from the body.
   * A field cleared that had a value comes back as `null` — the instruction to
     remove the key.
   * A checkbox is `true` or nothing: unticking one that was ticked is `null`,
     and `false` is never written.
   * A required field left blank is an Error naming every one that is missing.

   Pure functions over field definitions and plain values, so
   tests/test_form_model.mjs can pin them under node. */

/** A number box's text: '' when blank, a number when it is one, else the text
    as typed (validation names it on save). */
export function numberValue(text) {
  if (text.trim() === '') return '';
  const n = Number(text);
  return Number.isNaN(n) ? text : n;
}

/** Text *or* a number: a typed whole number goes back as a number. */
export function scalarValue(text) {
  const raw = text.trim();
  return /^-?\d+$/.test(raw) ? Number(raw) : raw;
}

/** A stored UTC timestamp → what `<input type=datetime-local>` shows
    ("YYYY-MM-DDTHH:MM", read as UTC). '' when it is not a date. */
export function isoToInput(value) {
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? '' : d.toISOString().slice(0, 16);
}

/** …and back: the box's zoneless text, taken as UTC, to a stored timestamp. */
export const inputToIso = (text) => (text ? new Date(text + 'Z').toISOString()
  .replace(/\.\d{3}Z$/, 'Z') : '');

/** One nested object (a service, a range): whatever is blank is left out, and
    so is an unticked checkbox. Nothing is required and nothing is `null` — a
    sub-object is written whole, so there is no key to clear. */
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

/**
 * The body for one entry.
 * @param {object[]} fields   the fields the form shows, in the order it shows them
 * @param {object} original   the entry as it was when the form opened ({} for a new one)
 * @param {object} values     what each widget holds now, by field name
 * @returns {object} only what was set, with `null` for what was cleared
 * @throws {Error} with a human message if a required field is blank
 */
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
      else if (had) out[name] = null;   // an explicit clear
      continue;
    }
    out[name] = value;
  }
  if (missing.length) {
    throw new Error(`${missing.join(', ')} ${missing.length === 1 ? 'is' : 'are'} required`);
  }
  return out;
}
