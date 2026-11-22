
export function parseAddress(text) {
  if (typeof text !== 'string') return null;
  const value = text.trim();
  if (!value) return null;
  if (value.includes(':')) return parseV6(value);
  return parseV4(value);
}

function parseV4(text) {
  const parts = text.split('.');
  if (parts.length !== 4) return null;
  let out = 0n;
  for (const part of parts) {
    if (!/^\d{1,3}$/.test(part)) return null;
    const n = Number(part);
    if (n > 255) return null;
    out = (out << 8n) | BigInt(n);
  }
  return { version: 4, value: out };
}

function parseV6(text) {
  const halves = text.split('::');
  if (halves.length > 2) return null;
  const head = halves[0] ? halves[0].split(':') : [];
  const tail = halves.length === 2 ? (halves[1] ? halves[1].split(':') : []) : null;
  const groups = tail === null
    ? head
    : [...head, ...Array(8 - head.length - tail.length).fill('0'), ...tail];
  if (groups.length !== 8) return null;
  let out = 0n;
  for (const group of groups) {
    if (!/^[0-9a-fA-F]{1,4}$/.test(group)) return null;
    out = (out << 16n) | BigInt(parseInt(group, 16));
  }
  return { version: 6, value: out };
}

export function formatAddress(version, value) {
  if (version === 4) {
    return [24n, 16n, 8n, 0n].map((shift) => Number((value >> shift) & 255n)).join('.');
  }
  const groups = [];
  for (let i = 7n; i >= 0n; i--) groups.push(Number((value >> (i * 16n)) & 0xffffn));
  let bestAt = -1, bestLen = 0, at = -1, len = 0;
  groups.forEach((group, i) => {
    if (group === 0) {
      if (at < 0) at = i;
      len++;
      if (len > bestLen) { bestAt = at; bestLen = len; }
    } else { at = -1; len = 0; }
  });
  const hex = groups.map((g) => g.toString(16));
  if (bestLen < 2) return hex.join(':');
  return `${hex.slice(0, bestAt).join(':')}::${hex.slice(bestAt + bestLen).join(':')}`;
}

export function parseCidr(text) {
  if (typeof text !== 'string') return null;
  const [addrText, lenText] = text.trim().split('/');
  const addr = parseAddress(addrText);
  if (!addr) return null;
  const bits = addr.version === 4 ? 32 : 128;
  const prefixlen = lenText === undefined ? bits : Number(lenText);
  if (!Number.isInteger(prefixlen) || prefixlen < 0 || prefixlen > bits) return null;
  const hostBits = BigInt(bits - prefixlen);
  const mask = ((1n << BigInt(prefixlen)) - 1n) << hostBits;
  const network = addr.value & mask;
  const size = 1n << hostBits;
  return {
    version: addr.version, bits, prefixlen, network,
    broadcast: network + size - 1n, size,
  };
}

const contains = (net, addrValue) =>
  net && addrValue >= net.network && addrValue <= net.broadcast;

export function isSubnetOf(inner, outer) {
  return inner && outer && inner.version === outer.version &&
    inner.prefixlen > outer.prefixlen &&
    inner.network >= outer.network && inner.broadcast <= outer.broadcast;
}

export function usableRange(net) {
  if (!net) return null;
  if (net.version === 4 && net.prefixlen <= 30) {
    return { first: net.network + 1n, last: net.broadcast - 1n, count: net.size - 2n };
  }
  return { first: net.network, last: net.broadcast, count: net.size };
}

export const GRID_LIMIT = 1024n;

export const drawable = (net) => net && net.size <= GRID_LIMIT;

export function countLabel(n) {
  if (n < 1000000n) return n.toLocaleString();
  const exp = n.toString().length - 1;
  return `10^${exp}`;
}

export function nextFree(net, used, ranges = []) {
  const range = usableRange(net);
  if (!range) return null;
  const blocked = ranges.map((r) => ({
    from: parseAddress(r.start)?.value, to: parseAddress(r.end)?.value,
  })).filter((r) => r.from !== undefined && r.to !== undefined);
  const ceiling = range.first + (range.count > 65536n ? 65536n : range.count);
  for (let a = range.first; a < ceiling; a++) {
    if (used.has(a)) continue;
    if (blocked.some((b) => a >= b.from && a <= b.to)) continue;
    return formatAddress(net.version, a);
  }
  return null;
}

