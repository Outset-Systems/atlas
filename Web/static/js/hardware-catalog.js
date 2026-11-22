
export const DEVICE_GROUPS = [
  { label: 'Network', types: [
    { id: 'switch-12', label: 'Switch, 12 ports', kind: 'switch', size: 1 },
    { id: 'switch-24', label: 'Switch, 24 ports', kind: 'switch', size: 1 },
    { id: 'switch-48', label: 'Switch, 48 ports', kind: 'switch', size: 1 },
    { id: 'gateway', label: 'Gateway', kind: 'gateway', size: 1 },
    { id: 'router', label: 'Router', kind: 'gateway', size: 1 },
    { id: 'firewall', label: 'Firewall', kind: 'gateway', size: 1 },
    { id: 'patch', label: 'Patch panel', kind: 'patch', size: 1 },
  ] },
  { label: 'Compute', types: [
    { id: 'computer', label: 'Computer', kind: 'compute', size: 2 },
    { id: 'server-1u', label: 'Server, 1U', kind: 'compute', size: 1 },
    { id: 'server-2u', label: 'Server, 2U', kind: 'compute', size: 2 },
    { id: 'poweredge', label: 'Dell PowerEdge', kind: 'compute', size: 2 },
    { id: 'blade', label: 'Blade enclosure', kind: 'enclosure', size: 6 },
    { id: 'gpu', label: 'GPU server', kind: 'forge', size: 4 },
    { id: 'mini', label: 'Mini PC', kind: 'compute', size: 1 },
    { id: 'pi', label: 'Raspberry Pi', kind: 'compute', size: 1 },
  ] },
  { label: 'Storage', types: [
    { id: 'nas', label: 'NAS', kind: 'storage', size: 2 },
    { id: 'jbod', label: 'Disk shelf (JBOD)', kind: 'storage', size: 2 },
  ] },
  { label: 'Power', types: [
    { id: 'pdu', label: 'PDU', kind: 'power', size: 1 },
    { id: 'ups', label: 'UPS', kind: 'power', size: 2 },
  ] },
];

export const SEATS = [
  { id: 'front', label: 'Front' },
  { id: 'back', label: 'Back' },
  { id: 'inside', label: 'Inside' },
];

export function typeById(id) {
  for (const g of DEVICE_GROUPS) {
    const hit = g.types.find((t) => t.id === id);
    if (hit) return hit;
  }
  return null;
}

const clean = (s) => String(s ?? '').trim().replace(/\s+/g, ' ');

export function addName({ node = null, typed = '', type = null } = {}) {
  return clean(node?.name) || clean(typed) || clean(type?.label);
}

export function addBody({ seat = 'front', name, node = null, type = null, size = 1, u = '', rackId = '' } = {}) {
  const said = clean(name);
  const body = { name: said };
  if (rackId) body.rack = rackId;
  if (node?.id) body.node = node.id;
  if (type && clean(type.label).toLowerCase() !== said.toLowerCase()) body.desc = type.label;
  if (seat === 'front') {
    return { section: 'rack', body: { u, ...body, size, ...(type ? { kind: type.kind } : {}) } };
  }
  return { section: 'rack_rear', body: seat === 'inside' ? { ...body, side: 'inside' } : body };
}
