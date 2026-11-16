/* THE ROSTER's rules, with no DOM: what a place's stamp says, how the table
   sorts and filters, what this browser remembers, and how a long list of
   writes is cut into saves. Pure, so node can test it
   (tests/test_roster_model.mjs, and tests/test_standing.mjs through the
   re-export in editor/standing.js).

   Two readers share it (2026-11-13): the Desk's table of places
   (editor/panel.js) and NODES (nodes.js). The standing and review rules moved
   here from editor/standing.js unchanged, so the two can never disagree about
   which places nobody has checked.

   The server writes the stamp (provenance.py) and is the only one who may.
   This file only reads it back. */

/* ── what a place's stamp says (moved from editor/standing.js) ───────────── */

/** 'checked' | 'changed' | 'unchecked' | 'unknown' (charted before the map kept the record).
    'changed' is a place a person checked that has changed since: the review
    stands for what was there, and what changed is waiting for a look. The rule
    is the server's (`provenance.settled`), so the Desk lists exactly the places
    a cloud token is not being shown: the mark an import leaves, a stamp whose
    change is later than its review, or one that cannot say when it was reviewed. */
export function standing(entry) {
  const mark = entry && entry.provenance;
  if (!mark || typeof mark !== 'object' || typeof mark.reviewed !== 'boolean') return 'unknown';
  if (!mark.reviewed) return 'unchecked';
  const reviewed = String(mark.reviewed_at || '');
  if (mark.changed_since_review === true || !reviewed || String(mark.changed_at || '') > reviewed) return 'changed';
  return 'checked';
}

const day = (stamp) => String(stamp || '').slice(0, 10);

function by(who, when) {
  if (who && when) return `by ${who} on ${day(when)}`;
  if (when) return `on ${day(when)}`;
  return who ? `by ${who}` : '';
}

/** One or two sentences for the form's head and a row's tooltip. */
export function sentence(entry) {
  const mark = (entry && entry.provenance) || {};
  const state = standing(entry);
  const parts = [];
  if (mark.charted_at || mark.charted_by) {
    const from = mark.source && mark.source !== 'hand' ? `, from ${mark.source}` : '';
    parts.push(`Charted ${by(mark.charted_by, mark.charted_at)}${from}.`);
  } else {
    parts.push('Charted before the map kept a record of who and when.');
  }
  if (state === 'checked' || state === 'changed') {
    parts.push(`Checked ${by(mark.reviewed_by, mark.reviewed_at)}`.trim() + '.');
    if (state === 'changed') parts.push('It has changed since, and nobody has looked at what changed.');
  } else {
    parts.push('Not yet checked by a person.');
  }
  return parts.join(' ');
}

/** The line above the table: how many are waiting, and why. */
export function waiting(entries, plural = 'places') {
  const pending = entries.filter((e) => standing(e) !== 'checked');
  if (!pending.length) return '';
  const unknown = pending.filter((e) => standing(e) === 'unknown').length;
  const changed = pending.filter((e) => standing(e) === 'changed').length;
  const imported = pending.length - unknown - changed;
  const n = pending.length;
  let head = `${n} of ${entries.length} ${plural} ${n === 1 ? 'has' : 'have'} not been checked by a person.`;
  if (n === entries.length) {
    head = n === 1 ? 'The one entry here has not been checked by a person.'
      : `None of the ${n} ${plural} here has been checked by a person.`;
  }
  // a changed place WAS checked, so "has not been checked" would be untrue of it
  if (changed) head = `${n} of ${entries.length} ${plural} ${n === 1 ? 'is' : 'are'} waiting for a person to look.`;
  const why = [];
  if (imported) why.push(`${imported} came from an import`);
  if (changed) why.push(`${changed} changed after being checked`);
  if (unknown) why.push(`${unknown} ${unknown === 1 ? 'was' : 'were'} charted before the map kept this record`);
  return `${head} ${why.join(', ')}.`;
}

/** A roster row's standing. The row carries the stamp's fields flat; the
    server's own `unchecked` (v1.69.0's rule, worked out where the stamp is
    written) decides between waiting and checked whenever it is given. */
export function rowStanding(row) {
  if (!row || typeof row.reviewed !== 'boolean') return 'unknown';
  const mine = standing({ provenance: {
    reviewed: row.reviewed, reviewed_at: row.reviewed_at, changed_since_review: row.changed_since_review,
  } });
  if (typeof row.unchecked !== 'boolean') return mine;
  if (!row.unchecked) return 'checked';
  return mine === 'checked' ? 'changed' : mine;
}

