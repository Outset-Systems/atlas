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
