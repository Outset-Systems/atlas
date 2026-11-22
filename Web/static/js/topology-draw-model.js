
import { CARD_H, CARD_W, buildGraph } from './topology-model.js';

const isObj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
const rows = (v) => (Array.isArray(v) ? v.filter(isObj) : []);
const text = (v) => (typeof v === 'string' ? v.trim() : (typeof v === 'number' && Number.isFinite(v) ? String(v) : ''));

export const LIMIT = 1000000;
export const ID_MAX = 48;
export const NUDGE = 16;
export const HIT = 8;


export function slugify(value) {
  const s = text(value).toLowerCase().normalize('NFKD').replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9._-]+/g, '-').replace(/-{2,}/g, '-').replace(/^[^a-z0-9]+/, '');
  return s.slice(0, ID_MAX).replace(/[-._]+$/, '');
}

export function freeId(want, taken) {
  const has = (id) => (taken instanceof Set ? taken.has(id) : Array.isArray(taken) && taken.includes(id));
  const base = slugify(want) || 'item';
  if (!has(base)) return base;
  for (let n = 2; ; n++) {
    const tail = `-${n}`;
    const id = base.slice(0, ID_MAX - tail.length).replace(/[-._]+$/, '') + tail;
    if (!has(id)) return id;
  }
}

export function takenIds(data, section) {
  return new Set(rows(isObj(data) ? data[section] : null).map((e) => e.id).filter((id) => typeof id === 'string' && id));
}

export function cableIdFor(a, b, taken) {
  return freeId(`${text(a)}-to-${text(b)}`, taken);
}

export function stubIdFor(name, taken) {
  return freeId(slugify(name) || 'stub', taken);
}


export function portsOf(data, placeId) {
  const out = [];
  for (const p of rows(isObj(data) ? data.interfaces : null)) {
    const name = text(p.name);
    if (p.device === placeId && name && !out.includes(name)) out.push(name);
  }
  return out;
}

export function newPortOps(data, ends, ports) {
  const ops = [];
  const seen = new Set();
  (ends || []).forEach((end, i) => {
    const name = text(ports?.[i]);
    if (!end || end.type !== 'place' || !name) return;
    const key = `${end.id}\u0000${name}`;
    const have = portsOf(data, end.id).some((p) => p.toLowerCase() === name.toLowerCase());
    if (seen.has(key.toLowerCase()) || have) return;
    seen.add(key.toLowerCase());
    ops.push({ op: 'insert', section: 'interfaces', body: { device: end.id, name } });
  });
  return ops;
}


export const UNWIRED_ROUTES = ['mesh', 'telemetry'];

export function routesWithoutCable(data) {
  const graph = buildGraph(data);
  const taken = takenIds(data, 'cables');
  for (const l of graph.links) if (l.layer === 'cable') taken.add(l.id);
  const out = [];
  const pairs = new Set();
  for (const l of graph.links) {
    if (l.layer !== 'route' || l.shadowed) continue;
    const a = graph.byId.get(l.a);
    const b = graph.byId.get(l.b);
    if (!a || !b || a.type !== 'place' || b.type !== 'place') continue;
    const key = l.a < l.b ? `${l.a}\u0000${l.b}` : `${l.b}\u0000${l.a}`;
    if (pairs.has(key)) continue;
    pairs.add(key);
    const id = cableIdFor(l.a, l.b, taken);
    taken.add(id);
    out.push({ key, from: l.a, to: l.b, kind: l.kind, id, fromName: a.name, toName: b.name,
               wired: !UNWIRED_ROUTES.includes(l.kind) });
  }
  return out;
}

export function cablesFromRoutes(picked) {
  return (picked || []).map((r) => ({
    op: 'insert', section: 'cables',
    body: { id: r.id, a: r.from, b: r.to, state: 'assumed', source: 'hand' },
  }));
}


const asVlan = (v) => (/^\d{1,4}$/.test(v) ? Number(v) : v);

export function parseTagged(value) {
  const s = text(value).replace(/^\[|\]$/g, '');
  if (!s) return [];
  return s.split(/[\s,;]+/).filter(Boolean).map(asVlan);
}

const asWatts = (v) => (/^\d+(\.\d+)?$/.test(v) && Number.isFinite(Number(v)) ? Number(v) : v);

