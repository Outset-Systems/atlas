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
    `pos`, each place's {x, y} by id. */
export function layout(nodes) {
  const tiers = [[], [], [], []];
  for (const n of nodes) tiers[tierOf(n)].push(n);
  const TIER_Y = [8, 30, 55, 82];
  const pos = {};
  tiers.forEach((tier, t) => {
    tier.forEach((n, i) => {
      pos[n.id] = { x: (100 * (i + 1)) / (tier.length + 1), y: TIER_Y[t] };
    });
  });
  return { tiers, pos };
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
