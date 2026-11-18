/* Atlas — TOPOLOGY (was THE PATH): the realm, tier by tier
   (2026-07-11, broken back out of the Ledger and rebuilt SolarWinds-NPM-style):

     tier 0  the world beyond                (two places, by id)
     tier 1  the ways in                     (four places, by id)
     tier 2  network gear + physical hosts   (everything else)
     tier 3  the guests                      (any place with a `parent` — NetBox
                                              virtualization model)

   Which ids those are, the layout and the edges are path-model.js's.

   Edges come from routes[] plus parent containment; nodes and edges take live
   health from the signals feed on every open. Click a node → fly to it on the
   map. Pure SVG + DOM, no libraries. */

import { A, $, esc, zoneById, FALLBACK_HUE } from './config.js';
import { say } from './words.js';
import { chainPairs, edgesOf, layout, servicesCrossing } from './path-model.js';

const SVGNS = 'http://www.w3.org/2000/svg';
let root, svg, nodesEl, legendEl;

let tracedEdge = null;   // "<a> <b>" of the hop currently being traced, or null
let lastFocus = null;    // the service-card view to return to when a trace is released

/** Light every road that crosses this hop, end to end — not just the hop.
    Clicking one segment of Jellyfin's road should show you the whole of it
    (gateway → edge → traefik → pangolin → the-wild), because the useful
    question at a hop is never "does traffic cross here" — you clicked it, so it
    does — but "where is that traffic coming from, and where is it going". */
function traceEdge(a, b, crossing) {
  clearTrace();
  tracedEdge = `${a} ${b}`;
  root.classList.add('pth-focus-mode', 'pth-traced');

  const litNodes = new Set(), litPairs = new Set();
  for (const { chain } of crossing) {
    for (const id of chain) litNodes.add(id);
    for (const pair of chainPairs(chain)) litPairs.add(pair);
  }
  for (const p of svg.querySelectorAll('.pth-edge')) {
    const on = litPairs.has(`${p.dataset.a} ${p.dataset.b}`);
    p.classList.toggle('pth-reach', on);
    // the hop actually clicked is the one the eye should land on first
    p.classList.toggle('pth-hop', p.dataset.a === a && p.dataset.b === b);
  }
  for (const el of nodesEl.querySelectorAll('.pth-node')) {
    el.classList.toggle('pth-lit', litNodes.has(el.dataset.id));
  }

  // Each road names the place it starts from, not just the service. Two of the
  // realm's roads can carry the same label — charted from two different hosts,
  // genuinely different roads over this hop — and a legend that printed
  // the label twice would read as a bug in the map rather than a fact about it.
  const names = crossing.map(({ host, link, chain }) =>
    `<span class="pth-lg pth-lg-svc"><strong>${esc(link.label)}</strong>` +
    `<span class="pth-lg-from"> from ${esc(host.name.toLowerCase())}</span>` +
    ` · ${chain.length} stops</span>`).join('');
  legendEl.insertAdjacentHTML('afterbegin',
    `<span class="pth-lg pth-lg-note pth-lg-trace">◈ ${crossing.length} ` +
    `${crossing.length === 1 ? 'route crosses' : 'routes cross'} this hop — click it again to release</span>` + names);
}

/** Strip the marks a trace leaves, and nothing else. Kept separate from
    releaseTrace because tracing a second hop must NOT restore the card's focus
    view underneath the new trace — it only needs the previous one wiped. */
function clearTrace() {
  tracedEdge = null;
  if (!root) return;
  root.classList.remove('pth-traced');
  // only drop focus mode if a service card did not put us in it
  if (!root.dataset.svcFocus) root.classList.remove('pth-focus-mode');
  for (const p of svg.querySelectorAll('.pth-edge')) p.classList.remove('pth-reach', 'pth-hop');
  for (const el of nodesEl.querySelectorAll('.pth-node')) el.classList.remove('pth-lit', 'pth-focus');
  for (const el of legendEl.querySelectorAll('.pth-lg-trace, .pth-lg-svc')) el.remove();
}

/** Let a traced hop go. If a service card put us here, that view is what the
    diagram goes back to — reopening restores it exactly, marks and legend
    line and all, rather than leaving the service you arrived to inspect dark. */
