/* TOPOLOGY, the model: which tier a place stands on, where it is drawn, which
   edges join the places, and which charted service roads cross a hop.

   Pure functions over the dataset's rows — no DOM, no `A` — so
   tests/test_path_model.mjs can pin them under node. path.js draws what these
   return. */

/** Every charted service road that crosses a given hop, each with the WHOLE
    road it belongs to.

    A road is `[the service's host, ...link.path]` — the same chain `open()`
    lights when a service card hands one over, built the same way here so the
    two can never disagree about where a road begins. A hop is crossed when the
    chain names both ends CONSECUTIVELY: an unordered "contains both" would
    claim Jellyfin crosses gateway→pangolin, two stops that are on its road
    but not adjacent on it, and a picture that cannot tell "next to" from
    "somewhere along" is the starburst this whole chain drawing replaced.

    Direction is not checked. The edge is drawn once for a pair, and traffic on
    it is answered in both directions; a road that runs b→a still runs over this
    hop. Services with no charted `path` are skipped rather than guessed at —
    39 of the realm's 49 have none, and inventing roads for them would fill the
    map with lines nobody surveyed. */
export function servicesCrossing(nodes, a, b) {
  const out = [];
  for (const n of nodes || []) {
    for (const link of n.links || []) {
      const hops = Array.isArray(link.path) ? link.path.filter(Boolean) : [];
      if (!hops.length) continue;
      const chain = [n.id, ...hops];
      for (let i = 0; i < chain.length - 1; i++) {
        if ((chain[i] === a && chain[i + 1] === b) || (chain[i] === b && chain[i + 1] === a)) {
          out.push({ host: n, link, chain });
          break;                       // a road crossing a hop twice is still one road
        }
      }
    }
  }
  return out;
}

export function tierOf(n) {
  if (n.id === 'the-wild' || n.id === 'cloudflare') return 0;
  if (['gateway', 'traefik', 'tailscale', 'pangolin'].includes(n.id)) return 1;  // the ways in
  if (n.parent) return 3;
  return 2;                       // physical iron + remaining network gear
}

/** Lay the tiers out on a normalized 100×100 grid. Returns the four tiers and
    `pos`, each place's {x, y} by id.

    Wide (the default) the tiers are rows down the page and a tier's places
    spread across it. `narrow` (a phone, 2026-11-18) turns the picture a quarter:
    the tiers that hold anything are columns across the page, left to right in
    tier order, and a tier's places stack down from the top, every tier on the
    same rows. A phone has room downward and none across, and a name needs a
    column's width to be read. `rows` is the busiest tier's count (what the
    narrow picture's height is cut by) and `cols` the number of columns it has.

    `needs` (narrow only) is what each place must have to be read, by id, as a
    share of the picture's width out of 100: its longest word or its address,
    measured by the caller, and `air` the room the caller would like beside
    it. A column is as wide as its neediest place asks and the rest share what
    is left (`columnWidths`), so with no needs, or none over an equal share,
    the columns are the equal ones they always were. A narrow place also
    carries `w`, its column's width, and `c`, its column. */
export function layout(nodes, narrow = false, needs = {}, air = 0) {
  const tiers = [[], [], [], []];
  for (const n of nodes) tiers[tierOf(n)].push(n);
  const TIER_Y = [8, 30, 55, 82];
  const pos = {};
  if (!narrow) {
    tiers.forEach((tier, t) => {
      tier.forEach((n, i) => {
        pos[n.id] = { x: (100 * (i + 1)) / (tier.length + 1), y: TIER_Y[t] };
      });
    });
    return { tiers, pos };
  }
  const held = tiers.filter((tier) => tier.length);
  const cols = Math.max(held.length, 1);
  const rows = Math.max(...tiers.map((tier) => tier.length), 1);
  const widths = columnWidths(held.map((tier) => Math.max(0, ...tier.map((n) => Number(needs?.[n.id]) || 0))), air);
  const even = widths.every((w) => w === 100 / cols);
  let left = 0;
  held.forEach((tier, c) => {
    const w = widths[c];
    // equal columns keep the centres they had, to the last digit
    const x = even ? (100 * (c + 0.5)) / cols : left + w / 2;
    left += w;
    tier.forEach((n, i) => {
      pos[n.id] = { x, y: (100 * (i + 0.5)) / rows, w, c };
    });
  });
  return { tiers, pos, rows, cols };
}

