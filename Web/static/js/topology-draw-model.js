/* TOPOLOGY, drawing's rules, with no DOM (2026-11-17): what topology-draw.js
   asks before it changes anything, so node can test it
   (tests/test_topology_draw_model.mjs).

     slugify(text)                    -> an id the schema takes, or ''
     freeId(want, taken)              -> want, or want-2, want-3 ... not in taken
     cableIdFor(a, b, taken)          -> the id offered for a cable between two things
     stubIdFor(name, taken)           -> the id a new stub takes from its name
     takenIds(data, section)          -> the ids a section already uses
     portsOf(data, placeId)           -> that place's interface names, in order
     routesWithoutCable(data)         -> [{key, from, to, kind, id}] one per pair
     cablesFromRoutes(rows, data)     -> ops: one assumed cable per row
     cableBody(values, ends, before, defaults) -> {body, problems} for a cable's form
     newPortOps(data, ends, ports)    -> ops: an interface for each new port
     cableOps(values, ends, data, before, defaults) -> {ops, problems}: ONE batch
     hitCable(geometries, point, tol) -> the id of the cable under a point, or null
     distanceToCurve(g, point)        -> how far a point is from a cable's curve
     clampPoint(p)                    -> a card's corner, kept where the server keeps it
     nudge(p, dir, step)              -> the corner moved one step that way
     withSaved(layout, saved)         -> a layout with the saved corners laid over it
     changedCards(before, after)      -> {id: {x, y} | null} what a save must send
     layoutQueue()                    -> the layout's saves and reads, kept in order

   An end is `{id, type}` with type 'place' or 'stub', as a card's thing is.
   Values come from the form as typed: blanks, and numbers as text. */

import { CARD_H, CARD_W, buildGraph } from './topology-model.js';

const isObj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
const rows = (v) => (Array.isArray(v) ? v.filter(isObj) : []);
const text = (v) => (typeof v === 'string' ? v.trim() : (typeof v === 'number' && Number.isFinite(v) ? String(v) : ''));

/** The server's limit on a card's corner (topology_layout.LIMIT). */
export const LIMIT = 1000000;
/** How long an id is offered at most. */
export const ID_MAX = 48;
/** How far an arrow key moves a card with Alt held, in canvas units. */
export const NUDGE = 16;
/** How near a press must be to a cable to pick it, in canvas units. */
export const HIT = 8;

/* ── ids ──────────────────────────────────────────────────────────────────── */

/** Text as an id the schema's slug rule takes (lowercase letters, digits, dot,
    dash and underscore, starting with a letter or digit), cut to ID_MAX. */
export function slugify(value) {
  const s = text(value).toLowerCase().normalize('NFKD').replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9._-]+/g, '-').replace(/-{2,}/g, '-').replace(/^[^a-z0-9]+/, '');
  return s.slice(0, ID_MAX).replace(/[-._]+$/, '');
}

/** `want`, or the first of want-2, want-3 ... that `taken` does not hold. */
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

/** The ids a section already uses. */
export function takenIds(data, section) {
  return new Set(rows(isObj(data) ? data[section] : null).map((e) => e.id).filter((id) => typeof id === 'string' && id));
}

/** The id offered for a new cable: `<a>-to-<b>`, made free. */
export function cableIdFor(a, b, taken) {
  return freeId(`${text(a)}-to-${text(b)}`, taken);
}

/** A new stub's id, from its name, free of every place's and stub's id (a
    stub may not share a place's id: the validator refuses it). */
export function stubIdFor(name, taken) {
  return freeId(slugify(name) || 'stub', taken);
}

/* ── ports ────────────────────────────────────────────────────────────────── */

/** A place's ports: the names of its `interfaces`, each once, in order. */
export function portsOf(data, placeId) {
  const out = [];
  for (const p of rows(isObj(data) ? data.interfaces : null)) {
    const name = text(p.name);
    if (p.device === placeId && name && !out.includes(name)) out.push(name);
  }
  return out;
}

/** Ops that add an interface for each place end whose typed port is new: the
    plan's "made on the spot if it is new". A stub has no interfaces. */
export function newPortOps(data, ends, ports) {
  const ops = [];
  const seen = new Set();
  (ends || []).forEach((end, i) => {
    const name = text(ports?.[i]);
    if (!end || end.type !== 'place' || !name) return;
    const key = `${end.id}\u0000${name}`;
    // a port is one port whatever its case, as the server's cable check reads it
    const have = portsOf(data, end.id).some((p) => p.toLowerCase() === name.toLowerCase());
    if (seen.has(key.toLowerCase()) || have) return;
    seen.add(key.toLowerCase());
    ops.push({ op: 'insert', section: 'interfaces', body: { device: end.id, name } });
  });
  return ops;
}

