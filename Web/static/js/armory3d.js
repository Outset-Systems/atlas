
import { A, CFG } from './config.js';
import * as THREE from './vendor/three.module.js';
import { OrbitControls } from './vendor/OrbitControls.js';
import { UH, RACK_W, LED_BY_STATE, crownOf, faceplate, ledSpot, rackDepthMm, setRackTheme } from './rack-model.js';
setRackTheme(CFG.THEME);

const NS = 'http://www.w3.org/2000/svg';
const RAIL = 0.55;
const WIDTH = RACK_W / UH;
const MM = WIDTH / 482.6;
const FOV = 40;
const GLIDE_MS = 900;
const REAR_W = 9.5;
const REAR_D = 106 * MM;
const VIEWS = {
  corner: { theta: 0.6, phi: 1.28 },
  front: { theta: 0, phi: 1.5 },
  side: { theta: Math.PI / 2, phi: 1.5 },
  rear: { theta: Math.PI - 0.5, phi: 1.32 },
};
const reduced = () => {
  try { return window.matchMedia('(prefers-reduced-motion: reduce)').matches; }
  catch { return false; }
};

function tok(name, fallback) {
  try {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fallback;
  } catch { return fallback; }
}

const FP_CLASSES = ['fp-panel', 'fp-ear', 'fp-hole', 'fp-screen', 'fp-glyph',
  'fp-port', 'fp-sfp', 'fp-key', 'fp-vent', 'fp-badge', 'fp-btn', 'fp-led', 'fp-bay'];
const _styleCache = {};
function fpStyle(kind) {
  if (_styleCache[kind]) return _styleCache[kind];
  const holder = document.createElement('div');
  holder.className = 'rel-dev rel-' + kind;
  holder.style.cssText = 'position:absolute;left:-9999px;top:0;width:0;height:0;overflow:hidden';
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('class', 'fp-svg');
  holder.appendChild(svg);
  const els = FP_CLASSES.map((c) => {
    const el = document.createElementNS(NS, 'rect');
    el.setAttribute('class', c);
    svg.appendChild(el);
    return el;
  });
  document.body.appendChild(holder);
  const rules = FP_CLASSES.map((c, i) => {
    const cs = getComputedStyle(els[i]);
    let r = `.${c}{fill:${cs.fill};`;
    if (c === 'fp-vent') r += `stroke:var(--fp-accent,${cs.stroke});`;
    else if (cs.stroke && cs.stroke !== 'none') r += `stroke:${cs.stroke};`;
    if (cs.stroke && cs.stroke !== 'none' && cs.strokeWidth) r += `stroke-width:${cs.strokeWidth};`;
    return r + '}';
  }).join('');
  document.body.removeChild(holder);
  _styleCache[kind] = rules;
  return rules;
}

function faceTexture(d, ledHex, maxAniso) {
  const H = d.size * UH;
  let svg = faceplate(d, ledHex);
  svg = svg.replace('<svg class="fp-svg"',
    `<svg class="fp-svg rel-${d.kind}" width="${RACK_W}" height="${H}"`);
  svg = svg.replace(/(<svg[^>]*>)/, `$1<style>${fpStyle(d.kind)}</style>`);
  const scale = 3;
  const canvas = document.createElement('canvas');
  canvas.width = RACK_W * scale;
  canvas.height = H * scale;
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = maxAniso;
  const img = new Image();
  img.onload = () => {
    const ctx = canvas.getContext('2d');
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    tex.needsUpdate = true;
  };
  img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
  return tex;
}

let R = null;
let sharedRenderer = null;
let _avail = null;

function available() {
  if (_avail !== null) return _avail;
  _avail = (() => {
    try {
      const c = document.createElement('canvas');
      const gl = c.getContext('webgl2') || c.getContext('webgl');
      if (!gl) return false;
      const dbg = gl.getExtension('WEBGL_debug_renderer_info');
      if (dbg) {
        const name = String(gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) || '');
        if (/swiftshader|llvmpipe|software/i.test(name)) return false;
      }
      return true;
    } catch { return false; }
  })();
  return _avail;
}

function getRenderer() {
  if (sharedRenderer) return sharedRenderer;
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.domElement.style.display = 'block';
  renderer.domElement.style.touchAction = 'none';
  renderer.domElement.addEventListener('webglcontextlost', (e) => {
    e.preventDefault();
    sharedRenderer = null;
    const cb = R && R.onLost;
    exit();
    if (cb) cb();
  }, false);
  sharedRenderer = renderer;
  return renderer;
}

