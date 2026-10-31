/* Atlas — ADDRESSES (was THE LEDGER; NetBox-style IPAM).

   Rebuilt on real CIDR maths (`ipam.js`). It used to assume a /24 everywhere:
   the prefix was the first three octets of an address and the grid was a fixed
   256 cells, so a /22 showed a quarter of itself and a /30 link claimed 254
   free addresses. Now any prefix length works, v4 and v6, nested prefixes
   nest, DHCP pools and reservations are drawn, and a prefix too large to draw
   cell-by-cell says so rather than lying.

   Addressing comes from `prefixes[]` when the dataset has it, and from
   `zones[].subnet` when it doesn't — so a map written before any of this
   renders exactly as it always did.

   Roads and topology live in THE PATH (path.js). */

import { A, CFG, $, esc } from './config.js';
import { makeScene } from './scene.js';
import {
  GRID_LIMIT, chartedAddresses, countLabel, drawable, formatAddress,
  nextFree, occupancy, prefixesOf, rangeAt, usableRange,
} from './ipam.js';

let root, listEl;

function liveDot(id) {
  const st = A.signalsFeed?.nodes?.[id]?.state;
  return `<span class="svc-health ${st ? (A.svcHealthClass[st] || '') : ''}" title="${esc(st || 'no signal')}"></span>`;
}

const zoneById = (id) => A.DATA.zones.find((z) => z.id === id);
const hueOf = (prefix) => zoneById(prefix.zone)?.hue || '#C9A554';

/* Every OTHER charted place answering on this address. chartedAddresses keeps
   one holder per address so the grid stays one-cell-one-lease; this is how the
   ones it set aside still get said out loud, instead of vanishing from the only
   view that claims to account for every address. */
function sharersOf(node) {
  const ip = String(node.ip || '').split('/')[0];
  if (!ip || ip === '—') return [];
  return A.DATA.nodes.filter((n) => n !== node
    && String(n.ip || '').split('/')[0] === ip);
}

/* ── the survey strip + the port map ──────────────────────────────────── */
function summaryHTML(prefixes, charted) {
  const v4 = prefixes.filter((p) => p.net.version === 4 && !p.children.length);
  const free = v4.reduce((sum, p) => sum + occupancy(p, charted).free, 0n);

  const ifaces = (A.DATA.interfaces || []);
  const byDevice = {};
  for (const i of ifaces) (byDevice[i.device] ||= []).push(i);

  const ports = Object.keys(byDevice).length
    ? Object.entries(byDevice).map(([device, list]) => {
        const node = A.DATA.nodes.find((n) => n.id === device);
        return `<div class="ldg-portgroup"><span class="ldg-portgroup-name">` +
          `${esc(node?.name || device)}</span><div class="ldg-ports">` +
          list.map((i) => {
            const z = A.DATA.zones.find((zz) => String(zz.vlan) === String(i.vlan));
            return `<span class="ldg-port${i.poe ? ' poe' : ''}" style="--p-hue:${esc(z?.hue || '#C9A554')}" ` +
              `title="${esc(i.name)} · ${esc(i.kind || 'rj45')}${i.vlan ? ' · vlan ' + esc(i.vlan) : ' · trunk'}` +
              `${i.speed ? ' · ' + esc(i.speed) : ''}${i.poe ? ' · PoE' : ''}${i.peer ? ' → ' + esc(i.peer) : ''}">` +
              `${esc(i.name)}</span>`;
          }).join('') + `</div></div>`;
      }).join('')
    : `<div class="ldg-note">port-level truth awaits the surveyor — add <code>ports</code> ` +
      `from the Desk (or curate <code>interfaces[]</code>) and every faceplate appears here, ` +
      `coloured by realm.</div>`;

  return `<div class="ldg-block ldg-path" style="--z-hue:#C9A554">
    <div class="ldg-zhead">
      <span class="ldg-zname">THE SURVEY</span>
      <span class="ldg-zsub">${prefixes.length} prefixes · ${charted.size} charted souls · ` +
      `${countLabel(free)} free grounds</span>
      <span class="ldg-zcount">routes live in TOPOLOGY</span>
    </div>
    ${ports}
  </div>`;
}

/* Zones that are surveyed but barely settled — the monitoring zone and the lookout zone
   are a /24 apiece holding almost nothing, and drawing 254 empty cells each
   pushed the zones you actually read off the first screen. They open folded;
   their head still states the count, so nothing is hidden, only rolled up.
   Every block's head toggles, so this is a default and not a restriction.
   (2026-08-04) */
