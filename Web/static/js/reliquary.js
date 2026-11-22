
import { A, CFG, $, esc, glassAttrs, nodeById, FALLBACK_HUE, DRAG_END, postJSON, canAdminWrite } from './config.js';
import { makeScene } from './scene.js';
import { locationByKey, looseAt, rackable, racksAt } from './locations-model.js';
import { setLocation } from './location-set.js';
import { DEVICE_GROUPS, SEATS, addBody, addName, typeById } from './hardware-catalog.js';
import { drawPlacePicker, markPlace, placeName, whereNow } from './scene-places.js';
import {
  UH, KIND_HUE, ledColor, uLabel, setRackTheme,
  buildDevices as modelBuildDevices, buildRear, fits as modelFits, faceplate as modelFaceplate,
  rackList, rackTitle, inRack, crownOf, peerNode, kindOf, freeTop, slotKey,
} from './rack-model.js';
setRackTheme(CFG.THEME);

const OVR_KEY = 'atlas-rack-overrides';
const RACK_KEY = 'atlas-rack-current';

let root, elevEl, detailEl, titleEl, rackEl;
let editing = false;
let devices = [], rackU = 12;
let racks = [], allRacks = [], rackId = null;
let place = '';
let where = null, loc = null;

const ledFor = (node) => ledColor(node ? A.signalsFeed?.nodes?.[node.id]?.state : '');

const readOvr = () => { try { return JSON.parse(localStorage.getItem(OVR_KEY) || '{}'); } catch { return {}; } };
const writeOvr = (o) => { try { localStorage.setItem(OVR_KEY, JSON.stringify(o)); } catch {   } };

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
    try { saved = localStorage.getItem(RACK_KEY); } catch {   }
    rackId = racks.some((r) => r.id === saved) ? saved : racks[0].id;
  }
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
  try { localStorage.setItem(RACK_KEY, id); } catch {   }
  const was3d = view3d;
  if (was3d) backTo2d();
  render();
  if (was3d) goto3d();
}

