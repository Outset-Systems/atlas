
import { A, $, esc, zoneById, nodeById, FALLBACK_HUE } from './config.js';
import { makeScene } from './scene.js';
import { availableBy, hostsAt, hostsIn, totalsOf, gb } from './tribute-model.js';
import { locationByKey, locationOfRack, rackById } from './locations-model.js';
import { drawPlacePicker, drawRackPicker, hostsNow, markPlace, offerFor, placeName, whereLine, whereNow } from './scene-places.js';

let vesselEl, sumEl, listEl, cpuVesselEl, cpuSumEl, whereEl, placesEl, racksEl, noteEl, byEl, built = false;
let place = '';
let rack = null;
let by = 'guests';

const nameOf = (id) => { const n = nodeById(id); return n ? n.name : id.toUpperCase(); };

function zoneHue(id) {
  const n = nodeById(id);
  const z = n && zoneById(n.zone);
  return z ? z.hue : FALLBACK_HUE;
}

const one = (n) => (+n).toFixed(1);
const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;

function capacityLine(h) {
  if (!h.capacity) return 'capacity not charted';
  const c = h.capacity;
  return [c.cores ? `${c.cores} cores` : '', c.threads !== null ? `${c.threads} threads` : '',
    c.total_gb !== null ? `${gb(c.total_gb)} GB` : ''].filter(Boolean).join(' · ') || 'capacity not charted';
}

