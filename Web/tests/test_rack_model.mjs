/* THE ARMORY's shared model — run with `node tests/test_rack_model.mjs`.

   rack-model.js is the one source of truth for what sits in the rack and what a
   vessel looks like, now that the 2D elevation (reliquary.js) and the 3D
   deep-dive (armory3d.js) both draw from it. A shared model that both views
   trust is either tested or a hope; this pins the parsing, the geometry, and
   the faceplate art. Plain node, no framework — same shape as test_project.mjs.
   DOM-free by design: every input is passed in, so nothing here needs a browser. */

import { rackList, rackTitle, inRack } from '../static/js/rack-model.js';
import assert from 'node:assert/strict';
import {
  UH, RACK_W, KIND_HUE, ledColor, slug, isEmpty, topU, slotKey, uLabel,
  kindOf, setRackTheme, buildDevices, buildRear, fits, faceplate, ledSpot,
  depthMm, rackDepthMm, KIND_DEPTH_MM, crownOf, peerNode,
} from '../static/js/rack-model.js';

let passed = 0;
function test(name, fn) {
  try { fn(); passed++; }
  catch (err) { console.error(`FAIL  ${name}\n      ${err.message}`); process.exitCode = 1; }
}

/* ── parsing helpers ─────────────────────────────────────────────────── */

test('topU reads the highest U from a label, any dash', () => {
  assert.equal(topU({ u: 'U5' }), 5);
  assert.equal(topU({ u: 'U3–6' }), 6);      // en-dash range → the top
  assert.equal(topU({ u: 'U3-6' }), 6);      // hyphen range
  assert.equal(topU({ u: undefined }), 0);   // no digits → 0
});

test('uLabel is a point for 1U and a range for taller', () => {
  assert.equal(uLabel(5, 1), 'U5');
  assert.equal(uLabel(6, 2), 'U5–6');
});

test('slug and slotKey', () => {
  assert.equal(slug('Main Hypervisor!'), 'main-hypervisor');
  assert.equal(slotKey({ node: 'edge' }), 'edge');
  assert.equal(slotKey({ name: 'Patch Panel' }), 'slot:patch-panel');
});

test('isEmpty only for node-less slots named empty', () => {
  assert.equal(isEmpty({ name: '— empty —' }), true);
  assert.equal(isEmpty({ node: 'x', name: 'empty' }), false);
  assert.equal(isEmpty({ name: 'App Host' }), false);
});

/* ── kind + LED colour ───────────────────────────────────────────────── */

test('kindOf names no lab until a theme does', () => {
  setRackTheme({});
  assert.equal(kindOf({ node: 'edge-router' }, null), 'compute');
  assert.equal(kindOf({ name: 'GPU Rig' }, null), 'compute');
  assert.equal(kindOf({ node: 'x' }, { kind: 'network' }), 'gateway');
});

test('kindOf routes by name then node', () => {
  setRackTheme({ gatewayNodes: ['edge-router'], forgeNames: ['gpu'] });
  assert.equal(kindOf({ name: 'Patch Panel' }, null), 'patch');
  assert.equal(kindOf({ node: 'edge-router' }, null), 'gateway');
  assert.equal(kindOf({ node: 'x' }, { kind: 'network' }), 'gateway');
  assert.equal(kindOf({ name: 'GPU Rig' }, null), 'forge');
  assert.equal(kindOf({ name: 'App Host', node: 'app-host' }, { kind: 'compute' }), 'compute');
});

test('ledColor maps live state, empty otherwise', () => {
  assert.equal(ledColor('healthy'), '#8EC07C');
  assert.equal(ledColor('degraded'), '#FABD2F');
  assert.equal(ledColor('down'), '#FB4934');
  assert.equal(ledColor(''), '');
  assert.equal(ledColor(undefined), '');
});

/* ── buildDevices: the list both views iterate ───────────────────────── */

const NODES = { edge: { id: 'edge', kind: 'compute' },
                gateway: { id: 'gateway', kind: 'network' } };
