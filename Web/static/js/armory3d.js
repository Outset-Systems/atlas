/* Atlas — armory3d.js: THE ARMORY as an orbitable 3D deep-dive.

   A companion to the 2D elevation (reliquary.js), not a replacement: the same
   vessels from the same rack-model.js, drawn as a matte survey-table rack you
   can turn in the light. The house rule is the design notes's "Illuminated Cartography"
   — ink and gold, an object on a table, never a generic three.js demo. All ten
   locked specs live in the design notes ("THE ARMORY — 3D deep-dive"); this file is
   their implementation.

   Zero-CSP-delta by construction: three.js and OrbitControls are vendored and
   imported by relative path (no import-map, which the app's `default-src 'self'`
   would block as inline script), and the BoxGeometry + CanvasTexture + orbit
   path pulls in no WASM, no workers, no eval, no network. The GL context is a
   scarce resource, so exactly one lives at a time and enter()/exit() are a
   strict pair — reliquary.js calls exit() on close.

   NOTE: written against three r160; runtime-verified only in a browser (needs
   the vendored lib present). Syntax is node-checked; behaviour is QA'd via
   /browse before ship. */

import { A, CFG } from './config.js';
import * as THREE from './vendor/three.module.js';
import { OrbitControls } from './vendor/OrbitControls.js';
import { UH, RACK_W, faceplate, ledSpot, setRackTheme } from './rack-model.js';
setRackTheme(CFG.THEME);   // THE THEME (v1.48.0)

const NS = 'http://www.w3.org/2000/svg';
const RAIL = 0.55;                       // rack-rail thickness, world units
const DEPTH = 6.5;                       // vessel depth: a real rack cabinet, not a slab
const WIDTH = RACK_W / UH;               // rack width in U-units (~13.5)
const LED_BY_STATE = { healthy: '#8EC07C', degraded: '#FABD2F', down: '#FB4934',
                       maintenance: '#83A598', slumbering: '#7c748a' };
const reduced = () => {
  try { return window.matchMedia('(prefers-reduced-motion: reduce)').matches; }
  catch { return false; }
};

/* Design tokens, read live so the rack tracks a retheme; the fallbacks are the
   real Gruvbox values (the design notes) for the rare case the prop is unreadable. */
function tok(name, fallback) {
  try {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fallback;
  } catch { return fallback; }
}

/* ── faceplate → texture (spec 3) ──────────────────────────────────────────
   The fp-* art is class-styled by atlas.css; an <img>-loaded SVG ignores the
   page's stylesheet, so the computed fills must be inlined. A hidden probe in
   the right kind context captures them (drift-proof, and it keeps fp-vent's
   --fp-accent var so compute/forge keep their accent). sRGB texture or gruvbox
   reads dark. */
const FP_CLASSES = ['fp-panel', 'fp-ear', 'fp-hole', 'fp-screen', 'fp-glyph',
  'fp-port', 'fp-sfp', 'fp-key', 'fp-vent', 'fp-badge', 'fp-btn', 'fp-led'];
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
  // give the SVG an intrinsic size (some engines need it to rasterise) and
  // inline the computed fp-* styles right after the opening tag.
  svg = svg.replace('<svg class="fp-svg"',
    `<svg class="fp-svg rel-${d.kind}" width="${RACK_W}" height="${H}"`);
  svg = svg.replace(/(<svg[^>]*>)/, `$1<style>${fpStyle(d.kind)}</style>`);
  const scale = 3;                                   // ~1380px wide — crisp on orbit
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

/* ── the one live instance ─────────────────────────────────────────────── */
let R = null;               // the running rig, or null when torn down
let sharedRenderer = null;  // ONE WebGL context for the app's life (getRenderer)
let _avail = null;          // cached WebGL-availability probe (never changes)

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
        if (/swiftshader|llvmpipe|software/i.test(name)) return false;  // unusably slow
      }
      return true;
    } catch { return false; }
  })();
  return _avail;
}

/* The renderer (and its GL context) is made ONCE and reused across every
   open/close. A WebGL context is scarce (~16 per page), so a new one per toggle
   trips "too many active WebGL contexts" — the leak the 20x-open test catches.
   Scene contents are still built fresh each enter() and freed each exit(); only
   the context persists. webglcontextlost is wired once here: it drops the shared
   renderer so the next open makes a fresh one, and falls back to 2D. */
function getRenderer() {
  if (sharedRenderer) return sharedRenderer;
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.domElement.style.display = 'block';
  renderer.domElement.style.touchAction = 'none';
  renderer.domElement.addEventListener('webglcontextlost', (e) => {
    e.preventDefault();
    sharedRenderer = null;                 // force a fresh context on next open
    const cb = R && R.onLost;
    exit();
    if (cb) cb();
  }, false);
  sharedRenderer = renderer;
  return renderer;
}

