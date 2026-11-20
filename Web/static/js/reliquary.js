/* Atlas — HARDWARE (was RACKS, THE ARMORY, THE RELIQUARY): each physical rack as an
   illuminated front-elevation with hardware-accurate engraved faceplates. Every
   vessel sits in a true U-slot; in Rearrange mode you can drag one to a free slot
   and Save the layout (persisted server-side via api/v2/rack, exactly like the map's
   moved dots). Rebuilt 2026-07-20. Titled by place since 2026-10-31:
   `Server room — Rack A`, with a picker when the lab charts more than one.
   The rack model + faceplate art moved to rack-model.js 2026-08-23 so the 3D
   deep-dive (armory3d.js) draws the same vessels from the same source (F5).

   HARDWARE, BY LOCATION (2026-11-20; owner: "adjust 'Racks' to say 'Hardware'
   and include any kind of compute iOT raspberry pi, etc.", "it should show a
   drop down of locations"). The scene shows every location or one. Its racks
   are the racks that stand there, and under them is a shelf, NOT IN A RACK:
   the machines that stand outside one (a single-board computer, an access
   point, a desk machine), which no elevation could ever show. A location may
   have a shelf and no rack at all. What a location is, and what counts as
   hardware outside a rack, is locations-model.js.

   ADD AND REMOVE (2026-11-20; owner: "add an add button next to arrange that
   will let you pick from a device, then you can drag it up and down in the
   rack", "the ability to add remove any of the things that are in there
   now"). Add puts a place from the map, or something that is not on it (a
   panel, a shelf), into the rack on screen at the highest free seat, and
   turns Rearrange on so it can be dragged from there. In Rearrange every
   vessel, front or rear, has a ✕ that takes it out of the rack; the place it
   stood for stays on the map and moves to the shelf. Both are changes to the
   map itself, written through the editor's own store (editor/store.js), so
   each is in the change log and can be undone there; a drag is still the
   rack's saved layout (Save). Where the viewer may not write, Add, ✕ and
   Save are drawn off and say why. */

import { A, CFG, $, esc, glassAttrs, nodeById, FALLBACK_HUE, DRAG_END, postJSON, canAdminWrite } from './config.js';
import { makeScene } from './scene.js';
import { locationByKey, locationOfRack, looseAt, rackable, racksAt } from './locations-model.js';
import { drawPlacePicker, markPlace, placeName, whereNow } from './scene-places.js';
import {
  UH, KIND_HUE, ledColor, uLabel, setRackTheme,
  buildDevices as modelBuildDevices, buildRear, fits as modelFits, faceplate as modelFaceplate,
  rackList, rackTitle, inRack, crownOf, peerNode, kindOf, freeTop, slotKey,
} from './rack-model.js';
setRackTheme(CFG.THEME);   // THE THEME (v1.48.0): which lab names are the gateway / the forge

const OVR_KEY = 'atlas-rack-overrides';   // { slotKey: topU } — per-browser, pre-Save
const RACK_KEY = 'atlas-rack-current';    // which rack this browser last looked at

let root, elevEl, detailEl, titleEl, rackEl;
let editing = false;
let devices = [], rackU = 12;
/* `allRacks` is every rack on the map, in the map's order (an unset or unknown
   `rack` on a slot means the first of THESE); `racks` is the ones at the
   location shown, which is all the picker offers. `rackId` is null where the
   location shown has no rack at all, only a shelf. */
let racks = [], allRacks = [], rackId = null;
/** The location shown; '' is every location. */
let place = '';
let where = null, loc = null;

const ledFor = (node) => ledColor(node ? A.signalsFeed?.nodes?.[node.id]?.state : '');

const readOvr = () => { try { return JSON.parse(localStorage.getItem(OVR_KEY) || '{}'); } catch { return {}; } };
const writeOvr = (o) => { try { localStorage.setItem(OVR_KEY, JSON.stringify(o)); } catch { /* private mode */ } };

// These thin wrappers keep this module's `devices`/`rackU` state and bind the
// live LED feed; the pure model + SVG art are in rack-model.js.
function buildDevices() {
  where = whereNow();
  loc = locationByKey(where, place);
  if (!loc) place = '';
  markPlace('rack', place);
  allRacks = rackList(A.DATA.racks, CFG.THEME?.text?.rack_location);
  racks = racksAt(where, loc);
  if (!racks.length) { rackId = null; devices = []; rackU = 1; return; }
  if (!racks.some((r) => r.id === rackId)) {
    let saved = null;
    try { saved = localStorage.getItem(RACK_KEY); } catch { /* private mode */ }
    rackId = racks.some((r) => r.id === saved) ? saved : racks[0].id;
  }
  // the band's menu marks the rack on show only where the location has a choice of them
  markPlace('rack', place, racks.length > 1 ? rackId : null);
  const built = modelBuildDevices(inRack(A.DATA.rack, allRacks, rackId), nodeById, readOvr());
  devices = built.devices;
  rackU = built.rackU;
}
const fits = (d, top) => modelFits(devices, rackU, d, top);
const faceplate = (d) => modelFaceplate(d, ledFor(d.node));


