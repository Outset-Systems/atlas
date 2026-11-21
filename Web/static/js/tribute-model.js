/* RESOURCES' sums, with no DOM (2026-11-20).

   RESOURCES shows how each machine's memory and processors are divided among
   its guests. Until now the sums were inside tribute.js and there was one
   machine: every guest was divided against the single `meta.tribute`,
   whichever host it named. This file is those sums for any number of hosts,
   so the scene can show one location, or everything with a total (owner:
   "selecting 'home office' will display just the resources there, but
   selecting 'Resources' will display a summary/total of everything").

   A HOST is any place a guest names as its `host`, in the order the guests
   name them, then any other place that declares capacity of its own (a
   machine that runs no guests is still compute: a Raspberry Pi, a GPU box).

   CAPACITY is the place's own, on the map: `ram_gb`, `ram_reserve_gb`,
   `cpu_cores`, `cpu_threads`. A lab charted before those fields has one
   `meta.tribute` and one host: when exactly one host with guests declares
   nothing of its own, `meta.tribute` is that host's, so that lab's numbers
   are what they were. A host with no capacity from either says so (null),
   and is never drawn as empty or as full: its guests are still summed, and
   the total says how many hosts it could not count.

   Unit-tested by tests/test_tribute_model.mjs under plain node. */

/** The capacity a place declares, in the order the scene reads them. */
export const CAPACITY_FIELDS = ['ram_gb', 'ram_reserve_gb', 'cpu_cores', 'cpu_threads'];

const num = (v) => (typeof v === 'number' && Number.isFinite(v) && v >= 0 ? v
  : (typeof v === 'string' && v.trim() !== '' && Number.isFinite(Number(v)) && Number(v) >= 0 ? Number(v) : null));
const sum = (list, pick) => list.reduce((s, x) => s + (num(pick(x)) || 0), 0);
/** Sums of tenths (4.6 + 5.4 …) come out as 9.999…: one decimal is all the map holds. */
const tenth = (n) => Math.round(n * 10) / 10;

/** A place's own capacity, or null when it declares none. A field it does not
    declare is null, not 0: "16 threads, memory not charted" is a real state. */
export function ownCapacity(node) {
  if (!node || typeof node !== 'object') return null;
  const cap = { total_gb: num(node.ram_gb), reserve_gb: num(node.ram_reserve_gb),
                cores: num(node.cpu_cores), threads: num(node.cpu_threads) };
  return cap.total_gb === null && cap.cores === null && cap.threads === null ? null : cap;
}

/** `meta.tribute` in the same shape, or null. */
export function legacyCapacity(meta) {
  const t = meta && typeof meta === 'object' ? meta.tribute : null;
  if (!t || typeof t !== 'object') return null;
  const cap = { total_gb: num(t.total_gb), reserve_gb: num(t.host_reserve_gb),
                cores: num(t.cpu_cores), threads: num(t.cpu_threads) };
  return cap.total_gb === null && cap.cores === null && cap.threads === null ? null : cap;
}

/** Every host with its guests and its sums.

    `ofNode` is locations-model's Map(place id → location key); a host it does
    not hold has `location: null`. `rackOf` is its Map(place id → rack id); a
    host in no rack has `rack: null` (and '' is a real rack id). Each host:
      {id, node, location, rack, capacity | null, legacy, guests, on,
       assigned_gb, demand_gb, free_gb | null, vcpu, threads_free | null, over} */