function releaseTrace() {
  clearTrace();
  if (lastFocus) open(lastFocus.focusId, lastFocus.reachIds, lastFocus.serviceLabel);
}

function build() {
  // off_map places are charted but not drawn — and THE PATH is a drawing.
  // Filtering here is enough for the roads too: the edge loop below requires
  // both endpoints to have a position, so their routes drop out with them.
  const nodes = A.DATA.nodes.filter((n) => !n.off_map);
  const feed = A.signalsFeed?.nodes || {};

  // lay tiers out on a normalized 100×100 grid
  const { tiers, pos } = layout(nodes);

  // Tell the CSS how many columns the busiest tier needs, so the table can be
  // sized to the REALM rather than to the window. These x's are percentages of
  // .pth-body, and .pth-body used to be the whole viewport: on a wide monitor a
  // two-node tier planted its pair a third of the screen apart and the diagram
  // changed shape every time the window did. Capping the body at
  // widest-tier × one column keeps the spacing honest and stops the resize
  // from restyling the realm. Narrow windows still win — the cap is a max.
  root.style.setProperty('--pth-cols', String(Math.max(...tiers.map((t2) => t2.length), 1)));

  // edges: routes[] + parent containment (drawn quieter)
  const edges = edgesOf(A.DATA.routes, nodes, pos);

  svg.setAttribute('viewBox', '0 0 100 100');
  svg.setAttribute('preserveAspectRatio', 'none');
  svg.innerHTML = '';
  for (const e of edges) {
    const a = pos[e.a], b = pos[e.b];
    const my = (a.y + b.y) / 2;
    const d = `M ${a.x} ${a.y} C ${a.x} ${my}, ${b.x} ${my}, ${b.x} ${b.y}`;
    const p = document.createElementNS(SVGNS, 'path');
    p.setAttribute('d', d);
    const st = feed[e.b]?.state;
    p.setAttribute('class',
      `pth-edge pth-k-${e.kind}${st === 'down' ? ' pth-dark' : st === 'degraded' ? ' pth-warn' : ''}`);
    p.dataset.a = e.a;
    p.dataset.b = e.b;
    svg.appendChild(p);
    // the click target — a 1.4px line is not one. Same `d`, fat transparent
    // stroke, drawn after so it sits above its own ink but paints nothing.
    // A hop nobody's road crosses gets no twin at all: an inert cursor is a
    // truer signal than a pointer that promises something and then shrugs.
    const crossing = servicesCrossing(A.DATA.nodes, e.a, e.b);
    if (!crossing.length) continue;
    const hit = document.createElementNS(SVGNS, 'path');
    hit.setAttribute('d', d);
    hit.setAttribute('class', 'pth-hit');
    hit.dataset.a = e.a;
    hit.dataset.b = e.b;
    const title = document.createElementNS(SVGNS, 'title');
    title.textContent = crossing.length === 1
      ? `${crossing[0].link.label} crosses here — click to trace its route`
      : `${crossing.length} services cross here — click to trace their routes`;
    hit.appendChild(title);
    hit.addEventListener('click', (ev) => {
      ev.stopPropagation();
      if (tracedEdge === `${e.a} ${e.b}`) { releaseTrace(); return; }   // click again to release
      traceEdge(e.a, e.b, crossing);
    });
    svg.appendChild(hit);
  }

  nodesEl.innerHTML = nodes.map((n) => {
    const p = pos[n.id];
    const z = zoneById(n.zone);
    const st = feed[n.id]?.state;
    return `<button class="pth-node k-${esc(n.kind || 'vm')}${st ? ' st-' + esc(st) : ''}"
      style="left:${p.x}%;top:${p.y}%;--n-hue:${esc(n.hue || z?.hue || FALLBACK_HUE)}" data-id="${esc(n.id)}">
      <span class="pth-dot"><span class="svc-health ${st ? (A.svcHealthClass[st] || '') : ''}"></span></span>
      <span class="pth-name">${esc(n.name)}</span>
      <span class="pth-ip">${esc(n.ip && n.ip !== '—' ? n.ip : (n.kind === 'network' ? 'beyond' : ''))}</span>
    </button>`;
  }).join('');

  for (const b of nodesEl.querySelectorAll('.pth-node')) {
    b.addEventListener('click', (e) => { e.stopPropagation(); close(); A.focusNode(b.dataset.id); });
  }

  legendEl.innerHTML =
    `<span class="pth-lg"><i class="pth-lg-line pth-k-wan"></i>wan</span>` +
    `<span class="pth-lg"><i class="pth-lg-line pth-k-edge"></i>edge</span>` +
    `<span class="pth-lg"><i class="pth-lg-line pth-k-vlan"></i>vlan</span>` +
    `<span class="pth-lg"><i class="pth-lg-line pth-k-mesh"></i>mesh (Tailscale)</span>` +
    `<span class="pth-lg"><i class="pth-lg-line pth-k-telemetry"></i>telemetry</span>` +
    `<span class="pth-lg"><i class="pth-lg-line pth-k-vassal"></i>${say('vassal of the hypervisor')}</span>` +
    `<span class="pth-lg pth-lg-note">◇ iron · ○ vm · ◈ ways — click any to fly there</span>`;
}

