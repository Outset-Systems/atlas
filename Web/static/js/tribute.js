/* RESOURCES (was THE TRIBUTE): how each machine's memory and processors are
   divided among its guests. A vessel-bar shows the whole divided; allocation
   bars per guest show each one's assigned memory and how full it runs.

   BY LOCATION since 2026-11-20 (owner: "selecting 'home office' will display
   just the resources there, but selecting 'Resources' will display a
   summary/total of everything"). The scene shows either everything, with the
   total across every host and the hosts under their locations, or one
   location: its own total and its own hosts. The sums are tribute-model.js
   (one host with one `meta.tribute`, the lab this was written for, reads
   exactly as it did); where a thing is, locations-model.js. A machine with
   no guests that declares its memory and processors is listed too: it is
   compute, even if it divides nothing.

   ONE RACK, the same day (owner: "you should be able to see the resources of
   a specific device, (Rack a or rack B) that is associated with a specific
   location"). A location's hosts stand under its racks, each with its own
   sum, and one rack can be shown alone: from the band's menu, from the
   picker beside the locations', or by pressing its name. */

import { A, $, esc, zoneById, nodeById, FALLBACK_HUE } from './config.js';
import { makeScene } from './scene.js';
import { hostsAt, hostsIn, totalsOf, gb } from './tribute-model.js';
import { locationByKey, locationOfRack, rackById } from './locations-model.js';
import { drawPlacePicker, drawRackPicker, hostsNow, markPlace, offerFor, placeName, whereLine, whereNow } from './scene-places.js';

let vesselEl, sumEl, listEl, cpuVesselEl, cpuSumEl, whereEl, placesEl, racksEl, noteEl, built = false;
/** The location shown; '' is everything. */
let place = '';
/** The one rack shown at it; null is the whole location ('' is a real rack id). */
let rack = null;

const nameOf = (id) => { const n = nodeById(id); return n ? n.name : id.toUpperCase(); };

function zoneHue(id) {
  const n = nodeById(id);
  const z = n && zoneById(n.zone);
  return z ? z.hue : FALLBACK_HUE;
}

const one = (n) => (+n).toFixed(1);
const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;

/** What a machine has, in one mono line: "16 cores · 32 threads · 128 GB". */
function capacityLine(h) {
  if (!h.capacity) return 'capacity not charted';
  const c = h.capacity;
  return [c.cores ? `${c.cores} cores` : '', c.threads !== null ? `${c.threads} threads` : '',
    c.total_gb !== null ? `${gb(c.total_gb)} GB` : ''].filter(Boolean).join(' · ') || 'capacity not charted';
}