/* enter({ container, model, ledStateFor, onPick, onLost }):
     container   — the element to fill with the canvas
     model       — { devices, rackU } from rack-model (shared with the 2D view)
     ledStateFor — (node) => state string, for the live LED colour
     onPick      — (device) => void, the shared detail pane
     onLost      — () => void, called if the GL context is lost (fall back to 2D)
   Returns true if the scene came up, false if it could not (caller stays 2D). */
function enter({ container, model, ledStateFor, onPick, onLost }) {
  if (R) exit();
  if (!available() || !container) return false;

  const rig = { container, onPick, onLost, disposables: [], devMeshes: [], leds: [],
                raf: 0, selected: null, downXY: null };
  const w = container.clientWidth || 640;
  const h = container.clientHeight || 480;

  const renderer = getRenderer();
  renderer.setSize(w, h);
  container.appendChild(renderer.domElement);
  rig.renderer = renderer;
  const maxAniso = renderer.capabilities.getMaxAnisotropy();

  const scene = new THREE.Scene();
  rig.scene = scene;
  const camera = new THREE.PerspectiveCamera(40, w / h, 0.1, 500);
  rig.camera = camera;

  // lighting (spec 2): one warm key, a soft hemi fill, no HDR, no blue rim.
  const key = new THREE.DirectionalLight(0xf0e0b0, 1.15);
  key.position.set(-8, 12, 14);
  scene.add(key);
  const fill = new THREE.HemisphereLight(0x3c3836, 0x282828, 0.55);
  scene.add(fill);
  scene.add(new THREE.AmbientLight(0xffffff, 0.12));

  const rackU = Math.max(1, model.rackU || 1);
  const half = rackU / 2;

  // materials (spec 1): matte survey-table metal, gilt as line-edges.
  const chassis = new THREE.MeshStandardMaterial({
    color: new THREE.Color(tok('--surface', '#282828')), roughness: 0.85, metalness: 0.12,
  });
  const railMat = new THREE.MeshStandardMaterial({
    color: new THREE.Color(tok('--ink-line', '#504945')), roughness: 0.8, metalness: 0.15,
  });
  const gilt = new THREE.Color(tok('--gilt', '#d79921'));
  const giltBright = new THREE.Color(tok('--gilt-bright', '#fabd2f'));
  const giltMat = new THREE.LineBasicMaterial({ color: gilt, transparent: true, opacity: 0.85 });
  rig.disposables.push(chassis, railMat, giltMat);

  const uToY = (centerU) => (centerU - (rackU + 1) / 2);   // U1 low, rackU high, centred

  // vessels
  for (const d of model.devices) {
    const gh = d.size - 0.08;                       // small inter-U gap
    const geo = new THREE.BoxGeometry(WIDTH, gh, DEPTH);
    const state = ledStateFor ? ledStateFor(d.node) : '';
    const ledHex = LED_BY_STATE[state] || '';
    const face = new THREE.MeshBasicMaterial({ map: faceTexture(d, ledHex, maxAniso) });
    // BoxGeometry material order: px,nx,py,ny,pz(+Z=front),nz
    const mats = [chassis, chassis, chassis, chassis, face, chassis];
    const mesh = new THREE.Mesh(geo, mats);
    const centerU = d.top - (d.size - 1) / 2;
    mesh.position.set(0, uToY(centerU), 0);
    mesh.userData.device = d;
    scene.add(mesh);
    rig.devMeshes.push(mesh);
    rig.disposables.push(geo, face, face.map);

    // gilt edge outline (spec 1)
    const edges = new THREE.LineSegments(new THREE.EdgesGeometry(geo), giltMat);
    edges.position.copy(mesh.position);
    mesh.userData.edges = edges;
    scene.add(edges);
    rig.disposables.push(edges.geometry);

    // breathing LED for attention states (spec 4)
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
        ledMesh.position.set(lx, ly, DEPTH / 2 + 0.02);
        mesh.add(ledMesh);
        rig.leds.push(ledMesh);
        rig.disposables.push(ledGeo, ledMat);
      }
    }
  }

  // rack rails + gilt frame outline
  const railH = rackU + 0.4;
  for (const sx of [-1, 1]) {
    const rgeo = new THREE.BoxGeometry(RAIL, railH, DEPTH);
    const rail = new THREE.Mesh(rgeo, railMat);
    rail.position.set(sx * (WIDTH / 2 + RAIL / 2), 0, 0);
    scene.add(rail);
    rig.disposables.push(rgeo);
    const redge = new THREE.LineSegments(new THREE.EdgesGeometry(rgeo), giltMat);
    redge.position.copy(rail.position);
    scene.add(redge);
    rig.disposables.push(redge.geometry);
  }

  // contact shadow (spec 2 / 10): a soft radial-gradient plane grounds the rack.
  const shadow = makeContactShadow();
  shadow.position.set(0, -half - 0.35, 0);   // centred under the deep footprint
  shadow.rotation.x = -Math.PI / 2;
  scene.add(shadow);
  rig.disposables.push(shadow.geometry, shadow.material, shadow.material.map);

  // camera framing: a 3/4 angle (spec 5), distance scaled to the rack height
  const dist = Math.max(WIDTH, rackU, DEPTH) * 1.35 + 8;   // include depth so the deep cabinet frames
  camera.position.set(dist * 0.62, dist * 0.28, dist * 0.82);
  camera.lookAt(0, 0, 0);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.target.set(0, 0, 0);
  controls.enablePan = false;
  controls.enableDamping = !reduced();
  controls.dampingFactor = 0.08;
  controls.minPolarAngle = 0.52;             // ~30° — never top-down
  controls.maxPolarAngle = 1.75;             // ~100° — never underneath
  controls.minDistance = dist * 0.6;
  controls.maxDistance = dist * 1.8;
  controls.rotateSpeed = 0.9;
  controls.update();
  rig.controls = controls;

  // selection: default to the crown vessel (parity with the 2D view)
  const crown = model.devices.find((d) => d.slot && d.slot.node === 'hypervisor')
    || model.devices[0];

  // picking — distinguish a click from an orbit drag
  const onDown = (e) => { rig.downXY = [e.clientX, e.clientY]; };
  const onUp = (e) => {
    if (!rig.downXY) return;
    const moved = Math.hypot(e.clientX - rig.downXY[0], e.clientY - rig.downXY[1]);
    rig.downXY = null;
    if (moved > 5) return;                    // that was an orbit, not a pick
    const rect = renderer.domElement.getBoundingClientRect();
    const ndc = new THREE.Vector2(
      ((e.clientX - rect.left) / rect.width) * 2 - 1,
      -((e.clientY - rect.top) / rect.height) * 2 + 1);
    const ray = new THREE.Raycaster();
    ray.setFromCamera(ndc, camera);
    const hit = ray.intersectObjects(rig.devMeshes, false)[0];
    if (hit) selectMesh(rig, hit.object, giltBright, gilt);
  };
  renderer.domElement.addEventListener('pointerdown', onDown);
  renderer.domElement.addEventListener('pointerup', onUp);
  rig.onDown = onDown; rig.onUp = onUp;

  R = rig;
  // apply the default selection (fires onPick for the shared detail pane)
  if (crown) {
    const m = rig.devMeshes.find((x) => x.userData.device === crown);
    if (m) selectMesh(rig, m, giltBright, gilt);
  }

  // render loop — continuous while damping/breathing; cheap for a dozen boxes
  const clock = new THREE.Clock();
  const tick = () => {
    rig.raf = requestAnimationFrame(tick);
    const t = clock.getElapsedTime();
    if (!reduced()) {
      for (let i = 0; i < rig.leds.length; i++) {
        // stagger like the map's marker-breathe — not synchronised
        const phase = 0.5 + 0.5 * Math.sin(t * 2.0 + i * 0.9);
        rig.leds[i].material.opacity = 0.4 + 0.55 * phase;
        rig.leds[i].scale.setScalar(0.85 + 0.3 * phase);
      }
    }
    controls.update();
    renderer.render(scene, camera);
  };
  rig.clock = clock;
  tick();
  return true;
}

