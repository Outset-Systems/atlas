/* Atlas — rack-model.js: the shared, DOM-free model + faceplate art
   for THE ARMORY. Both the 2D elevation (reliquary.js) and the 3D deep-dive
   (armory3d.js) build their device list and draw their faceplates from HERE, so
   the two views can never disagree about what is in the rack or what a vessel
   looks like. No `A`, no `document`, no localStorage: every input is passed in,
   every output is data or an SVG string — which is what makes it node-testable
   (tests/test_rack_model.mjs). Extracted from reliquary.js 2026-08-23 for the
   3D work (eng review F5); the 2D behaviour is unchanged. */

export const UH = 34;                 // px per rack U (and the SVG unit height)
export const RACK_W = 460;            // faceplate design width (px)

export const KIND_HUE =
  { gateway: '#5FA8D3', compute: '#C9A554', forge: '#C0714E', patch: '#8A8069' };

//: node.state → LED hex. The caller resolves the state from its own signals
//: feed and passes the string; '' means "no live signal, draw the dim default".
const LED_BY_STATE = { healthy: '#8EC07C', degraded: '#FABD2F', down: '#FB4934',
                       maintenance: '#83A598', slumbering: '#7c748a' };
export const ledColor = (state) => LED_BY_STATE[state] || '';