const rearHereBuilt = () => (rackId === null ? []
  : buildRear(inRack(A.DATA.rack_rear, allRacks, rackId), nodeById));

function pickRack(id) {
  openAddBox(false);
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
  // a location with a shelf and no rack is titled by the location alone
  if (titleEl) titleEl.textContent = here ? rackTitle(here) : placeName(loc);
  drawPlacePicker($('rel-places'), 'rack', place, (key) => setPlace(key));
  // what only a rack has: the two views of it, and rearranging it
  for (const id of ['rel-view', 'rel-edit', 'rel-add']) $(id)?.toggleAttribute('hidden', !here || (id !== 'rel-view' && view3d));
  if (!here) openAddBox(false);
  paintWrites();
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
  const shelved = renderShelf();
  root.classList.toggle('no-rack', rackId === null);
  if (rackId === null) {
    // nothing stands in a rack here: the shelf is the whole of it
    elevEl.innerHTML = '';
    rackEl.querySelector('.rel-rear:not(.rel-shelf)')?.remove();
    if (shelved.length) showDetail(shelved[0]);
    else detailEl.innerHTML = '<p class="rel-detail-lore">No hardware is charted here.</p>';
    return;
  }
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
    el.style.setProperty('--u-hue', KIND_HUE[d.kind] || FALLBACK_HUE);
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
    if (mayWrite()) el.appendChild(removeButton(d));   // shown in Rearrange (atlas.css)
    elevEl.appendChild(el);
  }
  const crown = crownOf(devices);
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
  const n = d.node, hue = KIND_HUE[d.kind] || FALLBACK_HUE;
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
  // rear vessels have no U — they hang behind the elevation (v1.34.0, §20a);
  // neither has a machine that stands outside a rack (2026-11-20)
  const seat = d.loose ? `not in a rack · ${d.where}`
    : d.rear ? 'rear of rack' : `${uLabel(d.top, d.size)} · ${d.size}U`;
  const data = [`<span>${esc(seat)}</span>`];
  if (ip) data.push(`<span>${esc(ip)}</span>`);
  if (desc && desc !== hw) data.push(`<span class="rel-detail-desc">${esc(desc)}</span>`);
  if (hw) data.push(`<span>${esc(hw)}</span>`);
  const links = (n?.links || []).filter((l) => l?.url).map((l) =>
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
          `data-port="${idx}" style="--p-hue:${esc(z?.hue || FALLBACK_HUE)}" ` +
          `title="what hangs on port ${esc(i.name)}?">${esc(i.name)}</button>`;
      }).join('') + `</div><div class="rel-port-detail" hidden></div></div>`
    : (n && ['gateway', 'switch', 'patch'].includes(d.kind)
        ? `<div class="rel-ports"><div class="ldg-note">no ports charted for this ` +
          `vessel yet — chart its <code>interfaces[]</code> in the map editor (PORTS) and ` +
          `the faceplate appears here, each port answering what hangs on it.</div></div>`
        : '');

  detailEl.innerHTML =
    `<div class="rel-detail-epi">${esc(d.loose ? d.where : d.rear ? 'rear' : uLabel(d.top, d.size))} · ${esc((role.split('·')[0] || '').trim())}</div>` +
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
      const peerN = peerNode(A.DATA.nodes, peerText);
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
  let rearEl = rackEl.querySelector('.rel-rear:not(.rel-shelf)');   // the shelf wears the class too
  if (rearEl) rearEl.remove();
  if (!rear.length) return;
  rearEl = document.createElement('div');
  rearEl.className = 'rel-rear';
  rearEl.innerHTML = '<span class="rel-rear-label">rear of rack</span>' +
    rear.map((r, idx) => `<span class="rel-rear-seat"><button class="rel-rear-item" data-rear="${idx}">` +
      `<span class="rel-rear-name">${esc(r.name)}</span>` +
      `<span class="rel-rear-desc">${esc(r.desc || '')}</span></button></span>`).join('');
  rackEl.insertBefore(rearEl, rackEl.querySelector('.rel-shelf'));   // the shelf stays last
  if (mayWrite()) rearEl.querySelectorAll('.rel-rear-seat').forEach((seat, idx) => seat.appendChild(removeButton(rear[idx])));
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