/** True when a person still has to look at this row. */
export const rowWaiting = (row) => (typeof row?.unchecked === 'boolean'
  ? row.unchecked : rowStanding(row) !== 'checked');

/** What pressing a row does (2026-11-13): the card already up on
    this place closes; any other press opens this place's card, as a marker
    on the map does. `shownId` is the place the card shows, or null. */
export const rowPress = (shownId, id) =>
  (typeof shownId === 'string' && shownId !== '' && shownId === id ? 'close' : 'open');

/* ── checked by a person: the writes ─────────────────────────────────────── */

/** The store takes 500 changes in one save; every bulk write is cut at 400. */
export const REVIEW_BATCH = 400;

/** `list` in pieces of at most `size`, in order. */
export function batches(list, size = REVIEW_BATCH) {
  const all = Array.isArray(list) ? list : [];
  const step = Math.max(1, Math.floor(Number(size) || REVIEW_BATCH));
  const out = [];
  for (let i = 0; i < all.length; i += step) out.push(all.slice(i, i + step));
  return out;
}

/** "I have looked at these and they are right", one op per place. */
export const reviewOps = (ids) => ids.map((id) => ({ op: 'review', section: 'nodes', id }));

/** Run `save` on each batch in turn. A save that answers nothing (someone
    else saved first, and the caller has already reloaded) stops the run.
    Resolves {done, stopped}: how many items were written, and whether it stopped. */
export async function inBatches(list, save, size = REVIEW_BATCH) {
  let done = 0;
  for (const part of batches(list, size)) {
    const result = await save(part);
    if (!result) return { done, stopped: true };
    done += part.length;
  }
  return { done, stopped: false };
}

/** Two presses (v1.69.0): the first counts what is on screen and says so, the
    second writes. `press(count)` takes a function that lists the ids now;
    it answers {armed: ids} on the first press, {write: ids} on the second
    (the ids counted on the first, not a recount), and {none: true} when there
    is nothing to mark. Anything else that changes the list calls `disarm`. */
export function twoPress() {
  let armed = null;
  return {
    get armed() { return armed; },
    press(count) {
      if (armed) { const ids = armed; armed = null; return { write: ids }; }
      const ids = [...(count() || [])];
      if (!ids.length) return { none: true };
      armed = ids;
      return { armed: ids };
    },
    disarm() { armed = null; },
  };
}

/** The armed button's words. */
export const armedLabel = (n) => `Yes, I have checked ${n === 1 ? 'this one' : `these ${n}`}`;
/** The toast once they are written. */
export const markedLine = (n) => (n === 1 ? 'Marked as checked.' : `${n} marked as checked.`);

/* ── sorting ─────────────────────────────────────────────────────────────── */

/** Worst first: what is broken outranks what is resting, and unknown is last. */
export const SEVERITY = ['down', 'degraded', 'maintenance', 'slumbering', 'healthy'];

const DAY_MS = 86400000;
const blank = (v) => v === null || v === undefined || v === '' || (typeof v === 'number' && Number.isNaN(v));
const time = (v) => { const t = Date.parse(v); return Number.isNaN(t) ? null : t; };

/** A dotted IPv4 address as one number, or null when it is not one. */
export function ipv4Number(text) {
  const m = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?:\/\d{1,2})?$/.exec(String(text ?? '').trim());
  if (!m) return null;
  const parts = m.slice(1).map(Number);
  if (parts.some((p) => p > 255)) return null;
  return ((parts[0] * 256 + parts[1]) * 256 + parts[2]) * 256 + parts[3];
}

/** A row's first address as a sort key: IPv4 numerically, anything else
    (a name, IPv6) after every IPv4, by its text. No address is blank. */
function addressKey(row) {
  const first = (row.addresses || []).find((a) => !blank(a));
  if (blank(first)) return null;
  const n = ipv4Number(first);
  return n === null ? [1, String(first).toLowerCase()] : [0, n];
}

function collectionNames(row, collections) {
  const names = new Map((collections || []).map((s) => [s.id, s.name || s.id]));
  return (row.collections || []).map((id) => names.get(id) || id);
}