function selectMesh(rig, mesh, giltBright, gilt) {
  // restore the previous selection to the shared gilt edge material
  if (rig.selected && rig.selected.userData._selMat) {
    rig.selected.userData.edges.material = rig.selected.userData._origMat;
    rig.selected.userData._selMat.dispose();
    rig.selected.userData._selMat = null;
  }
  rig.selected = mesh;
  if (mesh.userData.edges) {
    const sel = mesh.userData.edges.material.clone();
    sel.color.copy(giltBright);
    sel.opacity = 1;
    mesh.userData._origMat = mesh.userData.edges.material;
    mesh.userData._selMat = sel;
    mesh.userData.edges.material = sel;
  }
  void gilt;
  if (rig.onPick && mesh.userData.device) rig.onPick(mesh.userData.device);
}

function makeContactShadow() {
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
  const plane = new THREE.Mesh(new THREE.PlaneGeometry(WIDTH * 1.5, DEPTH * 1.7), mat);
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
  rig.controls?.dispose();
  if (rig.selected?.userData?._selMat) rig.selected.userData._selMat.dispose();
  // free this scene's GPU resources; KEEP the renderer + context for reuse
  for (const d of rig.disposables) { try { d.dispose?.(); } catch { /* */ } }
  rig.scene?.clear();
  rig.renderer.renderLists.dispose();
  if (el.parentNode) el.parentNode.removeChild(el);
}

A.armory3d = { available, enter, exit, resize, isActive: () => !!R };
