/* Atlas — region-model.js: the maths of REGIONS, with no
   DOM and no imports, so tests/test_region_model.mjs can ask it questions in
   plain node. regions.js is the shell: it reads the window and the camera,
   asks this module, and writes the answer to the page.

   Units. Everything on a map is in PERCENT of that map (0–100 across and down),
   the same units places use. A region's rectangle {x, y, w, h} is in percent
   of its PARENT map; a place's position on a region map is in percent of the
   region map. A camera is {x, y, k}: the map's top-left corner sits at screen
   (x, y) and one map pixel is k screen pixels. */

/** The regions drawn directly on a map: parent null/'' = the main map. */
export function childrenOf(regions, parentId) {
  const want = parentId || '';
  return (regions || []).filter((r) => (r.parent || '') === want);
}

/** [outermost … id], or [] when the chain is broken or loops. */
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

/** A parent-map point → the same point in a region's own percent. */
export function toChild(r, p) {
  return { x: ((p.x - r.x) / r.w) * 100, y: ((p.y - r.y) / r.h) * 100 };
}

/** A region-map point → the parent map's percent (the inverse). */
export function toParent(r, p) {
  return { x: r.x + (p.x / 100) * r.w, y: r.y + (p.y / 100) * r.h };
}

const inside = (p) => p.x >= 0 && p.x <= 100 && p.y >= 0 && p.y <= 100;

/** Where `node` is drawn on region `regionId`'s map, or null when it is not
    in that region. A pin in `places` wins; otherwise the place's position on
    the parent map is carried through the rectangle — recursively, so a
    grandchild region inherits pins made on its parent. */
export function placeOn(regions, regionId, node, _depth = 0) {
  if (_depth > 32) return null;                 // a loop the validator also reports
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

/** Which child region of `levelId` each drawn place stands in, on this level's
    map: `{ place id: region id }`. `at` is `{ id: {x, y} }`, everything drawn
    here. Only the children are asked; a place outside them all is not listed. */
export function homesAt(regions, levelId, at) {
  const kids = childrenOf(regions, levelId);
  const out = {};
  for (const [id, p] of Object.entries(at || {})) {
    const r = p && kids.find((k) => within(p, k));
    if (r) out[id] = r.id;
  }
  return out;
}

/** The places a FOLDED child region keeps to itself on this level's map.

    A region with `fold` is a country seen from far off: on its parent's map
    only the places that have a road to somewhere else on that map are drawn,
    and the rest wait inside. "Somewhere else" is a place drawn here that does
    not stand in the same region. Returns a Set of the place ids to leave out.
    A region without `fold` hides nothing, so an old map reads as it did. */
export function foldedAt(regions, levelId, at, routes) {
  const folds = new Set(childrenOf(regions, levelId).filter((r) => r.fold === true).map((r) => r.id));
  if (!folds.size) return new Set();
  const home = homesAt(regions, levelId, at);
  const speaks = new Set();
  for (const road of routes || []) {
    const a = road?.from, b = road?.to;
    if (!at[a] || !at[b] || home[a] === home[b]) continue;   // both drawn here, in different places
    speaks.add(a); speaks.add(b);
  }
  const hidden = new Set();
  for (const [id, region] of Object.entries(home)) {
    if (folds.has(region) && !speaks.has(id)) hidden.add(id);
  }
  return hidden;
}

/* The states a place can be in that are worth a word on a folded region's tab,
   worst first. `healthy` says nothing, and neither does a place nobody watches. */
const FOLD_ILLS = ['down', 'degraded', 'maintenance', 'slumbering'];
const FOLD_ALARMS = ['down', 'degraded', 'maintenance'];   // the ones that also get the cue

/** What each FOLDED child region of `levelId` is keeping to itself, and how
    those places are: `{ region id: { count, down, degraded, maintenance,
    slumbering, healthy, unknown, worst } }`.

    `at` is everything that stands on this level's map before folding
    (`{ id: {x, y} }`), `hidden` the ids the fold left out (foldedAt's answer),
    `states` the live feed's word for each place (`{ id: 'down' }`). A place
    with no word, or a word this does not know, is `unknown`: never healthy,
    never an alarm. `worst` is 'down', 'degraded' or 'maintenance', else null.
    Ids only: no name of a hidden place is read here or handed back. */
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

/** One region's summary in words: `8 places`, `8 places, 1 down`. '' when the
    fold hides nothing. Healthy and unknown places are counted and not named. */
export function foldWords(s) {
  if (!s || !s.count) return '';
  const said = { down: 'down', degraded: 'degraded', maintenance: 'in maintenance', slumbering: 'slumbering' };
  const ills = FOLD_ILLS.filter((st) => s[st] > 0).map((st) => `${s[st]} ${said[st]}`);
  return [`${s.count} ${s.count === 1 ? 'place' : 'places'}`, ...ills].join(', ');
}

/* ── exits: roads that leave the level ────────────────────────────────────── */

/** Where `node` would stand on region `regionId`'s map if the map had no
    edges: placeOn without the clip, so a place out on the parent map gets a
    point beyond 0–100 that says which way it lies. Pins are honoured at every
    level, as placeOn does; equal to placeOn wherever placeOn answers. */
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

/** Where the straight line from `from` (a place on this map) to `far` (a point
    beyond it) crosses the map's border, in percent. Null when `far` is on the
    map (nothing leaves), or either point is not a point. */
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
  const hold = (v) => Math.max(0, Math.min(100, v));   // rounding must not push it off the edge
  return { x: hold(a.x + dx * t), y: hold(a.y + dy * t) };
}

