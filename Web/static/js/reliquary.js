/* Atlas — RACKS (was THE ARMORY, THE RELIQUARY): each physical rack as an
   illuminated front-elevation with hardware-accurate engraved faceplates. Every
   vessel sits in a true U-slot; in Rearrange mode you can drag one to a free slot
   and Save the layout (persisted server-side via /api/rack, exactly like the map's
   moved dots). Rebuilt 2026-07-20. Titled by place since 2026-10-31:
   `Server room — Rack A`, with a picker when the lab charts more than one.
   The rack model + faceplate art moved to rack-model.js 2026-08-23 so the 3D
   deep-dive (armory3d.js) draws the same vessels from the same source (F5). */

import { A, CFG, $, esc, glassAttrs } from './config.js';
import { makeScene } from './scene.js';
import {
  UH, KIND_HUE, ledColor, uLabel, slotKey, setRackTheme,
  buildDevices as modelBuildDevices, buildRear, fits as modelFits, faceplate as modelFaceplate,
  rackList, rackTitle, inRack,
} from './rack-model.js';
setRackTheme(CFG.THEME);   // THE THEME (v1.48.0): which lab names are the gateway / the forge

const OVR_KEY = 'atlas-rack-overrides';   // { slotKey: topU } — per-browser, pre-Save
const RACK_KEY = 'atlas-rack-current';    // which rack this browser last looked at

let root, elevEl, detailEl, titleEl, rackEl;
let editing = false;
let devices = [], rackU = 12;
let racks = [], rackId = null;

const nodeById = (id) => A.DATA.nodes.find((n) => n.id === id);
const ledFor = (node) => ledColor(node ? A.signalsFeed?.nodes?.[node.id]?.state : '');

const readOvr = () => { try { return JSON.parse(localStorage.getItem(OVR_KEY) || '{}'); } catch { return {}; } };
const writeOvr = (o) => { try { localStorage.setItem(OVR_KEY, JSON.stringify(o)); } catch { /* private mode */ } };

// These thin wrappers keep this module's `devices`/`rackU` state and bind the
// live LED feed; the pure model + SVG art are in rack-model.js.
function buildDevices() {
  racks = rackList(A.DATA.racks, CFG.THEME?.text?.rack_location);
  if (!racks.some((r) => r.id === rackId)) {
    let saved = null;
    try { saved = localStorage.getItem(RACK_KEY); } catch { /* private mode */ }
    rackId = racks.some((r) => r.id === saved) ? saved : racks[0].id;
  }
  const built = modelBuildDevices(inRack(A.DATA.rack, racks, rackId), nodeById, readOvr());
  devices = built.devices;
  rackU = built.rackU;
}
const fits = (d, top) => modelFits(devices, rackU, d, top);
const faceplate = (d) => modelFaceplate(d, ledFor(d.node));


const rearHereBuilt = () => buildRear(inRack(A.DATA.rack_rear, racks, rackId), nodeById);

function pickRack(id) {
  rackId = id;
  try { localStorage.setItem(RACK_KEY, id); } catch { /* private mode */ }
  const was3d = view3d;
  if (was3d) backTo2d();
  render();
  if (was3d) goto3d();
}

/* The title says where the rack stands. The picker only appears with a second
   rack, and spells the place out only when the racks stand in different ones. */
function renderRackNav() {
  const here = racks.find((r) => r.id === rackId);
  if (titleEl) titleEl.textContent = rackTitle(here);
  const nav = $('rel-racks');
  if (!nav) return;
  nav.hidden = racks.length < 2;
  const oneSite = new Set(racks.map((r) => r.location)).size === 1;
  nav.innerHTML = racks.map((r) => {
    const on = r.id === rackId;
    return `<button class="rel-seg${on ? ' is-on' : ''}" data-rack="${esc(r.id)}" aria-pressed="${on}">` +
      `${esc(oneSite ? r.name : rackTitle(r))}</button>`;
  }).join('');
  for (const b of nav.querySelectorAll('[data-rack]')) {
    b.addEventListener('click', (e) => {
      e.stopPropagation();
      if (b.dataset.rack !== rackId) pickRack(b.dataset.rack);
    });
  }
}

