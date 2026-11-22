
import { A, $, esc, zoneById, FALLBACK_HUE } from './config.js';
import { say } from './words.js';
import { chainPairs, edgePath, edgesOf, layout, servicesCrossing } from './path-model.js';
import { PHONE_MEDIA } from './views-model.js';
import { awayFrom, locationByKey, locationOfRack, placesFor, rackById } from './locations-model.js';
import { drawPlacePicker, drawRackPicker, markPlace, placeName, whereLine, whereNow } from './scene-places.js';

const SVGNS = 'http://www.w3.org/2000/svg';
let root, svg, nodesEl, legendEl;
let scenePlace = '';
let sceneRack = null;

const phone = matchMedia(PHONE_MEDIA);

let drawn = [];
let placedWidth = -1;
const NAME_EDGE = 2;
const NAME_AIR = 6;
const NAME_TRACKS = ['0.12em', '0.10em', '0.08em'];

let tracedEdge = null;
let lastFocus = null;

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
    p.classList.toggle('pth-hop', p.dataset.a === a && p.dataset.b === b);
  }
  for (const el of nodesEl.querySelectorAll('.pth-node')) {
    el.classList.toggle('pth-lit', litNodes.has(el.dataset.id));
  }

  const names = crossing.map(({ host, link, chain }) =>
    `<span class="pth-lg pth-lg-svc"><strong>${esc(link.label)}</strong>` +
    `<span class="pth-lg-from"> from ${esc(host.name.toLowerCase())}</span>` +
    ` · ${chain.length} stops</span>`).join('');
  legendEl.insertAdjacentHTML('afterbegin',
    `<span class="pth-lg pth-lg-note pth-lg-trace">◈ ${crossing.length} ` +
    `${crossing.length === 1 ? 'route crosses' : 'routes cross'} this hop — click it again to release</span>` + names);
}

function clearTrace() {
  tracedEdge = null;
  if (!root) return;
  root.classList.remove('pth-traced');
  if (!root.dataset.svcFocus) root.classList.remove('pth-focus-mode');
  for (const p of svg.querySelectorAll('.pth-edge')) p.classList.remove('pth-reach', 'pth-hop');
  for (const el of nodesEl.querySelectorAll('.pth-node')) el.classList.remove('pth-lit', 'pth-focus');
  for (const el of legendEl.querySelectorAll('.pth-lg-trace, .pth-lg-svc')) el.remove();
}

function releaseTrace() {
  clearTrace();
  if (lastFocus) open(lastFocus.focusId, lastFocus.reachIds, lastFocus.serviceLabel);
}

function build() {
  const where = whereNow();
  const rack = rackById(where, sceneRack);
  if (!rack) sceneRack = null;
  const loc = rack ? locationOfRack(where, sceneRack) : locationByKey(where, scenePlace);
  scenePlace = loc ? loc.key : '';
  markPlace('path', scenePlace);
  const whereEl = $('pth-where');
  if (whereEl) whereEl.textContent = whereLine(loc, rack);
  drawPlacePicker($('pth-places'), 'path', scenePlace, (key) => setScenePlace(key));
  drawRackPicker($('pth-racks'), 'path', scenePlace, sceneRack, setSceneRack, loc ? `All of ${placeName(loc)}` : 'All');
  const nodes = placesFor(where, loc, A.DATA.nodes, A.DATA.routes, rack).filter((n) => !n.off_map || n._folded);
  const away = awayFrom(where, loc, nodes, rack);
  const awayName = (id) => {
    const other = rack && away.get(id) === loc.key ? rackById(where, where.rackOf.get(id)) : null;
    return other ? other.name : placeName(where.list.find((l) => l.key === away.get(id)));
  };
  const feed = A.signalsFeed?.nodes || {};
  drawn = nodes;

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
      if (tracedEdge === `${e.a} ${e.b}`) { releaseTrace(); return; }
      traceEdge(e.a, e.b, crossing);
    });
    svg.appendChild(hit);
  }

  nodesEl.innerHTML = nodes.map((n) => {
    const z = zoneById(n.zone);
    const st = feed[n.id]?.state;
    const under = away.has(n.id) ? `in ${awayName(n.id)}`
      : (n.ip && n.ip !== '—' ? n.ip : (n.kind === 'network' ? 'beyond' : ''));
    return `<button class="pth-node k-${esc(n.kind || 'vm')}${st ? ' st-' + esc(st) : ''}${away.has(n.id) ? ' pth-away' : ''}"
      style="--n-hue:${esc(n.hue || z?.hue || FALLBACK_HUE)}" data-id="${esc(n.id)}">
      <span class="pth-dot"><span class="svc-health ${st ? (A.svcHealthClass[st] || '') : ''}"></span></span>
      <span class="pth-name">${esc(n.name)}</span>
      <span class="pth-ip">${esc(under)}</span>
    </button>`;
  }).join('');

  for (const b of nodesEl.querySelectorAll('.pth-node')) {
    b.addEventListener('click', (e) => { e.stopPropagation(); close(); A.focusNode(b.dataset.id); });
  }

  legendEl.innerHTML =
    `<span class="pth-lg"><i class="pth-lg-line pth-k-wan"></i>wan</span>` +
    `<span class="pth-lg"><i class="pth-lg-line pth-k-edge"></i>edge</span>` +
    `<span class="pth-lg"><i class="pth-lg-line pth-k-vlan"></i>vlan</span>` +
    `<span class="pth-lg"><i class="pth-lg-line pth-k-mesh"></i>mesh</span>` +
    `<span class="pth-lg"><i class="pth-lg-line pth-k-telemetry"></i>telemetry</span>` +
    `<span class="pth-lg"><i class="pth-lg-line pth-k-vassal"></i>${say('vassal of the hypervisor')}</span>` +
    `<span class="pth-lg pth-lg-note">◇ iron · ○ vm · ◈ ways — click any to fly there</span>`;

  place();
}

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

