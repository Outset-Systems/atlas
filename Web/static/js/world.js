
import { A, CFG, REDUCED, $, esc, zoneById, nodeById, FALLBACK_HUE } from './config.js';
import { placeLabels } from './label-model.js';
import { applyOverrides, onStyleArt, dragOnMap, keepSpot } from './places.js';
import { buildRoutes, buildTerritories } from './roads.js';
import { ringZoom } from './constellation.js';

const overlay = $('overlay');
const zoneLabelsEl = $('zone-labels');
const markersEl = $('markers');

function autoZoneSpots() {
  const at = {};
  for (const n of A.DATA.nodes) if (!n.off_map) at[n.id] = { x: n.x, y: n.y };
  const charPx = CFG.ZONE_LABEL_PX * 1.14;
  const groups = A.DATA.zones.map((z) => ({
    id: z.id,
    ids: A.DATA.nodes.filter((n) => n.zone === z.id && at[n.id]).map((n) => n.id),
    hw: Math.max(3, String(z.name || '').length * charPx / A.MAPW * 50),
    hh: CFG.ZONE_LABEL_PX * 1.9 / A.MAPH * 50,
  }));
  const roads = (A.DATA.routes || []).map((r) => [r.from, r.to]);
  return placeLabels(groups, at, roads);
}

function buildZoneLabels() {
  const styled = onStyleArt();
  if (A.levelPlaces && !styled) return;
  const auto = styled ? autoZoneSpots() : {};
  for (const z of A.DATA.zones) {
    const pin = A.levelPlaces ? null : A.styleDraft().zones[z.id] || A.styleZones?.[z.id];
    const at = pin || auto[z.id];
    if (!at && (styled || z.hide_label || z.id === 'lower')) continue;
    const el = document.createElement('div');
    el.className = 'zone-label';
    el.addEventListener('pointerdown', (e) => {
      if (!A.editMode || !onStyleArt() || A.levelPlaces) return;
      let spot = null;
      dragOnMap(e, el, (p) => (spot = { x: Math.max(0, Math.min(100, p.x)), y: Math.max(-40, Math.min(140, p.y)) }),
        () => A.draftStyleSpot('zones', z.id, spot));
    });
    el.style.left = (at ? at.x : z.label_x) + '%';
    el.style.top = (at ? at.y : z.label_y) + '%';
    el.style.color = z.hue;
    el.style.fontSize = CFG.ZONE_LABEL_PX + 'px';
    el.innerHTML = `${esc(z.name)}<small>vlan ${esc(z.vlan)} · ${esc(z.subnet)}</small>`;
    zoneLabelsEl.appendChild(el);
  }
}

let lastDim = null, lastLabeled = null;

function updateZoneLabelFade() {
  const t = Math.max(0, Math.min(1, (A.cam.k / A.fitScale() - 1) / 1.2));
  if (inDepths) {
    if (lastDim !== null) {
      lastDim = null;
      for (const el of zoneLabelsEl.children) el.style.opacity = '';
    }
  } else {
    const dim = netOn ? '0' : (CFG.ZONE_LABEL_MAX_OPACITY * (1 - t)).toFixed(2);
    if (dim !== lastDim) {
      lastDim = dim;
      zoneLabelsEl.style.opacity = '';
      for (const el of zoneLabelsEl.children) {
        el.style.opacity = dim;
      }
    }
  }
  const labeled = t > CFG.CLOSEUP_T;
  if (labeled !== lastLabeled) {
    lastLabeled = labeled;
    for (const mk of markersEl.children) mk.classList.toggle('labeled', labeled);
  }
}

function resetFadeCache() { lastDim = null; lastLabeled = null; }

let inDepths = false;
let inSky = false;
let onCentre = true;
let shoreSnap = false;

function toggleDepths(force) {
  const next = force ?? !inDepths;
  if (next === inDepths) return;
  inDepths = next;
  document.body.classList.toggle('depths', inDepths);
}

