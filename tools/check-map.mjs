/* Replays world.js's three build guards against the live dataset, so "check the
   map" is a measurement rather than a squint. Mirrors buildMarkers (skip
   off_map), buildRoutes (both endpoints must resolve and be drawn) and
   buildTerritories (hull needs 3+ members on the table). */
import { readFileSync } from 'node:fs';

const D = JSON.parse(readFileSync(new URL('../Data/lab-data.json', import.meta.url), 'utf8'));
let OVER = {};
try { OVER = JSON.parse(readFileSync(new URL('../Data/positions.json', import.meta.url), 'utf8')); } catch {}

const byId = new Map(D.nodes.map((n) => [n.id, n]));
const pos = (n) => { const o = OVER[n.id]; return o ? [o.x, o.y] : [n.x, n.y]; };

const drawn = D.nodes.filter((n) => !n.off_map);
console.log(`markers      ${drawn.length} drawn of ${D.nodes.length} nodes` +
  ` (skipped: ${D.nodes.filter((n) => n.off_map).map((n) => n.id).join(', ') || 'none'})`);

let bad = 0;
const routesDrawn = D.routes.filter((r) => {
  const a = byId.get(r.from), b = byId.get(r.to);
  if (!a || !b) { console.log(`  ✗ route to unknown node: ${r.from} -> ${r.to}`); bad++; return false; }
  return !a.off_map && !b.off_map;
});
console.log(`routes       ${routesDrawn.length} drawn of ${D.routes.length}` +
  ` (${D.routes.length - routesDrawn.length} skipped for touching an off_map place)`);

const hulls = D.zones.map((z) => {
  const pts = D.nodes.filter((n) => n.zone === z.id && !n.off_map)
    .map(pos).filter(([, y]) => y >= -5 && y <= 105);
  return { id: z.id, members: pts.length, hull: pts.length >= 3 };
});
console.log('territories  ' + hulls.map((h) => `${h.id}:${h.members}${h.hull ? '(hull)' : ''}`).join('  '));

// dangling references anywhere
const dangling = [];
for (const n of D.nodes) {
  for (const t of n.reaches || []) if (!byId.has(t)) dangling.push(`${n.id}.reaches -> ${t}`);
  if (n.parent && !byId.has(n.parent)) dangling.push(`${n.id}.parent -> ${n.parent}`);
  for (const l of n.links || []) for (const c of l.connects || [])
    if (!byId.has(c)) dangling.push(`${n.id}/${l.label}.connects -> ${c}`);
}
const zoneIds = new Set(D.zones.map((z) => z.id));
for (const n of D.nodes) if (n.zone && !zoneIds.has(n.zone)) dangling.push(`${n.id}.zone -> ${n.zone}`);
console.log(`references   ${dangling.length ? '✗ ' + dangling.join(', ') : '✓ all resolve'}`);

// markers too close to read apart
const close = [];
for (let i = 0; i < drawn.length; i++)
  for (let j = i + 1; j < drawn.length; j++) {
    const [ax, ay] = pos(drawn[i]), [bx, by] = pos(drawn[j]);
    const d = Math.hypot(ax - bx, ay - by);
    if (d < 4) close.push(`${drawn[i].id}~${drawn[j].id} (${d.toFixed(2)})`);
  }
console.log(`spacing      ${close.length ? '⚠ ' + close.join(', ') : '✓ no pair under 4 units'}`);

// off the table entirely
const off = drawn.filter((n) => { const [, y] = pos(n); return y < -5 || y > 105; });
console.log(`on the table ${off.length ? '⚠ below/above: ' + off.map((n) => `${n.id}@y${pos(n)[1]}`).join(', ') : '✓ all drawn places on the table'}`);