/** `EDGE`, `EDGE, MEDIA`, `EDGE, MEDIA +2`: at most two names, then a count. */
export function exitLabel(names) {
  const list = (names || []).filter(Boolean);
  return list.slice(0, 2).join(', ') + (list.length > 2 ? ` +${list.length - 2}` : '');
}

/** Exits that leave ONE place through nearly the same spot become one line.
    `exits` is `[{ from, to, name, at: {x, y}, … }]`; two belong together when
    they share `from` and their border points are within `tol` percent. Each
    group keeps its first exit's fields (so its point, kind and road), and adds
    `ids` and `names` (in order, no place twice) and the `label` to draw. */
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

/** Every place that stands on region `id`'s map, before any folding:
    `{ place id: {x, y} }` in that map's percent. `spots` is where each place
    that is drawn at all stands on the main map (`{ id: {x, y} }`). */
export function standingOn(regions, id, spots) {
  const out = {};
  for (const [pid, p] of Object.entries(spots || {})) {
    const at = placeOn(regions, id, { id: pid, x: p.x, y: p.y });
    if (at) out[pid] = at;
  }
  return out;
}

/** The places drawn on some map above region `levelId`: the main map and each
    region on the way down to it, less what each of those maps folds away. A
    Set of place ids. `spots` as standingOn takes it. */
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

/** The roads that leave region `levelId`'s map: one entry per line,
    `{from, to, ids, names, label, at, kind, road}` (mergeExits' answer).
    `here` is what is drawn on this map (`{ id: {x, y} }`), `spots` where every
    drawn place stands on the main map, `names` each place's name by id. A road
    counts when one end is drawn here and the other is drawn on a map above. */
export function exitsFor(regions, levelId, here, spots, names, routes) {
  let above = null;
  const raw = [];
  for (const road of routes || []) {
    const a = here[road.from], b = here[road.to];
    if (Boolean(a) === Boolean(b)) continue;            // both drawn here, or neither
    const nearId = a ? road.from : road.to;
    const farId = a ? road.to : road.from;
    const spot = Object.hasOwn(spots, farId) ? spots[farId] : null;
    if (!spot) continue;                                // no such place, or one kept off the map
    above ??= drawnAbove(regions, levelId, spots, routes);
    if (!above.has(farId)) continue;
    const at = exitPoint(here[nearId], carryTo(regions, levelId, { id: farId, x: spot.x, y: spot.y }));
    if (at) raw.push({ from: nearId, to: farId, name: names[farId], at, kind: road.kind, road });
  }
  return mergeExits(raw);
}