function viewBand() {
  return { top: (0 - A.cam.y) / A.cam.k, bottom: (innerHeight - A.cam.y) / A.cam.k };
}

function checkVoid(userMove) {
  if (!A.MAPH) return;
  const bottomImgY = viewBand().bottom;
  if (userMove && !inDepths && bottomImgY > A.MAPH * CFG.DEPTHS_ENGAGE) toggleDepths(true);
  else if (inDepths && bottomImgY < A.MAPH * CFG.DEPTHS_RELEASE) toggleDepths(false);
}

const _clamp01 = (v) => Math.max(0, Math.min(1, v));

const shadeEl = () => $('depth-map-shade');
const skyLightEl = () => $('sky-map-light');
let lastDepthQ = null, lastSkyQ = null;
let fadeTargets = null;

function updateShades(userMove) {
  if (!A.MAPH) return;
  const { top: topImgY, bottom: bottomImgY } = viewBand();
  const depthT = _clamp01((bottomImgY / A.MAPH - 0.98) / 0.20);
  const skyT = _clamp01((-topImgY / A.MAPH) / (CFG.SKY_NORTH * 0.85));

  const depthQ = depthT.toFixed(2), skyQ = skyT.toFixed(2);
  if (depthQ !== lastDepthQ) { lastDepthQ = depthQ; shadeEl()?.style.setProperty('--depth-t', depthQ); }
  if (skyQ !== lastSkyQ) { lastSkyQ = skyQ; skyLightEl()?.style.setProperty('--sky-t', skyQ); }
  if (inSky ? skyT < CFG.SKY_RELEASE : skyT > CFG.SKY_ENGAGE) {
    inSky = !inSky;
    document.body.classList.toggle('in-sky', inSky);
  }
  const offCentre = Math.abs((topImgY + bottomImgY) / 2 / A.MAPH - 0.5);
  if (onCentre ? offCentre > CFG.CENTRE_LEAVE : offCentre < CFG.CENTRE_ENTER) {
    onCentre = !onCentre;
    if (onCentre) A.wakeDrift?.();
  }

  const fade = 1 - _clamp01(Math.max(skyT, depthT) * 1.8);
  const fadeQ = fade.toFixed(2);
  if (!fadeTargets) fadeTargets = ['card', 'index-drawer', 'map-drawer'].map($).filter(Boolean);
  for (const el of fadeTargets) {
    if (el.id === 'card' && A.splitRing()) {
      if (el.style.opacity !== '') { el.style.opacity = ''; el.style.pointerEvents = ''; }
      continue;
    }
    const open = el.classList.contains('show') || el.classList.contains('open')
              || el.classList.contains('visible');
    if (open && fade < 1) {
      if (el.style.opacity !== fadeQ) el.style.opacity = fadeQ;
      el.style.pointerEvents = fade < 0.5 ? 'none' : '';
    } else if (el.style.opacity !== '') {
      el.style.opacity = '';
      el.style.pointerEvents = '';
    }
  }
  const fit = A.fitScale();
  if (userMove && !shoreSnap && A.cam.k > fit * 1.06) {
    if (depthT > 0.75)    { shoreSnap = true; centerDepths(true); }
    else if (skyT > 0.35) { shoreSnap = true; A.ascend(); }
  }
  if (shoreSnap && depthT < 0.05 && skyT < 0.05) shoreSnap = false;
}

A.onCameraMove = (userMove) => { checkVoid(userMove); updateZoneLabelFade(); updateShades(userMove); };

function centerDepths(gliding = true) {
  toggleDepths(true);
  A.cam.k = A.fitScale();
  A.cam.x = (innerWidth - A.MAPW * A.cam.k) / 2;
  A.cam.y = A.landOn('abyss');
  A.clampCam();
  A.apply(gliding);
}

A.recenter = function recenter(gliding = true) {
  if (inDepths) centerDepths(gliding);
  else A.home(gliding);
};

