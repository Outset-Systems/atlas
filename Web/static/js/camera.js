
import { A, CFG, REDUCED, $ } from './config.js';
import { unproject } from './project.js';
import * as model from './camera-model.js';
import { mapKey, describe } from './keys-model.js';

const viewport = $('viewport');
const stage = $('stage');

const cam = { x: 0, y: 0, k: 1, min: 0.5, max: CFG.ZOOM_MAX };
A.cam = cam;

const _cardCss = getComputedStyle(document.documentElement);
const _cardPx = (name) => parseFloat(_cardCss.getPropertyValue(name)) || 0;

let voidDepth = CFG.VOID_DEPTH, skyNorth = CFG.SKY_NORTH;
function measureWorld() {
  const abyss = $('abyss'), sky = $('chronicle');
  if (!A.MAPH) return;
  if (A.levelPlaces) {
    voidDepth = 0; skyNorth = 0;
    if (A.apply) { A.clampCam(); A.apply(false); }
    return;
  }
  const fit = model.fitScale(view());
  abyss?.style.setProperty('--fit', fit);
  sky?.style.setProperty('--fit', fit);
  if (abyss?.offsetHeight) {
    voidDepth = (abyss.offsetTop + (abyss.offsetHeight + CFG.VOID_FOOT_PX) / fit) / A.MAPH - 1;
  }
  if (sky?.offsetHeight) {
    const top = Math.max(CFG.SKY_TOP, sky.offsetHeight / fit / A.MAPH + CFG.SKY_GAP);
    sky.style.top = `${(-top * 100).toFixed(2)}%`;
    skyNorth = Math.max(CFG.SKY_NORTH, top + CFG.VOID_FOOT_PX / fit / A.MAPH);
  }
  if (A.apply) { A.clampCam(); A.apply(false); }
}
A.measureWorld = measureWorld;

A.landOn = (id) => {
  const section = $(id), crown = $('scenes-list').getBoundingClientRect().bottom + 8;
  const air = Math.max(0, (innerHeight - crown - section.offsetHeight) / 2);
  return crown + air - section.offsetTop * cam.k;
};
const sectionWatch = new ResizeObserver(measureWorld);
sectionWatch.observe($('abyss'));
sectionWatch.observe($('chronicle'));
addEventListener('resize', measureWorld);
const CARD_SHARE_PX = _cardPx('--card-w') + 2 * _cardPx('--card-edge');
const narrowScreen = matchMedia('(max-width: 720px)');

function view() {
  const v = {
    vw: innerWidth, vh: innerHeight,
    mapW: A.MAPW, mapH: A.MAPH,
    kMin: cam.min, kMax: cam.max,
    voidDepth, skyNorth,
    cardSharePx: CARD_SHARE_PX, narrow: narrowScreen.matches,
  };
  cam.max = v.kMax = model.zoomCeiling(v, CFG.FOCUS_ZOOM, CFG.ZOOM_BTN, CFG.ZOOM_MAX);
  return v;
}

function adopt(target) {
  cam.x = target.x; cam.y = target.y; cam.k = target.k;
}

function fitScale() { return model.fitScale(view()); }
A.fitScale = fitScale;

function clampCam() { adopt(model.clampCam(cam, view())); }
A.clampCam = clampCam;

let frameQueued = false;
let committing = false;

function commit(gliding) {
  stage.classList.toggle('gliding', gliding && !REDUCED);
  stage.style.transform = `translate(${cam.x}px, ${cam.y}px) scale(${cam.k})`;
  if (committing) return;
  committing = true;
  try { A.onCameraMove?.(!gliding); } finally { committing = false; }
}

function apply(gliding = false) {
  if (gliding) { commit(true); return; }
  if (frameQueued) return;
  frameQueued = true;
  requestAnimationFrame(() => { frameQueued = false; commit(false); });
}
A.apply = apply;

function placesMidX() {
  const xs = (A.DATA?.nodes || []).filter((n) => !n.off_map && Number.isFinite(n.x))
    .map((n) => n.x).sort((a, z) => a - z);
  return xs.length ? xs[Math.floor(xs.length / 2)] : undefined;
}

function home(gliding = true) {
  adopt(model.homeTarget(view(), placesMidX()));
  apply(gliding);
}
A.home = home;
A.atHome = () => model.sameView(A.cam, model.homeTarget(view(), placesMidX()));
A.focusScale = () => model.focusScale(view(), CFG.FOCUS_ZOOM);

function glideTo(nx, ny, k, anchorX = innerWidth / 2) {
  adopt(model.glideTarget(nx, ny, k, anchorX, view()));
  apply(true);
}
A.glideTo = glideTo;


const focusAnchor = (nx, k) => model.focusAnchor(nx, k, view());
A.focusAnchor = focusAnchor;

function zoomAt(sx, sy, factor) {
  const target = model.zoomTarget(cam, unproject(sx, sy), factor, view());
  if (!target) return;
  adopt(target);
  apply(false);
}
A.zoomAt = zoomAt;