function cutsAWord(nodes, needs) {
  const { pos } = layout(nodes, true, needs, 0);
  return nodes.some((n) => (pos[n.id]?.w ?? 100) < (needs[n.id] || 0) - 1e-6);
}

function place() {
  const nodes = drawn;
  const narrow = phone.matches;
  root.classList.toggle('pth-narrow', narrow);
  const width = nodesEl.clientWidth;
  root.style.removeProperty('--pth-track');
  let { needs, words } = narrow ? needsOf() : { needs: {}, words: {} };
  for (const track of narrow ? NAME_TRACKS : []) {
    if (!cutsAWord(nodes, needs)) break;
    root.style.setProperty('--pth-track', track);
    ({ needs, words } = needsOf());
  }
  const { tiers, pos, rows = 1, cols = 1 } = layout(nodes, narrow,
    needs, narrow && width ? (100 * NAME_AIR) / width : 0);
  root.style.setProperty('--pth-rows', String(rows));
  root.style.setProperty('--pth-tiers', String(cols));

  root.style.setProperty('--pth-cols', String(Math.max(...tiers.map((t2) => t2.length), 1)));

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

function setScenePlace(key) {
  scenePlace = key || '';
  sceneRack = null;
  markPlace('path', scenePlace);
  if (root?.classList.contains('open')) open();
}

function setSceneRack(rackId) {
  sceneRack = rackId ?? null;
  if (sceneRack === null && whereNow().list.length < 2) scenePlace = '';
  if (root?.classList.contains('open')) open();
}

function open(focusId, reachIds, serviceLabel) {
  if (!root) return;
  if (focusId) { scenePlace = ''; sceneRack = null; }
  build();
  tracedEdge = null;
  root.classList.add('open');
  root.setAttribute('aria-hidden', 'false');
  root.classList.toggle('pth-focus-mode', !!focusId);
  if (focusId) root.dataset.svcFocus = focusId; else delete root.dataset.svcFocus;
  lastFocus = focusId ? { focusId, reachIds, serviceLabel } : null;
  A.closeCard?.();
  if (focusId) {
    const host = nodesEl.querySelector(`.pth-node[data-id="${CSS.escape(focusId)}"]`);
    if (host) host.classList.add('pth-focus');
    const reach = new Set(reachIds || []);
    for (const id of reach) {
      const n = nodesEl.querySelector(`.pth-node[data-id="${CSS.escape(id)}"]`);
      if (n) n.classList.add('pth-lit');
    }
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
    if (host && phone.matches) host.scrollIntoView({ block: 'nearest' });
  }
}
function close() {
  if (!root?.classList.contains('open')) return;
  tracedEdge = null;
  lastFocus = null;
  scenePlace = '';
  sceneRack = null;
  markPlace('path', '');
  root.classList.remove('open');
  root.setAttribute('aria-hidden', 'true');
  A.setSceneActive?.('atlas');
}
A.openPath = open;
A.closePath = close;
addEventListener('atlas:scene-place', (e) => { if (e.detail?.scene === 'path') setScenePlace(e.detail.place); });

A.buildPathScene = function buildPathScene() {
  root = $('path');
  if (!root) return;
  svg = $('pth-svg');
  nodesEl = $('pth-nodes');
  legendEl = $('pth-legend');
  $('pth-close')?.addEventListener('click', () => { close(); A.recenter?.(true); });
  root.addEventListener('pointerdown', (e) => { if (e.target === root) close(); });
  phone.addEventListener('change', () => {
    if (!root.classList.contains('open')) return;
    open(lastFocus?.focusId, lastFocus?.reachIds, lastFocus?.serviceLabel);
  });
  const again = () => { if (root.classList.contains('open') && phone.matches) place(); };
  if (typeof ResizeObserver === 'function') {
    new ResizeObserver(() => { if (nodesEl.clientWidth !== placedWidth) again(); }).observe(nodesEl);
  }
  document.fonts?.addEventListener?.('loadingdone', again);
  if (typeof MutationObserver === 'function') {
    new MutationObserver(again).observe(document.documentElement, { attributes: true, attributeFilter: ['data-scheme'] });
  }
};