function render() {
  buildDevices();
  renderRackNav();
  elevEl.style.height = (rackU * UH) + 'px';
  elevEl.innerHTML = '';
  const occ = new Set();
  devices.forEach((d) => { for (let u = d.top - d.size + 1; u <= d.top; u++) occ.add(u); });
  for (let u = rackU; u >= 1; u--) {
    const niche = document.createElement('div');
    niche.className = 'rel-niche' + (occ.has(u) ? ' filled' : '');
    niche.style.top = ((rackU - u) * UH) + 'px';
    niche.innerHTML = `<span class="rel-niche-u">${u}</span>`;
    elevEl.appendChild(niche);
  }
  for (const d of devices) {
    const el = document.createElement('div');
    el.className = `rel-dev rel-${d.kind}`;
    el.style.top = ((rackU - d.top) * UH) + 'px';
    el.style.height = (d.size * UH) + 'px';
    el.style.setProperty('--u-hue', KIND_HUE[d.kind] || '#C9A554');
    el.dataset.key = d.key;
    // The name is OFF the faceplate (2026-08-10). It was printed across
    // the drawn unit, which is the one part of this scene meant to be looked at
    // — twelve units meant twelve labels competing with the twelve pictures
    // underneath them. The U position stays, because that is *where the thing
    // is* and the whole point of an elevation. The name is still one hover or
    // one click away: `title` on the unit, and `rel-detail-name` in the pane.
    el.title = `${d.name} · ${uLabel(d.top, d.size)}`;
    el.innerHTML = faceplate(d) +
      `<span class="rel-dev-tag">` +
      `<span class="rel-dev-u">${esc(uLabel(d.top, d.size))}</span></span>` +
      `<span class="rel-grip" aria-hidden="true">⠿</span>`;
    el.addEventListener('click', () => {
      if (el.dataset.dragged) { delete el.dataset.dragged; return; }
      if (editing) return;
      select(d, el);
    });
    attachDrag(el, d);
    elevEl.appendChild(el);
  }
  const crown = devices.find((d) => d.slot.node === 'hypervisor') || devices[0];
  if (crown) {
    const cel = elevEl.querySelector(`.rel-dev[data-key="${crown.key}"]`);
    if (cel) cel.classList.add('active');
    showDetail(crown);
  } else {
    detailEl.innerHTML = '<p class="rel-detail-lore">This rack is empty.</p>';
  }
  renderRear();
}

function select(d, el) {
  for (const f of elevEl.querySelectorAll('.rel-dev')) f.classList.remove('active');
  el.classList.add('active');
  showDetail(d);
}