/** What each column sorts on. Blank values (null) always sort last. */
const KEYS = {
  state: (r) => { const i = SEVERITY.indexOf(r.state); return i < 0 ? null : i; },
  name: (r) => String(r.name || r.id || '').toLowerCase(),
  zone: (r) => (blank(r.zone_name) && blank(r.zone) ? null : String(r.zone_name || r.zone).toLowerCase()),
  kind: (r) => {
    const t = [r.kind, r.role].filter((v) => !blank(v)).join(' ').toLowerCase();
    return t || null;
  },
  addresses: addressKey,
  services: (r) => (typeof r.services === 'number' ? r.services : null),
  confirmed_by: (r) => (blank(r.confirmed_by) ? null : String(r.confirmed_by).toLowerCase()),
  reviewed: (r) => time(r.reviewed_at),
  maintenance: (r) => {
    const m = r.maintenance || {};
    if (m.now) return -Infinity;            // open now comes before any next start
    return blank(m.next) ? null : time(m.next);
  },
  cert: (r) => (r.cert && typeof r.cert.days === 'number' ? r.cert.days : null),
  collections: (r, ctx) => {
    const n = collectionNames(r, ctx.collections);
    return n.length ? n.join(', ').toLowerCase() : null;
  },
};

/** Sort keys and filter keys under an old name -> today's (collections were
    sets until 2026-11-14), so a sort or a filter this browser kept still works. */
const OLD_KEYS = Object.freeze({ sets: 'collections', set: 'collection' });

export const SORT_KEYS = Object.keys(KEYS);

/* One collator for every comparison: `localeCompare` with options makes a new
   one each call, which was most of a sort of 2,000 rows (stage 5). The same
   locale and options, so the same order. */
const COLLATOR = new Intl.Collator(undefined, { numeric: true });

function compare(a, b) {
  if (Array.isArray(a)) {
    for (let i = 0; i < a.length; i++) { const c = compare(a[i], b[i]); if (c) return c; }
    return 0;
  }
  if (typeof a === 'number' && typeof b === 'number') return a - b;
  return COLLATOR.compare(String(a), String(b));
}

/** A new array of `rows` sorted on one column. `dir` 'asc' or 'desc'; blank
    values stay last either way, and ties fall back to the name, then the id,
    so the order never shuffles between draws. `collections` names the
    collections column. */
export function sortRows(rows, key = 'name', dir = 'asc', collections = []) {
  const pick = KEYS[OLD_KEYS[key] || key] || KEYS.name;
  const sign = dir === 'desc' ? -1 : 1;
  const ctx = { collections };
  return (rows || [])
    .map((row) => ({ row, k: pick(row, ctx) }))
    .sort((x, y) => {
      const xb = blank(x.k); const yb = blank(y.k);
      if (xb !== yb) return xb ? 1 : -1;
      const c = xb ? 0 : sign * compare(x.k, y.k);
      if (c) return c;
      return compare(KEYS.name(x.row), KEYS.name(y.row)) || compare(String(x.row.id), String(y.row.id));
    })
    .map((x) => x.row);
}

/* ── filtering ───────────────────────────────────────────────────────────── */

/** The words a row is found by (the Index's `data-search` idea). */
export const haystack = (row) => [row.name, row.id, ...(row.addresses || []), row.role, row.zone_name]
  .filter((v) => !blank(v)).join(' ').toLowerCase();

/** True when nobody has checked this row in `days` days: never checked, or
    the last check is `days` days old or older (exactly 90 days old counts). */
export function staleFor(row, days, now = Date.now()) {
  const at = row?.reviewed ? time(row.reviewed_at) : null;
  if (at === null) return true;
  return now - at >= days * DAY_MS;
}

/** The empty filter: everything shows. */
export const NO_FILTER = Object.freeze({
  text: '', state: '', zone: '', kind: '', collection: '', unchecked: false, staleDays: 0,
});

/** `rows` that pass every criterion given. `state: 'unknown'` matches a row
    the feed says nothing about. `staleDays: 90` means not checked in 90 days. */
/** What a row's state reads as: `unmanaged` for a place nobody watches
    (2026-11-14: it has no state, on purpose), else its state, else
    `unknown`. The filter and the table say the same. */
export function rowState(row) {
  if (row && row.unmanaged === true) return 'unmanaged';
  return SEVERITY.includes(row?.state) ? row.state : 'unknown';
}

export function filterRows(rows, filter = {}, now = Date.now()) {
  const f = { ...NO_FILTER, ...(filter || {}) };
  const words = String(f.text || '').trim().toLowerCase().split(/\s+/).filter(Boolean);
  const stale = Number(f.staleDays) || 0;
  return (rows || []).filter((row) => {
    if (words.length) { const hay = haystack(row); if (!words.every((w) => hay.includes(w))) return false; }
    if (f.state && rowState(row) !== f.state) return false;
    if (f.zone && row.zone !== f.zone) return false;
    if (f.kind && row.kind !== f.kind) return false;
    if (f.collection && !(row.collections || []).includes(f.collection)) return false;
    if (f.unchecked && !rowWaiting(row)) return false;
    if (stale > 0 && !staleFor(row, stale, now)) return false;
    return true;
  });
}