function enter({ container, model, ledStateFor, onPick, onHover, onTurn, onLost }) {
  if (R) exit();
  if (!available() || !container) return false;

  const rig = { container, onPick, onHover, onLost, disposables: [], devMeshes: [], leds: [],
                raf: 0, selected: null, hovered: null, downXY: null, glide: null };
  const w = container.clientWidth || 640;
  const h = container.clientHeight || 480;

  const renderer = getRenderer();
  renderer.setSize(w, h);
  container.appendChild(renderer.domElement);
  rig.renderer = renderer;
  const maxAniso = renderer.capabilities.getMaxAnisotropy();

  const scene = new THREE.Scene();
  rig.scene = scene;
  const camera = new THREE.PerspectiveCamera(FOV, w / h, 0.1, 500);
  rig.camera = camera;

  const key = new THREE.DirectionalLight(0xf0e0b0, 1.15);
  key.position.set(-8, 12, 14);
  scene.add(key);
  const fill = new THREE.HemisphereLight(0x3c3836, 0x282828, 0.55);
  scene.add(fill);
  scene.add(new THREE.AmbientLight(0xffffff, 0.12));

  const rackU = Math.max(1, model.rackU || 1);
  const rear = model.rear || [];
  const rackD = rackDepthMm(model.devices, rear) * MM;
  const frontZ = rackD / 2;
  const railH = rackU + 0.8;

  const chassis = new THREE.MeshStandardMaterial({
    color: new THREE.Color(tok('--surface', '#282828')), roughness: 0.85, metalness: 0.12,
  });
  const railMat = new THREE.MeshStandardMaterial({
    color: new THREE.Color(tok('--ink-line', '#504945')), roughness: 0.8, metalness: 0.15,
  });
  const gilt = new THREE.Color(tok('--gilt', '#d79921'));
  const giltBright = new THREE.Color(tok('--gilt-bright', '#fabd2f'));
  const giltMat = new THREE.LineBasicMaterial({ color: gilt, transparent: true, opacity: 0.85 });
  const hoverMat = new THREE.LineBasicMaterial({ color: gilt, transparent: true, opacity: 1 });
  const selMat = new THREE.LineBasicMaterial({ color: giltBright, transparent: true, opacity: 1 });
  rig.edgeMats = { rest: giltMat, hover: hoverMat, picked: selMat };
  rig.disposables.push(chassis, railMat, giltMat, hoverMat, selMat);

  const addVessel = (d, gh, depth, x, y, z, faceIndex, ledHex) => {
    const geo = new THREE.BoxGeometry(d.rear ? REAR_W : WIDTH, gh, depth);
    const face = new THREE.MeshBasicMaterial({ map: faceTexture(d, ledHex, maxAniso) });
    const mats = [chassis, chassis, chassis, chassis, chassis, chassis];
    mats[faceIndex] = face;
    const mesh = new THREE.Mesh(geo, mats);
    mesh.position.set(x, y, z);
    mesh.userData.device = d;
    scene.add(mesh);
    rig.devMeshes.push(mesh);
    rig.disposables.push(geo, face, face.map);

    const edges = new THREE.LineSegments(new THREE.EdgesGeometry(geo), giltMat);
    edges.position.copy(mesh.position);
    mesh.userData.edges = edges;
    scene.add(edges);
    rig.disposables.push(edges.geometry);
    return mesh;
  };

  const uToY = (centerU) => (centerU - (rackU + 1) / 2);

  for (const d of model.devices) {
    const gh = d.size - 0.08;
    const depth = (d.depth || 430) * MM;
    const state = ledStateFor ? ledStateFor(d.node) : '';
    const ledHex = LED_BY_STATE[state] || '';
    const centerU = d.top - (d.size - 1) / 2;
    const mesh = addVessel(d, gh, depth, 0, uToY(centerU), frontZ - depth / 2, 4, ledHex);

    if (state === 'degraded' || state === 'down') {
      const spot = ledSpot(d);
      if (spot) {
        const H = d.size * UH;
        const lx = (spot.x / RACK_W - 0.5) * WIDTH;
        const ly = (0.5 - spot.y / H) * gh;
        const ledGeo = new THREE.CircleGeometry(0.16, 20);
        const ledMat = new THREE.MeshBasicMaterial({
          color: new THREE.Color(ledHex), transparent: true, opacity: 0.9,
          blending: THREE.AdditiveBlending, depthWrite: false,
        });
        const ledMesh = new THREE.Mesh(ledGeo, ledMat);
        ledMesh.position.set(lx, ly, depth / 2 + 0.02);
        mesh.add(ledMesh);
        rig.leds.push(ledMesh);
        rig.disposables.push(ledGeo, ledMat);
      }
    }
  }

  const rearStep = rear.length ? Math.min(2.2, railH / rear.length) : 0;
  rear.forEach((r, i) => {
    const y = railH / 2 - rearStep * (i + 0.5);
    addVessel({ ...r, size: 2 }, rearStep - 0.2, REAR_D, 0, y, -rackD / 2 + REAR_D / 2 + RAIL / 2, 5, '');
  });

  const beam = (bw, bh, bd, x, y, z) => {
    const geo = new THREE.BoxGeometry(bw, bh, bd);
    const mesh = new THREE.Mesh(geo, railMat);
    mesh.position.set(x, y, z);
    scene.add(mesh);
    const edge = new THREE.LineSegments(new THREE.EdgesGeometry(geo), giltMat);
    edge.position.copy(mesh.position);
    scene.add(edge);
    rig.disposables.push(geo, edge.geometry);
  };
  const postX = WIDTH / 2 + RAIL / 2;
  for (const sx of [-1, 1])
    for (const sz of [-1, 1]) beam(RAIL, railH, RAIL, sx * postX, 0, sz * frontZ);
  for (const sy of [-1, 1]) {
    const y = sy * (railH / 2 + 0.12);
    for (const sz of [-1, 1]) beam(WIDTH + RAIL * 2, 0.24, RAIL, 0, y, sz * frontZ);
    for (const sx of [-1, 1]) beam(RAIL, 0.24, rackD, sx * postX, y, 0);
  }

  const ticks = [];
  for (let u = 0; u <= rackU; u++) {
    const y = u - rackU / 2;
    for (const sx of [-1, 1]) {
      const inner = sx * WIDTH / 2, outer = sx * (WIDTH / 2 + RAIL);
      ticks.push(inner, y, frontZ + RAIL / 2 + 0.01, outer, y, frontZ + RAIL / 2 + 0.01);
    }
  }
  const tickGeo = new THREE.BufferGeometry();
  tickGeo.setAttribute('position', new THREE.Float32BufferAttribute(ticks, 3));
  scene.add(new THREE.LineSegments(tickGeo, giltMat));
  rig.disposables.push(tickGeo);

  const shadow = makeContactShadow(rackD);
  shadow.position.set(0, -railH / 2 - 0.3, 0);
  shadow.rotation.x = -Math.PI / 2;
  scene.add(shadow);
  rig.disposables.push(shadow.geometry, shadow.material, shadow.material.map);

  rig.bounds = { height: railH + 1, depth: rackD };
  const dist = fitDistance(camera, rig.bounds);
  camera.position.setFromSpherical(
    new THREE.Spherical(dist, VIEWS.corner.phi, VIEWS.corner.theta));
  camera.lookAt(0, 0, 0);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.target.set(0, 0, 0);
  controls.enablePan = false;
  controls.enableDamping = !reduced();
  controls.dampingFactor = 0.08;
  controls.minPolarAngle = 0.52;
  controls.maxPolarAngle = 1.75;
  controls.minDistance = dist * 0.6;
  controls.maxDistance = dist * 1.8;
  controls.rotateSpeed = 0.9;
  controls.update();
  controls.addEventListener('start', () => {
    rig.glide = null;
    if (onTurn) onTurn();
  });
  rig.controls = controls;

  const crown = crownOf(model.devices);

  const pickAt = (e) => {
    const rect = renderer.domElement.getBoundingClientRect();
    const ndc = new THREE.Vector2(
      ((e.clientX - rect.left) / rect.width) * 2 - 1,
      -((e.clientY - rect.top) / rect.height) * 2 + 1);
    const ray = new THREE.Raycaster();
    ray.setFromCamera(ndc, camera);
    return ray.intersectObjects(rig.devMeshes, false)[0]?.object || null;
  };

  const onDown = (e) => { rig.downXY = [e.clientX, e.clientY]; };
  const onUp = (e) => {
    if (!rig.downXY) return;
    const moved = Math.hypot(e.clientX - rig.downXY[0], e.clientY - rig.downXY[1]);
    rig.downXY = null;
    if (moved > 5) return;
    const mesh = pickAt(e);
    if (mesh) selectMesh(rig, mesh);
  };
  const onMove = (e) => { if (!e.buttons) hoverMesh(rig, pickAt(e)); };
  const onLeave = () => hoverMesh(rig, null);
  renderer.domElement.addEventListener('pointerdown', onDown);
  renderer.domElement.addEventListener('pointerup', onUp);
  renderer.domElement.addEventListener('pointermove', onMove);
  renderer.domElement.addEventListener('pointerleave', onLeave);
  rig.onDown = onDown; rig.onUp = onUp; rig.onMove = onMove; rig.onLeave = onLeave;

  R = rig;
  if (crown) {
    const m = rig.devMeshes.find((x) => x.userData.device === crown);
    if (m) selectMesh(rig, m);
  }

  const clock = new THREE.Clock();
  const tick = () => {
    rig.raf = requestAnimationFrame(tick);
    const t = clock.getElapsedTime();
    stepGlide(rig);
    if (!reduced()) {
      for (let i = 0; i < rig.leds.length; i++) {
        const phase = 0.5 + 0.5 * Math.sin(t * 2.0 + i * 0.9);
        rig.leds[i].material.opacity = 0.4 + 0.55 * phase;
        rig.leds[i].scale.setScalar(0.85 + 0.3 * phase);
      }
    }
    controls.update();
    renderer.render(scene, camera);
  };
  tick();
  return true;
}