const nodeById = (id) => NODES[id] || null;

test('buildDevices drops empties, resolves nodes, and computes rackU', () => {
  const rack = [
    { u: 'U12', size: 1, node: 'gateway', name: 'Gateway' },
    { u: 'U9–10', size: 2, node: 'edge', name: 'Edge' },
    { u: 'U1', size: 1, name: '— empty —' },
  ];
  const { devices, rackU } = buildDevices(rack, nodeById);
  assert.equal(rackU, 12);
  assert.equal(devices.length, 2);
  const g = devices.find((d) => d.key === 'gateway');
  assert.equal(g.kind, 'gateway');
  assert.equal(g.top, 12);
  const e = devices.find((d) => d.key === 'edge');
  assert.equal(e.size, 2);
  assert.equal(e.node.kind, 'compute');
});

test('an override moves a vessel and rewrites its slot label', () => {
  const slot = { u: 'U9–10', size: 2, node: 'edge', name: 'Edge' };
  const { devices } = buildDevices([slot], nodeById, { edge: 6 });
  assert.equal(devices[0].top, 6);
  assert.equal(slot.u, 'U5–6');              // deliberate write-through, as the 2D drag did
});

/* ── fits: the drag geometry ─────────────────────────────────────────── */

test('fits respects bounds and occupancy', () => {
  const rackU = 12;
  const a = { key: 'a', size: 1, top: 5 };
  const b = { key: 'b', size: 2, top: 10 };
  const devices = [a, b];
  assert.equal(fits(devices, rackU, a, 7), true);    // free slot
  assert.equal(fits(devices, rackU, a, 10), false);  // lands on b (U9–10)
  assert.equal(fits(devices, rackU, a, 13), false);  // above the rack
  assert.equal(fits(devices, rackU, b, 2), true);    // 2U at top 2 → U1–2, free
  assert.equal(fits(devices, rackU, b, 1), false);   // 2U at top 1 → U0–1, below the rack
});

/* ── faceplate art: shared SVG the 3D view will rasterise ─────────────── */

test('faceplate draws the right art per kind and paints the LED', () => {
  const gw = faceplate({ kind: 'gateway', size: 1 }, '#8EC07C');
  assert.ok(gw.includes('fp-screen') && gw.includes('fp-svg'));
  assert.ok(gw.includes('fill:#8EC07C'), 'LED colour is painted when live');

  const patch = faceplate({ kind: 'patch', size: 1 }, '');
  assert.ok(patch.includes('fp-key'));

  const forge = faceplate({ kind: 'forge', size: 2 }, '');
  assert.ok(forge.includes('fp-vent') && forge.includes('#C0714E'));

  const compute = faceplate({ kind: 'compute', size: 1 }, '');
  assert.ok(compute.includes('#C9A554'));
  assert.ok(!compute.includes('fill:#'), 'no LED fill style when state is empty');
});

test('the exported geometry constants are the design units', () => {
  assert.equal(UH, 34);
  assert.equal(RACK_W, 460);
  assert.equal(KIND_HUE.gateway, '#5FA8D3');
});

test('ledSpot locates the LED per kind, null for patch', () => {
  assert.deepEqual(ledSpot({ kind: 'gateway', size: 1 }), { x: 430, y: UH / 2 });
  assert.deepEqual(ledSpot({ kind: 'compute', size: 1 }), { x: RACK_W - 44, y: UH / 2 + 8 });
  assert.deepEqual(ledSpot({ kind: 'forge', size: 2 }), { x: RACK_W - 44, y: 40 });
  assert.equal(ledSpot({ kind: 'patch', size: 1 }), null);
});