A.pullBack = function pullBack() {
  const id = markersEl.querySelector('.mk.active')?.dataset.id || A.netSelected();
  const n = id ? nodeById(id) : null;
  const floor = Math.max(A.cam.min, A.fitScale());
  const atFloor = A.cam.k <= floor * 1.001;
  const k = Math.max(floor, A.cam.k / CFG.ZOOM_PULLBACK);
  if (n) A.glideTo(n.x, n.y, k);
  else if (!atFloor) A.zoomAt(innerWidth / 2, innerHeight / 2, k / A.cam.k);
  return atFloor ? 'floor' : 'ok';
};

A.descend = function descend() {
  if (inDepths) {
    A.closeCard();
    A.home(true);
    toggleDepths(false);
    return;
  }
  centerDepths(true);
};

A.ascend = function ascend() {
  A.closeCard();
  A.cam.k = A.fitScale();
  A.cam.x = (innerWidth - A.MAPW * A.cam.k) / 2;
  A.cam.y = A.landOn('chronicle');
  A.clampCam();
  A.apply(true);
};

function buildSkyIsland() {
  const island = $('sky-island');
  const shadow = $('sky-shadow');
  if (!island || !shadow) return;
  const w = A.MAPW * CFG.MESA_W, h = A.MAPH * CFG.MESA_H;
  const px = (CFG.MESA_POS.x / 100) * A.MAPW, py = (CFG.MESA_POS.y / 100) * A.MAPH;
  island.style.width = w + 'px';
  island.style.height = h + 'px';
  island.style.left = px + 'px';
  island.style.top = py + 'px';
  shadow.style.width = w * 0.9 + 'px';
  shadow.style.height = h * 0.7 + 'px';
  shadow.style.left = px + 'px';
  shadow.style.top = py + h * 0.5 + 'px';
}


let netOn = false;

A.netOn = () => netOn;

function atSurvey() {
  if (inDepths) return false;
  if (A.cam.k > A.fitScale() * 1.1) return false;
  const { top, bottom } = viewBand();
  const slack = A.MAPH * 0.02;
  return top > -slack && bottom < A.MAPH + slack;
}

A.toggleNet = function toggleNet(force) {
  const forced = typeof force === 'boolean';
  if (forced && force === netOn) return;
  if (!forced && !netOn && !atSurvey()) {
    if (inDepths) A.descend();
    else { A.closeCard?.(); A.recenter(true); }
    return;
  }
  netOn = forced ? force : !netOn;
  $('btn-net').classList.toggle('lit', netOn);
  if (!netOn) A.clearHighlight();
  if (netOn && !forced) { A.closeCard?.(); A.recenter(true); }
  if (netOn && !REDUCED) {
    overlay.querySelectorAll('path.route:not(.route-exit)').forEach((p, i) => {
      const L = p.getTotalLength();
      p.style.transition = 'none';
      p.style.strokeDasharray = String(L);
      p.style.strokeDashoffset = String(L);
      p.getBoundingClientRect();
      p.style.transition = '';
      setTimeout(() => { p.style.strokeDashoffset = '0'; }, 40 + i * 90);
    });
  }
  overlay.classList.toggle('net-on', netOn);
  document.body.classList.toggle('net-on', netOn);
  updateZoneLabelFade();
};