const zoomVia = (sx, sy, factor) => (A.zoomAt || zoomAt)(sx, sy, factor);

let drag = null, vel = { x: 0, y: 0 }, inertiaRAF = 0;
let lastWasDrag = false;

viewport.addEventListener('pointerdown', (e) => {
  if (e.button !== 0) return;
  cancelAnimationFrame(inertiaRAF);
  drag = { px: e.clientX, py: e.clientY, moved: false, id: e.pointerId };
});

viewport.addEventListener('pointermove', (e) => {
  if (!drag) return;
  const dx = e.clientX - drag.px, dy = e.clientY - drag.py;
  if (!drag.moved && Math.abs(dx) + Math.abs(dy) > CFG.DRAG_THRESHOLD_PX) {
    drag.moved = true;
    viewport.classList.add('dragging');
    try { viewport.setPointerCapture(drag.id); } catch {}
  }
  if (!drag.moved) return;
  const from = unproject(drag.px, drag.py);
  const to = unproject(e.clientX, e.clientY);
  const pdx = to.x - from.x, pdy = to.y - from.y;
  drag.px = e.clientX; drag.py = e.clientY;
  vel = { x: pdx, y: pdy };
  cam.x += pdx; cam.y += pdy;
  clampCam(); apply(false);
});

function endDrag() {
  if (!drag) return;
  lastWasDrag = drag.moved;
  drag = null;
  viewport.classList.remove('dragging');
  if (lastWasDrag && !REDUCED) {
    const decay = () => {
      vel.x *= CFG.INERTIA_DECAY; vel.y *= CFG.INERTIA_DECAY;
      if (Math.abs(vel.x) + Math.abs(vel.y) < 0.5) return;
      cam.x += vel.x; cam.y += vel.y;
      clampCam(); apply(false);
      inertiaRAF = requestAnimationFrame(decay);
    };
    inertiaRAF = requestAnimationFrame(decay);
  }
}
viewport.addEventListener('pointerup', endDrag);
viewport.addEventListener('pointercancel', endDrag);

viewport.addEventListener('wheel', (e) => {
  e.preventDefault();
  A.toggleDrawer?.(false);
  if (e.ctrlKey) {
    zoomVia(e.clientX, e.clientY, e.deltaY < 0 ? CFG.ZOOM_WHEEL : 1 / CFG.ZOOM_WHEEL);
  } else if (!model.atSurveyOrBeyond(cam.k, view())) {
    zoomVia(e.clientX, e.clientY, 1 / CFG.ZOOM_WHEEL);
  } else {
    const y = cam.y;
    cam.y -= e.deltaY * CFG.WHEEL_PAN;
    autoFrameSky();
    clampCam();
    apply(false);
    if (A.inRegion?.() && cam.y === y && e.deltaY > 0) A.regionFloor();
  }
}, { passive: false });

function autoFrameSky() {
  const framed = model.skyFrame(cam, view());
  cam.x = framed.x; cam.k = framed.k;
}

viewport.addEventListener('click', () => {
  if (lastWasDrag) { lastWasDrag = false; return; }
  A.closeCard?.();
});

viewport.addEventListener('dblclick', (e) => zoomVia(e.clientX, e.clientY, CFG.ZOOM_DBLCLICK));

addEventListener('keydown', (e) => {
  const away = document.body.classList.contains('deck');
  const action = mapKey(describe(e), { scene: !!A.sceneOpen, away });
  if (!action) return;
  const pan = CFG.PAN_KEY_PX;
  const zoom = (f) => zoomVia(innerWidth / 2, innerHeight / 2, f);
  switch (action) {
    case 'palette': e.preventDefault(); A.openPalette?.(); break;
    case 'escape': {
      if (A.glassOpen?.()) { A.closeGlass(); break; }
      const leaving = A.sceneOpen || A.cardOpen?.();
      A.closeMax?.(); A.closePalette?.(); A.closeAllScenes?.(); A.closeCard?.();
      A.toggleDecoys?.(false); A.toggleDrawer?.(false);
      if (leaving && !away) A.recenter?.(true);
      break;
    }
    case 'pan-left': cam.x += pan; clampCam(); apply(false); break;
    case 'pan-right': cam.x -= pan; clampCam(); apply(false); break;
    case 'pan-up': cam.y += pan; clampCam(); apply(false); break;
    case 'pan-down': cam.y -= pan; clampCam(); apply(false); break;
    case 'zoom-in': zoom(CFG.ZOOM_KEY); break;
    case 'zoom-out': zoom(1 / CFG.ZOOM_KEY); break;
    case 'home': A.closeCard?.(); home(true); break;
    case 'drawer': A.toggleDrawer?.(); break;
    case 'descend': A.descend?.(); break;
    case 'ascend': A.ascend?.(); break;
    case 'net': A.toggleNet?.(); break;
    case 'decoys': A.toggleDecoys?.(); break;
  }
});

addEventListener('resize', () => {
  cam.min = model.panFloor(innerWidth, A.MAPW, cam.min);
  clampCam(); apply(false);
});