function buildTribute() {
  const where = whereNow();
  const shownRack = rackById(where, rack);
  if (!shownRack) rack = null;
  const loc = shownRack ? locationOfRack(where, rack) : locationByKey(where, place);
  place = loc ? loc.key : '';
  markPlace('tribute', place);
  const every = hostsNow();
  const hosts = shownRack ? hostsIn(every, rack) : hostsAt(every, loc ? loc.key : null);
  const t = totalsOf(hosts);

  if (whereEl) whereEl.textContent = whereLine(loc, shownRack);
  drawPlacePicker(placesEl, 'tribute', place, (key) => setPlace(key));
  drawRackPicker(racksEl, 'tribute', place, rack, setRack, loc ? `All of ${placeName(loc)}` : 'All');

  const mem = hosts.filter((h) => h.guests.length && h.capacity && h.capacity.total_gb !== null);
  const cpu = hosts.filter((h) => h.guests.length && h.capacity && h.capacity.threads !== null);

  const total = t.total_gb;
  vesselEl.hidden = !(total > 0);
  cpuVesselEl.hidden = !(t.threads > 0);
  if (total > 0) {
    const seg = (label, amount, hue, cls) =>
      `<span class="trb-seg${cls ? ' ' + cls : ''}" style="width:${(amount / total * 100).toFixed(2)}%;--seg-hue:${esc(hue)}" title="${esc(label)} · ${gb(amount)} GB"></span>`;
    const assigned = mem.reduce((s, h) => s + h.assigned_gb, 0);
    const demand = mem.reduce((s, h) => s + h.demand_gb, 0);
    vesselEl.innerHTML =
      mem.flatMap((h) => h.on.map((v) => seg(nameOf(v.id), v.ram_gb, zoneHue(v.id)))).join('') +
      seg('Held back for the hosts', t.reserve_gb, '#57503F', 'reserve') +
      seg('Free headroom', t.free_gb, 'transparent', 'free');
    sumEl.innerHTML =
      `<span class="trb-sum-big">${one(assigned)}<small> / ${gb(total)} GB assigned</small></span>` +
      `<span>${one(demand)} GB in use</span>` +
      `<span class="trb-sum-free">${one(t.free_gb)} GB free</span>`;
  } else {
    vesselEl.innerHTML = '';
    sumEl.innerHTML = `<span>${t.hosts ? 'no memory charted for the hosts here' : 'nothing here divides memory among guests'}</span>`;
  }

  const threads = t.threads;
  if (threads > 0) {
    const vcpuOn = cpu.reduce((s, h) => s + h.vcpu, 0);
    const span = Math.max(threads, vcpuOn);
    const segCpu = (label, n, hue, cls) =>
      `<span class="trb-seg${cls ? ' ' + cls : ''}" style="width:${(n / span * 100).toFixed(2)}%;--seg-hue:${esc(hue)}" title="${esc(label)} · ${esc(n)} vCPU"></span>`;
    cpuVesselEl.innerHTML =
      cpu.flatMap((h) => h.on.map((v) => segCpu(nameOf(v.id), +v.vcpu || 0, zoneHue(v.id)))).join('') +
      segCpu('Unassigned threads', Math.max(0, threads - vcpuOn), 'transparent', 'free');
    cpuSumEl.innerHTML =
      `<span class="trb-sum-big">${vcpuOn}<small> / ${threads} vCPU assigned</small></span>` +
      (t.cores ? `<span>${t.cores} cores · ${threads} threads</span>` : '') +
      (t.over
        ? `<span class="trb-sum-over">${t.over} vCPU over — oversubscribed</span>`
        : `<span class="trb-sum-free">${t.threads_free} threads free</span>`);
  } else {
    cpuVesselEl.innerHTML = '';
    cpuSumEl.innerHTML = `<span>${t.hosts ? 'no processor count charted for the hosts here' : 'nothing here divides processors among guests'}</span>`;
  }

  const notes = [];
  const uncounted = Math.max(t.uncounted_gb, t.uncounted_cpu);
  if (uncounted && (total > 0 || threads > 0)) {
    notes.push(`${plural(uncounted, 'host')} with guests ${uncounted === 1 ? 'has' : 'have'} no capacity charted, and ${uncounted === 1 ? 'is' : 'are'} not in the bars above.`);
  }
  if (t.machines > 1) {
    notes.push(`${plural(t.machines, 'machine')} in all: ${t.cores_all} cores · ${t.threads_all} threads · ${gb(t.ram_all)} GB.`);
  }
  if (noteEl) {
    noteEl.innerHTML = notes.map((n) => `<span>${esc(n)}</span>`).join('');
    noteEl.hidden = !notes.length;
  }

  for (const b of byEl?.querySelectorAll('[data-by]') || []) {
    const on = b.dataset.by === by;
    b.classList.toggle('is-on', on);
    b.setAttribute('aria-pressed', String(on));
  }
  if (by !== 'guests') { drawAvailable(where, every, loc); return; }

  const maxRam = Math.max(...hosts.flatMap((h) => h.guests.map((v) => +v.ram_gb || 0)), 1);
  const row = (v) => {
    const off = v.state !== 'on';
    const hue = off ? '#6B6455' : zoneHue(v.id);
    const trackW = (v.ram_gb / maxRam * 100).toFixed(1);
    const fillW = v.demand_gb ? (v.demand_gb / v.ram_gb * 100).toFixed(1) : 0;
    const stat = `${esc(v.vcpu)} vCPU · ${esc(v.ram_gb)} GB` +
      (v.dynamic ? ` · dyn ${esc(v.dynamic)}` : '') + (off ? ' · slumbering' : '');
    return `<button class="trb-row${off ? ' off' : ''}" data-id="${esc(v.id)}" style="--row-hue:${esc(hue)}">
      <span class="trb-name">${esc(nameOf(v.id))}</span>
      <span class="trb-bar"><span class="trb-track" style="width:${trackW}%">` +
        `<span class="trb-fill" style="width:${fillW}%"></span></span></span>
      <span class="trb-stat">${stat}</span>
    </button>`;
  };
  const single = hosts.length === 1 && hosts[0].guests.length > 0;
  const hostBlock = (h) => (single ? '' : `
    <div class="trb-host${h.guests.length ? '' : ' trb-host-bare'}">
      <button class="trb-host-name" data-id="${esc(h.id)}">${esc(nameOf(h.id))}</button>
      <span class="trb-stat">${esc(capacityLine(h))}${h.guests.length ? '' : ' · runs no guests'}</span>
    </div>`) + h.guests.map(row).join('');
  const groups = [];
  const byRack = (scope) => {
    for (const r of scope.racks) {
      const here = hostsIn(hosts, r.id);
      if (here.length) {
        groups.push({ hosts: here,
          head: `<button class="trb-place" data-rack="${esc(r.id)}" title="Show only ${esc(r.name)}">${esc(r.name)}</button>` });
      }
    }
    const shelf = hosts.filter((h) => h.rack === null);
    if (shelf.length) groups.push({ hosts: shelf, head: '<span class="trb-place">Not in a rack</span>' });
    if (groups.length < 2) groups.splice(0, groups.length, { hosts, head: null });
  };
  if (shownRack) groups.push({ hosts, head: null });
  else if (loc) byRack(loc);
  else {
    const offer = offerFor('tribute');
    const chosen = new Set(offer.map((o) => o.loc.key));
    for (const { loc: l } of offer) {
      const here = hosts.filter((h) => h.location === l.key);
      if (here.length) {
        groups.push({ hosts: here,
          head: `<button class="trb-place" data-place="${esc(l.key)}" title="Show only ${esc(placeName(l))}">${esc(placeName(l))}</button>` });
      }
    }
    const adrift = hosts.filter((h) => h.location === null);
    if (adrift.length) groups.push({ hosts: adrift, head: '<span class="trb-place">Not placed</span>' });
    const idle = hosts.filter((h) => h.location !== null && !chosen.has(h.location));
    if (idle.length) groups.push({ hosts: idle, head: '<span class="trb-place">Elsewhere, running no guests</span>' });
    if (groups.length < 2) {
      groups.length = 0;
      if (offer.length === 1) byRack(offer[0].loc); else groups.push({ hosts, head: null });
    }
  }
  listEl.innerHTML = groups.map((g) => {
    if (g.head === null) return g.hosts.map(hostBlock).join('');
    const s = totalsOf(g.hosts);
    const said = [s.total_gb ? `${one(s.assigned_gb)} / ${gb(s.total_gb)} GB` : '',
      s.threads ? `${s.vcpu} / ${s.threads} vCPU` : '',
      !s.hosts && s.machines ? `${s.cores_all} cores · ${gb(s.ram_all)} GB` : ''].filter(Boolean).join(' · ');
    return `<div class="trb-place-head">${g.head}<span class="trb-stat">${esc(said)}</span></div>`
      + g.hosts.map(hostBlock).join('');
  }).join('') || '<div class="trb-empty">No machine here runs guests or says what compute it has.</div>';

  for (const el of listEl.querySelectorAll('[data-id]')) {
    el.addEventListener('click', () => { close(); A.focusNode(el.dataset.id); });
  }
  for (const el of listEl.querySelectorAll('[data-place]')) {
    el.addEventListener('click', () => setPlace(el.dataset.place));
  }
  for (const el of listEl.querySelectorAll('[data-rack]')) {
    el.addEventListener('click', () => setRack(el.dataset.rack));
  }
}