/** True when the filter shows everything. */
export const isEmptyFilter = (filter) => {
  const f = { ...NO_FILTER, ...(filter || {}) };
  return !String(f.text).trim() && !f.state && !f.zone && !f.kind && !f.collection
    && !f.unchecked && !Number(f.staleDays);
};

/** A filter cut down to the keys it may hold, of the types they take. */
export function cleanFilter(raw) {
  const f = raw && typeof raw === 'object' ? raw : {};
  const str = (v) => (typeof v === 'string' ? v.slice(0, 200) : '');
  return {
    text: str(f.text), state: str(f.state), zone: str(f.zone), kind: str(f.kind),
    collection: str(f.collection) || str(f.set),   // `set`: a filter kept before 2026-11-14
    unchecked: f.unchecked === true,
    staleDays: Number.isFinite(Number(f.staleDays)) && Number(f.staleDays) > 0 ? Math.floor(Number(f.staleDays)) : 0,
  };
}

/* ── the rail: collections, networks and kinds down the side (2026-11-14) ── */

/** The states that put a dot on a rail row: something inside needs a look. */
export const TROUBLE = Object.freeze(['down', 'degraded']);

function group(id, name, rows) {
  const trouble = rows.filter((r) => TROUBLE.includes(r.state));
  const worst = TROUBLE.find((s) => trouble.some((r) => r.state === s)) || '';
  return { id, name: name || id, count: rows.length, trouble: trouble.length, worst };
}

/** The rail's three lists from one roster answer: each row's name, how many
    places in it this viewer may see, and its worst trouble ('down',
    'degraded' or ''). Made from the rows the server already cut for this
    viewer, so a hidden place is never counted. Collections keep the order
    the map gives them (an empty one is listed: it was made for a reason);
    networks keep the map's order and list only those with a place in them;
    kinds are in name order. */
export function railGroups(roster) {
  const r = roster || {};
  const rows = (Array.isArray(r.rows) ? r.rows : []).filter((x) => x && typeof x === 'object');
  const members = new Map();
  for (const x of rows) for (const id of x.collections || []) {
    if (!members.has(id)) members.set(id, []);
    members.get(id).push(x);
  }
  const collections = (Array.isArray(r.collections) ? r.collections : [])
    .filter((c) => c && typeof c.id === 'string')
    .map((c) => group(c.id, c.name, members.get(c.id) || []));
  const byZone = new Map();
  const byKind = new Map();
  for (const x of rows) {
    if (!blank(x.zone)) { if (!byZone.has(x.zone)) byZone.set(x.zone, []); byZone.get(x.zone).push(x); }
    if (!blank(x.kind)) { if (!byKind.has(x.kind)) byKind.set(x.kind, []); byKind.get(x.kind).push(x); }
  }
  const networks = (Array.isArray(r.zones) ? r.zones : [])
    .filter((z) => z && typeof z.id === 'string' && byZone.has(z.id))
    .map((z) => group(z.id, z.name, byZone.get(z.id)));
  const kinds = [...byKind.keys()].sort((a, b) => String(a).localeCompare(String(b)))
    .map((k) => group(k, k, byKind.get(k)));
  return { collections, networks, kinds };
}

/** The groups a filter may name: the rail's, with every network the roster
    lists (a phone's picker offers empty networks too, and a filter on one of
    them must stay, not be reset by the next draw). */
export function filterGroups(roster) {
  const groups = railGroups(roster);
  const zones = Array.isArray(roster?.zones) ? roster.zones : [];
  return { ...groups, networks: zones.filter((z) => z && typeof z.id === 'string') };
}

/** A collection's `places` as a list: one id or a list of them, as the
    server reads it (`schema.as_list`). */
export const memberList = (places) => (Array.isArray(places) ? places
  : (typeof places === 'string' && places ? [places] : []));

/** Which filter field each rail section sets. */
export const RAIL_FIELDS = Object.freeze({ collections: 'collection', networks: 'zone', kinds: 'kind' });

/** A rail row pressed: its value, or nothing when it was already the filter
    (a second press shows everything again). Returns the filter patch. */