function showDetail(d) {
  const n = d.node, hue = KIND_HUE[d.kind] || '#C9A554';
  detailEl.style.setProperty('--rel-hue', hue);
  const role = n ? n.role : (d.desc || 'reserved');
  const ip = n && n.ip && n.ip !== '—' ? n.ip : '';
  const hw = n ? (n.hw || '') : '';
  const lore = n ? n.lore : '';
  /* THE SLOT'S OWN DESCRIPTION reaches the pane for EVERY vessel (the owner,
     2026-09-04: "the description of the selected item is not displaying").
     It used to stand in for the role and the hardware line ONLY when the slot
     was not a charted place — so on a charted rack every Description typed
     into the Desk went nowhere, and the one uncharted slot printed its twice
     (epigraph and hardware line). Now a charted vessel shows it as its own
     line under the seat — what THIS slot holds, in the surveyor's words,
     beside the place's own hardware — and an uncharted one, which already
     wears it as the epigraph, does not repeat it. */
  const desc = n ? (d.desc || '') : '';
  // rear vessels have no U — they hang behind the elevation (v1.34.0, §20a)
  const seat = d.rear ? 'rear of rack' : `${uLabel(d.top, d.size)} · ${d.size}U`;
  const data = [`<span>${esc(seat)}</span>`];
  if (ip) data.push(`<span>${esc(ip)}</span>`);
  if (desc && desc !== hw) data.push(`<span class="rel-detail-desc">${esc(desc)}</span>`);
  if (hw) data.push(`<span>${esc(hw)}</span>`);
  const links = (n?.links || []).map((l) =>
    `<a class="card-link" href="${esc(l.url)}" target="_blank" rel="noopener"` +
    `${glassAttrs(l.label, `a service of ${n.name}`, l.open_in)}>` +
    `<span class="ldot" style="background:${esc(l.hue)}"></span>${esc(l.label.toUpperCase())} ›</a>`).join('');

  /* §20a — THE FACEPLATE. A vessel whose ports are charted (`interfaces[]`,
     device = this node) grows a port strip in the SAME visual language as THE
     LEDGER's survey (`.ldg-port`, coloured by the port's realm), and every
     port answers a click with what hangs on its other end. This pane is
     shared by the 2D shelf and the 3D armory, so charting the second switch once
     lights the drilldown in both. Uncharted network iron (gateway/patch
     kinds) says so instead of drawing calm — the ports are a data question,
     and the lever is the Desk, not this code. */
  const ports = n ? (A.DATA.interfaces || []).filter((i) => i.device === n.id) : [];
  const faceplate = ports.length
    ? `<div class="rel-ports"><div class="rel-ports-head">the faceplate · ` +
      `${ports.length} port${ports.length === 1 ? '' : 's'} charted</div>` +
      `<div class="ldg-ports">` + ports.map((i, idx) => {
        const z = A.DATA.zones.find((zz) => String(zz.vlan) === String(i.vlan));
        return `<button type="button" class="ldg-port rel-port${i.poe ? ' poe' : ''}" ` +
          `data-port="${idx}" style="--p-hue:${esc(z?.hue || '#C9A554')}" ` +
          `title="what hangs on port ${esc(i.name)}?">${esc(i.name)}</button>`;
      }).join('') + `</div><div class="rel-port-detail" hidden></div></div>`
    : (n && ['gateway', 'switch', 'patch'].includes(d.kind)
        ? `<div class="rel-ports"><div class="ldg-note">no ports charted for this ` +
          `vessel yet — chart its <code>interfaces[]</code> in the map editor (PORTS) and ` +
          `the faceplate appears here, each port answering what hangs on it.</div></div>`
        : '');

  detailEl.innerHTML =
    `<div class="rel-detail-epi">${esc(d.rear ? 'rear' : uLabel(d.top, d.size))} · ${esc((role.split('·')[0] || '').trim())}</div>` +
    `<h3 class="rel-detail-name">${esc(d.name)}</h3>` +
    (lore ? `<p class="rel-detail-lore">${esc(lore)}</p>` : '') +
    `<div class="rel-detail-data">${data.join('')}</div>` +
    (links ? `<div class="rel-detail-links">${links}</div>` : '') +
    faceplate +
    (n ? `<button class="rel-map-btn" data-node="${esc(n.id)}">✦ Find on the map ›</button>` : '');
  const mb = detailEl.querySelector('.rel-map-btn');
  if (mb) mb.addEventListener('click', () => { close(); A.focusNode(mb.dataset.node); });

  /* port click → the other end of the wire. `peer` is prose by schema; when it
     names a charted place (by id or name, case-blind) the detail gains a
     fly-to. Clicking the selected port again folds the answer away. */
  const detailBox = detailEl.querySelector('.rel-port-detail');
  for (const pb of detailEl.querySelectorAll('.rel-port')) {
    pb.addEventListener('click', () => {
      const already = pb.classList.contains('selected');
      for (const other of detailEl.querySelectorAll('.rel-port.selected'))
        other.classList.remove('selected');
      if (already) { detailBox.hidden = true; return; }
      pb.classList.add('selected');
      const i = ports[Number(pb.dataset.port)];
      const z = A.DATA.zones.find((zz) => String(zz.vlan) === String(i.vlan));
      const peerText = String(i.peer || '').trim();
      const peerN = peerText && A.DATA.nodes.find((nn) =>
        nn.id.toLowerCase() === peerText.toLowerCase() ||
        String(nn.name || '').toLowerCase() === peerText.toLowerCase());
      const bits = [
        `port ${esc(i.name)}`,
        esc(i.kind || 'rj45'),
        z ? `${esc(z.name)} · vlan ${esc(z.vlan)}` : (i.vlan ? `vlan ${esc(i.vlan)}` : 'trunk'),
      ];
      if (i.speed) bits.push(esc(i.speed));
      if (i.poe) bits.push('PoE');
      detailBox.innerHTML =
        `<span class="rel-port-facts">${bits.join(' · ')}</span>` +
        `<span class="rel-port-peer">${peerText
          ? `→ ${esc(peerText)}` : '→ nothing charted on the other end'}</span>` +
        (i.note ? `<span class="rel-port-note">${esc(i.note)}</span>` : '') +
        (peerN ? `<button type="button" class="rel-map-btn rel-peer-btn" ` +
                 `data-node="${esc(peerN.id)}">✦ Fly to ${esc(peerN.name)} ›</button>` : '');
      detailBox.hidden = false;
      const fly = detailBox.querySelector('.rel-peer-btn');
      if (fly) fly.addEventListener('click', () => { close(); A.focusNode(fly.dataset.node); });
    });
  }
}

