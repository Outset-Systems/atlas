
import { serviceKey } from './alerts-model.js';


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
  if (changed) head = `${n} of ${entries.length} ${plural} ${n === 1 ? 'is' : 'are'} waiting for a person to look.`;
  const why = [];
  if (imported) why.push(`${imported} came from an import`);
  if (changed) why.push(`${changed} changed after being checked`);
  if (unknown) why.push(`${unknown} ${unknown === 1 ? 'was' : 'were'} charted before the map kept this record`);
  return `${head} ${why.join(', ')}.`;
}

export function rowStanding(row) {
  if (!row || typeof row.reviewed !== 'boolean') return 'unknown';
  const mine = standing({ provenance: {
    reviewed: row.reviewed, reviewed_at: row.reviewed_at, changed_since_review: row.changed_since_review,
  } });
  if (typeof row.unchecked !== 'boolean') return mine;
  if (!row.unchecked) return 'checked';
  return mine === 'checked' ? 'changed' : mine;
}

export const rowWaiting = (row) => (typeof row?.unchecked === 'boolean'
  ? row.unchecked : rowStanding(row) !== 'checked');

export const rowPress = (shownId, id) =>
  (typeof shownId === 'string' && shownId !== '' && shownId === id ? 'close' : 'open');


export const REVIEW_BATCH = 400;

export function batches(list, size = REVIEW_BATCH) {
  const all = Array.isArray(list) ? list : [];
  const step = Math.max(1, Math.floor(Number(size) || REVIEW_BATCH));
  const out = [];
  for (let i = 0; i < all.length; i += step) out.push(all.slice(i, i + step));
  return out;
}

export const reviewOps = (ids) => ids.map((id) => ({ op: 'review', section: 'nodes', id }));

export async function inBatches(list, save, size = REVIEW_BATCH) {
  let done = 0;
  for (const part of batches(list, size)) {
    const result = await save(part);
    if (!result) return { done, stopped: true };
    done += part.length;
  }
  return { done, stopped: false };
}

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

export const armedLabel = (n) => `Yes, I have checked ${n === 1 ? 'this one' : `these ${n}`}`;
export const markedLine = (n) => (n === 1 ? 'Marked as checked.' : `${n} marked as checked.`);


export const SEVERITY = ['down', 'degraded', 'maintenance', 'slumbering', 'healthy'];

const DAY_MS = 86400000;
const blank = (v) => v === null || v === undefined || v === '' || (typeof v === 'number' && Number.isNaN(v));
const time = (v) => { const t = Date.parse(v); return Number.isNaN(t) ? null : t; };

export function ipv4Number(text) {
  const m = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?:\/\d{1,2})?$/.exec(String(text ?? '').trim());
  if (!m) return null;
  const parts = m.slice(1).map(Number);
  if (parts.some((p) => p > 255)) return null;
  return ((parts[0] * 256 + parts[1]) * 256 + parts[2]) * 256 + parts[3];
}

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
    if (m.now) return -Infinity;
    return blank(m.next) ? null : time(m.next);
  },
  cert: (r) => (r.cert && typeof r.cert.days === 'number' ? r.cert.days : null),
  collections: (r, ctx) => {
    const n = collectionNames(r, ctx.collections);
    return n.length ? n.join(', ').toLowerCase() : null;
  },
};

const OLD_KEYS = Object.freeze({ sets: 'collections', set: 'collection' });

export const SORT_KEYS = Object.keys(KEYS);

const COLLATOR = new Intl.Collator(undefined, { numeric: true });

function compare(a, b) {
  if (Array.isArray(a)) {
    for (let i = 0; i < a.length; i++) { const c = compare(a[i], b[i]); if (c) return c; }
    return 0;
  }
  if (typeof a === 'number' && typeof b === 'number') return a - b;
  return COLLATOR.compare(String(a), String(b));
}

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


export const haystack = (row) => [row.name, row.id, ...(row.addresses || []), row.role, row.zone_name]
  .filter((v) => !blank(v)).join(' ').toLowerCase();

export function staleFor(row, days, now = Date.now()) {
  const at = row?.reviewed ? time(row.reviewed_at) : null;
  if (at === null) return true;
  return now - at >= days * DAY_MS;
}

export const NO_FILTER = Object.freeze({
  text: '', state: '', zone: '', kind: '', collection: '', unchecked: false, staleDays: 0,
  things: '',
});

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

export const isEmptyFilter = (filter) => {
  const f = { ...NO_FILTER, ...(filter || {}) };
  return !String(f.text).trim() && !f.state && !f.zone && !f.kind && !f.collection
    && !f.unchecked && !Number(f.staleDays) && !f.things;
};

export function cleanFilter(raw) {
  const f = raw && typeof raw === 'object' ? raw : {};
  const str = (v) => (typeof v === 'string' ? v.slice(0, 200) : '');
  return {
    text: str(f.text), state: str(f.state), zone: str(f.zone), kind: str(f.kind),
    collection: str(f.collection) || str(f.set),
    unchecked: f.unchecked === true,
    staleDays: Number.isFinite(Number(f.staleDays)) && Number(f.staleDays) > 0 ? Math.floor(Number(f.staleDays)) : 0,
    things: THING_KINDS.includes(f.things) ? f.things : '',
  };
}