function buildMarkers() {
  applyOverrides();
  A.DATA.nodes.forEach((n, i) => {
    if (n.off_map) return;
    const zone = zoneById(n.zone);
    const hue = n.hue || (zone ? zone.hue : FALLBACK_HUE);
    const mk = document.createElement('div');
    const kin = n.zone === 'lower' || n.y > 100;
    mk.className = 'mk' + (kin ? ' depths-kin' : '') + (n.planned ? ' mk-planned' : '');
    mk.dataset.id = n.id;
    mk.dataset.kind = n.kind || 'vm';
    if (n.device) mk.dataset.device = n.device;
    mk.dataset.shape = n.shape || ({ physical: 'square', network: 'square' }[n.kind] || 'circle');
    mk.dataset.hue = hue;
    mk.style.left = n.x + '%';
    mk.style.top = n.y + '%';
    mk.style.setProperty('--mk-hue', hue);
    mk.style.setProperty('--mk-glow', hue + '55');
    mk.style.setProperty('--breathe-delay', (i * 0.35 % CFG.BREATHE_S).toFixed(2) + 's');
    mk.innerHTML = `
      <div class="mk-dot">
        <div class="mk-ring"></div>
        <div class="mk-core"></div>
      </div>
      <div class="mk-label">${esc(n.name)}</div>`;
    const sigil = String(A.styleLogos?.[n.id] || '');
    if (/^[a-z0-9][a-z0-9-]{0,39}$/.test(sigil)) {
      mk.classList.add('mk-sigil');
      const core = mk.querySelector('.mk-core');
      core.style.webkitMaskImage = core.style.maskImage = `url("static/icons/${sigil}.svg")`;
    }
    mk.addEventListener('click', (e) => {
      if (mk.dataset.dragged) { delete mk.dataset.dragged; return; }
      e.stopPropagation();
      A.toggleDrawer?.(false);
      focusNode(n.id, true, true);
    });
    mk.addEventListener('pointerdown', (e) => {
      if (A.levelPlaces) { A.pinDrag?.(e, mk, n); return; }
      if (!A.editMode) return;
      const styled = onStyleArt();
      if (!styled && A.stylePlaces?.[n.id]) return;
      dragOnMap(e, mk, (p) => {
        n.x = Math.max(0, Math.min(100, p.x));
        n.y = Math.max(-40, Math.min(140, p.y));
        return n;
      }, () => {
        if (styled) A.draftStyleSpot('places', n.id, n);
        else keepSpot(n.id, n);
        A.redrawLines?.();
      });
    });
    markersEl.appendChild(mk);
  });
}

function focusNode(id, glide = true, toggle = false) {
  const n = nodeById(id);
  if (!n) return;
  if (A.splitRing() && A.splitRing().id !== id) A.collapseConstellation();
  if (netOn && A.netSelected() === id) {
    A.clearHighlight();
    A.closeCard?.();
    return;
  }
  if (toggle && !netOn && markersEl.querySelector('.mk.active')?.dataset.id === id) {
    A.closeCard?.();
    A.recenter(true);
    return;
  }
  for (const mk of markersEl.children) mk.classList.toggle('active', mk.dataset.id === id);
  const willSplit = (A.serviceEntriesFor?.(id) || []).length > 0;
  if (netOn) A.highlightNode(id);
  else if (glide && !willSplit) {
    const k = A.focusScale();
    const a = A.focusAnchor(n.x, k);
    A.setCardSide?.(a.cardLeft);
    A.glideTo(n.x, n.y, k, a.x);
  }
  if (willSplit) A.setCardSide?.(A.focusAnchor(n.x, ringZoom()).cardLeft);
  A.openCard(n);
  if (willSplit) A.openConstellation(id, { auto: true });
}
A.focusNode = focusNode;

A.buildWorld = function buildWorld() {
  if (A.clearHighlight) A.clearHighlight(); else A.collapseConstellation();
  resetFadeCache();
  zoneLabelsEl.innerHTML = '';
  markersEl.innerHTML = '';
  overlay.querySelector('#routes')?.remove();
  overlay.querySelector('#territories')?.remove();
  applyOverrides();
  buildZoneLabels();
  buildSkyIsland();
  buildTerritories();
  buildRoutes();
  buildMarkers();
  updateZoneLabelFade();
};

A.redrawLines = function redrawLines() {
  overlay.querySelector('#routes')?.remove();
  overlay.querySelector('#territories')?.remove();
  buildTerritories();
  buildRoutes();
  if (netOn) { overlay.classList.add('net-on'); }
  A.paintRoutes?.();
};