export function railPress(filter, section, id) {
  const field = RAIL_FIELDS[section];
  if (!field) return {};
  return { [field]: (filter || {})[field] === id ? '' : id };
}

/** The filter with any rail value that names nothing in `groups` emptied: an
    old saved filter, or a collection this viewer may not see, shows everything
    rather than nothing. */
export function dropUnknown(filter, groups) {
  const f = { ...(filter || {}) };
  for (const [section, field] of Object.entries(RAIL_FIELDS)) {
    if (f[field] && !((groups || {})[section] || []).some((g) => g.id === f[field])) f[field] = '';
  }
  return f;
}

export const RAIL_KEY = 'atlas.nodes.rail';
/** The rail's sections, in order. */
export const RAIL_SECTIONS = Object.freeze(['collections', 'networks', 'kinds', 'saved']);

/** Which sections this browser had shut: {section: true}. Everything is open
    unless it was shut; junk reads as nothing shut. */
export function readRail(storage) {
  const raw = readJSON(storage, RAIL_KEY);
  const out = {};
  if (raw && typeof raw === 'object') for (const k of RAIL_SECTIONS) if (raw[k] === true) out[k] = true;
  return out;
}
export const writeRail = (storage, shut) => writeJSON(storage, RAIL_KEY,
  Object.fromEntries(RAIL_SECTIONS.filter((k) => shut?.[k] === true).map((k) => [k, true])));

/* ── what this browser remembers (a convenience, never a collection) ─────── */

export const SAVED_KEY = 'atlas.nodes.saved';
export const SORT_KEY = 'atlas.nodes.sort';

function readJSON(storage, key) {
  try {
    const raw = storage?.getItem(key);
    return raw ? JSON.parse(raw) : null;
  } catch { return null; }
}
function writeJSON(storage, key, value) {
  try { storage?.setItem(key, JSON.stringify(value)); return true; } catch { return false; }
}

/** The current sort, or name ascending when nothing usable is stored. */
export function readSort(storage) {
  const s = readJSON(storage, SORT_KEY);
  const key = s && (OLD_KEYS[s.key] || s.key);
  return key && SORT_KEYS.includes(key) && (s.dir === 'asc' || s.dir === 'desc')
    ? { key, dir: s.dir } : { key: 'name', dir: 'asc' };
}
export const writeSort = (storage, sort) => writeJSON(storage, SORT_KEY, { key: sort.key, dir: sort.dir });

/** The saved filters: [{name, filter, sort?}], each cleaned; junk is dropped. */
export function readSaved(storage) {
  const list = readJSON(storage, SAVED_KEY);
  if (!Array.isArray(list)) return [];
  return list
    .filter((s) => s && typeof s.name === 'string' && s.name.trim())
    .map((s) => ({
      name: s.name.trim().slice(0, 60),
      filter: cleanFilter(s.filter),
      ...(s.sort && SORT_KEYS.includes(OLD_KEYS[s.sort.key] || s.sort.key)
        ? { sort: { key: OLD_KEYS[s.sort.key] || s.sort.key, dir: s.sort.dir === 'desc' ? 'desc' : 'asc' } } : {}),
    }));
}
export const writeSaved = (storage, list) => writeJSON(storage, SAVED_KEY, list);

/** The list with `name` saved (a filter of the same name is replaced in place). */
export function withSaved(list, name, filter, sort) {
  const clean = String(name || '').trim().slice(0, 60);
  if (!clean) return [...(list || [])];
  const entry = { name: clean, filter: cleanFilter(filter), ...(sort ? { sort: { key: sort.key, dir: sort.dir } } : {}) };
  const out = [...(list || [])];
  const at = out.findIndex((s) => s.name.toLowerCase() === clean.toLowerCase());
  if (at >= 0) out[at] = entry; else out.push(entry);
  return out;
}
export const withoutSaved = (list, name) => (list || []).filter((s) => s.name !== name);

/* ── words a cell needs worked out ───────────────────────────────────────── */

/** Whole days between `iso` and `now` (positive in the past). null when not a date. */
export function daysSince(iso, now = Date.now()) {
  const t = time(iso);
  return t === null ? null : Math.floor((now - t) / DAY_MS);
}

/** 'down' under 7 days or lapsed, 'warn' under 30, '' otherwise or unknown. */
export function certTone(days) {
  if (typeof days !== 'number' || Number.isNaN(days)) return '';
  // the same edges as OVERVIEW's certClass: "within 30 days" includes the 30th
  if (days <= 7) return 'down';
  if (days <= 30) return 'warn';
  return '';
}