function buildTribute() {
  const where = whereNow();
  // a rack is always shown inside its own location, whatever was asked with it
  const shownRack = rackById(where, rack);
  if (!shownRack) rack = null;
  const loc = shownRack ? locationOfRack(where, rack) : locationByKey(where, place);
  place = loc ? loc.key : '';
  markPlace('tribute', place, rack);
  const every = hostsNow();
  const hosts = shownRack ? hostsIn(every, rack) : hostsAt(every, loc ? loc.key : null);
  const t = totalsOf(hosts);

  if (whereEl) whereEl.textContent = whereLine(loc, shownRack);
  drawPlacePicker(placesEl, 'tribute', place, (key) => setPlace(key));
  drawRackPicker(racksEl, 'tribute', place, rack, setRack, loc ? `All of ${placeName(loc)}` : 'All');

  // the hosts whose memory, and whose processors, can be divided on a bar
  const mem = hosts.filter((h) => h.guests.length && h.capacity && h.capacity.total_gb !== null);
  const cpu = hosts.filter((h) => h.guests.length && h.capacity && h.capacity.threads !== null);

  // THE VESSEL: the memory divided left-to-right into per-guest segments + reserve + free
  // esc() on the hue too: it is a dataset value reaching a style attribute, and
  // an unescaped one could close the attribute and attach an event handler. The
  // schema validates hue as a hex colour on every write, so there is no way to
  // plant it today — but that makes the validator the only thing standing
  // between the dataset and the DOM, two layers away. the 2026-07-27 security review.
  const total = t.total_gb;
  // a bar with nothing to divide is not drawn: the line under it says why
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
    // No memory charted for any host here: say so rather than invent a whole.
    vesselEl.innerHTML = '';
    sumEl.innerHTML = `<span>${t.hosts ? 'no memory charted for the hosts here' : 'nothing here divides memory among guests'}</span>`;
  }

  /* THE SECOND VESSEL: the same division, told in processors.
     A vCPU is assigned against a LOGICAL processor, so threads is the honest
     denominator; cores is shown beside it because that is the iron actually
     doing the work, and 28/32 reads very differently once you know the 32 is
     16 cores twice over. Unlike memory, assigning more than there are is
     ordinary — the vessel widens to hold the overflow and says so in the warn
     tone rather than drawing a bar that runs off its own end. */
  const threads = t.threads;
  if (threads > 0) {
    const vcpuOn = cpu.reduce((s, h) => s + h.vcpu, 0);
    const span = Math.max(threads, vcpuOn);          // never draw past the vessel
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
    // No thread count charted: say nothing rather than invent a denominator.
    cpuVesselEl.innerHTML = '';
    cpuSumEl.innerHTML = `<span>${t.hosts ? 'no processor count charted for the hosts here' : 'nothing here divides processors among guests'}</span>`;
  }

  // what the bars could not count, and the compute that stands here in all
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

  // per-guest allocation rows (bars scaled to the largest so they compare)
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
  /* One host and nothing else is the scene as it always was: its guests, no
     headings. More than that, each host is named over its guests; under
     "everything" the hosts stand under their locations, and under one
     location under its racks (what is in no rack last), when that divides
     them at all. */
  const single = hosts.length === 1 && hosts[0].guests.length > 0;
  const hostBlock = (h) => (single ? '' : `
    <div class="trb-host${h.guests.length ? '' : ' trb-host-bare'}">
      <button class="trb-host-name" data-id="${esc(h.id)}">${esc(nameOf(h.id))}</button>
      <span class="trb-stat">${esc(capacityLine(h))}${h.guests.length ? '' : ' · runs no guests'}</span>
    </div>`) + h.guests.map(row).join('');
  // a group is {head, hosts}; `head` is the markup of its name, or null for no heading at all
  const groups = [];
  const offer = offerFor('tribute');
  // on a map of one location, everything IS that location, and is divided the same way
  const scope = loc || (offer.length === 1 ? offer[0].loc : null);
  if (!loc && offer.length > 1) {
    for (const l of where.list) {
      const here = hosts.filter((h) => h.location === l.key);
      if (here.length) {
        groups.push({ hosts: here,
          head: `<button class="trb-place" data-place="${esc(l.key)}" title="Show only ${esc(placeName(l))}">${esc(placeName(l))}</button>` });
      }
    }
    const adrift = hosts.filter((h) => h.location === null);
    if (adrift.length) groups.push({ hosts: adrift, head: '<span class="trb-place">Not placed</span>' });
  } else if (scope && !shownRack) {
    for (const r of scope.racks) {
      const here = hostsIn(hosts, r.id);
      if (here.length) {
        groups.push({ hosts: here,
          head: `<button class="trb-place" data-rack="${esc(r.id)}" title="Show only ${esc(r.name)}">${esc(r.name)}</button>` });
      }
    }
    const shelf = hosts.filter((h) => h.rack === null);
    if (shelf.length) groups.push({ hosts: shelf, head: '<span class="trb-place">Not in a rack</span>' });
    // one group is no division: the location's own line above already says it
    if (groups.length < 2) groups.splice(0, groups.length, { hosts, head: null });
  } else groups.push({ hosts, head: null });
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

function redraw() {
  built = false;
  if ($('tribute')?.classList.contains('open')) { buildTribute(); built = true; }
}

/** Show one location ('' = everything), or one rack at it; drawn at once
    when the scene is up. */
function setPlace(key, rackId = null) {
  place = key || '';
  rack = place && rackId !== undefined ? rackId : null;
  markPlace('tribute', place, rack);
  redraw();
}

/** Show one rack of the location on show (null = the whole location). On a
    map of one location the whole of it is everything, and is said so, so
    that RESOURCES pressed once still closes the scene. */
function setRack(rackId) {
  rack = rackId ?? null;
  if (rack === null && offerFor('tribute', place).length < 2) place = '';
  redraw();
}

const scene = makeScene({ id: 'tribute', closeId: 'trb-close', build: () => { if (!built) { buildTribute(); built = true; } },
  // closed, the scene goes back to everything: RESOURCES pressed afresh is the total
  onClose: () => { place = ''; rack = null; built = false; markPlace('tribute', ''); } });
const { open, close } = scene;

/* New map data: built once is no longer built (2026-11-19, the 11-12 audit's
   Scenes 3: nothing set `built` back, so RESOURCES drew the first map it saw
   for the life of the tab). Redrawn now if it is up, else on the next open. */
addEventListener('atlas:data', () => {
  built = false;
  if ($('tribute')?.classList.contains('open')) { buildTribute(); built = true; }
});
// the band's menu of locations, and a press on RESOURCES while one is shown
addEventListener('atlas:scene-place', (e) => { if (e.detail?.scene === 'tribute') setPlace(e.detail.place, e.detail.rack); });
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
};
