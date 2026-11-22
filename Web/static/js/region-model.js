

export const SHOWN_KEY = 'atlas-zoom-maps';

export const choiceKey = (art, id) => `${art || ''}|${id}`;

export function parseChoices(raw) {
  let v = raw;
  if (typeof raw === 'string') { try { v = JSON.parse(raw); } catch { return {}; } }
  if (!v || typeof v !== 'object' || Array.isArray(v)) return {};
  return Object.fromEntries(Object.entries(v).filter(([, on]) => typeof on === 'boolean'));
}

export function shownByChoice(r, choices = {}, art = '') {
  const own = choices[choiceKey(art, r.id)];
  return typeof own === 'boolean' ? own : r.hidden !== true;
}

export function shownRegions(regions, choices = {}, art = '') {
  const list = regions || [];
  const byId = new Map(list.map((r) => [r.id, r]));
  const memo = new Map();
  const ok = (r, depth = 0) => {
    if (memo.has(r.id)) return memo.get(r.id);
    let on = shownByChoice(r, choices, art);
    if (on && r.parent) {
      const up = byId.get(r.parent);
      on = Boolean(up) && depth < 32 && ok(up, depth + 1);
    }
    memo.set(r.id, on);
    return on;
  };
  const out = list.filter((r) => ok(r));
  return out.length === list.length ? list : out;
}

export function zoomMapRows(regions, choices = {}, art = '') {
  const list = regions || [];
  const rows = [];
  const walk = (parentId, depth, reachable) => {
    for (const r of childrenOf(list, parentId)) {
      if (rows.some((row) => row.id === r.id) || depth > 32) continue;
      const on = shownByChoice(r, choices, art);
      rows.push({ id: r.id, name: r.name || r.id, parent: r.parent || '', depth, on,
                  byDefault: r.hidden !== true, reachable });
      walk(r.id, depth + 1, reachable && on);
    }
  };
  walk(null, 0, true);
  return rows;
}

export function withChoice(choices, r, on, art = '') {
  const next = { ...parseChoices(choices) };
  const key = choiceKey(art, r.id);
  if (Boolean(on) === (r.hidden !== true)) delete next[key];
  else next[key] = Boolean(on);
  return next;
}

export function childrenOf(regions, parentId) {
  const want = parentId || '';
  return (regions || []).filter((r) => (r.parent || '') === want);
}

export function chainOf(regions, id) {
  const byId = new Map((regions || []).map((r) => [r.id, r]));
  const out = [];
  const seen = new Set();
  let cur = byId.get(id);
  while (cur) {
    if (seen.has(cur.id)) return [];
    seen.add(cur.id);
    out.unshift(cur);
    if (!cur.parent) return out;
    cur = byId.get(cur.parent);
    if (!cur) return [];
  }
  return out;
}

export function toChild(r, p) {
  return { x: ((p.x - r.x) / r.w) * 100, y: ((p.y - r.y) / r.h) * 100 };
}

export function toParent(r, p) {
  return { x: r.x + (p.x / 100) * r.w, y: r.y + (p.y / 100) * r.h };
}

const inside = (p) => p.x >= 0 && p.x <= 100 && p.y >= 0 && p.y <= 100;

export function placeOn(regions, regionId, node, _depth = 0) {
  if (_depth > 32) return null;
  const r = (regions || []).find((x) => x.id === regionId);
  if (!r || !node) return null;
  const pin = r.places && typeof r.places === 'object' ? r.places[node.id] : null;
  if (pin && Number.isFinite(pin.x) && Number.isFinite(pin.y)) return { x: pin.x, y: pin.y };
  const above = r.parent
    ? placeOn(regions, r.parent, node, _depth + 1)
    : (Number.isFinite(node.x) && Number.isFinite(node.y) ? { x: node.x, y: node.y } : null);
  if (!above) return null;
  const q = toChild(r, above);
  return inside(q) ? q : null;
}

const within = (p, r) => p.x >= r.x && p.x <= r.x + r.w && p.y >= r.y && p.y <= r.y + r.h;

export function homesAt(regions, levelId, at) {
  const kids = childrenOf(regions, levelId);
  const out = {};
  for (const [id, p] of Object.entries(at || {})) {
    const r = p && kids.find((k) => within(p, k));
    if (r) out[id] = r.id;
  }
  return out;
}