export const TROUBLE = Object.freeze(['down', 'degraded']);

function group(id, name, rows) {
  const trouble = rows.filter((r) => TROUBLE.includes(r.state));
  const worst = TROUBLE.find((s) => trouble.some((r) => r.state === s)) || '';
  return { id, name: name || id, count: rows.length, trouble: trouble.length, worst };
}

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

export function filterGroups(roster) {
  const groups = railGroups(roster);
  const zones = Array.isArray(roster?.zones) ? roster.zones : [];
  return { ...groups, networks: zones.filter((z) => z && typeof z.id === 'string') };
}

export const memberList = (places) => (Array.isArray(places) ? places
  : (typeof places === 'string' && places ? [places] : []));

export const RAIL_FIELDS = Object.freeze({ collections: 'collection', networks: 'zone', kinds: 'kind', things: 'things' });

export function railPress(filter, section, id) {
  const field = RAIL_FIELDS[section];
  if (!field) return {};
  return { [field]: (filter || {})[field] === id ? '' : id };
}

export function dropUnknown(filter, groups) {
  const f = { ...(filter || {}) };
  for (const [section, field] of Object.entries(RAIL_FIELDS)) {
    if (section === 'things') { if (f.things && !THING_KINDS.includes(f.things)) f.things = ''; continue; }
    if (f[field] && !((groups || {})[section] || []).some((g) => g.id === f[field])) f[field] = '';
  }
  return f;
}

export const RAIL_KEY = 'atlas.nodes.rail';
export const RAIL_SECTIONS = Object.freeze(['collections', 'networks', 'kinds', 'saved']);

export function readRail(storage) {
  const raw = readJSON(storage, RAIL_KEY);
  const out = {};
  if (raw && typeof raw === 'object') for (const k of RAIL_SECTIONS) if (raw[k] === true) out[k] = true;
  return out;
}
export const writeRail = (storage, shut) => writeJSON(storage, RAIL_KEY,
  Object.fromEntries(RAIL_SECTIONS.filter((k) => shut?.[k] === true).map((k) => [k, true])));


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

export function readSort(storage) {
  const s = readJSON(storage, SORT_KEY);
  const key = s && (OLD_KEYS[s.key] || s.key);
  return key && SORT_KEYS.includes(key) && (s.dir === 'asc' || s.dir === 'desc')
    ? { key, dir: s.dir } : { key: 'name', dir: 'asc' };
}
export const writeSort = (storage, sort) => writeJSON(storage, SORT_KEY, { key: sort.key, dir: sort.dir });

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


export function daysSince(iso, now = Date.now()) {
  const t = time(iso);
  return t === null ? null : Math.floor((now - t) / DAY_MS);
}

export function certTone(days) {
  if (typeof days !== 'number' || Number.isNaN(days)) return '';
  if (days <= 7) return 'down';
  if (days <= 30) return 'warn';
  return '';
}

export function slugFor(text, taken = [], fallback = 'collection') {
  const base = String(text || '').toLowerCase().normalize('NFKD').replace(/\p{M}/gu, '')
    .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 48) || fallback;
  const used = new Set(taken);
  if (!used.has(base)) return base;
  let n = 2;
  while (used.has(`${base}-${n}`)) n++;
  return `${base}-${n}`;
}

export function mergeNeeds(id, existing, more) {
  const out = [];
  for (const v of [...(Array.isArray(existing) ? existing : []), ...(more || [])]) {
    if (v && v !== id && !out.includes(v)) out.push(v);
  }
  return out;
}


const asIds = (v) => (Array.isArray(v) ? v.filter((x) => typeof x === 'string') : []);
const openWindows = (windows) => (Array.isArray(windows) ? windows : []).filter((w) => w && w.open === true);

export function inMode(windows, kind, id) {
  const field = kind === 'collection' ? 'collections' : kind === 'service' ? 'services' : 'nodes';
  return openWindows(windows).some((w) => asIds(w[field]).includes(id));
}

export function modeVia(windows, collectionIds) {
  const named = new Set(openWindows(windows).flatMap((w) => asIds(w.collections)));
  return asIds(collectionIds).filter((c) => named.has(c));
}

export function modeChange(windows, targets, on, { now, reason = 'Maintenance mode', taken = [] } = {}) {
  const list = Array.isArray(windows) ? windows : [];
  const nodes = asIds(targets?.nodes);
  const collections = asIds(targets?.collections);
  const svcs = asIds(targets?.services);
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
    if (!keepNodes.length && !keepCols.length && !keepSvcs.length) continue;
    const next = { ...w };
    if (keepNodes.length) next.nodes = keepNodes; else delete next.nodes;
    if (keepCols.length) next.collections = keepCols; else delete next.collections;
    if (keepSvcs.length) next.services = keepSvcs; else delete next.services;
    out.push(next);
  }
  return changed ? out : null;
}