export function hostsOf(data, ofNode = new Map(), rackOf = new Map()) {
  const d = data && typeof data === 'object' ? data : {};
  const nodes = (Array.isArray(d.nodes) ? d.nodes : []).filter((n) => n && typeof n.id === 'string');
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const vms = (Array.isArray(d.vms) ? d.vms : []).filter((v) => v && typeof v.id === 'string');
  const guestIds = new Set(vms.map((v) => v.id));

  const order = [];
  const seen = new Set();
  const add = (id) => { if (typeof id === 'string' && id && !seen.has(id)) { seen.add(id); order.push(id); } };
  for (const v of vms) add(v.host);
  for (const n of nodes) if (!guestIds.has(n.id) && n.kind !== 'vm' && ownCapacity(n)) add(n.id);

  const guestsOf = (id) => vms.filter((v) => v.host === id);
  const legacy = legacyCapacity(d.meta);
  const unsaid = order.filter((id) => guestsOf(id).length && !ownCapacity(byId.get(id)));
  const heir = legacy && unsaid.length === 1 ? unsaid[0] : null;

  return order.map((id) => {
    const node = byId.get(id) || null;
    const guests = guestsOf(id);
    const on = guests.filter((v) => v.state === 'on');
    const capacity = ownCapacity(node) || (id === heir ? legacy : null);
    const assigned = tenth(sum(on, (v) => v.ram_gb));
    const vcpu = sum(on, (v) => v.vcpu);
    const total = capacity ? capacity.total_gb : null;
    const threads = capacity ? capacity.threads : null;
    return {
      id, node, location: ofNode.get(id) ?? null, rack: rackOf.get(id) ?? null,
      capacity, legacy: id === heir && !ownCapacity(node),
      guests, on,
      assigned_gb: assigned,
      demand_gb: tenth(sum(on, (v) => v.demand_gb)),
      free_gb: total === null ? null : tenth(Math.max(0, total - (capacity.reserve_gb || 0) - assigned)),
      vcpu,
      threads_free: threads === null ? null : Math.max(0, threads - vcpu),
      over: threads === null ? 0 : Math.max(0, vcpu - threads),
    };
  });
}

/** The hosts at one location (every host when the key is null or ''). */
export function hostsAt(hosts, key) {
  return key === null || key === undefined || key === '' ? hosts : hosts.filter((h) => h.location === key);
}

/** The hosts in one rack. `''` is a real rack id, so the rack is asked for
    by id and never by truth. */
export const hostsIn = (hosts, rackId) => hosts.filter((h) => h.rack === rackId);

/** RESOURCES' answer to "is there anything of mine here" (locations-model
    `offered`): a machine that runs guests, at the location or in the rack.
    A machine that only declares its compute divides nothing, so it does not
    make a place to choose (owner, 2026-11-20: "hide them, for example living
    room should be hidden"); it is still listed, under everything. */
export const holdsHosts = (hosts) => (l, r) => hosts.some((h) => h.guests.length > 0
  && (r ? h.rack === r.id : h.location === l.key));

/** One line of sums over some hosts.

    The memory and processor sums count only the hosts that DIVIDE theirs
    among guests, and of those only the ones whose capacity is known:
    `uncounted_gb` and `uncounted_cpu` say how many were left out, so a total
    is never read as the whole when it is not. `machines`, `cores_all`,
    `threads_all` and `ram_all` are every machine that declares capacity,
    guests or none: the compute that stands there. */
export function totalsOf(hosts) {
  const dividing = hosts.filter((h) => h.guests.length);
  const mem = dividing.filter((h) => h.capacity && h.capacity.total_gb !== null);
  const cpu = dividing.filter((h) => h.capacity && h.capacity.threads !== null);
  const declared = hosts.filter((h) => h.capacity);
  return {
    hosts: dividing.length,
    guests: sum(dividing, (h) => h.guests.length),
    guests_on: sum(dividing, (h) => h.on.length),
    total_gb: tenth(sum(mem, (h) => h.capacity.total_gb)),
    reserve_gb: tenth(sum(mem, (h) => h.capacity.reserve_gb)),
    assigned_gb: tenth(sum(dividing, (h) => h.assigned_gb)),
    demand_gb: tenth(sum(dividing, (h) => h.demand_gb)),
    free_gb: tenth(sum(mem, (h) => h.free_gb)),
    uncounted_gb: dividing.length - mem.length,
    threads: sum(cpu, (h) => h.capacity.threads),
    cores: sum(cpu, (h) => h.capacity.cores),
    vcpu: sum(dividing, (h) => h.vcpu),
    threads_free: sum(cpu, (h) => h.threads_free),
    over: sum(cpu, (h) => h.over),
    uncounted_cpu: dividing.length - cpu.length,
    machines: declared.length,
    cores_all: sum(declared, (h) => h.capacity.cores),
    threads_all: sum(declared, (h) => h.capacity.threads),
    ram_all: tenth(sum(declared, (h) => h.capacity.total_gb)),
  };
}