/* ── routes with no cable yet ─────────────────────────────────────────────── */

/** The route kinds that say two places talk without saying a cable runs
    between them: a mesh is a tunnel and telemetry is a scrape path. They are
    listed like the rest and start unticked. */
export const UNWIRED_ROUTES = ['mesh', 'telemetry'];

/** Every pair of places a route joins and no cable does yet, one row per
    pair, in the routes' order, with the id a cable between them would take
    (free of every cable's id and of the rows before it). `wired` is whether
    the row starts ticked: false for a mesh or a telemetry route. */
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

/** One `assumed` cable per row, source `hand`, no ports: the ops of one save. */
export function cablesFromRoutes(picked) {
  return (picked || []).map((r) => ({
    op: 'insert', section: 'cables',
    body: { id: r.id, a: r.from, b: r.to, state: 'assumed', source: 'hand' },
  }));
}

/* ── a cable's form ───────────────────────────────────────────────────────── */

/** A VLAN as typed: a number when it is digits, else the words (the server
    then says what is wrong with them, in the form). */
const asVlan = (v) => (/^\d{1,4}$/.test(v) ? Number(v) : v);

/** The tagged VLANs as typed (`10, 20` or `10 20`): a list, numbers where
    they are digits. */
export function parseTagged(value) {
  const s = text(value).replace(/^\[|\]$/g, '');
  if (!s) return [];
  return s.split(/[\s,;]+/).filter(Boolean).map(asVlan);
}

/** Watts as typed: a number, or the words. Digits too many to be a number
    stay the words: read as one they are Infinity, which is sent as null, and
    null on an edit clears the field without a word (2026-11-18). */
const asWatts = (v) => (/^\d+(\.\d+)?$/.test(v) && Number.isFinite(Number(v)) ? Number(v) : v);

/** The fields the form writes, and how a typed value is read. */
const FIELDS = {
  a_port: (v) => v, b_port: (v) => v, kind: (v) => v, state: (v) => v,
  vlan: asVlan, tagged: parseTagged, poe_w: asWatts, speed: (v) => v, note: (v) => v,
};
const FORM_KEY = { a_port: 'aPort', b_port: 'bPort', poe_w: 'poe' };

/** A cable's body from the form's values. `ends` are the two things, A then
    B; `before` is the cable as it is on disk when it is being edited (null
    for a new one). A new cable leaves out what is blank and is marked
    `source: hand`; an edit sends null for a field that was set and is now
    blank (an upsert merges, and null is how it clears a field), and leaves
    its ends as they are; a field the cable on disk leaves out reads as its
    schema default (`defaults`, kind copper and state confirmed when not
    given), so a cable made without a kind is not rewritten by a save of
    something else. `problems` are what the form can say before the
    server is asked: an empty id, or two ends that are the same thing. */
/** The schema's defaults for the two select fields (schema.py `cables`). */
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
  // a person who changes a cable a connection reported makes it theirs: a
  // review never overwrites a `hand` cable, and would otherwise offer the
  // person's own change back as the connection's update
  else if (Object.keys(body).length && text(before.source) && before.source !== 'hand') body.source = 'hand';
  return { body, problems };
}

/** ONE batch for a cable's form: the new ports first, then the cable (an
    insert, or an upsert of the one being edited). Nothing when the form
    has a problem, or an edit changes nothing. */