// ── RACKS: a place and a name, one rack or many ─────────────────────────────
test('RACKS: a place and a name, one rack or many', () => {
  const fallback = rackList(undefined, 'Home lab');
  assert.deepEqual(fallback, [{ id: '', name: 'Rack A', location: 'Home lab' }],
    'a lab that charted no racks still has its one rack');
  assert.equal(rackTitle(fallback[0]), 'Home lab — Rack A');
  assert.equal(rackTitle({ name: 'Rack A', location: '' }), 'Rack A');

  const two = rackList([{ id: 'a', name: 'Rack A', location: 'Server room' }, { id: 'b', name: 'Rack B' }], 'Home');
  assert.equal(rackTitle(two[0]), 'Server room — Rack A');
  assert.equal(rackTitle(two[1]), 'Home — Rack B', 'a blank location falls back to the theme');

  const slots = [{ name: 'one' }, { name: 'two', rack: 'b' }, { name: 'lost', rack: 'gone' }];
  assert.deepEqual(inRack(slots, two, 'a').map((s) => s.name), ['one', 'lost'],
    'unset or unknown goes to the first rack, never disappears');
  assert.deepEqual(inRack(slots, two, 'b').map((s) => s.name), ['two']);
  assert.deepEqual(inRack(undefined, two, 'a'), []);

  assert.notEqual(slotKey({ name: 'Patch Panel', rack: 'a' }), slotKey({ name: 'Patch Panel', rack: 'b' }),
    'two racks may each hold a Patch Panel');
  assert.equal(slotKey({ name: 'Patch Panel' }), 'slot:patch-panel', 'an existing lab keeps its saved keys');
  assert.equal(slotKey({ name: 'Patch Panel', rack: 'rack-b' }), 'slot:rack-b-patch-panel');
});

/* ── the wider armory: switches, storage, power, enclosures ──────────── */

test('kindOf reads the iron from a slot name or description', () => {
  setRackTheme({});
  assert.equal(kindOf({ name: 'Core Switch', node: 'x' }, { kind: 'network' }), 'switch');
  assert.equal(kindOf({ name: 'CLOSET-1', desc: 'USW-Pro-24-PoE' }, null), 'switch');
  assert.equal(kindOf({ name: 'NAS', desc: 'Synology NAS' }, null), 'storage');
  assert.equal(kindOf({ name: 'UNAS Pro 8' }, null), 'storage');
  assert.equal(kindOf({ name: 'UPS 2U Pro' }, null), 'power');
  assert.equal(kindOf({ name: 'CLOSET-2', desc: 'USP PDU Pro' }, null), 'power');
  assert.equal(kindOf({ name: 'RackMac Studio' }, null), 'enclosure');
  assert.equal(kindOf({ name: 'PDU', desc: 'Switched, eight outlets.' }, null), 'power');
  assert.equal(kindOf({ name: 'App Host', desc: 'Switched to Debian' }, null), 'compute');
});

test('a slot kind beats the words, and auto or nonsense does not', () => {
  assert.equal(kindOf({ name: 'UPS monitor', kind: 'compute' }, null), 'compute');
  assert.equal(kindOf({ name: 'UPS', kind: 'auto' }, null), 'power');
  assert.equal(kindOf({ name: 'UPS', kind: 'toaster' }, null), 'power');
});

test('a themed gateway keeps its faceplate whatever its description says', () => {
  setRackTheme({ gatewayNodes: ['edge'], forgeNames: ['rig'] });
  assert.equal(kindOf({ node: 'edge', desc: 'switch and router' }, null), 'gateway');
  assert.equal(kindOf({ name: 'GPU Rig', desc: 'on the UPS' }, null), 'forge');
  setRackTheme({});
});

test('depth comes from the slot, then the kind', () => {
  assert.equal(depthMm({ depth_mm: 630 }, 'compute'), 630);
  assert.equal(depthMm({ depth_mm: '' }, 'power'), KIND_DEPTH_MM.power);
  assert.equal(depthMm({ depth_mm: 0 }, 'patch'), KIND_DEPTH_MM.patch);
  for (const kind of Object.keys(KIND_HUE)) assert.ok(KIND_DEPTH_MM[kind] > 0, kind);
});

