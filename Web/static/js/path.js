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
import { chainPairs, edgePath, edgesOf, layout, servicesCrossing } from './path-model.js';
import { PHONE_MEDIA } from './views-model.js';

const SVGNS = 'http://www.w3.org/2000/svg';
let root, svg, nodesEl, legendEl;

/* A phone (the views' own rule for one, 2026-11-18): the tiers are drawn as
   columns and the scene scrolls downward. This one flag picks the layout here
   and, as `#path.pth-narrow`, the rules that go with it. */
const phone = matchMedia(PHONE_MEDIA);

/* What build() drew and place() last placed: the places, and the width the
   columns were cut for (a phone's columns are cut from measured words, so a
   new width asks again). */
let drawn = [];
let placedWidth = -1;
/* A column is its longest word, the 2px its button is short of the column,
   and 6px of air between one column's word and the next; the air is what
   gives way first when the words are a tight fit. */
const NAME_EDGE = 2;
const NAME_AIR = 6;
/* The names' tracking on a phone, the type's own first (2026-11-19, the
   owner: "fix the 320px breaks too"). Only when the longest words cannot
   stand side by side at the type's own 0.14em is the next step tried, and so
   on to the last: at 320px the demo's map needs 0.12em in the dark scheme and
   0.10em in the light; at 340px and wider nothing changes. */