export function cableOps(values, ends, data, before = null, defaults = CABLE_DEFAULTS) {
  const { body, problems } = cableBody(values, ends, before, defaults);
  if (problems.length) return { ops: [], problems };
  // an edit makes a port only where the port was changed: one left as it
  // was is not made on a save that is about something else
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

/* ── picking a cable ──────────────────────────────────────────────────────── */

/** How far `point` is from a cable's curve (cableGeometry's shape), measured
    against 32 straight pieces of it. */
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

/** The cable nearest `point` within `tol` units: `geometries` is a list of
    `{id, g}`. Ties go to the one listed last (drawn on top). Null when none. */
export function hitCable(geometries, point, tol = HIT) {
  let win = null;
  let best = Infinity;
  for (const { id, g } of geometries || []) {
    const d = distanceToCurve(g, point);
    if (d <= tol && d <= best) { best = d; win = id; }
  }
  return win;
}

/* ── moving cards ─────────────────────────────────────────────────────────── */

/** A card's corner as the server keeps it: finite, within LIMIT, to a tenth. */
export function clampPoint(p) {
  const one = (v) => {
    const n = Number.isFinite(v) ? v : 0;
    return Math.round(Math.max(-LIMIT, Math.min(LIMIT, n)) * 10) / 10;
  };
  return { x: one(p?.x), y: one(p?.y) };
}

/** The corner moved one step left, right, up or down. */
export function nudge(p, dir, step = NUDGE) {
  const dx = dir === 'left' ? -step : dir === 'right' ? step : 0;
  const dy = dir === 'up' ? -step : dir === 'down' ? step : 0;
  return clampPoint({ x: (p?.x || 0) + dx, y: (p?.y || 0) + dy });
}

/** `arrange(graph)`'s answer with the saved corners laid over it, the same
    answer `arrange(graph, {saved})` gives (a saved card keeps its place, the
    rest stay where they were laid): positions, width, height and bounds.
    Only cards already in the layout take a saved corner. A new object;
    nothing it is given is changed. */
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

/** What a save must send to turn `before` into `after`: each card moved or
    new, and null for each card forgotten. */
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

/* ── the layout's saves and reads, in order ───────────────────────────────── */

const isPoint = (p) => isObj(p) && Number.isFinite(p.x) && Number.isFinite(p.y);

/** The layout's saves and reads, kept in order (2026-11-18). It sends and
    reads nothing itself: topology-draw.js asks it what to send, tells it what
    came back, and lays what it answers. The rules:

    ONE SAVE IN FLIGHT. `move(id, p)` and `clear()` (Re-arrange) only note what
    waits; `take()` hands over everything waiting as one batch, `{cards,
    expect}` with `replace: true` after a clear, or null while a save is out
    or nothing waits. A card moved twice before it is sent goes once, where it
    was put last, so an older place is never sent after a newer one.

    `done(outcome, stamp)` is the answer to that batch, and is true when moves
    made meanwhile wait and may go at once:
      'saved'    the stamp is the one the save answered with
      'stale'    (a 409) the batch is dropped, as the page then says; what
                 was moved meanwhile is KEPT, and nothing more is sent until
                 the layout has been read again
      'failed'   (no answer, or a 5xx) the batch goes back under what was
                 moved meanwhile, to go with the next save; never by itself
      'refused'  (any other refusal) the batch is dropped

    A READ NEVER GOES OVER SOMETHING NEWER. `read()` gives a ticket as a read
    starts; `land(ticket, body)` gives `{cards}` to lay on screen, or null:
      an older read than the last one started   null (the later one answers)
      a save went out or came back meanwhile    null, and `owed` is true once
                                                nothing is in flight: read again
      the read failed (`body` not an object)    null; a stale save stays held
                                                (`stale`), so nothing is sent on the
                                                old stamp: read again first
      else                                      the stamp is the read's, and
                                                `cards` are its cards with the
                                                moves not yet sent laid over
                                                (alone, after a clear) */
export function layoutQueue() {
  let pending = {};      // moves not yet sent: {id: {x, y}}
  let replace = false;   // the next save throws the saved layout away first
  let flight = null;     // the batch out now: {cards, replace}
  let hold = false;      // a save came back stale: read before sending more
  let stamp = null;      // the layout's stamp, as last read or written
  let writes = 0;        // every save sent and every save answered
  let reads = 0;         // every read started
  let owed = false;      // a read crossed a save
  const waiting = () => replace || Object.keys(pending).length > 0;
  return {
    get stamp() { return stamp; },
    get busy() { return flight !== null || hold; },
    get waiting() { return waiting(); },
    get owed() { return owed && flight === null && !hold; },
    /** A save came back stale and the layout has not been read since. */
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
        // a clear made meanwhile throws the failed batch away with the rest
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
      // a read that failed leaves a stale save held: sending again on the old
      // stamp would only be refused again, and read again, without end
      if (!isObj(body)) return null;
      hold = false;
      stamp = typeof body.stamp === 'string' ? body.stamp : null;
      const cards = replace || !isObj(body.cards) ? {} : { ...body.cards };
      for (const [id, p] of Object.entries(pending)) cards[id] = { x: p.x, y: p.y };
      return { cards };
    },
  };
}