export function foldedAt(regions, levelId, at, routes) {
  const folds = new Set(childrenOf(regions, levelId).filter((r) => r.fold === true).map((r) => r.id));
  if (!folds.size) return new Set();
  const home = homesAt(regions, levelId, at);
  const speaks = new Set();
  for (const road of routes || []) {
    const a = road?.from, b = road?.to;
    if (!at[a] || !at[b] || home[a] === home[b]) continue;
    speaks.add(a); speaks.add(b);
  }
  const hidden = new Set();
  for (const [id, region] of Object.entries(home)) {
    if (folds.has(region) && !speaks.has(id)) hidden.add(id);
  }
  return hidden;
}

const FOLD_ILLS = ['down', 'degraded', 'maintenance', 'slumbering'];
const FOLD_ALARMS = ['down', 'degraded', 'maintenance'];

export function foldSummary(regions, levelId, at, hidden, states) {
  const out = {};
  for (const r of childrenOf(regions, levelId)) {
    if (r.fold === true) {
      out[r.id] = { count: 0, down: 0, degraded: 0, maintenance: 0, slumbering: 0, healthy: 0, unknown: 0, worst: null };
    }
  }
  const home = homesAt(regions, levelId, at);
  for (const id of hidden || []) {
    const s = out[home[id]];
    if (!s) continue;
    s.count++;
    const st = states ? states[id] : undefined;
    if (st === 'healthy' || FOLD_ILLS.includes(st)) s[st]++;
    else s.unknown++;
  }
  for (const s of Object.values(out)) s.worst = FOLD_ALARMS.find((st) => s[st] > 0) || null;
  return out;
}

export function foldWords(s) {
  if (!s || !s.count) return '';
  const said = { down: 'down', degraded: 'degraded', maintenance: 'in maintenance', slumbering: 'slumbering' };
  const ills = FOLD_ILLS.filter((st) => s[st] > 0).map((st) => `${s[st]} ${said[st]}`);
  return [`${s.count} ${s.count === 1 ? 'place' : 'places'}`, ...ills].join(', ');
}


export function carryTo(regions, regionId, node, _depth = 0) {
  if (_depth > 32) return null;
  const r = (regions || []).find((x) => x.id === regionId);
  if (!r || !node) return null;
  const pin = r.places && typeof r.places === 'object' ? r.places[node.id] : null;
  if (pin && Number.isFinite(pin.x) && Number.isFinite(pin.y)) return { x: pin.x, y: pin.y };
  const above = r.parent
    ? carryTo(regions, r.parent, node, _depth + 1)
    : (Number.isFinite(node.x) && Number.isFinite(node.y) ? { x: node.x, y: node.y } : null);
  if (!above || !(r.w > 0) || !(r.h > 0)) return null;
  return toChild(r, above);
}

export function exitPoint(from, far) {
  if (!from || !far || ![from.x, from.y, far.x, far.y].every(Number.isFinite)) return null;
  if (inside(far)) return null;
  const a = { x: Math.max(0, Math.min(100, from.x)), y: Math.max(0, Math.min(100, from.y)) };
  const dx = far.x - a.x, dy = far.y - a.y;
  let t = 1;
  if (dx > 0) t = Math.min(t, (100 - a.x) / dx);
  else if (dx < 0) t = Math.min(t, (0 - a.x) / dx);
  if (dy > 0) t = Math.min(t, (100 - a.y) / dy);
  else if (dy < 0) t = Math.min(t, (0 - a.y) / dy);
  const hold = (v) => Math.max(0, Math.min(100, v));
  return { x: hold(a.x + dx * t), y: hold(a.y + dy * t) };
}

export function exitLabel(names) {
  const list = (names || []).filter(Boolean);
  return list.slice(0, 2).join(', ') + (list.length > 2 ? ` +${list.length - 2}` : '');
}

export function mergeExits(exits, tol = 4) {
  const groups = [];
  for (const ex of exits || []) {
    if (!ex || !ex.at) continue;
    const g = groups.find((o) => o.from === ex.from && Math.hypot(o.at.x - ex.at.x, o.at.y - ex.at.y) <= tol);
    if (!g) { groups.push({ ...ex, ids: [ex.to], names: [ex.name] }); continue; }
    if (!g.ids.includes(ex.to)) { g.ids.push(ex.to); g.names.push(ex.name); }
  }
  for (const g of groups) g.label = exitLabel(g.names);
  return groups;
}