export const SUMMARY_ORDER = Object.freeze(['down', 'degraded', 'maintenance', 'slumbering', 'healthy', 'unknown', 'unmanaged']);

export function stateCounts(rows) {
  const n = new Map();
  for (const row of rows || []) {
    if (!row) continue;
    const s = rowState(row);
    n.set(s, (n.get(s) || 0) + 1);
  }
  return SUMMARY_ORDER.filter((s) => n.get(s)).map((s) => [s, n.get(s)]);
}

export function recentFor(events, places, services, max = 8) {
  const on = new Set(places || []);
  const keys = services instanceof Map ? services : new Map();
  const out = [];
  for (const e of Array.isArray(events) ? events : []) {
    if (!e || typeof e !== 'object' || typeof e.target !== 'string') continue;
    let place = null;
    if (e.kind === 'node' && on.has(e.target)) place = e.target;
    else if (e.kind === 'service' && on.has(keys.get(e.target))) place = keys.get(e.target);
    if (place) out.push({ ...e, place });
  }
  const seq = (e) => (Number.isFinite(Number(e.id)) ? Number(e.id) : -1);
  out.sort((a, b) => seq(b) - seq(a) || String(b.at || '').localeCompare(String(a.at || '')));
  return out.slice(0, Math.max(0, max));
}


export const THING_KINDS = Object.freeze(['container', 'service']);

export function thingKind(link) {
  if (link && (link.kind === 'container' || link.kind === 'service')) return link.kind;
  return typeof link?.container === 'string' && link.container.trim() ? 'container' : 'service';
}

export function thingRows(data, roster, feed) {
  const rows = new Map();
  for (const r of roster?.rows || []) if (r && typeof r.id === 'string') rows.set(r.id, r);
  const holding = new Map();
  for (const c of roster?.collections || []) {
    if (!c || typeof c.id !== 'string') continue;
    for (const k of Array.isArray(c.services) ? c.services : []) {
      if (!holding.has(k)) holding.set(k, []);
      holding.get(k).push(c);
    }
  }
  const maint = new Set(Array.isArray(feed?.maintenance_services) ? feed.maintenance_services : []);
  const live = feed?.services && typeof feed.services === 'object' ? feed.services : {};
  const out = [];
  const seen = new Set();
  for (const node of Array.isArray(data?.nodes) ? data.nodes : []) {
    if (!node || typeof node.id !== 'string') continue;
    const row = rows.get(node.id);
    if (!row) continue;
    for (const link of Array.isArray(node.links) ? node.links : []) {
      if (!link || typeof link !== 'object') continue;
      const key = serviceKey(node.id, link);
      if (seen.has(key)) continue;
      seen.add(key);
      const cols = holding.get(key) || [];
      const unmanaged = row.unmanaged === true || link.unmanaged === true || cols.some((c) => c.unmanaged === true);
      const said = live[key]?.state;
      out.push({
        key, place: node.id, place_name: row.name || node.id,
        label: typeof link.label === 'string' && link.label ? link.label : key,
        kind: thingKind(link),
        container: typeof link.container === 'string' ? link.container.trim() : '',
        zone: row.zone ?? null,
        state: maint.has(key) ? 'maintenance' : (SEVERITY.includes(said) ? said : null),
        unmanaged,
        collections: cols.map((c) => c.id),
        place_collections: Array.isArray(row.collections) ? row.collections : [],
      });
    }
  }
  return out;
}

export function filterThings(things, filter = {}) {
  const f = { ...NO_FILTER, ...(filter || {}) };
  const words = String(f.text || '').trim().toLowerCase().split(/\s+/).filter(Boolean);
  return (things || []).filter((x) => {
    if (!x) return false;
    if (f.things && x.kind !== f.things) return false;
    if (words.length) {
      const hay = [x.label, x.place_name, x.place, x.container, x.key].filter((v) => !blank(v)).join(' ').toLowerCase();
      if (!words.every((w) => hay.includes(w))) return false;
    }
    if (f.state && rowState(x) !== f.state) return false;
    if (f.zone && x.zone !== f.zone) return false;
    if (f.collection && !(x.collections || []).includes(f.collection)
        && !(x.place_collections || []).includes(f.collection)) return false;
    return true;
  });
}

const THING_ORDER = [...SEVERITY, 'unknown', 'unmanaged'];
export function sortThings(things) {
  const rank = (x) => THING_ORDER.indexOf(rowState(x));
  return [...(things || [])].sort((a, b) => rank(a) - rank(b)
    || String(a.place_name).localeCompare(String(b.place_name))
    || String(a.label).localeCompare(String(b.label)));
}

export function thingGroups(things) {
  return THING_KINDS.map((k) => group(k, k, (things || []).filter((x) => x && x.kind === k)))
    .filter((g) => g.count > 0);
}