function drawAvailable(where, every, loc) {
  const rows = availableBy(every, where, by, by === 'rack' && loc ? loc.key : '');
  const said = (s) => {
    const parts = [];
    if (s.total_gb > 0) parts.push(`<b>${gb(s.free_gb)} GB free</b> of ${gb(s.total_gb)}`);
    if (s.threads > 0) {
      parts.push(s.over ? `${s.over} vCPU over ${s.threads} threads` : `<b>${s.threads_free} threads free</b> of ${s.threads}`);
    }
    if (!parts.length) parts.push('capacity not charted');
    parts.push(plural(s.machines, 'machine'), `${plural(s.guests_on, 'guest')} on`);
    if (s.uncharted && (s.total_gb > 0 || s.threads > 0)) parts.push(`${s.uncharted} not charted`);
    return parts.join(' · ');
  };
  const row = (r) => {
    const s = r.sum;
    const used = s.total_gb > 0 ? Math.min(100, ((s.total_gb - s.free_gb) / s.total_gb) * 100) : 0;
    const attrs = r.kind === 'place' ? `data-place="${esc(r.key)}"` : r.kind === 'rack' ? `data-rack="${esc(r.id)}" data-at="${esc(r.key)}"` : '';
    const tag = attrs ? 'button' : 'div';
    const names = r.hosts.map((h) => nameOf(h.id)).join(', ');
    return `<${tag} class="trb-row trb-avail" ${attrs}${attrs ? ` title="Show the guests ${r.kind === 'rack' ? 'in' : 'at'} ${esc(r.name)}"` : ''}>
      <span class="trb-name">${esc(r.name)}<small>${esc([by === 'rack' ? r.at : '', names].filter(Boolean).join(' · '))}</small></span>
      <span class="trb-bar"><span class="trb-track" style="width:100%"><span class="trb-fill" style="width:${used.toFixed(1)}%"></span></span></span>
      <span class="trb-stat">${said(s)}</span>
    </${tag}>`;
  };
  const head = by === 'rack'
    ? `Available compute, by hardware${loc ? ` at ${esc(placeName(loc))}` : ''}`
    : 'Available compute, by location';
  listEl.innerHTML = rows.length
    ? `<div class="trb-place-head"><span class="trb-place">${head}</span></div>` + rows.map(row).join('')
    : '<div class="trb-empty">No machine here says what compute it has.</div>';
  for (const el of listEl.querySelectorAll('[data-place]')) {
    el.addEventListener('click', () => { by = 'guests'; setPlace(el.dataset.place); });
  }
  for (const el of listEl.querySelectorAll('[data-rack]')) {
    el.addEventListener('click', () => { by = 'guests'; place = el.dataset.at || place; setRack(el.dataset.rack); });
  }
}

function redraw() {
  built = false;
  if ($('tribute')?.classList.contains('open')) { buildTribute(); built = true; }
}

function setPlace(key) {
  place = key || '';
  rack = null;
  markPlace('tribute', place);
  redraw();
}

function setRack(rackId) {
  rack = rackId ?? null;
  if (rack === null && whereNow().list.length < 2) place = '';
  redraw();
}

const scene = makeScene({ id: 'tribute', closeId: 'trb-close', build: () => { if (!built) { buildTribute(); built = true; } },
  onClose: () => { place = ''; rack = null; by = 'guests'; built = false; markPlace('tribute', ''); } });
const { open, close } = scene;

addEventListener('atlas:data', () => {
  built = false;
  if ($('tribute')?.classList.contains('open')) { buildTribute(); built = true; }
});
addEventListener('atlas:scene-place', (e) => { if (e.detail?.scene === 'tribute') setPlace(e.detail.place); });
A.openTribute = open;
A.closeTribute = close;

A.buildTributeScene = function buildTributeScene() {
  if (!scene.mount()) return;
  vesselEl = $('trb-vessel');
  sumEl = $('trb-summary');
  cpuVesselEl = $('trb-vessel-cpu');
  cpuSumEl = $('trb-summary-cpu');
  listEl = $('trb-list');
  whereEl = $('trb-where');
  placesEl = $('trb-places');
  racksEl = $('trb-racks');
  noteEl = $('trb-note');
  byEl = $('trb-by');
  byEl?.addEventListener('click', (e) => {
    const b = e.target.closest('[data-by]');
    if (!b || b.dataset.by === by) return;
    e.stopPropagation();
    by = b.dataset.by;
    redraw();
  });
};
