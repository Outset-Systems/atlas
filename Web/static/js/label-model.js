
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

export function toSegment(p, a, b) {
  const dx = b.x - a.x, dy = b.y - a.y;
  const len2 = dx * dx + dy * dy;
  const t = len2 ? clamp(((p.x - a.x) * dx + (p.y - a.y) * dy) / len2, 0, 1) : 0;
  return Math.hypot(p.x - (a.x + t * dx), p.y - (a.y + t * dy));
}

const overlaps = (a, b) =>
  Math.abs(a.x - b.x) < a.hw + b.hw && Math.abs(a.y - b.y) < a.hh + b.hh;

function crosses(box, a, b) {
  for (let i = 0; i <= 8; i++) {
    const t = i / 8;
    const x = a.x + (b.x - a.x) * t, y = a.y + (b.y - a.y) * t;
    if (Math.abs(x - box.x) < box.hw && Math.abs(y - box.y) < box.hh) return true;
  }
  return false;
}

export function placeLabels(groups, places, roads = [], { dot = 2.2, gap = 1.2, spread = 18 } = {}) {
  const drawn = Object.entries(places || {}).filter(([, p]) => p && Number.isFinite(p.x) && Number.isFinite(p.y));
  const lines = (roads || []).map(([a, b]) => [places[a], places[b]]).filter(([a, b]) => a && b);
  const set = [];
  const out = {};
  const order = [...(groups || [])]
    .map((g) => ({ ...g, pts: (g.ids || []).map((id) => places[id]).filter(Boolean) }))
    .filter((g) => g.pts.length)
    .sort((a, b) => b.pts.length - a.pts.length || String(a.id).localeCompare(String(b.id)));

  for (const g of order) {
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
      { x: cx, y: top - dot - hh - gap },
      { x: cx, y: bottom + dot + hh + gap },
      { x: right + dot + hw + gap, y: cy },
      { x: left - dot - hw - gap, y: cy },
    ];
    let best = null;
    tries.forEach((c, i) => {
      const box = { x: clamp(c.x, hw + 1, 99 - hw), y: clamp(c.y, hh + 1, 99 - hh), hw, hh };
      let cost = i * 0.01;
      cost += (Math.abs(box.x - c.x) + Math.abs(box.y - c.y)) * 2;
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