const FOLDED_BY_DEFAULT = new Set(CFG.THEME.foldedZones || []);   // THE THEME (v1.48.0) names which

/* ── one prefix ───────────────────────────────────────────────────────── */
function prefixHTML(prefix, charted, depth = 0) {
  const hue = hueOf(prefix);
  const stats = occupancy(prefix, charted);
  const zone = zoneById(prefix.zone);
  const version = prefix.net.version;
  const folded = FOLDED_BY_DEFAULT.has(prefix.zone);

  const head =
    `<div class="ldg-zhead" role="button" tabindex="0"
       aria-expanded="${folded ? 'false' : 'true'}"
       title="${folded ? 'Unfold' : 'Fold'} this ground">
      <span class="ldg-fold" aria-hidden="true">▾</span>
      <span class="ldg-zname">${esc(prefix.name || zone?.name || prefix.cidr)}</span>
      <span class="ldg-zsub">${esc(prefix.cidr)}${zone ? ` · vlan ${esc(zone.vlan)}` : ''}` +
        `${prefix.role && prefix.role !== 'prefix' ? ` · ${esc(prefix.role)}` : ''}` +
        `${version === 6 ? ' · ipv6' : ''}</span>
      <span class="ldg-zcount">${stats.container
        ? `${prefix.children.length} delegated · ${countLabel(stats.free)} undivided`
        : `${stats.direct.length} charted · ${countLabel(stats.free)} free`}</span>
    </div>`;

  const bar = stats.total > 0n
    ? `<div class="ldg-util" title="${stats.percent}% of the prefix is spoken for">
         <span class="ldg-util-fill" style="width:${Math.max(stats.percent, 1)}%"></span>
         <span class="ldg-util-pct">${stats.percent < 1 && stats.percent > 0
           ? '<1' : Math.round(stats.percent)}%</span>
       </div>`
    : '';

  let grid;
  if (prefix.role === 'container') {
    grid = `<div class="ldg-note">a container — its ground is divided among ` +
           `${prefix.children.length} prefix${prefix.children.length === 1 ? '' : 'es'} below.</div>`;
  } else if (drawable(prefix.net)) {
    grid = gridHTML(prefix, charted);
  } else {
    grid = `<div class="ldg-note">${countLabel(prefix.net.size)} addresses — too much ground ` +
           `to draw cell by cell (the grid stops at ${GRID_LIMIT}). ` +
           `${stats.direct.length} charted below.</div>`;
  }

  // No "next free" on a container: you delegate a subnet out of it, you don't
  // hand an address from it to a host.
  const free = stats.container ? null : nextFree(prefix.net, new Set(charted.keys()), prefix.ranges);
  const legend = [
    ...(prefix.ranges || []).map((r) =>
      `<span class="ldg-legend-item ldg-r-${esc(r.kind || 'dhcp')}">` +
      `${esc(r.kind || 'dhcp')} ${esc(r.start)}–${esc(r.end)}${r.note ? ` · ${esc(r.note)}` : ''}</span>`),
    free ? `<span class="ldg-legend-item ldg-next">next free <code>${esc(free)}</code></span>` : '',
  ].filter(Boolean).join('');

  const table = stats.direct.map(({ value, node }) => {
    const band = rangeAt(prefix, value);
    const shared = sharersOf(node);
    return `<button class="ldg-host" data-id="${esc(node.id)}">` +
      `<span class="ldg-host-ip">${esc(formatAddress(version, value))}</span>` +
      `<span class="ldg-host-name">${liveDot(node.id)}${esc(node.name)}</span>` +
      `<span class="ldg-host-role">${esc((node.role || '').split('·')[0].trim())}` +
      `${band ? ` <i class="ldg-inband">in the ${esc(band.kind || 'dhcp')} range</i>` : ''}` +
      `${shared.length ? ` <i class="ldg-shared">shared with ${
        esc(shared.map((n) => n.name).join(', '))}</i>` : ''}</span>` +
      `</button>`;
  }).join('');

  return `<div class="ldg-block${depth ? ' ldg-child' : ''}${folded ? ' ldg-folded' : ''}" style="--z-hue:${esc(hue)}">
    ${head}${bar}${grid}
    ${legend ? `<div class="ldg-legend">${legend}</div>` : ''}
    <div class="ldg-hosts">${table}</div>
  </div>` + prefix.children.map((child) => prefixHTML(child, charted, depth + 1)).join('');
}