test('buildDevices carries depth, and the cabinet clears the deepest vessel', () => {
  const rack = [{ u: 'U1–2', size: 2, name: 'UPS', depth_mm: 630 }, { u: 'U3', name: 'Host' }];
  const { devices } = buildDevices(rack, () => null);
  assert.equal(devices[0].depth, 630);
  assert.equal(devices[1].depth, KIND_DEPTH_MM.compute);
  assert.equal(rackDepthMm(devices), 690);
  assert.equal(rackDepthMm(devices, [{}]), 820);      // rear fittings need their own room
  assert.equal(rackDepthMm([]), 500);                 // an empty rack is still a cabinet
});

test('buildRear matches what the shared detail pane reads', () => {
  const rear = buildRear(
    [{ name: 'NAS', node: 'nas', desc: 'Synology NAS' }, { name: 'Shelf' }],
    (id) => ({ id }));
  assert.equal(rear[0].key, 'rear:0');
  assert.equal(rear[0].node.id, 'nas');
  assert.equal(rear[0].kind, 'storage');
  assert.equal(rear[0].rear, true);
  assert.equal(rear[1].node, null);
  assert.deepEqual(buildRear(undefined, () => null), []);
});

test('every kind draws a faceplate, and every LED lands where the art puts it', () => {
  for (const kind of Object.keys(KIND_HUE)) {
    for (const size of [1, 2, 3]) {
      const svg = faceplate({ kind, size }, '#FB4934');
      assert.ok(svg.startsWith('<svg') && !svg.includes('undefined') && !svg.includes('NaN'),
        `${kind} ${size}U`);
      const spot = ledSpot({ kind, size });
      if (spot) assert.ok(svg.includes(`cx="${spot.x}" cy="${spot.y}"`), `${kind} ${size}U LED`);
    }
  }
});

test('a storage faceplate shows four bays a row', () => {
  const bays = (size) => faceplate({ kind: 'storage', size }, '').match(/fp-bay/g).length;
  assert.equal(bays(1), 4);
  assert.equal(bays(2), 8);
});

test('a rack opens on the crown when it holds it, else on its first vessel', () => {
  const dev = (node, key) => ({ key, slot: node ? { node } : { name: key } });
  const first = dev('', 'patch'), crown = dev('hypervisor', 'crown'), other = dev('host-b', 'b');
  assert.equal(crownOf([first, other, crown]), crown);
  assert.equal(crownOf([first, other]), first);
  assert.equal(crownOf([]), undefined);
  const twin = dev('hypervisor', 'twin');
  assert.equal(crownOf([other, crown, twin]), crown, 'the first of two wins');
  // a device with no slot is passed over, not tripped on
  assert.equal(crownOf([{ key: 'bare' }, crown]), crown);
});

test('a port peer is a charted place when it names one whole, case-blind', () => {
  const nodes = [{ id: 'core-switch', name: 'CORE SWITCH' }, { id: 'host-a', name: 'Host A' }, { id: 'bare' }];
  assert.equal(peerNode(nodes, 'core-switch'), nodes[0]);
  assert.equal(peerNode(nodes, 'Core Switch'), nodes[0], 'by name');
  assert.equal(peerNode(nodes, 'HOST-A'), nodes[1], 'by id, any case');
  assert.equal(peerNode(nodes, 'BARE'), nodes[2], 'a place with no name still matches by id');
  assert.equal(peerNode(nodes, 'host-a port 3'), undefined, 'prose around the name is not a match');
  assert.equal(peerNode(nodes, ''), '', 'blank text asks nothing');
});

test('the compute and forge faceplates wear their kind\'s hue', () => {
  assert.equal(KIND_HUE.forge, '#C0714E');
  assert.equal(KIND_HUE.compute, '#C9A554');
  assert.ok(faceplate({ kind: 'forge', size: 2 }, '').includes('#C0714E'));
  assert.ok(faceplate({ kind: 'compute', size: 2 }, '').includes('#C9A554'));
  assert.ok(!faceplate({ kind: 'compute', size: 2 }, '').includes('#C0714E'));
});

console.log(`rack-model: ${passed} passed`);