const FIELDS = {
  a_port: (v) => v, b_port: (v) => v, kind: (v) => v, state: (v) => v,
  vlan: asVlan, tagged: parseTagged, poe_w: asWatts, speed: (v) => v, note: (v) => v,
};
const FORM_KEY = { a_port: 'aPort', b_port: 'bPort', poe_w: 'poe' };

export const CABLE_DEFAULTS = Object.freeze({ kind: 'copper', state: 'confirmed' });

export function cableBody(values, ends, before = null, defaults = CABLE_DEFAULTS) {
  const v = values || {};
  const problems = [];
  const body = {};
  const id = text(v.id);
  if (!id) problems.push('id');
  if (!before) {
    const [a, b] = ends || [];
    if (!a || !b) problems.push('ends');
    else if (a.id === b.id && a.type === b.type) problems.push('same');
    if (a) body[a.type === 'stub' ? 'a_stub' : 'a'] = a.id;
    if (b) body[b.type === 'stub' ? 'b_stub' : 'b'] = b.id;
  }
  if (id && (!before || id !== before.id)) body.id = id;
  for (const [field, read] of Object.entries(FIELDS)) {
    const raw = text(v[FORM_KEY[field] || field]);
    const value = raw ? read(raw) : null;
    const empty = value === null || (Array.isArray(value) && !value.length);
    if (!before) {
      if (!empty) body[field] = value;
      continue;
    }
    const had = before[field];
    if (empty) {
      if (had !== undefined && had !== null && had !== '' && !(Array.isArray(had) && !had.length)) body[field] = null;
    } else if (JSON.stringify(had ?? defaults?.[field]) !== JSON.stringify(value)) {
      body[field] = value;
    }
  }
  if (!before) body.source = 'hand';
  else if (Object.keys(body).length && text(before.source) && before.source !== 'hand') body.source = 'hand';
  return { body, problems };
}

export function cableOps(values, ends, data, before = null, defaults = CABLE_DEFAULTS) {
  const { body, problems } = cableBody(values, ends, before, defaults);
  if (problems.length) return { ops: [], problems };
  const typed = [values?.aPort, values?.bPort].map((p, i) =>
    (before && text(p) === text(before[i ? 'b_port' : 'a_port']) ? '' : p));
  const ports = newPortOps(data, ends, typed);
  if (before) {
    if (!Object.keys(body).length && !ports.length) return { ops: [], problems: [] };
    const ops = [...ports];
    if (Object.keys(body).length) ops.push({ op: 'upsert', section: 'cables', id: before.id, body });
    return { ops, problems: [] };
  }
  return { ops: [...ports, { op: 'insert', section: 'cables', body }], problems: [] };
}


export function distanceToCurve(g, point) {
  if (!isObj(g) || !isObj(point)) return Infinity;
  const at = (t) => {
    const u = 1 - t;
    return {
      x: u * u * u * g.x1 + 3 * u * u * t * g.c1x + 3 * u * t * t * g.c2x + t * t * t * g.x2,
      y: u * u * u * g.y1 + 3 * u * u * t * g.c1y + 3 * u * t * t * g.c2y + t * t * t * g.y2,
    };
  };
  let best = Infinity;
  let prev = at(0);
  for (let i = 1; i <= 32; i++) {
    const next = at(i / 32);
    const dx = next.x - prev.x;
    const dy = next.y - prev.y;
    const len2 = dx * dx + dy * dy;
    const t = len2 ? Math.max(0, Math.min(1, ((point.x - prev.x) * dx + (point.y - prev.y) * dy) / len2)) : 0;
    best = Math.min(best, Math.hypot(point.x - (prev.x + t * dx), point.y - (prev.y + t * dy)));
    prev = next;
  }
  return best;
}

export function hitCable(geometries, point, tol = HIT) {
  let win = null;
  let best = Infinity;
  for (const { id, g } of geometries || []) {
    const d = distanceToCurve(g, point);
    if (d <= tol && d <= best) { best = d; win = id; }
  }
  return win;
}


export function clampPoint(p) {
  const one = (v) => {
    const n = Number.isFinite(v) ? v : 0;
    return Math.round(Math.max(-LIMIT, Math.min(LIMIT, n)) * 10) / 10;
  };
  return { x: one(p?.x), y: one(p?.y) };
}