function renderRear() {
  const rear = rearHereBuilt();
  let rearEl = rackEl.querySelector('.rel-rear');
  if (rearEl) rearEl.remove();
  if (!rear.length) return;
  rearEl = document.createElement('div');
  rearEl.className = 'rel-rear';
  rearEl.innerHTML = '<span class="rel-rear-label">rear of rack</span>' +
    rear.map((r, idx) => `<button class="rel-rear-item" data-rear="${idx}">` +
      `<span class="rel-rear-name">${esc(r.name)}</span>` +
      `<span class="rel-rear-desc">${esc(r.desc || '')}</span></button>`).join('');
  rackEl.appendChild(rearEl);
  /* A rear vessel used to fly straight to the map. It opens the SAME detail
     pane as a front vessel now (v1.34.0, §20a) — a rear-mounted switch is
     exactly where the faceplate matters most — and the ✦ button inside the
     pane still offers the map for the charted ones. */
  for (const b of rearEl.querySelectorAll('.rel-rear-item')) {
    b.addEventListener('click', () => {
      const r = rear[Number(b.dataset.rear)];
      if (!r) return;
      if (view3d) A.armory3d.select(r.key);   // the scene picks it, and picks open the pane
      else showDetail(r);
    });
    b.addEventListener('pointerenter', () => { if (view3d) A.armory3d.hover(rear[Number(b.dataset.rear)]?.key); });
    b.addEventListener('pointerleave', () => { if (view3d) A.armory3d.hover(null); });
  }
}

function attachDrag(el, d) {
  el.addEventListener('pointerdown', (e) => {
    if (!editing) return;
    e.preventDefault(); e.stopPropagation();
    el.setPointerCapture(e.pointerId);
    el.classList.add('grabbing');
    const startY = e.clientY, origPx = (rackU - d.top) * UH, maxPx = (rackU - d.size) * UH;
    let curTop = d.top;
    const move = (ev) => {
      let px = Math.max(0, Math.min(maxPx, origPx + (ev.clientY - startY)));
      el.style.top = px + 'px';
      el.dataset.dragged = '1';
      curTop = Math.max(d.size, Math.min(rackU, rackU - Math.round(px / UH)));
      el.classList.toggle('blocked', !fits(d, curTop));
    };
    const up = () => {
      try { el.releasePointerCapture(e.pointerId); } catch { /* */ }
      el.classList.remove('grabbing', 'blocked');
      el.removeEventListener('pointermove', move);
      el.removeEventListener('pointerup', up);
      if (fits(d, curTop) && curTop !== d.top) {
        d.top = curTop; d.slot.u = uLabel(curTop, d.size);
        const o = readOvr(); o[d.key] = curTop; writeOvr(o);
        A.showToast?.(`${d.name} moved to ${uLabel(curTop, d.size)} — Save to keep it.`);
      }
      render();
    };
    el.addEventListener('pointermove', move);
    el.addEventListener('pointerup', up);
  });
}

function setEditing(on) {
  editing = on;
  root.classList.toggle('editing', on);
  $('rel-edit')?.classList.toggle('on', on);
  const save = $('rel-save'), reset = $('rel-reset');
  if (save) save.hidden = !on;
  if (reset) reset.hidden = !on;
  if (on) A.showToast?.('Rearrange the rack — drag any vessel to a free slot, then Save.');
}

async function saveLayout() {
  const o = readOvr();
  if (!Object.keys(o).length) { A.showToast?.('Nothing moved yet.'); return; }
  try {
    const r = await fetch('api/v2/rack', {
      method: 'POST',
      // X-Atlas-Write is what proves this came from the Atlas and not another
      // origin — a cross-site page cannot set it (see Web/security.py)
      headers: { 'Content-Type': 'application/json', 'X-Atlas-Write': '1' },
      body: JSON.stringify(o),
    });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.status);
    const res = await r.json();
    localStorage.removeItem(OVR_KEY);
    A.showToast?.(`Saved the rack — ${res.saved} ${res.saved === 1 ? 'vessel' : 'vessels'}, for everyone.`);
  } catch (err) {
    A.showToast?.(`Could not save: ${err.message || err}`);
  }
}

function resetLayout() { localStorage.removeItem(OVR_KEY); location.reload(); }

// ── 2D ⇄ 3D (the RACKS deep-dive) ───────────────────────────────────────────
// The 3D view is armory3d.js, lazy-imported on first request so the ~1 MB three
// vendor only loads when someone asks for it — and so a missing/broken vendor
// can never take down the 2D elevation (the core app never imports it). The
// detail pane is shared: a pick in 3D calls the same showDetail().
let view3d = false, rel3dEl = null, legendEl = null;
const ledStateFor = (node) => (node ? (A.signalsFeed?.nodes?.[node.id]?.state || '') : '');

/* THE LEGEND: names stay off the faceplates (see render()), so in 3D they sit
   here, top of the rack first. It is also the keyboard's way into the scene,
   which a canvas alone does not offer. */
