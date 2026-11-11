/* Where a network's name stands on a map, worked out from what is drawn there.
   Pure: no DOM, so node can test it (tests/test_label_model.mjs).

   A name used to be pinned by hand, once, on one picture. Move the places and
   it stays where it was, naming an empty stretch of sea. Here it follows its
   places instead: beside the group it names, on whichever side is clear of
   other places, of names already set down, and of the roads.

   Everything is in the map's own percent, the unit places are charted in. */

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

/** Distance from point `p` to the segment a–b. */
export function toSegment(p, a, b) {
  const dx = b.x - a.x, dy = b.y - a.y;
  const len2 = dx * dx + dy * dy;
  const t = len2 ? clamp(((p.x - a.x) * dx + (p.y - a.y) * dy) / len2, 0, 1) : 0;
  return Math.hypot(p.x - (a.x + t * dx), p.y - (a.y + t * dy));
}

const overlaps = (a, b) =>
  Math.abs(a.x - b.x) < a.hw + b.hw && Math.abs(a.y - b.y) < a.hh + b.hh;

/** Does the segment a–b pass through the box? Sampled: a name is a few percent
    wide and a road is a line, so eight looks along it are plenty. */
function crosses(box, a, b) {
  for (let i = 0; i <= 8; i++) {
    const t = i / 8;
    const x = a.x + (b.x - a.x) * t, y = a.y + (b.y - a.y) * t;
    if (Math.abs(x - box.x) < box.hw && Math.abs(y - box.y) < box.hh) return true;
  }
  return false;
}

/** Place one name per group.

    `groups`  [{ id, ids: [place id], hw, hh }]: the places a name is for, and
              half the name's width and height
    `places`  { id: {x, y} }: everything drawn on this map
    `roads`   [[place id, place id]]: the roads drawn on this map
    `dot`     half the room a place's marker and its own name take (default 2.2)
    `spread`  how far from its heart a group's places still count as one cluster (18)

    Returns { group id: {x, y} }, the centre of each name. A group with no
    place drawn here gets none. The biggest group is set down first, so the
    small ones fit around it; ties go above, then below, right, left. */
export function placeLabels(groups, places, roads = [], { dot = 2.2, gap = 1.2, spread = 18 } = {}) {
  const drawn = Object.entries(places || {}).filter(([, p]) => p && Number.isFinite(p.x) && Number.isFinite(p.y));
  const lines = (roads || []).map(([a, b]) => [places[a], places[b]]).filter(([a, b]) => a && b);
  const set = [];                                  // names already down
  const out = {};
  const order = [...(groups || [])]
    .map((g) => ({ ...g, pts: (g.ids || []).map((id) => places[id]).filter(Boolean) }))
    .filter((g) => g.pts.length)
    .sort((a, b) => b.pts.length - a.pts.length || String(a.id).localeCompare(String(b.id)));

  for (const g of order) {
    // a network scattered across the map is named at its heart, not over the
    // whole spread: the place nearest the middle, and those standing near it
    const mx = g.pts.reduce((t, p) => t + p.x, 0) / g.pts.length;
    const my = g.pts.reduce((t, p) => t + p.y, 0) / g.pts.length;
    const heart = g.pts.reduce((best, p) =>
      (Math.hypot(p.x - mx, p.y - my) < Math.hypot(best.x - mx, best.y - my) ? p : best));
    const core = g.pts.filter((p) => Math.hypot(p.x - heart.x, p.y - heart.y) <= spread);
    const xs = core.map((p) => p.x), ys = core.map((p) => p.y);
    const left = Math.min(...xs), right = Math.max(...xs), top = Math.min(...ys), bottom = Math.max(...ys);
    const cx = (left + right) / 2, cy = (top + bottom) / 2;
    const hw = g.hw || 6, hh = g.hh || 2;
    const tries = [
      { x: cx, y: top - dot - hh - gap },          // above
      { x: cx, y: bottom + dot + hh + gap },       // below
      { x: right + dot + hw + gap, y: cy },        // right
      { x: left - dot - hw - gap, y: cy },         // left
    ];
    let best = null;
    tries.forEach((c, i) => {
      const box = { x: clamp(c.x, hw + 1, 99 - hw), y: clamp(c.y, hh + 1, 99 - hh), hw, hh };
      let cost = i * 0.01;                         // the order, when all else is equal
      cost += (Math.abs(box.x - c.x) + Math.abs(box.y - c.y)) * 2;      // pushed in from the edge
      for (const [, p] of drawn) if (overlaps(box, { x: p.x, y: p.y, hw: dot, hh: dot })) cost += 10;
      for (const s of set) if (overlaps(box, s)) cost += 25;
      for (const [a, b] of lines) if (crosses(box, a, b)) cost += 3;
      if (!best || cost < best.cost) best = { cost, box };
    });
    set.push(best.box);
    out[g.id] = { x: Math.round(best.box.x * 10) / 10, y: Math.round(best.box.y * 10) / 10 };
  }
  return out;
}