export function standingOn(regions, id, spots) {
  const out = {};
  for (const [pid, p] of Object.entries(spots || {})) {
    const at = placeOn(regions, id, { id: pid, x: p.x, y: p.y });
    if (at) out[pid] = at;
  }
  return out;
}

export function drawnAbove(regions, levelId, spots, routes) {
  const ids = new Set();
  const add = (at, onId) => {
    const hidden = foldedAt(regions, onId, at, routes);
    for (const id of Object.keys(at)) if (!hidden.has(id)) ids.add(id);
  };
  add(spots, null);
  for (const r of chainOf(regions, levelId).slice(0, -1)) add(standingOn(regions, r.id, spots), r.id);
  return ids;
}

export function exitsFor(regions, levelId, here, spots, names, routes) {
  let above = null;
  const raw = [];
  for (const road of routes || []) {
    const a = here[road.from], b = here[road.to];
    if (Boolean(a) === Boolean(b)) continue;
    const nearId = a ? road.from : road.to;
    const farId = a ? road.to : road.from;
    const spot = Object.hasOwn(spots, farId) ? spots[farId] : null;
    if (!spot) continue;
    above ??= drawnAbove(regions, levelId, spots, routes);
    if (!above.has(farId)) continue;
    const at = exitPoint(here[nearId], carryTo(regions, levelId, { id: farId, x: spot.x, y: spot.y }));
    if (at) raw.push({ from: nearId, to: farId, name: names[farId], at, kind: road.kind, road });
  }
  return mergeExits(raw);
}

export function viewRect(cam, mapW, mapH, vw, vh) {
  const sw = mapW * cam.k;
  const sh = mapH * cam.k;
  return { x: (-cam.x / sw) * 100, y: (-cam.y / sh) * 100, w: (vw / sw) * 100, h: (vh / sh) * 100 };
}

export function coverage(view, r) {
  const ix = Math.max(0, Math.min(view.x + view.w, r.x + r.w) - Math.max(view.x, r.x));
  const iy = Math.max(0, Math.min(view.y + view.h, r.y + r.h) - Math.max(view.y, r.y));
  const area = view.w * view.h;
  return area > 0 ? (ix * iy) / area : 0;
}

export function shown(view, r) {
  const ix = Math.max(0, Math.min(view.x + view.w, r.x + r.w) - Math.max(view.x, r.x));
  const iy = Math.max(0, Math.min(view.y + view.h, r.y + r.h) - Math.max(view.y, r.y));
  const area = r.w * r.h;
  return area > 0 ? (ix * iy) / area : 0;
}

const ENTER_AT = 0.55;
export const REARM_BELOW = 0.35;

export function autoCandidate(regions, parentId, view, armed = () => true) {
  let best = null;
  let bestCov = ENTER_AT;
  for (const r of childrenOf(regions, parentId)) {
    if (r.auto === false || !armed(r.id)) continue;
    const cov = coverage(view, r);
    if (cov >= bestCov) { best = r; bestCov = cov; }
  }
  return best;
}

export function fitContain(mapW, mapH, vw, vh, pad = 24) {
  const k = Math.min((vw - 2 * pad) / mapW, (vh - 2 * pad) / mapH);
  return { k, x: (vw - mapW * k) / 2, y: (vh - mapH * k) / 2 };
}

export function fitRect(r, mapW, mapH, vw, vh, pad = 24) {
  const rw = (r.w / 100) * mapW;
  const rh = (r.h / 100) * mapH;
  const k = Math.min((vw - 2 * pad) / rw, (vh - 2 * pad) / rh);
  const cx = ((r.x + r.w / 2) / 100) * mapW;
  const cy = ((r.y + r.h / 2) / 100) * mapH;
  return { k, x: vw / 2 - cx * k, y: vh / 2 - cy * k };
}

export function clampLens(cam, mapW, mapH, vw, vh) {
  const sw = mapW * cam.k;
  const sh = mapH * cam.k;
  const x = sw <= vw ? (vw - sw) / 2 : Math.min(0, Math.max(vw - sw, cam.x));
  const y = sh <= vh ? (vh - sh) / 2 : Math.min(0, Math.max(vh - sh, cam.y));
  return { k: cam.k, x, y };
}

export function zoomAround(cam, sx, sy, factor, kMin, kMax) {
  const want = cam.k * factor;
  const k = Math.max(kMin, Math.min(kMax, want));
  const atFloor = factor < 1 && want < kMin * 1.0001;
  const mx = (sx - cam.x) / cam.k;
  const my = (sy - cam.y) / cam.k;
  return { cam: { k, x: sx - mx * k, y: sy - my * k }, atFloor };
}