function renderLegend() {
  legendEl.innerHTML = [...devices].sort((a, b) => b.top - a.top).map((d) =>
    `<button type="button" class="rel-legend-item" data-key="${esc(d.key)}">` +
    `<span class="rel-dev-u">${esc(uLabel(d.top, d.size))}</span>${esc(d.name)}</button>`).join('');
  for (const b of legendEl.querySelectorAll('.rel-legend-item')) {
    b.addEventListener('click', () => A.armory3d.select(b.dataset.key));
    for (const ev of ['pointerenter', 'focus'])
      b.addEventListener(ev, () => A.armory3d.hover(b.dataset.key));
    for (const ev of ['pointerleave', 'blur'])
      b.addEventListener(ev, () => A.armory3d.hover(null));
  }
}
const markLegend = (cls, key) => {
  for (const b of legendEl.querySelectorAll('.rel-legend-item'))
    b.classList.toggle(cls, b.dataset.key === key);
};

function setCamButton(name) {
  for (const b of document.querySelectorAll('.rel-cam')) {
    const on = b.dataset.view === name;
    b.classList.toggle('is-on', on);
    b.setAttribute('aria-pressed', String(on));
  }
}

function setSeg(on3d) {
  const b2 = $('rel-2d'), b3 = $('rel-3d-btn');
  b2?.classList.toggle('is-on', !on3d); b2?.setAttribute('aria-pressed', String(!on3d));
  b3?.classList.toggle('is-on', on3d);  b3?.setAttribute('aria-pressed', String(on3d));
}

function backTo2d() {
  view3d = false;
  A.armory3d?.exit();
  if (rel3dEl) rel3dEl.hidden = true;
  if (legendEl) legendEl.hidden = true;
  if (elevEl) elevEl.hidden = false;
  $('rel-edit')?.removeAttribute('hidden');
  setSeg(false);
}

async function goto3d() {
  try { await import('./armory3d.js'); }
  catch { A.showToast?.('Could not load the 3D view.'); return; }
  if (!A.armory3d?.available()) {
    A.showToast?.('3D is unavailable on this device — showing the elevation.');
    return;
  }
  setEditing(false);
  if (!devices.length) buildDevices();
  view3d = true;
  if (elevEl) elevEl.hidden = true;
  $('rel-edit')?.setAttribute('hidden', '');     // no drag-rearrange in 3D v1
  rel3dEl.hidden = false;                          // must be laid out before enter reads its size
  legendEl.hidden = false;
  renderLegend();
  setCamButton('corner');
  setSeg(true);
  const ok = A.armory3d.enter({
    container: rel3dEl,
    model: { devices, rackU, rear: rearHereBuilt() },
    ledStateFor,
    onPick: (d) => { showDetail(d); markLegend('is-on', d.key); },
    onHover: (key) => markLegend('is-hover', key),
    onTurn: () => setCamButton(''),
    onLost: () => { A.showToast?.('The 3D view was lost — back to the elevation.'); backTo2d(); },
  });
  if (!ok) { A.showToast?.('Could not start 3D — showing the elevation.'); backTo2d(); }
}

const scene = makeScene({ id: 'reliquary', closeId: 'rel-close', build: () => render(),
  onClose: () => { setEditing(false); backTo2d(); } });
const { open, close } = scene;
A.openReliquary = open;
A.closeReliquary = close;

A.buildReliquary = function buildReliquary() {
  root = scene.mount();
  if (!root) return;
  titleEl = $('rel-title');
  elevEl = $('rel-elevation');
  detailEl = $('rel-detail');
  rackEl = elevEl.parentElement;
  $('rel-edit')?.addEventListener('click', (e) => { e.stopPropagation(); setEditing(!editing); });
  $('rel-save')?.addEventListener('click', (e) => { e.stopPropagation(); saveLayout(); });
  $('rel-reset')?.addEventListener('click', (e) => { e.stopPropagation(); resetLayout(); });
  rel3dEl = $('rel-3d');
  legendEl = $('rel-3d-legend');
  for (const b of root.querySelectorAll('.rel-cam')) {
    b.addEventListener('click', (e) => {
      e.stopPropagation();
      setCamButton(b.dataset.view);
      A.armory3d?.view(b.dataset.view);
    });
  }
  $('rel-2d')?.addEventListener('click', (e) => { e.stopPropagation(); if (view3d) backTo2d(); });
  $('rel-3d-btn')?.addEventListener('click', (e) => { e.stopPropagation(); if (!view3d) goto3d(); });
  window.addEventListener('resize', () => { if (view3d) A.armory3d?.resize(); });
};