function gridHTML(prefix, charted) {
  const range = usableRange(prefix.net);
  const version = prefix.net.version;
  let cells = '';
  for (let a = prefix.net.network; a <= prefix.net.broadcast; a++) {
    const node = charted.get(a);
    const edge = range && (a < range.first || a > range.last);
    const band = rangeAt(prefix, a);
    if (node) {
      cells += `<span class="ldg-cell lit" data-id="${esc(node.id)}" ` +
        `style="--c-hue:${esc(hueOf(prefix))}" ` +
        `title="${esc(node.name)} · ${esc(formatAddress(version, a))}"></span>`;
    } else if (edge) {
      cells += `<span class="ldg-cell edge" title="${esc(formatAddress(version, a))} · ` +
        `${a === prefix.net.network ? 'the network address' : 'the broadcast address'}"></span>`;
    } else if (band) {
      cells += `<span class="ldg-cell ldg-r-${esc(band.kind || 'dhcp')}" ` +
        `title="${esc(formatAddress(version, a))} · ${esc(band.kind || 'dhcp')}` +
        `${band.note ? ' · ' + esc(band.note) : ''}"></span>`;
    } else {
      cells += `<span class="ldg-cell" title="${esc(formatAddress(version, a))}"></span>`;
    }
  }
  return `<div class="ldg-grid">${cells}</div>`;
}

/* ── build ────────────────────────────────────────────────────────────── */
function build() {
  const charted = chartedAddresses(A.DATA);
  const prefixes = prefixesOf(A.DATA);
  const roots = prefixes.filter((p) => !p.parent);

  listEl.innerHTML = summaryHTML(prefixes, charted) +
    (roots.length
      ? roots.map((p) => prefixHTML(p, charted)).join('')
      : `<div class="ldg-note">no ground surveyed yet — give a realm a subnet, or add a ` +
        `<code>prefix</code> from the Desk, and its addresses appear here.</div>`);

  // an unclaimed address is still worth seeing: hosts outside every prefix
  const loose = [...charted.entries()].filter(([value]) =>
    !prefixes.some((p) => value >= p.net.network && value <= p.net.broadcast));
  if (loose.length) {
    listEl.insertAdjacentHTML('beforeend',
      `<div class="ldg-block" style="--z-hue:#C49A52">
        <div class="ldg-zhead">
          <span class="ldg-zname">OFF THE SURVEY</span>
          <span class="ldg-zsub">charted, but inside no prefix you have described</span>
          <span class="ldg-zcount">${loose.length}</span>
        </div>
        <div class="ldg-hosts">` +
        loose.map(([value, node]) =>
          `<button class="ldg-host" data-id="${esc(node.id)}">` +
          `<span class="ldg-host-ip">${esc(node.ip)}</span>` +
          `<span class="ldg-host-name">${liveDot(node.id)}${esc(node.name)}</span>` +
          `<span class="ldg-host-role">${esc((node.role || '').split('·')[0].trim())}</span>` +
          `</button>`).join('') +
      `</div></div>`);
  }

  const goTo = (id) => { close(); A.focusNode(id); };
  for (const c of listEl.querySelectorAll('.ldg-cell.lit, .ldg-host')) {
    c.addEventListener('click', () => goTo(c.dataset.id));
  }

  // fold/unfold a ground. Not only the default-folded ones — any head takes it,
  // so a crowded zone can be rolled up too. Rebuilt on every open(), so the
  // fold state is per-visit by design: the default is the opinion, not a memory.
  for (const head of listEl.querySelectorAll('.ldg-zhead[role="button"]')) {
    const toggle = () => {
      const block = head.closest('.ldg-block');
      const nowFolded = block.classList.toggle('ldg-folded');
      head.setAttribute('aria-expanded', String(!nowFolded));
      head.title = `${nowFolded ? 'Unfold' : 'Fold'} this ground`;
    };
    head.addEventListener('click', toggle);
    head.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); }
    });
  }
}

// rebuild each open: cheap, and health dots stay current
const scene = makeScene({ id: 'ledger', closeId: 'ldg-close', build: () => build() });
const { open, close } = scene;
A.openLedger = open;
A.closeLedger = close;

A.buildLedgerScene = function buildLedgerScene() {
  root = scene.mount();
  if (!root) return;
  listEl = $('ldg-list');
};
