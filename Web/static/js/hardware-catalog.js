/* WHAT CAN BE PUT IN A RACK: hardware-catalog.js (2026-11-21), with no DOM.

   Owner: "in the hardware when you click add, it should also have a drop down
   for device. like network: switch 12/24/48, gateway, patch panel, router,
   etc. Compute: Computer, Blade, Dell Poweredge, raspberry pi etc. Storage:
   NAS, etc, Power: PDU. and a location front, back inside."

   A TYPE is a kind of device HARDWARE's Add offers: its words, the faceplate
   it wears (`kind`, one of the map's rack kinds), and how tall it usually is.
   Picking one fills the height and, for a thing that is not on the map, its
   name. It is a starting point, not a record: nothing here is stored but the
   faceplate, the height, the name and a line of description.

   A SEAT is where in the rack it goes:
     front    a U slot on the front elevation (`rack`);
     back     hung behind the rack, with no U (`rack_rear`);
     inside   in the cabinet and on neither face: a shelf, a mini PC lying on
              a tray, a power strip on the floor of it (`rack_rear` with
              `side: 'inside'`).

   `addBody` is what the editing API is sent. Unit-tested by
   tests/test_hardware_catalog.mjs. */

/** The groups, in the order the picker lists them. `kind` is a faceplate the
    map already knows (schema RACK_KINDS). */
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

/** The type an id names, or null ('' and an unknown id: no type chosen). */
export function typeById(id) {
  for (const g of DEVICE_GROUPS) {
    const hit = g.types.find((t) => t.id === id);
    if (hit) return hit;
  }
  return null;
}

const clean = (s) => String(s ?? '').trim().replace(/\s+/g, ' ');

/** The name a thing is added under: a place's own; else what was typed;
    else the type's words. '' when there is none of the three. */
export function addName({ node = null, typed = '', type = null } = {}) {
  return clean(node?.name) || clean(typed) || clean(type?.label);
}

/** What to send for one Add.

    `seat` is 'front' | 'back' | 'inside'; `u` is the front's U label
    (rack-model.js uLabel), unused elsewhere. Returns {section, body}; the
    body names its rack only when the map charts racks (`rackId` not ''), and
    says what type it is in `desc` when its name does not already. */
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