/** Share a width of 100 among columns that each need some of it, and would
    each like `air` beside what they need. Every column gets an equal share
    unless need and air together are more; one that asks more takes that, and
    the others share what is left equally (asked again, since a smaller share
    can be less than another column asks). The air gives way first: when the
    needs fit and the air does not, every column gets its need and an equal
    part of what is over. When the needs alone add up to 100 or more there is
    nothing to share and something must be cut: the neediest columns are, down
    to one width between them, and every column that needs less than that
    keeps all of its need. The picture still fits its width, and as few of the
    caller's names break as can (cutting every column in proportion broke the
    longest name in each of them). */
export function columnWidths(needs, air = 0) {
  const need = (needs || []).map((v) => Math.max(0, Number(v) || 0));
  if (!need.length) return [];
  const room = Math.max(0, Number(air) || 0);
  const bare = need.reduce((a, b) => a + b, 0);
  if (bare >= 100) {
    const out = new Array(need.length).fill(0);
    const order = need.map((_, i) => i).sort((a, b) => need[a] - need[b]);
    let left = 100;
    order.forEach((i, k) => {
      const share = left / (order.length - k);
      out[i] = Math.min(need[i], share);
      left -= out[i];
    });
    return out;
  }
  if (bare + room * need.length >= 100) return need.map((v) => v + (100 - bare) / need.length);
  const want = need.map((v) => v + room);
  const out = new Array(want.length).fill(0);
  let open = want.map((_, i) => i);
  let left = 100;
  for (;;) {
    const share = left / open.length;
    const over = open.filter((i) => want[i] > share);
    if (!over.length) {
      for (const i of open) out[i] = share;
      return out;
    }
    for (const i of over) { out[i] = want[i]; left -= want[i]; }
    open = open.filter((i) => !over.includes(i));
  }
}

/** The curve between two places, as an SVG path's `d` on the same grid. Wide,
    it leaves and arrives vertically (the tiers are rows); narrow, horizontally
    (the tiers are columns). Narrow, two places in one column would be joined
    by a straight line down through every name between them, so that curve
    bows out into the gap beside the column instead: toward the column before
    it, or after it for the first. `cols` is the narrow layout's column count;
    a place that carries its column's own width and number (`w`, `c`, from
    `layout`) is bowed by those, since columns need not be equal. */
export function edgePath(a, b, narrow = false, cols = 1) {
  if (!narrow) {
    const my = (a.y + b.y) / 2;
    return `M ${a.x} ${a.y} C ${a.x} ${my}, ${b.x} ${my}, ${b.x} ${b.y}`;
  }
  if (a.x === b.x) {
    const width = a.w ?? 100 / Math.max(cols, 1);
    const first = a.c != null ? a.c === 0 : a.x < width;
    const bx = a.x + (first ? 0.62 : -0.62) * width;
    return `M ${a.x} ${a.y} C ${bx} ${a.y}, ${bx} ${b.y}, ${b.x} ${b.y}`;
  }
  const mx = (a.x + b.x) / 2;
  return `M ${a.x} ${a.y} C ${mx} ${a.y}, ${mx} ${b.y}, ${b.x} ${b.y}`;
}

/** edges: routes[] + parent containment (drawn quieter). A route is kept only
    when both of its ends have a position. */
export function edgesOf(routes, nodes, pos) {
  const edges = [];
  for (const r of routes || []) {
    if (pos[r.from] && pos[r.to]) edges.push({ a: r.from, b: r.to, kind: r.kind || 'road' });
  }
  for (const n of nodes) {
    if (n.parent && pos[n.parent]) edges.push({ a: n.parent, b: n.id, kind: 'vassal' });
  }
  return edges;
}

/** Every consecutive pair of a chain, both ways round, as `a<sep>b` — an edge
    is drawn once for a pair, so a lookup must match it in either direction. */
export function chainPairs(chain, sep = ' ') {
  const pairs = new Set();
  for (let i = 0; i < chain.length - 1; i++) {
    pairs.add(`${chain[i]}${sep}${chain[i + 1]}`);
    pairs.add(`${chain[i + 1]}${sep}${chain[i]}`);
  }
  return pairs;
}