function renderRackNav() {
  const here = racks.find((r) => r.id === rackId);
  if (titleEl) titleEl.textContent = here ? rackTitle(here) : placeName(loc);
  drawPlacePicker($('rel-places'), 'rack', place, (key) => setPlace(key));
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
  shown = null;
  buildDevices();
  renderRackNav();
  const shelved = renderShelf();
  root.classList.toggle('no-rack', rackId === null);
  if (rackId === null) {
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
    if (mayWrite()) el.appendChild(removeButton(d));
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

let shown = null;

function select(d, el) {
  for (const f of elevEl.querySelectorAll('.rel-dev')) f.classList.remove('active');
  el.classList.add('active');
  showDetail(d);
}

function showDetail(d) {
  shown = d;
  const n = d.node, hue = KIND_HUE[d.kind] || FALLBACK_HUE;
  detailEl.style.setProperty('--rel-hue', hue);
  const role = n ? n.role : (d.desc || 'reserved');
  const ip = n && n.ip && n.ip !== '—' ? n.ip : '';
  const hw = n ? (n.hw || '') : '';
  const lore = n ? n.lore : '';
  const desc = n ? (d.desc || '') : '';
  const seat = d.loose ? `not in a rack · ${d.where}`
    : d.rear ? (d.slot?.side === 'inside' ? 'inside the rack' : 'rear of rack') : `${uLabel(d.top, d.size)} · ${d.size}U`;
  const data = [`<span>${esc(seat)}</span>`];
  if (ip) data.push(`<span>${esc(ip)}</span>`);
  if (desc && desc !== hw) data.push(`<span class="rel-detail-desc">${esc(desc)}</span>`);
  if (hw) data.push(`<span>${esc(hw)}</span>`);
  const links = (n?.links || []).filter((l) => l?.url).map((l) =>
    `<a class="card-link" href="${esc(l.url)}" target="_blank" rel="noopener"` +
    `${glassAttrs(l.label, `a service of ${n.name}`, l.open_in)}>` +
    `<span class="ldot" style="background:${esc(l.hue)}"></span>${esc(l.label.toUpperCase())} ›</a>`).join('');

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
  let rearEl = rackEl.querySelector('.rel-rear:not(.rel-shelf)');
  if (rearEl) rearEl.remove();
  if (!rear.length) return;
  rearEl = document.createElement('div');
  rearEl.className = 'rel-rear';
  const seat = (r, idx) => `<span class="rel-rear-seat"><button class="rel-rear-item" data-rear="${idx}">` +
    `<span class="rel-rear-name">${esc(r.name)}</span>` +
    `<span class="rel-rear-desc">${esc(r.desc || '')}</span></button></span>`;
  const half = (label, inside) => {
    const seats = rear.map((r, idx) => ((r.slot?.side === 'inside') === inside ? seat(r, idx) : '')).join('');
    return seats ? `<span class="rel-rear-label">${label}</span>${seats}` : '';
  };
  rearEl.innerHTML = half('rear of rack', false) + half('inside the rack', true);
  rackEl.insertBefore(rearEl, rackEl.querySelector('.rel-shelf'));
  if (mayWrite()) rearEl.querySelectorAll('.rel-rear-seat').forEach((el) => el.appendChild(removeButton(rear[Number(el.querySelector('[data-rear]').dataset.rear)])));
  for (const b of rearEl.querySelectorAll('.rel-rear-item')) {
    b.addEventListener('click', () => {
      const r = rear[Number(b.dataset.rear)];
      if (!r) return;
      if (view3d) A.armory3d.select(r.key);
      else showDetail(r);
    });
    b.addEventListener('pointerenter', () => { if (view3d) A.armory3d.hover(rear[Number(b.dataset.rear)]?.key); });
    b.addEventListener('pointerleave', () => { if (view3d) A.armory3d.hover(null); });
  }
}

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

function setPlace(key) {
  place = key || '';
  markPlace('rack', place);
  if (!root?.classList.contains('open')) return;
  setEditing(false);
  openAddBox(false);
  if (view3d) backTo2d();
  render();
}


const mayWrite = () => canAdminWrite() && document.body.dataset.editable === '1';
const WRITE_WHY = 'Add, remove and Save are off here: they need an admin, on an Atlas that takes changes.';

async function editorStore() {
  const { Editor } = await import('./editor/index.js');
  await Editor.load();
  return Editor;
}

const rackOf = (slot) => (allRacks.some((r) => r.id === slot.rack) ? slot.rack : allRacks[0].id);

function paintWrites() {
  const can = mayWrite();
  const add = $('rel-add'), save = $('rel-save'), why = $('rel-why');
  if (add) { add.disabled = !can; add.title = can ? 'Put a device in this rack' : WRITE_WHY; }
  if (save) { save.disabled = !can; save.title = can ? '' : WRITE_WHY; }
  const locate = $('rel-loc');
  if (locate) { locate.disabled = !can; locate.title = can ? 'Say where the machine shown, or this rack, stands' : 'Location is off here: it needs an admin, on an Atlas that takes changes.'; }
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
  const can = rackable(A.DATA, where);
  const group = (label, list) => (list.length ? `<optgroup label="${label}">${list.map(option).join('')}</optgroup>` : '');
  $('rel-add-what').innerHTML = group('Machines', can.filter((n) => n.kind === 'physical'))
    + group('Other places on the map', can.filter((n) => n.kind !== 'physical'))
    + '<option value="">Something that is not on the map…</option>';
  $('rel-add-type').innerHTML = '<option value="">Not said</option>' + DEVICE_GROUPS.map((g) =>
    `<optgroup label="${esc(g.label)}">${g.types.map((t) => `<option value="${esc(t.id)}">${esc(t.label)}</option>`).join('')}</optgroup>`).join('');
  $('rel-add-seat').innerHTML = SEATS.map((s) => `<option value="${s.id}">${s.label}</option>`).join('');
  $('rel-add-name').value = '';
  $('rel-add-msg').textContent = '';
  paintAddName();
  paintAddSeat();
  $('rel-add-what').focus();
}
const paintAddName = () => { $('rel-add-name-wrap').hidden = $('rel-add-what').value !== ''; };
const paintAddSeat = () => { $('rel-add-size').closest('.rel-add-field').hidden = $('rel-add-seat').value !== 'front'; };
function paintAddType() {
  const type = typeById($('rel-add-type').value);
  if (!type) return;
  const size = $('rel-add-size');
  if ([...size.options].some((o) => Number(o.value) === type.size)) size.value = String(type.size);
  $('rel-add-name').placeholder = type.label;
}

async function addVessel() {
  const msg = $('rel-add-msg');
  const say = (text) => { msg.textContent = text; };
  const node = $('rel-add-what').value ? nodeById($('rel-add-what').value) : null;
  const type = typeById($('rel-add-type').value);
  const seat = $('rel-add-seat').value || 'front';
  const name = addName({ node, typed: $('rel-add-name').value, type });
  const size = Math.max(1, Math.min(12, parseInt($('rel-add-size').value, 10) || 1));
  if (!name) { say('Give it a name, or say what device it is.'); $('rel-add-name').focus(); return; }
  const here = racks.find((r) => r.id === rackId);
  if (!here) return;
  if (seat !== 'front') { addFitting({ seat, name, node, type, here, say }); return; }
  if (Object.keys(readOvr()).length) { say('Save or Reset the moves you have made first, then add.'); return; }
  const top = freeTop(devices, rackU, size);
  const { body } = addBody({ seat, name, node, type, size, u: uLabel(top, size), rackId });
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

async function addFitting({ seat, name, node, type, here, say }) {
  const mine = inRack(A.DATA.rack_rear, allRacks, rackId);
  if (node && [...(A.DATA.rack || []), ...(A.DATA.rack_rear || [])].some((s) => s && s.node === node.id)) {
    say(`${name} is in a rack already.`);
    return;
  }
  if (mine.some((s) => String(s.name || '').toLowerCase() === name.toLowerCase())) {
    say(`This rack already has a "${name}" behind or inside it. Give it another name.`);
    return;
  }
  const { section, body } = addBody({ seat, name, node, type, rackId });
  const go = $('rel-add-go');
  go.disabled = true;
  const words = seat === 'inside' ? 'inside' : 'behind';
  try {
    const store = await editorStore();
    await store.apply([{ op: 'insert', section, body }], `put ${name} ${words} ${rackTitle(here)} (HARDWARE)`);
    openAddBox(false);
    render();
    A.showToast?.(`${name} is ${words} ${here.name}.`);
  } catch (err) {
    say(`Not added: ${err.message || err}`);
  } finally {
    go.disabled = false;
  }
}

async function locate() {
  if (!mayWrite()) return;
  const ask = shown?.node ? { node: shown.node.id } : rackId !== null ? { rack: rackId } : null;
  if (!ask) { A.showToast?.('Pick a machine first, then Location.'); return; }
  if (await setLocation(ask)) render();
}

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

function removeButton(d) {
  const b = document.createElement('button');
  b.type = 'button';
  b.className = 'rel-remove';
  b.textContent = '✕';
  b.title = `Take ${d.name} out of the rack`;
  b.setAttribute('aria-label', b.title);
  let armed = 0;
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
    delete el.dataset.dragged;
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
      try { el.releasePointerCapture(e.pointerId); } catch {   }
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
    for (const t of DRAG_END) el.addEventListener(t, up);
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
    const r = await postJSON('api/v2/rack', o);
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.status);
    const res = await r.json();
    localStorage.removeItem(OVR_KEY);
    A.showToast?.(`Saved the rack — ${res.saved} ${res.saved === 1 ? 'vessel' : 'vessels'}, for everyone.`);
  } catch (err) {
    A.showToast?.(`Could not save: ${err.message || err}`);
  }
}

function resetLayout() { localStorage.removeItem(OVR_KEY); location.reload(); }

let view3d = false, rel3dEl = null, legendEl = null;
const ledStateFor = (node) => (node ? (A.signalsFeed?.nodes?.[node.id]?.state || '') : '');

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
  for (const id of ['rel-edit', 'rel-add']) $(id)?.setAttribute('hidden', '');
  openAddBox(false);
  rel3dEl.hidden = false;
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
  onClose: () => { setEditing(false); openAddBox(false); backTo2d(); place = ''; markPlace('rack', ''); } });
const { open, close } = scene;
A.openReliquary = open;
A.closeReliquary = close;
addEventListener('atlas:scene-tools', (e) => {
  if (e.detail?.scene !== 'reliquary' || e.detail.on) return;
  setEditing(false);
  openAddBox(false);
});
addEventListener('atlas:scene-place', (e) => { if (e.detail?.scene === 'rack') setPlace(e.detail.place); });

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
  $('rel-loc')?.addEventListener('click', (e) => { e.stopPropagation(); locate(); });
  $('rel-add-what')?.addEventListener('change', paintAddName);
  $('rel-add-type')?.addEventListener('change', paintAddType);
  $('rel-add-seat')?.addEventListener('change', paintAddSeat);
  $('rel-add-go')?.addEventListener('click', (e) => { e.stopPropagation(); addVessel(); });
  $('rel-add-cancel')?.addEventListener('click', (e) => { e.stopPropagation(); openAddBox(false); });
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