export const slug = (s) =>
  String(s || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
export const isEmpty = (slot) => !slot.node && /empt/i.test(slot.name || '');
export const topU = (slot) => {
  const m = String(slot.u).match(/\d+/g);
  return m ? Math.max(...m.map(Number)) : 0;
};
export const slotKey = (slot) => slot.node || ('slot:' + slug(slot.name));
export const uLabel = (top, size) => (size <= 1 ? `U${top}` : `U${top - size + 1}–${top}`);

/* Which faceplate a slot wears. Takes the already-resolved node so the model
   never has to know how the caller looks nodes up (A.DATA in the browser, a
   stub in the tests).
   Which lab names mean "the gateway" or "the forge" is the THEME's to say
   (v1.48.0: `gateway_nodes`, `forge_names`), set once by the browser modules
   through setRackTheme(); the model itself names no lab. */
const RACK_THEME = { gatewayNodes: [], forgeNames: [] };
export function setRackTheme({ gatewayNodes = [], forgeNames = [] } = {}) {
  RACK_THEME.gatewayNodes = gatewayNodes.map(String);
  RACK_THEME.forgeNames = forgeNames.map(n => String(n).toLowerCase()).filter(Boolean);
}
export function kindOf(slot, node) {
  const name = (slot.name || '').toLowerCase();
  if (name.includes('patch')) return 'patch';
  if (RACK_THEME.gatewayNodes.includes(slot.node) || (node && node.kind === 'network')) return 'gateway';
  if (RACK_THEME.forgeNames.some(f => name.includes(f))) return 'forge';
  return 'compute';
}

/* rack (raw slots) + a nodeById(id) resolver + pre-Save overrides → the device
   list and the rack height. Pure but for one deliberate write: an override
   rewrites its slot's `u` label (as the 2D drag did), so the caller's dataset
   reflects the moved vessel. */
export function buildDevices(rack, nodeById, overrides = {}) {
  rack = rack || [];
  const rackU = Math.max(1, ...rack.map(topU));
  const devices = rack.filter((s) => !isEmpty(s)).map((slot) => {
    const size = slot.size || 1;
    let top = topU(slot);
    if (Number.isInteger(overrides[slotKey(slot)])) {
      top = overrides[slotKey(slot)];
      slot.u = uLabel(top, size);
    }
    const node = slot.node ? nodeById(slot.node) : null;
    return { slot, key: slotKey(slot), node, name: slot.name, desc: slot.desc,
             size, top, kind: kindOf(slot, node) };
  });
  return { devices, rackU };
}

/* Would device `d` fit with its top at `top`, given the current layout? */
export function fits(devices, rackU, d, top) {
  const lo = top - d.size + 1, hi = top;
  if (lo < 1 || hi > rackU) return false;
  for (const o of devices) {
    if (o.key === d.key) continue;
    if (lo <= o.top && (o.top - o.size + 1) <= hi) return false;
  }
  return true;
}

/* ── faceplate art: pure SVG-string builders, class-styled by atlas.css ──────
   Shared so the 3D view can rasterise the very same faceplate to a texture. */

function ports(x, y, n, pw, ph, gap, cls) {
  let s = '';
  for (let i = 0; i < n; i++)
    s += `<rect class="${cls || 'fp-port'}" x="${x + i * (pw + gap)}" y="${y}" width="${pw}" height="${ph}" rx="1.5"/>`;
  return s;
}
function ears(size) {
  const H = size * UH; let h = '';
  for (let u = 0; u < size; u++) {
    const cy = u * UH + UH / 2;
    h += `<circle class="fp-hole" cx="10" cy="${cy}" r="2.3"/><circle class="fp-hole" cx="${RACK_W - 10}" cy="${cy}" r="2.3"/>`;
  }
  return `<rect class="fp-ear" x="0.5" y="0.5" width="20" height="${H - 1}"/>` +
         `<rect class="fp-ear" x="${RACK_W - 20.5}" y="0.5" width="20" height="${H - 1}"/>${h}`;
}
function svgWrap(size, inner) {
  const H = size * UH;
  return `<svg class="fp-svg" viewBox="0 0 ${RACK_W} ${H}" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">` +
    `<rect class="fp-panel" x="0.5" y="0.5" width="${RACK_W - 1}" height="${H - 1}" rx="3"/>${ears(size)}${inner}</svg>`;
}
function led(x, y, hex) {
  return `<circle class="fp-led" cx="${x}" cy="${y}" r="3"${hex ? ` style="fill:${hex}"` : ''}/>`;
}

function faceGateway(size, ledHex) {
  const H = size * UH, mid = H / 2;
  return svgWrap(size,
    `<rect class="fp-screen" x="32" y="6" width="26" height="${H - 12}" rx="3"/>` +
    `<path class="fp-glyph" d="M45 ${mid - 5} l6 10 h-12 z"/>` +
    ports(78, mid - 4, 2, 15, 9, 5, 'fp-sfp') +
    ports(122, mid - 5, 8, 12, 10, 3) +
    ports(232, mid - 5, 4, 12, 10, 3) +
    `<rect class="fp-badge" x="300" y="${mid - 7}" width="118" height="14" rx="2"/>` +
    led(430, mid, ledHex));
}
function facePatch(size) {
  const H = size * UH, n = 24, pw = 12, gap = 4;
  const total = n * pw + (n - 1) * gap, x0 = (RACK_W - total) / 2, y = H / 2 - 6;
  return svgWrap(size, ports(x0, y, n, pw, 12, gap, 'fp-key'));
}
function faceCompute(size, ledHex, accent) {
  const H = size * UH, cols = 24, rows = Math.max(2, size * 2);
  const vw = 11, vh = 7, gx = 4, gy = 5;
  const fieldW = cols * (vw + gx) - gx, fieldH = rows * (vh + gy) - gy;
  const x0 = 30 + ((RACK_W - 100) - fieldW) / 2, y0 = (H - fieldH) / 2;
  let vent = '';
  for (let r = 0; r < rows; r++)
    for (let c = 0; c < cols; c++)
      vent += `<rect class="fp-vent" x="${x0 + c * (vw + gx)}" y="${y0 + r * (vh + gy)}" width="${vw}" height="${vh}" rx="2"/>`;
  const bx = RACK_W - 44;
  const pwr = `<circle class="fp-btn" cx="${bx}" cy="${size >= 2 ? 22 : H / 2 - 6}" r="5"/>` +
              led(bx, size >= 2 ? 40 : H / 2 + 8, ledHex);
  return svgWrap(size, `<g style="--fp-accent:${accent}">${vent}</g>${pwr}`);
}

/* Where the LED sits on a device's faceplate, in faceplate coords
   (0..RACK_W × 0..size*UH), or null for a faceplate with no LED. The 3D
   view places a breathing light here; the 2D art draws it at the same spot. */
export function ledSpot(d) {
  const H = d.size * UH;
  if (d.kind === 'patch') return null;
  if (d.kind === 'gateway') return { x: 430, y: H / 2 };
  return { x: RACK_W - 44, y: d.size >= 2 ? 40 : H / 2 + 8 };   // compute / forge
}

/* The faceplate for a device, with its live LED colour already resolved. */
export function faceplate(d, ledHex) {
  if (d.kind === 'gateway') return faceGateway(d.size, ledHex);
  if (d.kind === 'patch') return facePatch(d.size);
  if (d.kind === 'forge') return faceCompute(d.size, ledHex, '#C0714E');
  return faceCompute(d.size, ledHex, '#C9A554');
}