/** The part of a map the window shows, in that map's percent. */
export function viewRect(cam, mapW, mapH, vw, vh) {
  const sw = mapW * cam.k;
  const sh = mapH * cam.k;
  return { x: (-cam.x / sw) * 100, y: (-cam.y / sh) * 100, w: (vw / sw) * 100, h: (vh / sh) * 100 };
}

/** How much of the window `view` is taken by rectangle `r` (0–1). */
export function coverage(view, r) {
  const ix = Math.max(0, Math.min(view.x + view.w, r.x + r.w) - Math.max(view.x, r.x));
  const iy = Math.max(0, Math.min(view.y + view.h, r.y + r.h) - Math.max(view.y, r.y));
  const area = view.w * view.h;
  return area > 0 ? (ix * iy) / area : 0;
}

/** How much of rectangle `r` the window shows (0–1): a region you have
    zoomed PAST (its art fills the window and more) still counts as entered. */
export function shown(view, r) {
  const ix = Math.max(0, Math.min(view.x + view.w, r.x + r.w) - Math.max(view.x, r.x));
  const iy = Math.max(0, Math.min(view.y + view.h, r.y + r.h) - Math.max(view.y, r.y));
  const area = r.w * r.h;
  return area > 0 ? (ix * iy) / area : 0;
}

/* 55%, down from 75% (owner, 2026-11-11). The zoom now stops one + past the
   scale a clicked place is shown at, and at that ceiling a tall, narrow region
   (an island a quarter of the map wide) fills about 63% of a wide window: 75%
   could no longer be reached, so the region only opened from its tab. 55% is
   above what a click on a place gives (about 52%), so going to a place does
   not open the region around it; one + from there does. */
const ENTER_AT = 0.55;   // the rectangle fills 55% of the window…
export const REARM_BELOW = 0.35; // …and must fall back under 35% before it can fire again

/** The region zooming would open now, or null. Only regions drawn on this map
    (`parentId`), only those with `auto` not false, only one the window is
    mostly made of — and, of those, the one it is most made of. */
export function autoCandidate(regions, parentId, view, armed = () => true) {
  let best = null;
  let bestCov = ENTER_AT;
  for (const r of childrenOf(regions, parentId)) {
    if (r.auto === false || !armed(r.id)) continue;
    const cov = coverage(view, r);      // a window wholly inside the rectangle = 1
    if (cov >= bestCov) { best = r; bestCov = cov; }
  }
  return best;
}

/** A camera that shows the whole map, centred, with `pad` px to spare. */
export function fitContain(mapW, mapH, vw, vh, pad = 24) {
  const k = Math.min((vw - 2 * pad) / mapW, (vh - 2 * pad) / mapH);
  return { k, x: (vw - mapW * k) / 2, y: (vh - mapH * k) / 2 };
}

/** A camera that frames rectangle `r` (percent of the map) in the window. */
export function fitRect(r, mapW, mapH, vw, vh, pad = 24) {
  const rw = (r.w / 100) * mapW;
  const rh = (r.h / 100) * mapH;
  const k = Math.min((vw - 2 * pad) / rw, (vh - 2 * pad) / rh);
  const cx = ((r.x + r.w / 2) / 100) * mapW;
  const cy = ((r.y + r.h / 2) / 100) * mapH;
  return { k, x: vw / 2 - cx * k, y: vh / 2 - cy * k };
}

/** Keep a region map on screen: smaller than the window = centred on that
    axis; bigger = its edges may not pull in past the window's. */
export function clampLens(cam, mapW, mapH, vw, vh) {
  const sw = mapW * cam.k;
  const sh = mapH * cam.k;
  const x = sw <= vw ? (vw - sw) / 2 : Math.min(0, Math.max(vw - sw, cam.x));
  const y = sh <= vh ? (vh - sh) / 2 : Math.min(0, Math.max(vh - sh, cam.y));
  return { k: cam.k, x, y };
}