/* NOT IN A RACK (2026-11-20): the machines at the location shown that stand
   outside a rack, as one strip under the rack in the rear strip's own dress.
   Each opens the same detail pane a vessel does. Returns them as the pane
   takes them, so a location with no rack can open on the first. */
function renderShelf() {
  rackEl.querySelector('.rel-shelf')?.remove();
  const everywhere = !loc && where.list.length > 1;
  const loose = looseAt(where, loc).map(({ node, location }) => ({
    slot: {}, key: `loose:${node.id}`, node, name: node.name, desc: '', loose: true,
    where: placeName(location), size: 0, top: 0, kind: kindOf({ name: node.name }, node),
  }));
  if (!loose.length) return loose;
  const el = document.createElement('div');
  el.className = 'rel-rear rel-shelf';
  el.innerHTML = '<span class="rel-rear-label">not in a rack</span>' +
    loose.map((d, idx) => `<button class="rel-rear-item" data-loose="${idx}">` +
      `<span class="rel-rear-name">${esc(d.name)}</span>` +
      `<span class="rel-rear-desc">${esc([everywhere ? d.where : '', d.node.hw || d.node.role || ''].filter(Boolean).join(' · '))}</span></button>`).join('');
  rackEl.appendChild(el);
  for (const b of el.querySelectorAll('[data-loose]')) {
    b.addEventListener('click', () => {
      for (const f of elevEl.querySelectorAll('.rel-dev')) f.classList.remove('active');
      showDetail(loose[Number(b.dataset.loose)]);
    });
  }
  return loose;
}

/** Show one location ('' = every location), and one rack at it when one is
    asked for (the band's menu lists the racks under their locations); drawn
    at once when the scene is up. */
function setPlace(key, askedRack = null) {
  place = key || '';
  const stands = place ? locationOfRack(whereNow(), askedRack) : null;
  if (stands) {
    place = stands.key;          // a rack is shown at its own location, whatever came with it
    rackId = askedRack;
    try { localStorage.setItem(RACK_KEY, askedRack); } catch { /* private mode */ }
  }
  markPlace('rack', place);
  if (!root?.classList.contains('open')) return;
  setEditing(false);
  openAddBox(false);
  if (view3d) backTo2d();
  render();
}

/* ── add and remove ──────────────────────────────────────────────────────── */

const mayWrite = () => canAdminWrite() && document.body.dataset.editable === '1';
const WRITE_WHY = 'Add, remove and Save are off here: they need an admin, on an Atlas that takes changes.';

/** The editor's store, read fresh: its `data` is the map as it is on disk
    (what this scene draws is overlaid with the saved layout), and its stamp
    is what makes a write refuse a map that changed underneath it. */
async function editorStore() {
  const { Editor } = await import('./editor/index.js');
  await Editor.load();
  return Editor;
}

/** Which rack a raw slot is in, as the scene reads it (unset or unknown: the first). */
const rackOf = (slot) => (allRacks.some((r) => r.id === slot.rack) ? slot.rack : allRacks[0].id);

function paintWrites() {
  const can = mayWrite();
  const add = $('rel-add'), save = $('rel-save'), why = $('rel-why');
  if (add) { add.disabled = !can; add.title = can ? 'Put a device in this rack' : WRITE_WHY; }
  if (save) { save.disabled = !can; save.title = can ? '' : WRITE_WHY; }
  if (why) { why.textContent = can ? '' : `${WRITE_WHY} A drag still tries a layout out; it stays in this browser.`; why.hidden = can || !editing; }
}

function openAddBox(on) {
  const box = $('rel-addbox');
  if (!box) return;
  box.hidden = !on;
  $('rel-add')?.classList.toggle('on', on);
  if (!on) return;
  const here = racks.find((r) => r.id === rackId);
  $('rel-add-to').textContent = here ? rackTitle(here) : '';
  const option = (n) => {
    const at = where.ofNode.get(n.id);
    const said = at !== undefined && where.list.length > 1 ? ` · ${placeName(where.list.find((l) => l.key === at))}` : '';
    return `<option value="${esc(n.id)}">${esc(n.name)}${esc(said)}</option>`;
  };
  // the machines first; a place of another kind may be a box (a switch) or an
  // idea (the internet), so those stand apart and are the picker's to judge
  const can = rackable(A.DATA, where);
  const group = (label, list) => (list.length ? `<optgroup label="${label}">${list.map(option).join('')}</optgroup>` : '');
  $('rel-add-what').innerHTML = group('Machines', can.filter((n) => n.kind === 'physical'))
    + group('Other places on the map', can.filter((n) => n.kind !== 'physical'))
    + '<option value="">Something that is not on the map…</option>';
  $('rel-add-name').value = '';
  $('rel-add-msg').textContent = '';
  paintAddName();
  $('rel-add-what').focus();
}
const paintAddName = () => { $('rel-add-name-wrap').hidden = $('rel-add-what').value !== ''; };