export function nudge(p, dir, step = NUDGE) {
  const dx = dir === 'left' ? -step : dir === 'right' ? step : 0;
  const dy = dir === 'up' ? -step : dir === 'down' ? step : 0;
  return clampPoint({ x: (p?.x || 0) + dx, y: (p?.y || 0) + dy });
}

export function withSaved(layout, saved) {
  if (!isObj(layout) || !isObj(layout.positions)) return layout;
  const keep = isObj(saved) ? saved : {};
  const positions = Object.create(null);
  for (const id of Object.keys(layout.positions)) {
    const s = Object.prototype.hasOwnProperty.call(keep, id) ? keep[id] : null;
    positions[id] = isObj(s) && Number.isFinite(s.x) && Number.isFinite(s.y)
      ? { x: s.x, y: s.y } : { ...layout.positions[id] };
  }
  let x0 = Infinity; let y0 = Infinity; let x1 = -Infinity; let y1 = -Infinity;
  for (const id in positions) {
    const p = positions[id];
    x0 = Math.min(x0, p.x); y0 = Math.min(y0, p.y);
    x1 = Math.max(x1, p.x + CARD_W); y1 = Math.max(y1, p.y + CARD_H);
  }
  if (x0 === Infinity) { x0 = 0; y0 = 0; x1 = 0; y1 = 0; }
  return {
    ...layout, positions,
    width: Math.max(0, x1), height: Math.max(0, y1),
    bounds: { x: x0, y: y0, w: x1 - x0, h: y1 - y0 },
  };
}

export function changedCards(before, after) {
  const a = isObj(before) ? before : {};
  const b = isObj(after) ? after : {};
  const out = {};
  for (const [id, p] of Object.entries(b)) {
    if (!isObj(a[id]) || a[id].x !== p.x || a[id].y !== p.y) out[id] = { x: p.x, y: p.y };
  }
  for (const id of Object.keys(a)) if (!(id in b)) out[id] = null;
  return out;
}


const isPoint = (p) => isObj(p) && Number.isFinite(p.x) && Number.isFinite(p.y);

export function layoutQueue() {
  let pending = {};
  let replace = false;
  let flight = null;
  let hold = false;
  let stamp = null;
  let writes = 0;
  let reads = 0;
  let owed = false;
  const waiting = () => replace || Object.keys(pending).length > 0;
  return {
    get stamp() { return stamp; },
    get busy() { return flight !== null || hold; },
    get waiting() { return waiting(); },
    get owed() { return owed && flight === null && !hold; },
    get stale() { return hold && flight === null; },
    move(id, p) {
      if (typeof id !== 'string' || !id || !isPoint(p)) return false;
      pending[id] = { x: p.x, y: p.y };
      return true;
    },
    clear() {
      pending = {};
      replace = true;
    },
    take() {
      if (flight !== null || hold || !waiting()) return null;
      flight = { cards: pending, replace };
      pending = {};
      replace = false;
      writes += 1;
      return { cards: { ...flight.cards }, ...(flight.replace ? { replace: true } : {}), expect: stamp };
    },
    done(outcome, newStamp) {
      const sent = flight;
      if (!sent) return false;
      flight = null;
      writes += 1;
      const meanwhile = waiting();
      if (outcome === 'saved') {
        if (typeof newStamp === 'string' && newStamp) stamp = newStamp;
      } else if (outcome === 'stale') {
        hold = true;
      } else if (outcome === 'failed' && !replace) {
        pending = { ...sent.cards, ...pending };
        replace = sent.replace;
      }
      return meanwhile && !hold;
    },
    read() {
      owed = false;
      reads += 1;
      return { reads, writes };
    },
    land(ticket, body) {
      if (!isObj(ticket) || ticket.reads !== reads) return null;
      if (flight !== null || ticket.writes !== writes) {
        owed = true;
        return null;
      }
      if (!isObj(body)) return null;
      hold = false;
      stamp = typeof body.stamp === 'string' ? body.stamp : null;
      const cards = replace || !isObj(body.cards) ? {} : { ...body.cards };
      for (const [id, p] of Object.entries(pending)) cards[id] = { x: p.x, y: p.y };
      return { cards };
    },
  };
}
