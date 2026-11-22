
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
          break;
        }
      }
    }
  }
  return out;
}

export function tierOf(n) {
  if (n.id === 'internet') return 0;
  if (['gateway', 'router', 'firewall', 'proxy', 'caddy', 'nginx', 'haproxy', 'wireguard'].includes(n.id)) return 1;
  if (n.parent) return 3;
  return 2;
}

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
    const x = even ? (100 * (c + 0.5)) / cols : left + w / 2;
    left += w;
    tier.forEach((n, i) => {
      pos[n.id] = { x, y: (100 * (i + 0.5)) / rows, w, c };
    });
  });
  return { tiers, pos, rows, cols };
}

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

export function chainPairs(chain, sep = ' ') {
  const pairs = new Set();
  for (let i = 0; i < chain.length - 1; i++) {
    pairs.add(`${chain[i]}${sep}${chain[i + 1]}`);
    pairs.add(`${chain[i + 1]}${sep}${chain[i]}`);
  }
  return pairs;
}