async function addVessel() {
  const msg = $('rel-add-msg');
  const say = (text) => { msg.textContent = text; };
  const node = $('rel-add-what').value ? nodeById($('rel-add-what').value) : null;
  const name = (node ? node.name : $('rel-add-name').value).trim().replace(/\s+/g, ' ');
  const size = Math.max(1, Math.min(12, parseInt($('rel-add-size').value, 10) || 1));
  if (!name) { say('Give it a name.'); $('rel-add-name').focus(); return; }
  const here = racks.find((r) => r.id === rackId);
  if (!here) return;
  // the seat is found on the layout as it is SAVED: with moves waiting, the
  // one on screen is a draft, and the map would be told a seat the draft freed
  if (Object.keys(readOvr()).length) { say('Save or Reset the moves you have made first, then add.'); return; }
  const top = freeTop(devices, rackU, size);
  const body = { u: uLabel(top, size), name, size };
  if (rackId) body.rack = rackId;
  if (node) body.node = node.id;
  // a vessel is known by its place, else by its name in its rack: two of one
  // name would be moved, and removed, as one
  const key = slotKey(body);
  if ((A.DATA.rack || []).some((s) => slotKey(s) === key)) {
    say(node ? `${name} is in a rack already.` : `This rack already has a "${name}". Give it another name.`);
    return;
  }
  const go = $('rel-add-go');
  go.disabled = true;
  try {
    const store = await editorStore();
    await store.apply([{ op: 'insert', section: 'rack', body }], `put ${name} in ${rackTitle(here)} (HARDWARE)`);
    openAddBox(false);
    render();
    setEditing(true);
    const el = elevEl.querySelector(`.rel-dev[data-key="${CSS.escape(key)}"]`);
    const d = devices.find((x) => x.key === key);
    if (el && d) select(d, el);
    A.showToast?.(`${name} is in at ${uLabel(top, size)}. Drag it to its seat, then Save.`);
  } catch (err) {
    say(`Not added: ${err.message || err}`);
  } finally {
    go.disabled = false;
  }
}

/** Take a vessel out of the rack: a front slot or a rear fitting. The place
    it stood for stays on the map. Where the map names the rack's location
    and the place named none, the place is told it, so it is found on that
    location's shelf; nothing is written where the location is only the
    default one. */
async function removeVessel(d) {
  const here = racks.find((r) => r.id === rackId);
  try {
    const store = await editorStore();
    const section = d.rear ? 'rack_rear' : 'rack';
    const raw = (store.data[section] || []).map((slot, index) => ({ slot, index }))
      .filter((x) => x.slot && rackOf(x.slot) === rackId);
    const hit = d.rear
      ? raw[Number(d.key.slice('rear:'.length))]
      : raw.find((x) => slotKey(x.slot) === d.key);
    if (!hit || hit.slot.name !== d.name) throw new Error('the map has changed; look again and retry');
    const ops = [{ op: 'delete', section, index: hit.index, ...(d.rear ? {} : { id: d.key }) }];
    // told where it stands only when the MAP names the rack's location: a rack
    // that names none is at the default one, and so is a place that names none
    const node = d.node && (store.data.nodes || []).find((n) => n.id === d.node.id);
    const written = String((store.data.racks || []).find((r) => r && r.id === rackId)?.location || '').trim();
    if (node && !String(node.location || '').trim() && written) {
      ops.push({ op: 'upsert', section: 'nodes', id: node.id, body: { location: written } });
    }
    await store.apply(ops, `took ${d.name} out of ${here ? rackTitle(here) : 'the rack'} (HARDWARE)`);
    const o = readOvr();
    if (d.key in o) { delete o[d.key]; writeOvr(o); }
    render();
    A.showToast?.(d.node ? `${d.name} is out of the rack. It is still on the map.` : `${d.name} is out of the rack.`);
  } catch (err) {
    A.showToast?.(`Not removed: ${err.message || err}`);
    render();
  }
}