const NAME_TRACKS = ['0.12em', '0.10em', '0.08em'];

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
  drawn = nodes;

  // edges: routes[] + parent containment (drawn quieter). Which are drawn is
  // settled by which places are, not by where: place() gives every curve its
  // path and every place its point, here and again when the width changes.
  const edges = edgesOf(A.DATA.routes, nodes, layout(nodes).pos);

  svg.setAttribute('viewBox', '0 0 100 100');
  svg.setAttribute('preserveAspectRatio', 'none');
  svg.innerHTML = '';
  for (const e of edges) {
    const p = document.createElementNS(SVGNS, 'path');
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
    const z = zoneById(n.zone);
    const st = feed[n.id]?.state;
    return `<button class="pth-node k-${esc(n.kind || 'vm')}${st ? ' st-' + esc(st) : ''}"
      style="--n-hue:${esc(n.hue || z?.hue || FALLBACK_HUE)}" data-id="${esc(n.id)}">
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

  place();
}

/** What each drawn place needs to be read on a phone, by id, as a share of the
    picture's width out of 100: its longest word (a name breaks at a space or
    after a hyphen, and nowhere else by choice) or its address, whichever is
    wider, in the type the page is drawing them in. Measured on hidden copies,
    since a name already broken has no honest width of its own. `words` is each
    name's longest word in px (2026-11-19): the CSS lets a name of several
    words run to its column's edge only as far as that word must. */
function needsOf() {
  const width = nodesEl.clientWidth;
  if (!width) return { needs: {}, words: {} };
  const items = [];
  for (const b of nodesEl.querySelectorAll('.pth-node')) {
    const name = b.querySelector('.pth-name')?.textContent || '';
    const ip = b.querySelector('.pth-ip')?.textContent || '';
    for (const word of name.replace(/-/g, '- ').split(/\s+/).filter(Boolean)) items.push([b.dataset.id, 'pth-name', word]);
    if (ip) items.push([b.dataset.id, 'pth-ip', ip]);
  }
  const probe = document.createElement('div');
  probe.setAttribute('aria-hidden', 'true');
  probe.style.cssText = 'position:absolute;left:0;top:0;visibility:hidden;pointer-events:none';
  probe.innerHTML = items.map(([, cls, text]) =>
    `<span class="${cls}" style="display:block;width:max-content;white-space:nowrap">${esc(text)}</span>`).join('');
  root.appendChild(probe);
  const needs = {};
  const words = {};
  [...probe.children].forEach((el, i) => {
    const [id, cls] = items[i];
    const px = Math.ceil(el.getBoundingClientRect().width);
    needs[id] = Math.max(needs[id] || 0, (100 * (px + NAME_EDGE)) / width);
    if (cls === 'pth-name') words[id] = Math.max(words[id] || 0, px);
  });
  probe.remove();
  return { needs, words };
}

/** Whether the phone's columns, cut from these needs with no air, leave some
    place narrower than its longest word: the model cuts only when the words
    themselves cannot stand side by side (path-model `columnWidths`). */
function cutsAWord(nodes, needs) {
  const { pos } = layout(nodes, true, needs, 0);
  return nodes.some((n) => (pos[n.id]?.w ?? 100) < (needs[n.id] || 0) - 1e-6);
}

/** Put what build() drew where it belongs: the tiers on a normalized 100×100
    grid, rows on a wide screen, columns on a phone, where the body is cut to
    the busiest tier's rows and scrolls and a column is as wide as its longest
    word needs. Apart from build() so a new width, or a face that arrives late,
    moves the picture without redrawing it: a traced hop, a service's lit
    reach and the legend's lines stay as they are. */
function place() {
  const nodes = drawn;
  const narrow = phone.matches;
  root.classList.toggle('pth-narrow', narrow);
  const width = nodesEl.clientWidth;
  root.style.removeProperty('--pth-track');
  let { needs, words } = narrow ? needsOf() : { needs: {}, words: {} };
  // a word the columns would have to cut: tighten the tracking a step, and
  // measure again, until none is or the last step is reached
  for (const track of narrow ? NAME_TRACKS : []) {
    if (!cutsAWord(nodes, needs)) break;
    root.style.setProperty('--pth-track', track);
    ({ needs, words } = needsOf());
  }
  const { tiers, pos, rows = 1, cols = 1 } = layout(nodes, narrow,
    needs, narrow && width ? (100 * NAME_AIR) / width : 0);
  root.style.setProperty('--pth-rows', String(rows));
  root.style.setProperty('--pth-tiers', String(cols));

  // Tell the CSS how many columns the busiest tier needs, so the table can be
  // sized to the REALM rather than to the window. These x's are percentages of
  // .pth-body, and .pth-body used to be the whole viewport: on a wide monitor a
  // two-node tier planted its pair a third of the screen apart and the diagram
  // changed shape every time the window did. Capping the body at
  // widest-tier × one column keeps the spacing honest and stops the resize
  // from restyling the realm. Narrow windows still win — the cap is a max.
  root.style.setProperty('--pth-cols', String(Math.max(...tiers.map((t2) => t2.length), 1)));

  // an edge and its click target are the same curve
  for (const p of svg.querySelectorAll('path')) {
    const a = pos[p.dataset.a], b = pos[p.dataset.b];
    p.setAttribute('d', edgePath(a, b, narrow, cols));
  }
  for (const b of nodesEl.querySelectorAll('.pth-node')) {
    const p = pos[b.dataset.id];
    b.style.left = `${p.x}%`;
    b.style.top = `${p.y}%`;
    if (narrow) {
      b.style.setProperty('--pth-w', `${p.w}%`);
      b.style.setProperty('--pth-word', `${words[b.dataset.id] || 0}px`);
    } else {
      b.style.removeProperty('--pth-w');
      b.style.removeProperty('--pth-word');
    }
  }
  placedWidth = width;
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
    // on a phone the tiers scroll: the place asked for is brought wholly into
    // sight, once the legend has its line (the legend's height is the body's loss)
    if (host && phone.matches) host.scrollIntoView({ block: 'nearest' });
  }
}
function close() {
  if (!root?.classList.contains('open')) return;   // as scene.js: only an open scene closes
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
  // a phone turned on its side, or a window drawn across the line: redraw what is open
  phone.addEventListener('change', () => {
    if (!root.classList.contains('open')) return;
    open(lastFocus?.focusId, lastFocus?.reachIds, lastFocus?.serviceLabel);
  });
  // a phone's columns are cut from measured words for one width and one face:
  // a phone turned between two widths that are both a phone's never crosses the
  // line above, and a face can arrive after the first drawing, so both ask again
  const again = () => { if (root.classList.contains('open') && phone.matches) place(); };
  if (typeof ResizeObserver === 'function') {
    new ResizeObserver(() => { if (nodesEl.clientWidth !== placedWidth) again(); }).observe(nodesEl);
  }
  document.fonts?.addEventListener?.('loadingdone', again);
  // and for one scheme (2026-11-19): a light name wears a plate the dark one
  // does not, so a pick, the T key or the OS turning to dark while the scene is
  // up asks again; all three move only <html data-scheme>
  if (typeof MutationObserver === 'function') {
    new MutationObserver(again).observe(document.documentElement, { attributes: true, attributeFilter: ['data-scheme'] });
  }
};
