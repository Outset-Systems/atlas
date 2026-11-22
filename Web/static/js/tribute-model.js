
export const CAPACITY_FIELDS = ['ram_gb', 'ram_reserve_gb', 'cpu_cores', 'cpu_threads'];

const num = (v) => (typeof v === 'number' && Number.isFinite(v) && v >= 0 ? v
  : (typeof v === 'string' && v.trim() !== '' && Number.isFinite(Number(v)) && Number(v) >= 0 ? Number(v) : null));
const sum = (list, pick) => list.reduce((s, x) => s + (num(pick(x)) || 0), 0);
const tenth = (n) => Math.round(n * 10) / 10;

export function ownCapacity(node) {
  if (!node || typeof node !== 'object') return null;
  const cap = { total_gb: num(node.ram_gb), reserve_gb: num(node.ram_reserve_gb),
                cores: num(node.cpu_cores), threads: num(node.cpu_threads) };
  return cap.total_gb === null && cap.cores === null && cap.threads === null ? null : cap;
}

export function legacyCapacity(meta) {
  const t = meta && typeof meta === 'object' ? meta.tribute : null;
  if (!t || typeof t !== 'object') return null;
  const cap = { total_gb: num(t.total_gb), reserve_gb: num(t.host_reserve_gb),
                cores: num(t.cpu_cores), threads: num(t.cpu_threads) };
  return cap.total_gb === null && cap.cores === null && cap.threads === null ? null : cap;
}

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

export function hostsAt(hosts, key) {
  return key === null || key === undefined || key === '' ? hosts : hosts.filter((h) => h.location === key);
}

export const hostsIn = (hosts, rackId) => hosts.filter((h) => h.rack === rackId);

export const holdsHosts = (hosts) => (l, r) => hosts.some((h) => h.guests.length > 0
  && (r ? h.rack === r.id : h.location === l.key));

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

export const gb = (n) => (+n).toFixed(1).replace(/\.0$/, '');