function open(focusId, reachIds, serviceLabel) {
  if (!root) return;
  build();   // rebuild each open — cheap, and live states stay current
  tracedEdge = null;                 // build() just threw away the traced edges
  root.classList.add('open');
  root.setAttribute('aria-hidden', 'false');
  root.classList.toggle('pth-focus-mode', !!focusId);
  // remember WHO dimmed the diagram. Releasing a traced hop must restore the
  // service card's focus view rather than clearing it — arriving from a card
  // and clicking a hop twice should leave you where you arrived, not on a flat
  // diagram with the service you came to look at no longer lit.
  if (focusId) root.dataset.svcFocus = focusId; else delete root.dataset.svcFocus;
  lastFocus = focusId ? { focusId, reachIds, serviceLabel } : null;
  A.closeCard?.();
  // arriving from a service card: halo the host, light its reach web,
  // and dim everything the service can't touch
  if (focusId) {
    const host = nodesEl.querySelector(`.pth-node[data-id="${CSS.escape(focusId)}"]`);
    if (host) host.classList.add('pth-focus');
    const reach = new Set(reachIds || []);
    for (const id of reach) {
      const n = nodesEl.querySelector(`.pth-node[data-id="${CSS.escape(id)}"]`);
      if (n) n.classList.add('pth-lit');
    }
    // A road's middle edges join two hops, not the host and a hop — so when the
    // card hands over an ordered `path` (links[].path), light every consecutive
    // pair as well. Without this, THE PATH lit gateway→edge only if the
    // service happened to live on one of them, and a five-hop road showed as
    // one lit edge and four orphaned dots.
    const chain = Array.isArray(reachIds) ? [focusId, ...reachIds] : [focusId];
    const consecutive = chainPairs(chain, '\0');
    for (const p of svg.querySelectorAll('.pth-edge')) {
      const { a, b } = p.dataset;
      if ((a === focusId && reach.has(b)) || (b === focusId && reach.has(a))
          || consecutive.has(`${a}\0${b}`)) {
        p.classList.add('pth-reach');
      }
    }
    if (serviceLabel) {
      legendEl.insertAdjacentHTML('afterbegin',
        `<span class="pth-lg pth-lg-svc">◈ the reach of <strong>${esc(serviceLabel)}</strong> from its home</span>`);
    }
  }
}
function close() {
  if (!root) return;
  // a trace is a selection inside this scene, not a thing to find still lit on
  // the next open — and lastFocus must go with it, or reopening THE PATH from
  // the scene switcher would silently restore a service view nobody asked for
  tracedEdge = null;
  lastFocus = null;
  root.classList.remove('open');
  root.setAttribute('aria-hidden', 'true');
  A.setSceneActive?.('atlas');
}
A.openPath = open;
A.closePath = close;

A.buildPathScene = function buildPathScene() {
  root = $('path');
  if (!root) return;
  svg = $('pth-svg');
  nodesEl = $('pth-nodes');
  legendEl = $('pth-legend');
  $('pth-close')?.addEventListener('click', () => { close(); A.recenter?.(true); });
  root.addEventListener('pointerdown', (e) => { if (e.target === root) close(); });
};