/** The ✕ a vessel wears in Rearrange. Two presses: the first asks. */
function removeButton(d) {
  const b = document.createElement('button');
  b.type = 'button';
  b.className = 'rel-remove';
  b.textContent = '✕';
  b.title = `Take ${d.name} out of the rack`;
  b.setAttribute('aria-label', b.title);
  let armed = 0;
  // never the start of a drag, and never a pick of the vessel under it
  b.addEventListener('pointerdown', (e) => e.stopPropagation());
  b.addEventListener('click', (e) => {
    e.stopPropagation();
    if (!armed) {
      b.textContent = 'Take out?';
      b.classList.add('armed');
      armed = setTimeout(() => { armed = 0; b.textContent = '✕'; b.classList.remove('armed'); }, 4000);
      return;
    }
    clearTimeout(armed);
    b.disabled = true;
    removeVessel(d);
  });
  return b;
}

function attachDrag(el, d) {
  el.addEventListener('pointerdown', (e) => {
    delete el.dataset.dragged;   // a cancelled drag leaves no mark (the 11-12 audit's Map 12, as regions.js)
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
      for (const t of DRAG_END) el.removeEventListener(t, up);
      if (fits(d, curTop) && curTop !== d.top) {
        d.top = curTop; d.slot.u = uLabel(curTop, d.size);
        const o = readOvr(); o[d.key] = curTop; writeOvr(o);
        A.showToast?.(`${d.name} moved to ${uLabel(curTop, d.size)} — Save to keep it.`);
      }
      render();
    };
    el.addEventListener('pointermove', move);
    for (const t of DRAG_END) el.addEventListener(t, up);   // cancel and lost capture end it too
  });
}

function setEditing(on) {
  editing = on;
  root.classList.toggle('editing', on);
  $('rel-edit')?.classList.toggle('on', on);
  const save = $('rel-save'), reset = $('rel-reset');
  if (save) save.hidden = !on;
  if (reset) reset.hidden = !on;
  paintWrites();
  if (on) A.showToast?.('Rearrange the rack — drag any vessel to a free slot, then Save.');
}

async function saveLayout() {
  const o = readOvr();
  if (!Object.keys(o).length) { A.showToast?.('Nothing moved yet.'); return; }
  try {
    const r = await postJSON('api/v2/rack', o);   // carries the write proof (config.js)
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.status);
    const res = await r.json();
    localStorage.removeItem(OVR_KEY);
    A.showToast?.(`Saved the rack — ${res.saved} ${res.saved === 1 ? 'vessel' : 'vessels'}, for everyone.`);
  } catch (err) {
    A.showToast?.(`Could not save: ${err.message || err}`);
  }
}

function resetLayout() { localStorage.removeItem(OVR_KEY); location.reload(); }

// ── 2D ⇄ 3D (the rack's deep-dive) ──────────────────────────────────────────
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
  if (rackId !== null) for (const id of ['rel-edit', 'rel-add']) $(id)?.removeAttribute('hidden');
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
  for (const id of ['rel-edit', 'rel-add']) $(id)?.setAttribute('hidden', '');   // no rearranging, and no adding, in 3D v1
  openAddBox(false);
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
  // closed, the scene goes back to every location: HARDWARE pressed afresh is all of it
  onClose: () => { setEditing(false); openAddBox(false); backTo2d(); place = ''; markPlace('rack', ''); } });
const { open, close } = scene;
A.openReliquary = open;
A.closeReliquary = close;
// the band's menu of locations, and a press on HARDWARE while one is shown
addEventListener('atlas:scene-place', (e) => { if (e.detail?.scene === 'rack') setPlace(e.detail.place, e.detail.rack); });

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
  $('rel-add')?.addEventListener('click', (e) => {
    e.stopPropagation();
    if (!$('rel-add').disabled) openAddBox($('rel-addbox').hidden);
  });
  $('rel-add-what')?.addEventListener('change', paintAddName);
  $('rel-add-go')?.addEventListener('click', (e) => { e.stopPropagation(); addVessel(); });
  $('rel-add-cancel')?.addEventListener('click', (e) => { e.stopPropagation(); openAddBox(false); });
  // Enter in the box adds; its keys are not the map's
  $('rel-addbox')?.addEventListener('keydown', (e) => {
    e.stopPropagation();
    if (e.key === 'Enter' && e.target.id !== 'rel-add-cancel') { e.preventDefault(); addVessel(); }
    else if (e.key === 'Escape') openAddBox(false);
  });
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