/* ── AVAILABLE COMPUTE, BY SITE OR BY RACK (2026-11-21) ──────────────────────
   Owner: "in resources, can we add buttons for like location and hardware so
   we can see the available compute by rack or site".

   `totalsOf` is the scene's bars: it counts only the machines that divide
   their memory among guests. What is AVAILABLE is a different question: a
   machine that runs no guests has all of its memory and every thread free,
   and that is exactly the compute someone asking "where can this go" wants
   counted. So `availableOf` sums every machine that says what it has. */

/** What some machines have and what of it is unspoken for.
      {machines, uncharted, guests_on, total_gb, reserve_gb, assigned_gb,
       free_gb, cores, threads, vcpu, threads_free, over}
    `uncharted` machines say nothing of their capacity and are in none of the
    sums; a machine that charts its threads and not its memory is in the
    processor sums only. */
export function availableOf(hosts) {
  const list = Array.isArray(hosts) ? hosts : [];
  const charted = list.filter((h) => h.capacity);
  const mem = charted.filter((h) => h.capacity.total_gb !== null);
  const cpu = charted.filter((h) => h.capacity.threads !== null);
  return {
    machines: list.length,
    uncharted: list.length - charted.length,
    guests_on: sum(list, (h) => h.on.length),
    total_gb: tenth(sum(mem, (h) => h.capacity.total_gb)),
    reserve_gb: tenth(sum(mem, (h) => h.capacity.reserve_gb)),
    assigned_gb: tenth(sum(mem, (h) => h.assigned_gb)),
    free_gb: tenth(sum(mem, (h) => h.free_gb)),
    cores: sum(cpu, (h) => h.capacity.cores),
    threads: sum(cpu, (h) => h.capacity.threads),
    vcpu: sum(cpu, (h) => h.vcpu),
    threads_free: sum(cpu, (h) => h.threads_free),
    over: sum(cpu, (h) => h.over),
  };
}

/** The rows of that question, one per site or one per rack.

    `where` is locations-model's whereabouts; `by` is 'site' or 'rack';
    `locKey` narrows 'rack' to one location's racks ('' or null: every
    location's). Each row is {kind, key | id, name, at, hosts, sum}:
      kind 'place'  a location (key);
           'rack'   a rack (id; `at` is its location's name, `key` its key);
           'shelf'  a location's machines that are in no rack (key);
           'adrift' the machines that stand at no location at all.
    A group with no machine in it is not a row: nothing is available there. */
export function availableBy(hosts, where, by, locKey = '') {
  const list = Array.isArray(hosts) ? hosts : [];
  const places = (where && Array.isArray(where.list)) ? where.list : [];
  const rows = [];
  const push = (row, mine) => { if (mine.length) rows.push({ ...row, hosts: mine, sum: availableOf(mine) }); };
  if (by === 'rack') {
    for (const l of places) {
      if (locKey && l.key !== locKey) continue;
      for (const r of l.racks || []) {
        push({ kind: 'rack', id: r.id, key: l.key, name: r.name, at: l.name }, list.filter((h) => h.rack === r.id));
      }
      push({ kind: 'shelf', key: l.key, name: 'Not in a rack', at: l.name },
        list.filter((h) => h.location === l.key && h.rack === null));
    }
  } else {
    for (const l of places) push({ kind: 'place', key: l.key, name: l.name, at: '' }, list.filter((h) => h.location === l.key));
  }
  if (!locKey || by !== 'rack') push({ kind: 'adrift', name: 'Not placed', at: '' }, list.filter((h) => h.location === null));
  return rows;
}

/** A figure as the scene writes it: one decimal, and none when it is whole. */
export const gb = (n) => (+n).toFixed(1).replace(/\.0$/, '');