/** A short, safe id for a new collection or window: lowercase, dashes,
    starting with a letter or digit (schema.py `_SLUG_RE`), and not one
    already taken. */
export function slugFor(text, taken = [], fallback = 'collection') {
  // every mark (\p{M}), the same as redaction.slug on the server
  const base = String(text || '').toLowerCase().normalize('NFKD').replace(/\p{M}/gu, '')
    .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 48) || fallback;
  const used = new Set(taken);
  if (!used.has(base)) return base;
  let n = 2;
  while (used.has(`${base}-${n}`)) n++;
  return `${base}-${n}`;
}

/** What a place needs after adding `more`: its own list kept, the new ones
    added once each, and never the place itself. */
export function mergeNeeds(id, existing, more) {
  const out = [];
  for (const v of [...(Array.isArray(existing) ? existing : []), ...(more || [])]) {
    if (v && v !== id && !out.includes(v)) out.push(v);
  }
  return out;
}

/* ── maintenance mode (2026-11-14, the owner's Q4 answer) ─────────────────
   Maintenance mode is a repair window marked `open: true`: it starts when it
   is turned on and has no end (maintenance.py). These decide what a toggle
   writes, as the whole list of windows the repairs store saves. */

const asIds = (v) => (Array.isArray(v) ? v.filter((x) => typeof x === 'string') : []);
const openWindows = (windows) => (Array.isArray(windows) ? windows : []).filter((w) => w && w.open === true);

/** True when an open (mode) window names this place (`nodes`) or this
    collection (`collections`) itself. */
export function inMode(windows, kind, id) {
  const field = kind === 'collection' ? 'collections' : kind === 'service' ? 'services' : 'nodes';
  return openWindows(windows).some((w) => asIds(w[field]).includes(id));
}

/** The collections, of those given (a place's), that are in maintenance
    mode: the place is in it through them, and its own switch cannot end it. */
export function modeVia(windows, collectionIds) {
  const named = new Set(openWindows(windows).flatMap((w) => asIds(w.collections)));
  return asIds(collectionIds).filter((c) => named.has(c));
}

/** The windows after a mode toggle on `targets` ({nodes, collections}), or
    null when nothing would change. On: one new open window for the targets
    not already in mode themselves, starting `now`. Off: the targets leave
    every open window that names them; a window left naming nothing goes.
    Scheduled windows are never touched. */
export function modeChange(windows, targets, on, { now, reason = 'Maintenance mode', taken = [] } = {}) {
  const list = Array.isArray(windows) ? windows : [];
  const nodes = asIds(targets?.nodes);
  const collections = asIds(targets?.collections);
  const svcs = asIds(targets?.services);                     // stage 3b
  if (on) {
    const addNodes = nodes.filter((id) => !inMode(list, 'place', id));
    const addCols = collections.filter((id) => !inMode(list, 'collection', id));
    const addSvcs = svcs.filter((id) => !inMode(list, 'service', id));
    if (!addNodes.length && !addCols.length && !addSvcs.length) return null;
    const window = { id: slugFor('maintenance mode', [...taken, ...list.map((w) => w?.id)], 'window'),
      reason, open: true, starts: now, repeat: 'none' };
    if (addNodes.length) window.nodes = addNodes;
    if (addCols.length) window.collections = addCols;
    if (addSvcs.length) window.services = addSvcs;
    return [...list, window];
  }
  let changed = false;
  const out = [];
  for (const w of list) {
    if (!w || w.open !== true) { out.push(w); continue; }
    const keepNodes = asIds(w.nodes).filter((id) => !nodes.includes(id));
    const keepCols = asIds(w.collections).filter((id) => !collections.includes(id));
    const keepSvcs = asIds(w.services).filter((id) => !svcs.includes(id));
    if (keepNodes.length === asIds(w.nodes).length && keepCols.length === asIds(w.collections).length
        && keepSvcs.length === asIds(w.services).length) {
      out.push(w);
      continue;
    }
    changed = true;
    if (!keepNodes.length && !keepCols.length && !keepSvcs.length) continue;      // left naming nothing: it goes
    const next = { ...w };
    if (keepNodes.length) next.nodes = keepNodes; else delete next.nodes;
    if (keepCols.length) next.collections = keepCols; else delete next.collections;
    if (keepSvcs.length) next.services = keepSvcs; else delete next.services;
    out.push(next);
  }
  return changed ? out : null;
}