export function prefixesOf(data) {
  const out = [];
  const seen = new Set();

  for (const prefix of data.prefixes || []) {
    const net = parseCidr(prefix.cidr);
    if (!net) continue;
    seen.add(prefix.cidr);
    out.push({ ...prefix, net, source: 'prefix' });
  }
  for (const zone of data.zones || []) {
    if (!zone.subnet || seen.has(zone.subnet)) continue;
    const net = parseCidr(zone.subnet);
    if (!net) continue;
    seen.add(zone.subnet);
    out.push({
      id: `zone:${zone.id}`, cidr: zone.subnet, zone: zone.id,
      name: zone.name, role: 'prefix', ranges: [], net, source: 'zone',
    });
  }

  out.sort((a, b) => (a.net.version - b.net.version) ||
                     (a.net.network < b.net.network ? -1 : a.net.network > b.net.network ? 1 : 0) ||
                     (a.net.prefixlen - b.net.prefixlen));
  for (const prefix of out) {
    prefix.children = out.filter((other) => other !== prefix && isSubnetOf(other.net, prefix.net));
    prefix.parent = out.find((other) => other !== prefix && isSubnetOf(prefix.net, other.net)) || null;
  }
  return out;
}

export function chartedAddresses(data) {
  const out = new Map();
  const rank = (n) => (n.kind === 'vm' || n.kind === 'physical' ? 0 : 1);
  for (const node of data.nodes || []) {
    const addr = parseAddress(String(node.ip || '').split('/')[0]);
    if (!addr) continue;
    const held = out.get(addr.value);
    if (!held || rank(node) < rank(held)) out.set(addr.value, node);
  }
  return out;
}

export function sharersOf(nodes, node) {
  const ip = String(node.ip || '').split('/')[0];
  if (!ip || ip === '—') return [];
  return nodes.filter((n) => n !== node
    && String(n.ip || '').split('/')[0] === ip);
}

export function occupancy(prefix, charted) {
  const range = usableRange(prefix.net);
  const hosts = [];
  for (const [value, node] of charted) {
    if (contains(prefix.net, value)) hosts.push({ value, node });
  }
  hosts.sort((a, b) => (a.value < b.value ? -1 : 1));
  const direct = prefix.children?.length
    ? hosts.filter(({ value }) => !prefix.children.some((c) => contains(c.net, value)))
    : hosts;
  const pool = (prefix.ranges || []).reduce((sum, r) => {
    const from = parseAddress(r.start)?.value;
    const to = parseAddress(r.end)?.value;
    return (from !== undefined && to !== undefined && to >= from) ? sum + (to - from + 1n) : sum;
  }, 0n);

  const container = prefix.role === 'container';
  const delegated = container
    ? (prefix.children || []).reduce((sum, c) => sum + c.net.size, 0n)
    : 0n;

  const used = container ? delegated : BigInt(direct.length) + pool;
  const total = container ? prefix.net.size : (range ? range.count : 0n);
  return {
    hosts, direct, range, pool, container, delegated,
    used,
    free: total > used ? total - used : 0n,
    total,
    percent: total > 0n ? Number((used * 10000n) / total) / 100 : 0,
  };
}

export function rangeAt(prefix, value) {
  for (const r of prefix.ranges || []) {
    const from = parseAddress(r.start)?.value;
    const to = parseAddress(r.end)?.value;
    if (from !== undefined && to !== undefined && value >= from && value <= to) return r;
  }
  return null;
}

export function freeV4(prefixes, charted) {
  const v4 = prefixes.filter((p) => p.net.version === 4 && !p.children.length);
  return v4.reduce((sum, p) => sum + occupancy(p, charted).free, 0n);
}

export function looseAddresses(prefixes, charted) {
  return [...charted.entries()].filter(([value]) =>
    !prefixes.some((p) => value >= p.net.network && value <= p.net.broadcast));
}