export function rectOnScreen(r, cam, mapW, mapH) {
  return {
    left: cam.x + (r.x / 100) * mapW * cam.k,
    top: cam.y + (r.y / 100) * mapH * cam.k,
    width: (r.w / 100) * mapW * cam.k,
    height: (r.h / 100) * mapH * cam.k,
  };
}


export function rectToChild(r, rect) {
  return {
    x: ((rect.x - r.x) / r.w) * 100, y: ((rect.y - r.y) / r.h) * 100,
    w: (rect.w / r.w) * 100, h: (rect.h / r.h) * 100,
  };
}
export function rectToParent(r, rect) {
  return {
    x: r.x + (rect.x / 100) * r.w, y: r.y + (rect.y / 100) * r.h,
    w: (rect.w / 100) * r.w, h: (rect.h / 100) * r.h,
  };
}

export function carryRect(regions, fromId, toId, rect) {
  const up = fromId ? chainOf(regions, fromId) : [];
  const down = toId ? chainOf(regions, toId) : [];
  if ((fromId && !up.length) || (toId && !down.length)) return null;
  let shared = 0;
  while (shared < up.length && shared < down.length && up[shared].id === down[shared].id) shared++;
  let out = { ...rect };
  for (let i = up.length - 1; i >= shared; i--) out = rectToParent(up[i], out);
  for (const r of down.slice(shared)) out = rectToChild(r, out);
  return out;
}

export function clampRect(rect, digits = 1) {
  if (!rect || ![rect.x, rect.y, rect.w, rect.h].every(Number.isFinite)) return null;
  const f = 10 ** digits;
  const round = (v) => Math.round(v * f) / f;
  const x0 = round(Math.max(0, Math.min(100, rect.x)));
  const y0 = round(Math.max(0, Math.min(100, rect.y)));
  const x1 = round(Math.max(0, Math.min(100, rect.x + rect.w)));
  const y1 = round(Math.max(0, Math.min(100, rect.y + rect.h)));
  if (x1 - x0 <= 0 || y1 - y0 <= 0) return null;
  return { x: x0, y: y0, w: round(x1 - x0), h: round(y1 - y0) };
}

export function rectFromView(cam, mapW, mapH, vw, vh, digits = 1) {
  return clampRect(viewRect(cam, mapW, mapH, vw, vh), digits);
}


const HASH_KEY = 'region';
const hashParts = (hash) => String(hash ?? '').replace(/^#/, '').split('&').filter(Boolean);
const keyOf = (part) => { const i = part.indexOf('='); return i < 0 ? part : part.slice(0, i); };

export function regionFromHash(hash) {
  for (const part of hashParts(hash)) {
    if (keyOf(part) !== HASH_KEY || !part.includes('=')) continue;
    let id;
    try { id = decodeURIComponent(part.slice(part.indexOf('=') + 1)); } catch { return null; }
    id = id.trim();
    return id && id.length <= 200 ? id : null;
  }
  return null;
}

export function hashWithRegion(hash, id) {
  const mine = id ? `${HASH_KEY}=${encodeURIComponent(id)}` : null;
  const out = [];
  let placed = false;
  for (const part of hashParts(hash)) {
    if (keyOf(part) !== HASH_KEY) { out.push(part); continue; }
    if (!placed && mine) out.push(mine);
    placed = true;
  }
  if (!placed && mine) out.push(mine);
  return out.join('&');
}


export function pinchStep(cam, a0, b0, a1, b1, kMin, kMax) {
  const d0 = Math.hypot(b0.x - a0.x, b0.y - a0.y);
  const d1 = Math.hypot(b1.x - a1.x, b1.y - a1.y);
  const factor = d0 > 0 && d1 > 0 ? d1 / d0 : 1;
  const want = cam.k * factor;
  const k = Math.max(kMin, Math.min(kMax, want));
  const atFloor = factor < 1 && want < kMin * 1.0001;
  const m0 = { x: (a0.x + b0.x) / 2, y: (a0.y + b0.y) / 2 };
  const m1 = { x: (a1.x + b1.x) / 2, y: (a1.y + b1.y) / 2 };
  const mx = (m0.x - cam.x) / cam.k;
  const my = (m0.y - cam.y) / cam.k;
  return { cam: { k, x: m1.x - mx * k, y: m1.y - my * k }, atFloor, factor };
}
