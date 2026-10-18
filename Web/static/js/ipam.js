/* Address math for THE LEDGER.

   The Ledger used to assume every segment was a /24 — it derived a prefix by
   taking the first three octets of an address (`ip.split('.').slice(0,3)`) and
   drew a fixed 256-cell grid with `254 - charted` free. That is correct for
   exactly one shape of network and quietly wrong for every other: a /22 showed
   a quarter of itself, a /30 point-to-point link claimed 254 free addresses,
   and IPv6 didn't exist.

   BigInt throughout, so v4 and v6 are the same code. Nothing here touches the
   DOM — it is arithmetic, and it is tested against the Python side's
   `ipaddress` results. */

/** Parse a dotted quad or a v6 literal into a BigInt, or null. */
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
  // one "::" may stand in for a run of zero groups
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
  // RFC 5952: collapse the *longest* run of zero groups, and only if it is
  // longer than one. A naive regex gets `fd00:beef::` wrong as `fd00:beef::0`.
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

/**
 * Parse `192.0.2.0/24` (or a bare address, treated as a host route).
 * @returns {{version, bits, prefixlen, network, broadcast, size}|null}
 */
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

export const contains = (net, addrValue) =>
  net && addrValue >= net.network && addrValue <= net.broadcast;

/** True when `inner` sits entirely inside `outer` and is not the same prefix. */
export function isSubnetOf(inner, outer) {
  return inner && outer && inner.version === outer.version &&
    inner.prefixlen > outer.prefixlen &&
    inner.network >= outer.network && inner.broadcast <= outer.broadcast;
}

/**
 * The addresses that can actually be assigned.
 *
 * IPv4 reserves the network and broadcast addresses — except on /31 (RFC 3021
 * point-to-point) and /32 (a host route), where both ends are usable and
 * pretending otherwise reports a link as having −2 addresses. IPv6 has no
 * broadcast, so only the subnet-router anycast address at the bottom is spoken
 * for, and even that is a convention rather than a rule.
 */
export function usableRange(net) {
  if (!net) return null;
  if (net.version === 4 && net.prefixlen <= 30) {
    return { first: net.network + 1n, last: net.broadcast - 1n, count: net.size - 2n };
  }
  return { first: net.network, last: net.broadcast, count: net.size };
}

/** Below this, a prefix is drawn cell by cell; above it, summarised. */
export const GRID_LIMIT = 1024n;

export const drawable = (net) => net && net.size <= GRID_LIMIT;

/** Format a count that may be astronomically large (a /64 is 1.8e19). */
export function countLabel(n) {
  if (n < 1000000n) return n.toLocaleString();
  const exp = n.toString().length - 1;
  return `10^${exp}`;
}

/**
 * The lowest assignable address not already claimed.
 * @param {object} net       parsed prefix
 * @param {Set<bigint>} used addresses already charted
 * @param {Array} ranges     pools/reservations to stay out of
 */
export function nextFree(net, used, ranges = []) {
  const range = usableRange(net);
  if (!range) return null;
  const blocked = ranges.map((r) => ({
    from: parseAddress(r.start)?.value, to: parseAddress(r.end)?.value,
  })).filter((r) => r.from !== undefined && r.to !== undefined);
  // Only ever walk a sane number of candidates: on a /64 the answer is the
  // first address anyway, and scanning 1.8e19 of them is not a plan.
  const ceiling = range.first + (range.count > 65536n ? 65536n : range.count);
  for (let a = range.first; a < ceiling; a++) {
    if (used.has(a)) continue;
    if (blocked.some((b) => a >= b.from && a <= b.to)) continue;
    return formatAddress(net.version, a);
  }
  return null;
}

/**
 * Turn the dataset into the prefix list the Ledger draws.
 *
 * `prefixes[]` is the modern shape. A dataset that predates it — every dataset
 * written before now — carries its addressing on `zones[].subnet`, so those
 * are synthesised into prefixes and behave identically. Nothing has to be
 * migrated for the Ledger to keep working.
 */
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

/** Every charted address, as {value: node}. Skips `—` and anything unparseable. */
/** value -> the place that holds it.

    More than one charted place can answer on one address: the edge the VM and
    The edge services drawn as their own places, TRAEFIK and PANGOLIN, all sit
    on one address. This used to keep whichever came LAST in node order, so the
    IPAM named a service and lost the host entirely.

    The machine wins — a `vm` or `physical` place is the thing that actually
    holds the lease; a `network` place charted at the same address is a role
    running on it. Ties keep the first, so the answer is stable across edits.
    Co-claimants are not dropped: the Ledger names them on the row (see
    ledger.js sharersOf). */
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

/** What the Ledger needs to draw one prefix. */
export function occupancy(prefix, charted) {
  const range = usableRange(prefix.net);
  const hosts = [];
  for (const [value, node] of charted) {
    if (contains(prefix.net, value)) hosts.push({ value, node });
  }
  hosts.sort((a, b) => (a.value < b.value ? -1 : 1));
  // A host inside a child prefix belongs to the child, not to its container —
  // otherwise a /16 would report every address in the building as its own.
  const direct = prefix.children?.length
    ? hosts.filter(({ value }) => !prefix.children.some((c) => contains(c.net, value)))
    : hosts;
  const pool = (prefix.ranges || []).reduce((sum, r) => {
    const from = parseAddress(r.start)?.value;
    const to = parseAddress(r.end)?.value;
    return (from !== undefined && to !== undefined && to >= from) ? sum + (to - from + 1n) : sum;
  }, 0n);

  // A container's occupancy is how much of it has been delegated, not how many
  // hosts sit loose in it. "65,533 free" on a /16 that is fully carved into
  // /24s is arithmetically true and completely useless.
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

/** Which range (if any) an address falls inside — colours the grid cell. */
export function rangeAt(prefix, value) {
  for (const r of prefix.ranges || []) {
    const from = parseAddress(r.start)?.value;
    const to = parseAddress(r.end)?.value;
    if (from !== undefined && to !== undefined && value >= from && value <= to) return r;
  }
  return null;
}