function fitDistance(camera, { height, depth }) {
  const t = Math.tan((FOV * Math.PI) / 360);
  return Math.max((height / 2) / t, (Math.hypot(WIDTH, depth) / 2) / (t * camera.aspect)) * 1.4;
}

function paintEdges(rig, mesh) {
  if (!mesh || !mesh.userData.edges) return;
  const m = rig.edgeMats;
  mesh.userData.edges.material =
    mesh === rig.selected ? m.picked : mesh === rig.hovered ? m.hover : m.rest;
}

function selectMesh(rig, mesh) {
  const prev = rig.selected;
  rig.selected = mesh;
  paintEdges(rig, prev);
  paintEdges(rig, mesh);
  if (rig.onPick && mesh.userData.device) rig.onPick(mesh.userData.device);
}

function hoverMesh(rig, mesh) {
  if (mesh === rig.hovered) return;
  const prev = rig.hovered;
  rig.hovered = mesh;
  paintEdges(rig, prev);
  paintEdges(rig, mesh);
  rig.renderer.domElement.style.cursor = mesh ? 'pointer' : '';
  if (rig.onHover) rig.onHover(mesh ? mesh.userData.device.key : null);
}

const meshFor = (key) => R?.devMeshes.find((m) => m.userData.device.key === key) || null;

