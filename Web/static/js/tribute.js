/* Atlas — RESOURCES (was THE TRIBUTE): the hypervisor divides its 64 GB
   among its vassals. A vessel-bar shows the whole divided; illuminated allocation
   bars per VM show each one's assigned RAM and how full it runs. The standby host slumbers.
   Live headroom math from vms[] (VM Configuration Scroll). */

import { A, $, esc, zoneById, nodeById, FALLBACK_HUE } from './config.js';
import { makeScene } from './scene.js';

let vesselEl, sumEl, listEl, cpuVesselEl, cpuSumEl, built = false;

const nameOf = (id) => { const n = nodeById(id); return n ? n.name : id.toUpperCase(); };

function zoneHue(id) {
  const n = nodeById(id);
  const z = n && zoneById(n.zone);
  return z ? z.hue : FALLBACK_HUE;
}

function buildTribute() {
  const vms = A.DATA.vms || [];
  const meta = (A.DATA.meta && A.DATA.meta.tribute) || { total_gb: 64, host_reserve_gb: 5 };
  const total = meta.total_gb, reserve = meta.host_reserve_gb;
  const on = vms.filter((v) => v.state === 'on');
  const assigned = on.reduce((s, v) => s + v.ram_gb, 0);
  const demand = on.reduce((s, v) => s + (v.demand_gb || 0), 0);
  const free = Math.max(0, total - reserve - assigned);
  const maxRam = Math.max(...vms.map((v) => v.ram_gb), 1);

  // THE VESSEL — 64 GB divided left-to-right into per-VM segments + reserve + free
  const fmt = (g) => (+g).toFixed(1).replace(/\.0$/, '');
  // esc() on the hue too: it is a dataset value reaching a style attribute, and
  // an unescaped one could close the attribute and attach an event handler. The
  // schema validates hue as a hex colour on every write, so there is no way to
  // plant it today — but that makes the validator the only thing standing
  // between the dataset and the DOM, two layers away. the 2026-07-27 security review.
  const seg = (label, gb, hue, cls) =>
    `<span class="trb-seg${cls ? ' ' + cls : ''}" style="width:${(gb / total * 100).toFixed(2)}%;--seg-hue:${esc(hue)}" title="${esc(label)} · ${fmt(gb)} GB"></span>`;
  vesselEl.innerHTML =
    on.map((v) => seg(nameOf(v.id), v.ram_gb, zoneHue(v.id))).join('') +
    seg('Host + Hyper-V overhead', reserve, '#57503F', 'reserve') +
    seg('Free headroom', free, 'transparent', 'free');

  sumEl.innerHTML =
    `<span class="trb-sum-big">${assigned.toFixed(1)}<small> / ${total} GB assigned</small></span>` +
    `<span>${demand.toFixed(1)} GB in use</span>` +
    `<span class="trb-sum-free">${free.toFixed(1)} GB free</span>`;

  /* THE SECOND VESSEL — the same division, told in processors.
     A vCPU is assigned against a LOGICAL processor, so threads is the honest
     denominator; cores is shown beside it because that is the iron actually
     doing the work, and 28/32 reads very differently once you know the 32 is
     16 cores twice over. Unlike memory, assigning more than there are is
     ordinary — the vessel widens to hold the overflow and says so in the warn
     tone rather than drawing a bar that runs off its own end. */
  const threads = +meta.cpu_threads || 0;
  const cores = +meta.cpu_cores || 0;
  const vcpuOn = on.reduce((s, v) => s + (+v.vcpu || 0), 0);
  if (threads > 0) {
    const span = Math.max(threads, vcpuOn);          // never draw past the vessel
    const freeT = Math.max(0, threads - vcpuOn);
    const over = Math.max(0, vcpuOn - threads);
    const segCpu = (label, n, hue, cls) =>
      `<span class="trb-seg${cls ? ' ' + cls : ''}" style="width:${(n / span * 100).toFixed(2)}%;--seg-hue:${esc(hue)}" title="${esc(label)} · ${esc(n)} vCPU"></span>`;
    cpuVesselEl.innerHTML =
      on.map((v) => segCpu(nameOf(v.id), +v.vcpu || 0, zoneHue(v.id))).join('') +
      segCpu('Unassigned threads', freeT, 'transparent', 'free');
    cpuSumEl.innerHTML =
      `<span class="trb-sum-big">${vcpuOn}<small> / ${threads} vCPU assigned</small></span>` +
      (cores ? `<span>${cores} cores · ${threads} threads</span>` : '') +
      (over
        ? `<span class="trb-sum-over">${over} vCPU over — oversubscribed</span>`
        : `<span class="trb-sum-free">${freeT} threads free</span>`);
  } else {
    // No thread count charted: say nothing rather than invent a denominator.
    cpuVesselEl.innerHTML = '';
    cpuSumEl.innerHTML = '<span>no processor count charted for this host</span>';
  }

  // per-VM allocation rows (bars scaled to the largest vessel so they compare)
  listEl.innerHTML = vms.map((v) => {
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
  }).join('');

  for (const row of listEl.children) {
    row.addEventListener('click', () => { close(); A.focusNode(row.dataset.id); });
  }
}

const scene = makeScene({ id: 'tribute', closeId: 'trb-close', build: () => { if (!built) { buildTribute(); built = true; } } });
const { open, close } = scene;
A.openTribute = open;
A.closeTribute = close;

A.buildTributeScene = function buildTributeScene() {
  if (!scene.mount()) return;
  vesselEl = $('trb-vessel');
  sumEl = $('trb-summary');
  cpuVesselEl = $('trb-vessel-cpu');
  cpuSumEl = $('trb-summary-cpu');
  listEl = $('trb-list');
};