/** Zoom by `factor` about screen point (sx, sy), held between kMin and kMax.
    Returns the new camera and whether the floor stopped it (the cue that a
    further zoom-out means "leave"). */
export function zoomAround(cam, sx, sy, factor, kMin, kMax) {
  const want = cam.k * factor;
  const k = Math.max(kMin, Math.min(kMax, want));
  const atFloor = factor < 1 && want < kMin * 1.0001;
  const mx = (sx - cam.x) / cam.k;
  const my = (sy - cam.y) / cam.k;
  return { cam: { k, x: sx - mx * k, y: sy - my * k }, atFloor };
}

/** Where rectangle `r` sits on screen under camera `cam` (for the transition
    that grows the detailed map out of its frame). */
export function rectOnScreen(r, cam, mapW, mapH) {
  return {
    left: cam.x + (r.x / 100) * mapW * cam.k,
    top: cam.y + (r.y / 100) * mapH * cam.k,
    width: (r.w / 100) * mapW * cam.k,
    height: (r.h / 100) * mapH * cam.k,
  };
}

/* ── "use the current view" (the Desk's rectangle helper) ─────────────────── */

/** A rectangle in a parent map's percent → the same rectangle in region
    `r`'s own percent, and back. The point maps above, applied to a box. */
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

/** Carry a rectangle drawn on map `fromId` (null = the main map) onto map
    `toId`: up through `fromId`'s chain to the main map, then down through
    `toId`'s (skipping the maps both chains share). Null when either chain is
    broken. A rectangle that lies outside the target map comes back outside
    it — `clampRect` says so. */
export function carryRect(regions, fromId, toId, rect) {
  const up = fromId ? chainOf(regions, fromId) : [];
  const down = toId ? chainOf(regions, toId) : [];
  if ((fromId && !up.length) || (toId && !down.length)) return null;
  let shared = 0;                 // the maps both chains pass through: no trip needed
  while (shared < up.length && shared < down.length && up[shared].id === down[shared].id) shared++;
  let out = { ...rect };
  for (let i = up.length - 1; i >= shared; i--) out = rectToParent(up[i], out);
  for (const r of down.slice(shared)) out = rectToChild(r, out);
  return out;
}

/** Hold a rectangle to its map (0–100 both ways) and round it to `digits`
    decimals — edges first, so the rounded box still fits (x + w ≤ 100).
    Null when nothing of it is on the map. */
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

/** What camera `cam` shows of a mapW×mapH map in a vw×vh window, as a
    rectangle a region can take: clamped to the map, rounded. A map smaller
    than the window (letterboxed) gives the whole of it on that axis. */
export function rectFromView(cam, mapW, mapH, vw, vh, digits = 1) {
  return clampRect(viewRect(cam, mapW, mapH, vw, vh), digits);
}

/* ── deep links: #region=<id> ─────────────────────────────────────────────
   The hash is a list of `key=value` parts joined by `&`; `region` is ours and
   any other part is someone else's and kept, in its place. */

const HASH_KEY = 'region';
const hashParts = (hash) => String(hash ?? '').replace(/^#/, '').split('&').filter(Boolean);
const keyOf = (part) => { const i = part.indexOf('='); return i < 0 ? part : part.slice(0, i); };

/** The region a hash names, or null (absent, empty, or not decodable). */
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

/** `hash` with its region part set to `id` (null = removed); every other
    part kept where it was. Returned without the leading '#', '' when empty. */
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

/* ── pinch (two pointers) ──────────────────────────────────────────────── */

/** One step of a two-finger pinch: the pointers were at a0, b0 and are now
    at a1, b1 (screen px). The map point under their old midpoint ends up
    under the new one (so a pinch also pans), and the zoom follows the change
    in their distance, held between kMin and kMax. `atFloor` as zoomAround:
    pinching out with the floor in the way. */
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