function view(name) {
  const to = VIEWS[name];
  if (!R || !to) return;
  const from = new THREE.Spherical().setFromVector3(R.camera.position);
  if (reduced()) {
    R.glide = null;
    R.camera.position.setFromSpherical(from.set(from.radius, to.phi, to.theta));
    return;
  }
  const turn = ((to.theta - from.theta + Math.PI * 3) % (Math.PI * 2)) - Math.PI;
  R.glide = { start: performance.now(), radius: from.radius,
              phi: from.phi, dPhi: to.phi - from.phi, theta: from.theta, dTheta: turn };
}

function stepGlide(rig) {
  const g = rig.glide;
  if (!g) return;
  const k = Math.min(1, (performance.now() - g.start) / GLIDE_MS);
  const ease = 1 - (1 - k) ** 3;
  rig.camera.position.setFromSpherical(
    new THREE.Spherical(g.radius, g.phi + g.dPhi * ease, g.theta + g.dTheta * ease));
  if (k === 1) rig.glide = null;
}

function makeContactShadow(depth) {
  const c = document.createElement('canvas');
  c.width = c.height = 256;
  const ctx = c.getContext('2d');
  const g = ctx.createRadialGradient(128, 128, 10, 128, 128, 128);
  g.addColorStop(0, 'rgba(0,0,0,0.5)');
  g.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 256, 256);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  const mat = new THREE.MeshBasicMaterial({ map: tex, transparent: true, depthWrite: false });
  const plane = new THREE.Mesh(new THREE.PlaneGeometry(WIDTH * 1.6, depth * 1.5), mat);
  return plane;
}

function resize() {
  if (!R) return;
  const w = R.container.clientWidth || 640;
  const h = R.container.clientHeight || 480;
  R.camera.aspect = w / h;
  R.camera.updateProjectionMatrix();
  R.renderer.setSize(w, h);
}

function exit() {
  if (!R) return;
  const rig = R; R = null;
  if (rig.raf) cancelAnimationFrame(rig.raf);
  const el = rig.renderer.domElement;
  el.removeEventListener('pointerdown', rig.onDown);
  el.removeEventListener('pointerup', rig.onUp);
  el.removeEventListener('pointermove', rig.onMove);
  el.removeEventListener('pointerleave', rig.onLeave);
  el.style.cursor = '';
  rig.controls?.dispose();
  for (const d of rig.disposables) { try { d.dispose?.(); } catch {   } }
  rig.scene?.clear();
  rig.renderer.renderLists.dispose();
  if (el.parentNode) el.parentNode.removeChild(el);
}

A.armory3d = {
  available, enter, exit, resize, view,
  isActive: () => !!R,
  select: (key) => { const m = meshFor(key); if (m) selectMesh(R, m); },
  hover: (key) => { if (R) hoverMesh(R, meshFor(key)); },
};
