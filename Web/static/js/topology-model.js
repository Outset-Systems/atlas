/* TOPOLOGY's rules, with no DOM (2026-11-16): the dataset turned into a graph
   of device cards and the cables, routes and parent ties between them, laid
   out with the head of the network on top, and the small questions the canvas
   asks of it (which VLAN a cable carries, what to light, what to find, what is
   on screen, the rows of the connections spreadsheet). Pure, so node can test
   it (tests/test_topology_model.mjs); the cases every reader must agree on are
   in tests/topology_cases.json, which the server's twin of `heads`, `layers`,
   `pathToHead` and `connections` reads too.

   It stands beside the tier diagram's rules (path-model.js, TOPOLOGY in the
   band), which draw routes plus `parent` on rows named after one lab's own
   ids. Here nothing is named: the heads come from the data, everything
   hangs below them by cable, then a guest from its host, then by route,
   then by parent, and the same input always gives the same picture.

   The contract the drawing codes against:

     buildGraph(data)              -> {things, links, byId, linkById}
     vlanNumber(value)             -> a VLAN number or null
     vlanLabel(link)               -> 'U10' | 'U1 T10,20' | 'T10,20' | ''
     heads(graph)                  -> [thing id, ...]
     layers(graph)                 -> Map id -> {depth, up, head, loose}
     arrange(graph, {saved, ratio})-> {positions, width, height, bounds}
     infrastructure(graph)         -> graph of network gear only
     foldLeaves(graph, {limit})    -> graph with leaves folded into groups
     pathToHead(graph, id)         -> {things: [ids], links: [ids]}
     vlanList(graph, zones)        -> [{vlan, name, hue, cables, things}]
     carries(link, vlan)           -> boolean
     onVlan(graph, id, vlan, zones)-> boolean
     stripes(link, zones)          -> [hue, ...]
     find(graph, text)             -> [thing id, ...]
     seen(positions, box, margin)  -> [thing id, ...]
     connections(graph)            -> [{id, name, to, toId, port, farPort, vlan, poe, path}]

   And the drawing's own sums (2026-11-17), so the canvas files only draw:

     groupHolding(graph, id)       -> the folded group a thing is in, or null
     vlanLit(graph, vlan, zones)   -> {things: [ids], links: [ids]}
     pathMarks(things, links, at)  -> {things, links, failedThing, failedLink}

   Where a cable runs, how text is sized and cut, and the view's sums (fit,
   zoom, what is on screen) are topology-geometry.js (moved out 2026-11-17).

   Positions are the TOP-LEFT corner of a card, in the same units as the size
   constants below. Order is always the dataset's: things are the places as
   listed, then the stubs as listed; links are the cables, then the routes,
   then the parent ties. Hand-edited data is read leniently: a missing
   section, a row that is not an object, a second row with an id already
   seen, or a cable whose end is gone is skipped, never thrown on. Nothing
   here changes what it is given. */

/* ── sizes the drawing shares ─────────────────────────────────────────────── */

/** A card's width and height, the gap between cards side by side and between
    rows, and the extra gap between separate trees. */
export const CARD_W = 176;
export const CARD_H = 64;
export const GAP_X = 32;
export const GAP_Y = 96;
export const PIECE_GAP = 96;
/** One card plus its gap, across and down: the layout's grid. */
export const SLOT = CARD_W + GAP_X;
export const ROW = CARD_H + GAP_Y;
/** Past this many things, leaves fold into groups (foldLeaves). */
export const FOLD_LIMIT = 150;
/** The stub kinds that count as network gear (shown in Infrastructure). */
export const INFRA_STUBS = ['internet', 'switch', 'patch'];
/** The order a thing prefers to hang by, and a folded group's link takes. */
export const LAYERS = ['cable', 'route', 'parent'];

/* ── reading hand-edited values ───────────────────────────────────────────── */

const isObj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
const rows = (v) => (Array.isArray(v) ? v.filter(isObj) : []);
const okId = (v) => typeof v === 'string' && v !== '';
const words = (v) => (typeof v === 'string' ? v.trim() : (typeof v === 'number' && Number.isFinite(v) ? String(v) : ''));
const NO_ADDRESS = new Set(['', '\u2014', '-', '\u2013']);

/** A VLAN as a number: an integer 0 to 4095, or a string of digits that is
    one. Anything else (blank, the em dash placeholder, words) is null. */
export function vlanNumber(value) {
  let n = null;
  if (typeof value === 'number') n = value;
  else if (typeof value === 'string' && /^\s*\d{1,4}\s*$/.test(value)) n = Number(value.trim());
  return Number.isInteger(n) && n >= 0 && n <= 4095 ? n : null;
}

/** A tagged list read leniently: numbers only, each once, ascending. A value
    that is not a list is an empty one. */
function taggedList(value) {
  if (!Array.isArray(value)) return [];
  const out = [...new Set(value.map(vlanNumber).filter((n) => n !== null))];
  return out.sort((a, b) => a - b);
}

/** Watts as a positive number, or null. */
function watts(value) {
  let n = null;
  if (typeof value === 'number') n = value;
  else if (typeof value === 'string' && /^\s*\d+(\.\d+)?\s*$/.test(value)) n = Number(value);
  return Number.isFinite(n) && n > 0 ? n : null;
}

const pairKey = (a, b) => (a < b ? `${a}\u0000${b}` : `${b}\u0000${a}`);

/* ── the graph ────────────────────────────────────────────────────────────── */

