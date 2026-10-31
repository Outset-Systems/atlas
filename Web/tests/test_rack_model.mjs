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
  kindOf, setRackTheme, buildDevices, fits, faceplate, ledSpot,
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

console.log(`rack-model: ${passed} passed`);
