
export function fitScale(v) {
  return Math.max(v.vw / v.mapW, v.vh / v.mapH);
}

export function focusScale(v, focusZoom, floor = 1.4) {
  return Math.max(fitScale(v) * focusZoom, floor);
}

export function zoomCeiling(v, focusZoom, step, hard = Infinity) {
  return Math.min(hard, focusScale(v, focusZoom) * step);
}

export function clampK(k, v) {
  return Math.max(v.kMin, Math.min(v.kMax, k));
}

export function minCamX(w, v) {
  return Math.min(0, v.vw - w);
}

export function clampCam(cam, v) {
  const w = v.mapW * cam.k;
  const south = v.mapH * (1 + v.voidDepth) * cam.k;
  const north = v.mapH * v.skyNorth * cam.k;
  const minY = Math.min(0, v.vh - south);
  return {
    x: w <= v.vw ? (v.vw - w) / 2
                 : Math.max(minCamX(w, v), Math.min(0, cam.x)),
    y: Math.max(minY, Math.min(north, cam.y)),
    k: cam.k,
  };
}

export function homeTarget(v, focusX) {
  const k = fitScale(v);
  const w = v.mapW * k;
  const x = Number.isFinite(focusX) && w > v.vw ? v.vw / 2 - (focusX / 100) * w : (v.vw - w) / 2;
  return clampCam({ x, y: (v.vh - v.mapH * k) / 2, k }, v);
}

export function sameView(cam, target, px = 2) {
  return Math.abs(cam.x - target.x) <= px && Math.abs(cam.y - target.y) <= px &&
    Math.abs(cam.k / target.k - 1) <= 0.005;
}

export function glideTarget(nx, ny, k, anchorX, v) {
  const kk = clampK(k, v);
  const ax = anchorX === undefined ? v.vw / 2 : anchorX;
  return clampCam({
    x: ax - (nx / 100) * v.mapW * kk,
    y: v.vh * 0.44 - (ny / 100) * v.mapH * kk,
    k: kk,
  }, v);
}

export function focusAnchor(nx, k, v) {
  const kk = clampK(k, v);
  const w = v.mapW * kk;
  if (v.narrow || w <= v.vw)
    return { x: v.vw / 2, cardLeft: false };

  const half = (v.vw - v.cardSharePx) / 2;
  const anchorRight = v.vw - half;
  const desired = anchorRight - (nx / 100) * w;
  if (desired <= 0 && desired >= minCamX(w, v))
    return { x: anchorRight, cardLeft: true };

  if (desired < minCamX(w, v)) {
    const atEastStop = (nx / 100) * w + minCamX(w, v);
    return { x: atEastStop, cardLeft: atEastStop >= v.cardSharePx };
  }
  const atWestStop = (nx / 100) * w;
  if (atWestStop >= v.cardSharePx)
    return { x: atWestStop, cardLeft: true };
  return { x: half, cardLeft: false };
}

export function zoomTarget(cam, p, factor, v) {
  const k2 = clampK(cam.k * factor, v);
  if (k2 === cam.k) return null;
  return clampCam({
    x: p.x - ((p.x - cam.x) / cam.k) * k2,
    y: p.y - ((p.y - cam.y) / cam.k) * k2,
    k: k2,
  }, v);
}

export function atSurveyOrBeyond(k, v) {
  return k <= fitScale(v) * 1.001;
}

export function skyFrame(cam, v) {
  const topImgY = (0 - cam.y) / cam.k;
  if (topImgY >= 0) return { x: cam.x, k: cam.k };
  const into = Math.min(1, -topImgY / (v.mapH * 0.42));
  const k = cam.k + (fitScale(v) - cam.k) * 0.16 * into;
  const centerX = (v.vw - v.mapW * k) / 2;
  return { x: cam.x + (centerX - cam.x) * 0.18 * into, k };
}

export function panFloor(vw, mapW, previous) {
  if (!(vw > 0) || !mapW) return previous;
  return vw / mapW;
}