/** The dataset as things and links.

    Takes the dataset (`nodes`, `stubs`, `cables`, `routes`; any may be
    missing). Returns `{things, links, byId, linkById}`: two arrays in dataset
    order and two Maps by id.

    A thing is `{id, type: 'place'|'stub', name, kind, sub, ip, zone, parent,
    planned, unmanaged, infra, order}`. `sub` is the line under the name: a
    place's address (blank when it has none, or the em dash), a stub's raw kind
    (the drawing puts it in words). `infra` is network gear: a place whose kind
    is `network`, or a stub of kind internet, switch or patch. `parent` is kept
    only when it names another place. `order` is its index in `things`.

    A link is `{id, layer: 'cable'|'route'|'parent', a, b, aPort, bPort, kind,
    state, vlan, tagged, poe, speed, source, note, lane, lanes, shadowed}`.
    One per cable (its `a`/`b` the place or stub at that end, its id the
    cable's, or `cable:<n>` when it has none or a used one), one per route
    (`a` is `from`; id `route:<from>:<to>`, with `:<n>` added for a repeat), and
    one per place's `parent` (`a` the host, `b` the guest; id `parent:<guest>`)
    unless a cable or route already joins the two. A route between two things
    a cable already joins is kept with `shadowed: true`, so the drawing may hide
    it. `lane` and `lanes` number the links of one layer between one pair, so
    two cables between the same two things can be drawn apart. Anything whose
    end does not exist, or that joins a thing to itself, is skipped. */
export function buildGraph(data) {
  const d = isObj(data) ? data : {};
  const things = [];
  const byId = new Map();

  for (const n of rows(d.nodes)) {
    if (!okId(n.id) || byId.has(n.id)) continue;
    const ip = words(n.ip);
    const kind = words(n.kind);
    const t = {
      id: n.id, type: 'place', name: words(n.name) || n.id, kind,
      sub: NO_ADDRESS.has(ip) ? '' : ip, ip: NO_ADDRESS.has(ip) ? '' : ip,
      zone: okId(n.zone) ? n.zone : null, parent: okId(n.parent) ? n.parent : null,
      planned: n.planned === true, unmanaged: n.unmanaged === true,
      infra: kind === 'network', order: things.length,
    };
    things.push(t);
    byId.set(t.id, t);
  }
  for (const s of rows(d.stubs)) {
    if (!okId(s.id) || byId.has(s.id)) continue;
    const kind = words(s.kind);
    const t = {
      id: s.id, type: 'stub', name: words(s.name) || s.id, kind, sub: kind, ip: '',
      zone: null, parent: null, planned: false, unmanaged: false,
      infra: INFRA_STUBS.includes(kind), order: things.length,
    };
    things.push(t);
    byId.set(t.id, t);
  }
  // a parent is kept only when it is another place (it may be listed later)
  for (const t of things) {
    if (t.parent !== null && (t.parent === t.id || !byId.has(t.parent) || byId.get(t.parent).type !== 'place')) {
      t.parent = null;
    }
  }

  const links = [];
  const linkById = new Map();
  const cabled = new Set();
  const routed = new Set();
  const add = (link) => { links.push(link); linkById.set(link.id, link); };
  const freeId = (want, fallback) => {
    if (okId(want) && !linkById.has(want)) return want;
    let id = fallback;
    for (let n = 2; linkById.has(id); n++) id = `${fallback}:${n}`;
    return id;
  };
  const end = (c, side) => {
    const place = c[side];
    const stub = c[`${side}_stub`];
    if (okId(place) && byId.has(place)) return place;
    if (okId(stub) && byId.has(stub)) return stub;
    return null;
  };

  rows(d.cables).forEach((c, i) => {
    const a = end(c, 'a');
    const b = end(c, 'b');
    if (a === null || b === null || a === b) return;
    cabled.add(pairKey(a, b));
    add({
      id: freeId(c.id, `cable:${i}`), layer: 'cable', a, b,
      aPort: words(c.a_port), bPort: words(c.b_port),
      kind: words(c.kind) || 'copper', state: c.state === 'assumed' ? 'assumed' : 'confirmed',
      vlan: vlanNumber(c.vlan), tagged: taggedList(c.tagged), poe: watts(c.poe_w),
      speed: words(c.speed), source: words(c.source), note: words(c.note),
      lane: 0, lanes: 1, shadowed: false,
    });
  });
  for (const r of rows(d.routes)) {
    const a = r.from;
    const b = r.to;
    if (!okId(a) || !okId(b) || a === b || !byId.has(a) || !byId.has(b)) continue;
    routed.add(pairKey(a, b));
    add({
      id: freeId(null, `route:${a}:${b}`), layer: 'route', a, b, aPort: '', bPort: '',
      kind: words(r.kind) || 'vlan', state: null, vlan: null, tagged: [], poe: null,
      speed: '', source: '', note: '', lane: 0, lanes: 1, shadowed: cabled.has(pairKey(a, b)),
    });
  }
  for (const t of things) {
    if (t.parent === null) continue;
    const key = pairKey(t.parent, t.id);
    if (cabled.has(key) || routed.has(key)) continue;
    add({
      id: freeId(null, `parent:${t.id}`), layer: 'parent', a: t.parent, b: t.id, aPort: '', bPort: '',
      kind: 'parent', state: null, vlan: null, tagged: [], poe: null,
      speed: '', source: '', note: '', lane: 0, lanes: 1, shadowed: false,
    });
  }
  setLanes(links);
  return { things, links, byId, linkById };
}

