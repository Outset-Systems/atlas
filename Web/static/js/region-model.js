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

export const ENTER_AT = 0.75;    // the rectangle fills 75% of the window…
export const REARM_BELOW = 0.5;  // …and must fall back under 50% before it can fire again

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