/** Number the links of one layer between one pair: lane 0, 1, ... of lanes. */
function setLanes(links) {
  const groups = new Map();
  for (const link of links) {
    const key = `${link.layer}\u0000${pairKey(link.a, link.b)}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(link);
  }
  for (const group of groups.values()) {
    group.forEach((link, i) => { link.lane = i; link.lanes = group.length; });
  }
}

/** A graph made from parts: the same shape buildGraph returns. */
function graphOf(things, links) {
  return {
    things, links,
    byId: new Map(things.map((t) => [t.id, t])),
    linkById: new Map(links.map((l) => [l.id, l])),
  };
}

/* ── what touches what (worked out once per graph) ────────────────────────── */

const ADJ = new WeakMap();
const HEADS = new WeakMap();
const LAYERS_OF = new WeakMap();

/** Each thing's links in link order, as {link, other, index}. */
function adjacency(graph) {
  if (ADJ.has(graph)) return ADJ.get(graph);
  const adj = new Map();
  for (const t of graph.things) adj.set(t.id, []);
  graph.links.forEach((link, index) => {
    if (!adj.has(link.a) || !adj.has(link.b)) return;
    adj.get(link.a).push({ link, other: link.b, index });
    adj.get(link.b).push({ link, other: link.a, index });
  });
  ADJ.set(graph, adj);
  return adj;
}

const degree = (adj, id) => (adj.get(id) || []).length;

/* ── VLAN notation ────────────────────────────────────────────────────────── */

/** A cable's VLANs in switch notation. `U10` for an access cable (untagged
    only), `U1 T10,20,99` for a trunk, `T10,20` for tagged only, '' for none.
    Numbers ascending; a numeric string counts as its number. Takes a link or
    a raw cable (both have `vlan` and `tagged`). */
export function vlanLabel(link) {
  if (!isObj(link)) return '';
  const u = vlanNumber(link.vlan);
  const t = taggedList(link.tagged);
  const parts = [];
  if (u !== null) parts.push(`U${u}`);
  if (t.length) parts.push(`T${t.join(',')}`);
  return parts.join(' ');
}

/* ── heads ────────────────────────────────────────────────────────────────── */

/** The things that stand on the top row: at least one per connected piece.

    A piece is what cables, routes and parent ties join together. A thing
    with no link at all is not a piece: it is loose, and never a head. For
    each piece, the first rule that applies:

      1. every stub of kind `internet` in it (two lines in, two heads);
      2. else the inside end of a `wan` route. The demo's wan routes read
         `gateway -> the-wild` and `nas -> offsite`: the world is the `to` end
         and the place is the `from` end, but a second wan route (the NAS's
         line to an off-site copy) must not put the NAS on top. So the inside
         end is the end with more links (the `from` end on a tie), and of
         several the winner is a network-kind one first, then the one with
         the most links, then the first listed. That puts the gateway on top
         of a map that has routes and no cables yet;
      3. else the network-kind place with the most links;
      4. else the thing with the most links.

    Ties go to the thing listed first. Returns ids in thing order. */
export function heads(graph) {
  if (HEADS.has(graph)) return HEADS.get(graph);
  const adj = adjacency(graph);
  const { things, byId } = graph;

  // pieces, by union-find over every link
  const root = new Map(things.map((t) => [t.id, t.id]));
  const find = (id) => {
    let r = id;
    while (root.get(r) !== r) r = root.get(r);
    while (root.get(id) !== r) { const next = root.get(id); root.set(id, r); id = next; }
    return r;
  };
  for (const link of graph.links) {
    if (!root.has(link.a) || !root.has(link.b)) continue;
    const ra = find(link.a);
    const rb = find(link.b);
    if (ra !== rb) root.set(ra, rb);
  }
  const pieces = new Map();
  for (const t of things) {
    if (!degree(adj, t.id)) continue;
    const r = find(t.id);
    if (!pieces.has(r)) pieces.set(r, []);
    pieces.get(r).push(t);
  }
  const wanInside = new Map();
  for (const link of graph.links) {
    if (link.layer !== 'route' || link.kind !== 'wan' || !byId.has(link.a)) continue;
    const inside = degree(adj, link.a) >= degree(adj, link.b) ? link.a : link.b;
    const r = find(inside);
    if (!wanInside.has(r)) wanInside.set(r, new Set());
    wanInside.get(r).add(inside);
  }
  const best = (list, preferNetwork) => {
    let win = null;
    for (const t of list) {
      if (win === null) { win = t; continue; }
      const tn = preferNetwork && t.type === 'place' && t.kind === 'network';
      const wn = preferNetwork && win.type === 'place' && win.kind === 'network';
      if (tn !== wn) { if (tn) win = t; continue; }
      const dt = degree(adj, t.id);
      const dw = degree(adj, win.id);
      if (dt > dw || (dt === dw && t.order < win.order)) win = t;
    }
    return win;
  };

  const out = [];
  for (const [r, members] of pieces) {
    const lines = members.filter((t) => t.type === 'stub' && t.kind === 'internet');
    if (lines.length) { out.push(...lines); continue; }
    if (wanInside.has(r)) {
      const inside = members.filter((t) => wanInside.get(r).has(t.id));
      out.push(best(inside, true));
      continue;
    }
    const gear = members.filter((t) => t.type === 'place' && t.kind === 'network');
    out.push(best(gear.length ? gear : members, false));
  }
  const ids = out.sort((a, b) => a.order - b.order).map((t) => t.id);
  HEADS.set(graph, ids);
  return ids;
}

/* ── layers ───────────────────────────────────────────────────────────────── */

/** For each thing, how far below a head it stands and what it hangs from.

    Returns a Map, in thing order, of id -> `{depth, up, head, loose}`. `up` is
    `{id, link, layer}` (the thing above, the link it hangs by and that link's
    layer), or null for a head and a loose thing. `head` is the head its chain
    ends at. A loose thing (one nothing reaches) is `{depth: null, up: null,
    head: null, loose: true}` and is drawn in a last row of its own.

    The walk, in words the server's twin can copy:
      - Heads stand at depth 0. Cables are walked breadth first, a depth at a
        time, each depth's things taken in thing order and each thing's
        cables in link order; the first to reach a thing is what it hangs
        from. So depth is the fewest cable hops, and of two equal ways up the
        thing listed first wins.
      - When cables reach nothing more, A GUEST HANGS FROM ITS HOST (owner,
        2026-11-17): every place not yet reached whose `parent` is reached
        hangs from that host, one hop, by whatever joins the two (the route
        between them when there is one, else the parent tie). A guest with a
        route from the gateway used to hang from the gateway, a hypervisor's
        guests in one wide row under it. Cables are then walked again from
        all of them.
      - When no host adds anything, every thing not yet reached that has a
        route to a reached thing hangs by that route, one hop: from the
        reached end with the least depth, then the one listed first, then the
        route listed first. A guest whose host is not reached yet WAITS for
        it and takes no route in this step. Cables, then hosts, again.
      - When that adds nothing either, the guests still waiting hang by
        their routes, the same way.
      - Only when no route adds anything, the parent ties left are tried the
        same way (a host nothing else reaches hangs from its reached guest).
      - Repeat until nothing is added. Each thing is reached once, so a ring
        cannot loop. */
export function layers(graph) {
  if (LAYERS_OF.has(graph)) return LAYERS_OF.get(graph);
  const adj = adjacency(graph);
  const { byId } = graph;
  const info = new Map();
  const byOrder = (a, b) => byId.get(a).order - byId.get(b).order;
  let sinceHost = [];
  let sinceRoute = [];
  let sinceWait = [];
  let sinceParent = [];
  const reach = (id, entry) => {
    info.set(id, entry);
    sinceHost.push(id);
    sinceRoute.push(id);
    sinceWait.push(id);
    sinceParent.push(id);
  };
  // a guest whose host is not reached yet waits for it: no route takes it
  // while its host may still be reached
  const waits = (id) => { const p = byId.get(id).parent; return p !== null && byId.has(p) && !info.has(p); };
  // each host's guests, in thing order: the places whose `parent` it is
  const guests = new Map();
  for (const t of graph.things) {
    if (t.parent === null || !byId.has(t.parent)) continue;
    if (!guests.has(t.parent)) guests.set(t.parent, []);
    guests.get(t.parent).push(t.id);
  }

  const flood = (seeds) => {
    const buckets = [];
    let lo = Infinity;
    let hi = -1;
    for (const id of seeds) {
      const d = info.get(id).depth;
      (buckets[d] || (buckets[d] = [])).push(id);
      lo = Math.min(lo, d);
      hi = Math.max(hi, d);
    }
    for (let d = lo; d <= hi; d++) {
      const bucket = buckets[d];
      if (!bucket) continue;
      bucket.sort(byOrder);
      for (const id of bucket) {
        const head = info.get(id).head;
        for (const { link, other } of adj.get(id)) {
          if (link.layer !== 'cable' || info.has(other)) continue;
          reach(other, { depth: d + 1, up: { id, link: link.id, layer: 'cable' }, head, loose: false });
          (buckets[d + 1] || (buckets[d + 1] = [])).push(other);
          if (d + 1 > hi) hi = d + 1;
        }
      }
    }
  };

  const attach = (layer, sources, skip = null) => {
    const candidates = new Set();
    for (const id of sources) {
      for (const { link, other } of adj.get(id)) {
        if (link.layer === layer && !info.has(other) && !(skip && skip(other))) candidates.add(other);
      }
    }
    const chosen = [];
    for (const id of [...candidates].sort(byOrder)) {
      let win = null;
      for (const { link, other, index } of adj.get(id)) {
        if (link.layer !== layer || !info.has(other)) continue;
        const d = info.get(other).depth;
        const o = byId.get(other).order;
        if (win === null || d < win.d || (d === win.d && (o < win.o || (o === win.o && index < win.index)))) {
          win = { d, o, index, other, link };
        }
      }
      chosen.push([id, win]);
    }
    for (const [id, win] of chosen) {
      reach(id, {
        depth: win.d + 1, up: { id: win.other, link: win.link.id, layer },
        head: info.get(win.other).head, loose: false,
      });
    }
    return chosen.map(([id]) => id);
  };

  /** A guest hangs from its host: each unreached guest of a thing in
      `sources`, by the first link (in link order) that joins the two and is
      no cable. A guest nothing joins to its host is left for the routes. */
  const attachHost = (sources) => {
    const chosen = [];
    for (const host of sources) {
      for (const id of guests.get(host) || []) {
        if (info.has(id)) continue;
        const via = adj.get(id).find(({ link, other }) => other === host && link.layer !== 'cable');
        if (via) chosen.push([id, host, via.link]);
      }
    }
    chosen.sort((a, b) => byOrder(a[0], b[0]));
    for (const [id, host, link] of chosen) {
      const above = info.get(host);
      reach(id, { depth: above.depth + 1, up: { id: host, link: link.id, layer: link.layer }, head: above.head, loose: false });
    }
    return chosen.map(([id]) => id);
  };

  const tops = heads(graph);
  for (const id of tops) reach(id, { depth: 0, up: null, head: id, loose: false });
  flood(tops);
  for (;;) {
    const viaHost = sinceHost;
    sinceHost = [];
    let added = attachHost(viaHost);
    if (!added.length) {
      const viaRoute = sinceRoute;
      sinceRoute = [];
      added = attach('route', viaRoute, waits);
    }
    if (!added.length) {
      // nothing else moves: the guests still waiting hang by their routes
      const viaWait = sinceWait;
      sinceWait = [];
      added = attach('route', viaWait);
    }
    if (!added.length) {
      const viaParent = sinceParent;
      sinceParent = [];
      added = attach('parent', viaParent);
    }
    if (!added.length) break;
    flood(added);
  }

  const out = new Map();
  for (const t of graph.things) {
    out.set(t.id, info.get(t.id) || { depth: null, up: null, head: null, loose: true });
  }
  LAYERS_OF.set(graph, out);
  return out;
}

/* ── arrange ──────────────────────────────────────────────────────────────── */

/** The shape arrange packs toward when it is given none: 16:10. */
export const ASPECT = 16 / 10;
/** At most this many wrap widths are tried (evenly picked when there are more). */
const PACK_TRIES = 600;

/** Each thing's connected part, by union-find over every link: Map id -> a key. */
function connectedParts(graph) {
  const root = new Map(graph.things.map((t) => [t.id, t.id]));
  const top = (id) => {
    let r = id;
    while (root.get(r) !== r) r = root.get(r);
    while (root.get(id) !== r) { const next = root.get(id); root.set(id, r); id = next; }
    return r;
  };
  for (const link of graph.links) {
    if (!root.has(link.a) || !root.has(link.b)) continue;
    const ra = top(link.a);
    const rb = top(link.b);
    if (ra !== rb) root.set(ra, rb);
  }
  return new Map(graph.things.map((t) => [t.id, top(t.id)]));
}

/** The window shape asked for, kept between 1:5 and 10:1. */
function ratioOf(options) {
  const r = options && options.ratio;
  return Number.isFinite(r) && r > 0 ? Math.min(10, Math.max(0.2, r)) : ASPECT;
}

/** Pack the pieces (`{w, h}` each, in order) and `nLoose` loose cards into
    rows, at the wrap width whose drawing best fits a screen `ratio` wide to
    1 high. Returns `{at: [{x, y}], cols, looseTop, width, height}`. */
function packPieces(blocks, nLoose, ratio) {
  const shelve = (wrap) => {
    const at = [];
    let x = 0;
    let y = 0;
    let rowH = 0;
    let right = 0;
    for (const b of blocks) {
      if (x > 0 && x + b.w > wrap) { y += rowH + PIECE_GAP; x = 0; rowH = 0; }
      at.push({ x, y });
      right = Math.max(right, x + b.w);
      x += b.w + PIECE_GAP;
      rowH = Math.max(rowH, b.h);
    }
    let width = right;
    let height = blocks.length ? y + rowH : 0;
    const looseTop = blocks.length ? height + PIECE_GAP : 0;
    let cols = 1;
    if (nLoose) {
      // as wide as the drawing (or the wrap), then rows made even
      const most = Math.min(nLoose, Math.max(1, Math.floor((Math.max(wrap, right) + GAP_X) / SLOT)));
      const rows = Math.ceil(nLoose / most);
      cols = Math.ceil(nLoose / rows);
      width = Math.max(width, cols * SLOT - GAP_X);
      height = looseTop + rows * ROW - GAP_Y;
    }
    return { at, cols, looseTop, width, height };
  };
  const tries = new Set();
  let run = -PIECE_GAP;
  for (const b of blocks) { run += b.w + PIECE_GAP; tries.add(run); }
  for (let k = 1; k <= nLoose; k++) tries.add(k * SLOT - GAP_X);
  let list = [...tries].sort((a, b) => a - b);
  if (list.length > PACK_TRIES) {
    const step = (list.length - 1) / (PACK_TRIES - 1);
    list = Array.from({ length: PACK_TRIES }, (_, i) => list[Math.round(i * step)]);
  }
  let best = null;
  for (const wrap of list) {
    const p = shelve(wrap);
    const score = Math.max(p.width, ratio * p.height);
    if (!best || score < best.score - 1e-9) best = { ...p, score };
  }
  return best || shelve(0);
}

/** Where every card goes.

    Takes the graph and `{saved, ratio}`: `saved` the positions a person
    dragged, `{id: {x, y}}`; `ratio` the window's width over its height.
    Returns `{positions, width, height, bounds}`. `positions` is a
    null-prototype object of id -> `{x, y}`, the TOP-LEFT of each card.
    `width`/`height` reach from 0,0 to the far edge of the farthest card,
    saved ones included; `bounds` is `{x, y, w, h}` round every card (it can
    start below 0 when a card was dragged up or left).

    The rule: a tidy tree over `layers`. Row = depth (`ROW` apart). A leaf
    takes one `SLOT`; a thing with children sits centred over its first and
    last child, so it is always inside their span, and no two subtrees share
    a column, so no two cards overlap. Siblings are first taken in thing
    order, then sorted once by where their other links go (the mean centre of
    every neighbour that is not their parent or child, or their own place when
    they have none), and laid again, which keeps most cross links from
    crossing.

    The pieces are then packed (2026-11-17). A piece is the trees of the heads
    that one connected part of the map stands on (laid side by side,
    `PIECE_GAP` apart); the loose things are one more piece, a block of rows
    as even as they can be. The pieces go in head order, the loose block
    last, left to right in rows `PIECE_GAP` apart, a row ending where the next
    piece would pass a wrap width; the loose block takes rows of its own under
    the rest, as wide as the drawing. Of every wrap width where a row could
    end, the one taken is the one whose drawing best fits a window of
    `ratio` (width over height; `options.ratio`, default `ASPECT`, 16:10): the
    least max(width, ratio x height), the narrower on a tie. So the piece the
    first head stands on is always at 0,0, a map of many small pieces is a
    block and not a line, and one big tree is laid as before.

    A saved thing keeps its saved place; the rest are laid as if it had not
    moved. Same input and ratio, same output. */
export function arrange(graph, options = {}) {
  const info = layers(graph);
  const adj = adjacency(graph);
  const { byId } = graph;
  const children = new Map();
  for (const t of graph.things) {
    const up = info.get(t.id).up;
    if (!up) continue;
    if (!children.has(up.id)) children.set(up.id, []);
    children.get(up.id).push(t.id);
  }
  const roots = heads(graph);
  const kids = (id) => children.get(id) || [];

  /* the trees of `list` side by side from 0, PIECE_GAP apart: each thing's
     left edge, and how far the last one reaches */
  const lay = (list) => {
    const x = new Map();
    let cursor = 0;
    let span = 0;
    for (const root of list) {
      // pre-order, iteratively, so a long chain cannot overflow the stack
      const pre = [];
      const stack = [root];
      while (stack.length) {
        const id = stack.pop();
        pre.push(id);
        const list = kids(id);
        for (let i = list.length - 1; i >= 0; i--) stack.push(list[i]);
      }
      const width = new Map();
      for (let i = pre.length - 1; i >= 0; i--) {
        const list = kids(pre[i]);
        width.set(pre[i], list.length ? list.reduce((sum, c) => sum + width.get(c), 0) : 1);
      }
      const left = new Map([[root, cursor]]);
      for (const id of pre) {
        let at = left.get(id);
        for (const c of kids(id)) { left.set(c, at); at += width.get(c) * SLOT; }
      }
      for (let i = pre.length - 1; i >= 0; i--) {
        const list = kids(pre[i]);
        x.set(pre[i], list.length ? (x.get(list[0]) + x.get(list[list.length - 1])) / 2 : left.get(pre[i]));
      }
      span = cursor + width.get(root) * SLOT - GAP_X;
      cursor = span + PIECE_GAP;
    }
    return { x, span };
  };

  let { x } = lay(roots);
  // one pass of sibling ordering by where their other links go
  for (const [id, list] of children) {
    if (list.length < 2) continue;
    const key = new Map();
    for (const c of list) {
      const own = new Set([id, ...kids(c)]);
      let sum = 0;
      let n = 0;
      for (const { other } of adj.get(c)) {
        if (own.has(other) || !x.has(other)) continue;
        sum += x.get(other);
        n++;
      }
      key.set(c, n ? sum / n : x.get(c));
    }
    children.set(id, [...list].sort((a, b) => (key.get(a) - key.get(b)) || (byId.get(a).order - byId.get(b).order)));
  }
  // the pieces: the heads one connected part stands on, in head order
  const pieceOf = connectedParts(graph);
  const pieceHeads = new Map();
  for (const root of roots) {
    const key = pieceOf.get(root);
    if (!pieceHeads.has(key)) pieceHeads.set(key, []);
    pieceHeads.get(key).push(root);
  }
  const deepestOf = new Map();
  for (const t of graph.things) {
    const entry = info.get(t.id);
    if (entry.loose) continue;
    deepestOf.set(entry.head, Math.max(deepestOf.get(entry.head) ?? 0, entry.depth));
  }
  const blocks = [...pieceHeads.values()].map((list) => {
    const laid = lay(list);
    const depth = Math.max(...list.map((r) => deepestOf.get(r) ?? 0));
    return { list, x: laid.x, w: laid.span, h: depth * ROW + CARD_H };
  });
  const loose = graph.things.filter((t) => info.get(t.id).loose);
  const pack = packPieces(blocks, loose.length, ratioOf(options));

  const positions = Object.create(null);
  blocks.forEach((b, i) => {
    const at = pack.at[i];
    for (const [id, left] of b.x) positions[id] = { x: at.x + left, y: at.y + info.get(id).depth * ROW };
  });
  loose.forEach((t, i) => {
    positions[t.id] = { x: (i % pack.cols) * SLOT, y: pack.looseTop + Math.floor(i / pack.cols) * ROW };
  });

  const saved = isObj(options && options.saved) ? options.saved : {};
  for (const t of graph.things) {
    if (!Object.prototype.hasOwnProperty.call(saved, t.id)) continue;
    const s = saved[t.id];
    if (isObj(s) && Number.isFinite(s.x) && Number.isFinite(s.y)) positions[t.id] = { x: s.x, y: s.y };
  }

  let x0 = Infinity; let y0 = Infinity; let x1 = -Infinity; let y1 = -Infinity;
  for (const id in positions) {
    const p = positions[id];
    x0 = Math.min(x0, p.x); y0 = Math.min(y0, p.y);
    x1 = Math.max(x1, p.x + CARD_W); y1 = Math.max(y1, p.y + CARD_H);
  }
  if (x0 === Infinity) { x0 = 0; y0 = 0; x1 = 0; y1 = 0; }
  return {
    positions,
    width: Math.max(0, x1), height: Math.max(0, y1),
    bounds: { x: x0, y: y0, w: x1 - x0, h: y1 - y0 },
  };
}

/* ── views ────────────────────────────────────────────────────────────────── */

/** The Infrastructure view: a new graph of only the `infra` things (network
    places, and internet, switch and patch stubs) and the links whose both ends
    are among them. Its heads and layers are worked out afresh. */
export function infrastructure(graph) {
  const things = graph.things.filter((t) => t.infra);
  const keep = new Set(things.map((t) => t.id));
  const links = graph.links.filter((l) => keep.has(l.a) && keep.has(l.b));
  return graphOf(things, links);
}

/** Leaves folded into group cards, for a big map.

    Takes the graph and `{limit}` (default `FOLD_LIMIT`, 150). With `limit` or
    fewer things the same graph comes back unchanged. With more, a leaf (a
    thing that is not `infra` or a group, whose links all go to one other
    thing, that other thing not itself such a leaf) is folded with the other
    leaves of the same kind on the same thing into one group, when there are at
    least two of them (a lone leaf stays a card). A group is a thing
    `{id: 'group:<parent id>:<kind>', type: 'group', kind, count, members,
    name, ...}` placed where its first member was, with one link to the parent
    (`fold:<parent id>:<kind>`, of the best layer its members hung by: cable,
    then route, then parent). The members' own links are dropped. Returns a new
    graph. `{open}` (2026-11-17) lists group ids a person pressed open: those
    leaves stay cards of their own. */
export function foldLeaves(graph, options = {}) {
  const limit = Number.isFinite(options && options.limit) ? options.limit : FOLD_LIMIT;
  // `open` (2026-11-17): group ids a person pressed open; their leaves stay cards
  const open = new Set(options && options.open ? options.open : []);
  if (graph.things.length <= limit) return graph;
  const adj = adjacency(graph);
  const lone = new Map();
  for (const t of graph.things) {
    if (t.infra || t.type === 'group') continue;
    const others = new Set(adj.get(t.id).map((e) => e.other));
    if (others.size === 1) lone.set(t.id, [...others][0]);
  }
  const groups = new Map();
  for (const t of graph.things) {
    const p = lone.get(t.id);
    if (p === undefined || lone.get(p) === t.id) continue;
    const key = `${p}\u0000${t.kind}`;
    if (!groups.has(key)) groups.set(key, { parent: p, kind: t.kind, members: [] });
    groups.get(key).members.push(t);
  }
  const folded = new Map();
  for (const g of groups.values()) {
    if (g.members.length < 2 || open.has(`group:${g.parent}:${g.kind}`)) continue;
    for (const m of g.members) folded.set(m.id, g);
  }
  if (!folded.size) return graph;

  const things = [];
  const groupLinks = [];
  const made = new Set();
  for (const t of graph.things) {
    const g = folded.get(t.id);
    if (!g) { things.push(t); continue; }
    if (made.has(g)) continue;
    made.add(g);
    const id = `group:${g.parent}:${g.kind}`;
    const zones = new Set(g.members.map((m) => m.zone));
    things.push({
      id, type: 'group', name: `${g.members.length} ${g.kind || 'things'}`, kind: g.kind,
      count: g.members.length, members: g.members.map((m) => m.id), sub: '', ip: '',
      zone: zones.size === 1 ? g.members[0].zone : null, parent: null,
      planned: false, unmanaged: false, infra: false, order: things.length,
    });
    const held = new Set();
    for (const m of g.members) for (const e of adj.get(m.id)) held.add(e.link.layer);
    const layer = LAYERS.find((l) => held.has(l)) || 'cable';
    groupLinks.push({
      id: `fold:${g.parent}:${g.kind}`, layer, a: g.parent, b: id, aPort: '', bPort: '',
      kind: 'group', state: null, vlan: null, tagged: [], poe: null,
      speed: '', source: '', note: '', lane: 0, lanes: 1, shadowed: false,
    });
  }
  // renumber `order` on copies, so the folded graph's order is its own
  const ordered = things.map((t, i) => (t.order === i ? t : { ...t, order: i }));
  const links = graph.links.filter((l) => !folded.has(l.a) && !folded.has(l.b)).concat(groupLinks);
  return graphOf(ordered, links);
}

/* ── questions the canvas asks ────────────────────────────────────────────── */

/** The chain from a thing up to its head: `{things: [id, ..., head id],
    links: [link ids, bottom first]}`. A head gives just itself; an unknown or
    loose thing gives two empty lists. */
export function pathToHead(graph, id) {
  const info = layers(graph);
  const entry = info.get(id);
  if (!entry || entry.loose) return { things: [], links: [] };
  const things = [id];
  const links = [];
  let at = entry;
  while (at.up) {
    things.push(at.up.id);
    links.push(at.up.link);
    at = info.get(at.up.id);
  }
  return { things, links };
}

/** Each zone's VLAN, first zone with a VLAN wins: Map vlan -> zone. */
function zonesByVlan(zones) {
  const out = new Map();
  for (const z of rows(zones)) {
    const v = vlanNumber(z.vlan);
    if (v !== null && !out.has(v)) out.set(v, z);
  }
  return out;
}

/** Each zone id's VLAN: Map zone id -> vlan. */
function vlanOfZone(zones) {
  const out = new Map();
  for (const z of rows(zones)) {
    const v = vlanNumber(z.vlan);
    if (okId(z.id) && v !== null && !out.has(z.id)) out.set(z.id, v);
  }
  return out;
}

/** Does this link carry the VLAN, untagged or tagged? Only a cable carries one. */
export function carries(link, vlan) {
  const v = vlanNumber(vlan);
  if (v === null || !isObj(link) || (link.layer && link.layer !== 'cable')) return false;
  return vlanNumber(link.vlan) === v || taggedList(link.tagged).includes(v);
}

/** Is this thing on the VLAN: a place whose zone has it, or either end of a
    cable that carries it? */
export function onVlan(graph, thingId, vlan, zones) {
  const v = vlanNumber(vlan);
  const t = graph.byId.get(thingId);
  if (v === null || !t) return false;
  if (t.zone !== null && vlanOfZone(zones).get(t.zone) === v) return true;
  return (adjacency(graph).get(thingId) || []).some(({ link }) => carries(link, v));
}

/** The VLANs for the side panel, ascending: every VLAN a zone has or a cable
    carries, as `{vlan, name, hue, cables, things}`. Name and hue come from the
    first zone with that VLAN (null when none has it, or it has no hue).
    `cables` counts the cables that carry it; `things` counts the places whose
    zone has it plus every end of a cable that carries it, each once. */
export function vlanList(graph, zones) {
  const byVlan = zonesByVlan(zones);
  const zoneVlan = vlanOfZone(zones);
  const found = new Map();
  const entry = (v) => {
    if (!found.has(v)) found.set(v, { cables: 0, things: new Set() });
    return found.get(v);
  };
  for (const v of byVlan.keys()) entry(v);
  for (const t of graph.things) {
    const v = t.zone === null ? undefined : zoneVlan.get(t.zone);
    if (v !== undefined) entry(v).things.add(t.id);
  }
  for (const link of graph.links) {
    if (link.layer !== 'cable') continue;
    const carried = new Set([vlanNumber(link.vlan), ...taggedList(link.tagged)]);
    carried.delete(null);
    for (const v of carried) {
      const e = entry(v);
      e.cables++;
      e.things.add(link.a);
      e.things.add(link.b);
    }
  }
  return [...found.keys()].sort((a, b) => a - b).map((v) => {
    const z = byVlan.get(v);
    return {
      vlan: v, name: z ? words(z.name) || null : null, hue: z ? words(z.hue) || null : null,
      cables: found.get(v).cables, things: found.get(v).things.size,
    };
  });
}

/** The colours a cable is drawn in: its VLANs' zone hues, untagged first,
    then tagged ascending, each VLAN once. One hue for an access cable, a
    stripe per VLAN for a trunk. A VLAN with no zone hue gives no stripe, so
    `[]` (no VLAN, or no hue for any) means the drawing's neutral ink. */
export function stripes(link, zones) {
  if (!isObj(link) || (link.layer && link.layer !== 'cable')) return [];
  const byVlan = zonesByVlan(zones);
  const order = [vlanNumber(link.vlan), ...taggedList(link.tagged)].filter((v) => v !== null);
  const out = [];
  for (const v of new Set(order)) {
    const hue = byVlan.has(v) ? words(byVlan.get(v).hue) : '';
    if (hue) out.push(hue);
  }
  return out;
}

/** Find on canvas: the ids, in thing order, of things whose name, id,
    address, or a port at their own end of one of their links contains the
    text (case-insensitive, trimmed). Empty text finds nothing. */
export function find(graph, text) {
  const q = words(text).toLowerCase();
  if (!q) return [];
  const adj = adjacency(graph);
  const out = [];
  for (const t of graph.things) {
    let hit = [t.name, t.id, t.ip].some((s) => s && s.toLowerCase().includes(q));
    if (!hit) {
      hit = (adj.get(t.id) || []).some(({ link }) => {
        const port = link.a === t.id ? link.aPort : link.bPort;
        return port !== '' && port.toLowerCase().includes(q);
      });
    }
    if (hit) out.push(t.id);
  }
  return out;
}

/** What is on screen: the ids whose card (`CARD_W` x `CARD_H` from its
    top-left) meets the box `{x, y, w, h}` grown by `margin` on every side.
    Takes positions as arrange returns them (or a Map). */
export function seen(positions, box, margin = 0) {
  const m = Number.isFinite(margin) ? margin : 0;
  if (!isObj(box)) return [];
  const bx0 = box.x - m;
  const by0 = box.y - m;
  const bx1 = box.x + box.w + m;
  const by1 = box.y + box.h + m;
  const entries = positions instanceof Map ? [...positions] : Object.entries(positions || {});
  const out = [];
  for (const [id, p] of entries) {
    if (!isObj(p)) continue;
    if (p.x <= bx1 && p.x + CARD_W >= bx0 && p.y <= by1 && p.y + CARD_H >= by0) out.push(id);
  }
  return out;
}

/** The connections spreadsheet: one row per place, and per stub with a
    cable, as `{id, name, to, toId, port, farPort, vlan, poe, path}`.

    A row is filled only when the thing hangs by a cable: `to` is the name of
    what it hangs from (`toId` its id), `port` its own port on that cable,
    `farPort` the port at the other end, `vlan` the cable's `vlanLabel`, `poe`
    its watts, `path` the names from it up to its head joined with ' \u203a '.
    Otherwise (a head, a thing that hangs by a route or a parent, a loose one)
    every one of those is '': never a guess from a route. Rows sort by name
    lower-cased, then id, in plain code-point order. */
export function connections(graph) {
  const info = layers(graph);
  const adj = adjacency(graph);
  const out = [];
  for (const t of graph.things) {
    if (t.type === 'group') continue;
    if (t.type === 'stub' && !adj.get(t.id).some(({ link }) => link.layer === 'cable')) continue;
    const row = { id: t.id, name: t.name, to: '', toId: '', port: '', farPort: '', vlan: '', poe: '', path: '' };
    const up = info.get(t.id).up;
    const link = up && up.layer === 'cable' ? graph.linkById.get(up.link) : null;
    if (link) {
      const mine = link.a === t.id;
      row.to = graph.byId.get(up.id).name;
      row.toId = up.id;
      row.port = mine ? link.aPort : link.bPort;
      row.farPort = mine ? link.bPort : link.aPort;
      row.vlan = vlanLabel(link);
      row.poe = link.poe === null ? '' : link.poe;
      row.path = pathToHead(graph, t.id).things.map((id) => graph.byId.get(id).name).join(' \u203a ');
    }
    out.push(row);
  }
  const key = (r) => r.name.toLowerCase();
  return out.sort((a, b) => {
    const ka = key(a);
    const kb = key(b);
    if (ka !== kb) return ka < kb ? -1 : 1;
    return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
  });
}

/* ── the drawing's own sums (2026-11-17) ──────────────────────────────────── */

/** The folded group a thing is in, in a graph foldLeaves returned, or null. */
export function groupHolding(graph, id) {
  for (const t of graph.things) {
    if (t.type === 'group' && Array.isArray(t.members) && t.members.includes(id)) return t.id;
  }
  return null;
}

/** What one VLAN lights: the things on it (onVlan) and the cables that carry
    it, both in graph order. */
export function vlanLit(graph, vlan, zones) {
  if (vlanNumber(vlan) === null) return { things: [], links: [] };
  return {
    things: graph.things.filter((t) => onVlan(graph, t.id, vlan, zones)).map((t) => t.id),
    links: graph.links.filter((l) => carries(l, vlan)).map((l) => l.id),
  };
}

/** A lit chain, head first: `things` from the head down, `links[i]` joining
    `things[i]` and `things[i + 1]`. With `failedAt` (an index into `things`)
    the chain is lit only as far as that step, which is the failed one, and
    the link into it is the failed link. Without it (null, or out of range)
    the whole chain is lit and nothing failed. */
export function pathMarks(things, links, failedAt) {
  const ts = Array.isArray(things) ? things : [];
  const ls = Array.isArray(links) ? links : [];
  if (!Number.isInteger(failedAt) || failedAt < 0 || failedAt >= ts.length) {
    return { things: [...ts], links: [...ls], failedThing: null, failedLink: null };
  }
  return {
    things: ts.slice(0, failedAt + 1),
    links: ls.slice(0, failedAt),
    failedThing: ts[failedAt],
    failedLink: failedAt > 0 && failedAt - 1 < ls.length ? ls[failedAt - 1] : null,
  };
}
