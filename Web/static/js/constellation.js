
import { A, CFG, $, esc, nodeById, svcKey } from './config.js';
import * as M from './world-model.js';
import { routeBaseHue } from './roads.js';

const SVGNS = 'http://www.w3.org/2000/svg';
const overlay = $('overlay');
const satsEl = $('satellites');

let constellation = null;
A.splitRing = () => constellation;
const conLines = () => overlay.querySelector('#constellation');

const SAT_GREYS = ['#DBD6CB', '#8E877C', '#C3BDB2', '#A49D92', '#CFC9BE', '#7F7A70',
                   '#B6B0A5', '#989187'];
const satGrey = (i) => SAT_GREYS[i % SAT_GREYS.length];

let _svcEntriesData = null, _svcEntriesCache = new Map();
A.serviceEntriesFor = function serviceEntriesFor(id) {
  if (_svcEntriesData !== A.DATA) { _svcEntriesData = A.DATA; _svcEntriesCache = new Map(); }
  const hit = _svcEntriesCache.get(id);
  if (hit) return hit;
  if (!nodeById(id)) return [];
  const entries = M.serviceEntries(A.DATA.nodes, id);
  _svcEntriesCache.set(id, entries);
  return entries;
};

function ringPoints(n, count) {
  return M.ringPoints(n, count, {
    radius: CFG.CONSTELLATION_R,
    twoRing: CFG.CONSTELLATION_TWO_RING,
    outer: CFG.CONSTELLATION_OUTER,
    yScale: A.MAPW / (A.MAPH || A.MAPW),
  });
}

function hitTwin(d, svcIndex, title) {
  const hit = document.createElementNS(SVGNS, 'path');
  hit.setAttribute('d', d);
  hit.setAttribute('class', 'con-hit');
  hit.dataset.svc = String(svcIndex);
  hit.addEventListener('click', (e) => { e.stopPropagation(); focusService(svcIndex, true); });
  if (title) {
    const t = document.createElementNS(SVGNS, 'title');
    t.textContent = title;
    hit.appendChild(t);
  }
  return hit;
}

function drawConstellationLines(n, entries, points, auto) {
  const g = document.createElementNS(SVGNS, 'g');
  g.id = 'constellation';
  const hx = n.x / 100 * A.MAPW, hy = n.y / 100 * A.MAPH;
  points.forEach((p, i) => {
    const { link, passing } = entries[i];
    const sx = p.x / 100 * A.MAPW, sy = p.y / 100 * A.MAPH;
    const hops = Array.isArray(link.path) ? link.path.filter(Boolean).length : 0;
    const tip = `${link.label} — ${hops ? `follow its route, ${hops} hop${hops === 1 ? '' : 's'}`
                                        : 'follow its routes'}`;
    const spokeD = `M ${hx} ${hy} L ${sx} ${sy}`;
    g.appendChild(hitTwin(spokeD, i, tip));
    const spoke = document.createElementNS(SVGNS, 'path');
    spoke.setAttribute('d', spokeD);
    spoke.setAttribute('class', 'con-spoke' + (passing ? ' con-pass' : ''));
    spoke.dataset.svc = String(i);
    spoke.style.setProperty('--con-hue', satGrey(i));
    g.appendChild(spoke);
    for (const tid of (auto ? [] : (link.connects || []).filter((id) => !nodeById(id)?.off_map))) {
      const t = nodeById(tid);
      if (!t) continue;
      const tx = t.x / 100 * A.MAPW, ty = t.y / 100 * A.MAPH;
      const mx = (sx + tx) / 2, my = (sy + ty) / 2 - Math.hypot(tx - sx, ty - sy) * 0.14;
      const d = `M ${sx} ${sy} Q ${mx} ${my} ${tx} ${ty}`;
      g.appendChild(hitTwin(d, i, tip));
      const line = document.createElementNS(SVGNS, 'path');
      line.setAttribute('d', d);
      line.setAttribute('class', 'con-line');
      line.dataset.svc = String(i);
      line.style.setProperty('--con-hue', routeBaseHue(t));
      g.appendChild(line);
    }
  });
  overlay.appendChild(g);
}

function drawSatellites(entries, points) {
  entries.forEach(({ host, link, passing }, i) => {
    const p = points[i];
    const el = document.createElement('div');
    el.className = 'mk mk-sat';
    el.dataset.sat = String(i);
    el.style.left = p.x + '%';
    el.style.top = p.y + '%';
    el.dataset.grey = satGrey(i);
    el.style.setProperty('--mk-hue', satGrey(i));
    el.style.setProperty('--breathe-delay', (i * 0.18).toFixed(2) + 's');
    el.innerHTML =
      `<div class="mk-dot"><div class="mk-ring"></div><div class="mk-core"></div></div>` +
      `<div class="mk-label sat-label">` +
      `<span class="svc-health" data-kuma="${esc(svcKey(link, host.id))}"></span>` +
      `${esc(link.label)}${passing ? `<span class="sat-host"> · ${esc(host.name.toLowerCase())}</span>` : ''}</div>`;
    el.addEventListener('click', (e) => {
      e.stopPropagation();
      focusService(i);
    });
    satsEl.appendChild(el);
  });
  A.paintServiceHealth?.(satsEl);
  A.paintConstellationHealth();
}

A.paintConstellationHealth = function paintConstellationHealth() {
  if (!constellation) return;
  const svcs = A.signalsFeed?.services || {};
  const nodes = A.signalsFeed?.nodes || {};
  const g = conLines();
  constellation.entries.forEach(({ host, link }, i) => {
    const state = svcs[svcKey(link, host.id)]?.state || nodes[host.id]?.state;
    const alarm = (state === 'down' || state === 'degraded') ? A.stateHue?.(state) : null;
    const hue = alarm || satGrey(i);
    const dot = satsEl.querySelector(`.mk-sat[data-sat="${i}"]`);
    if (dot) {
      dot.style.setProperty('--mk-hue', hue);
      dot.style.setProperty('--mk-glow', hue + (alarm ? '66' : '33'));
      dot.classList.toggle('sat-down', state === 'down');
    }
    if (g) {
      for (const p of g.querySelectorAll(`.con-spoke[data-svc="${i}"]`)) {
        p.style.setProperty('--con-hue', hue);
      }
    }
  });
};

function focusService(i, fromRoad) {
  if (!constellation) return;
  const { host, link } = constellation.entries[i];
  for (const el of satsEl.querySelectorAll('.mk-sat')) {
    el.classList.toggle('sat-active', el.dataset.sat === String(i));
  }
  const g = conLines();
  if (g) {
    g.classList.add('con-focus');
    for (const p of g.children) p.classList.toggle('con-lit', p.dataset.svc === String(i));
  }
  A.showServiceDetail?.(host, link);
  if (fromRoad) A.highlightService?.(host, link);
}

export const ringZoom = () => Math.max(A.cam.min, A.fitScale() * CFG.CONSTELLATION_ZOOM);

A.openConstellation = function openConstellation(id, { auto = false } = {}) {
  if (constellation && constellation.id === id) return true;
  A.collapseConstellation();
  const n = nodeById(id);
  const entries = A.serviceEntriesFor(id);
  if (!n || !entries.length) return false;

  if (!auto && !A.netOn()) A.toggleNet(true);

  const points = ringPoints(n, entries.length);
  constellation = { id, entries, points };
  drawConstellationLines(n, entries, points, auto);
  drawSatellites(entries, points);
  document.body.classList.add('constellation');
  if (!auto) A.highlightNode(id);
  const k = ringZoom();
  const a = A.focusAnchor?.(n.x, k);
  if (a) { A.setCardSide?.(a.cardLeft); A.glideTo(n.x, n.y, k, a.x); }
  else A.glideTo(n.x, n.y, k);
  if (!auto) {
    const passing = entries.filter((e) => e.passing).length;
    A.showToast(`${n.name} split into ${entries.length} ${entries.length === 1 ? 'service' : 'services'}` +
      (passing ? ` (${passing} passing through)` : '') + ` — click a service or one of its routes to follow it.`);
  }
  return true;
};

A.toggleConstellation = function toggleConstellation(id) {
  if (constellation && constellation.id === id) {
    A.collapseConstellation();
    return;
  }
  A.openConstellation(id);
};


A.collapseConstellation = function collapseConstellation() {
  if (!constellation) return;
  constellation = null;
  conLines()?.remove();
  satsEl.innerHTML = '';
  document.body.classList.remove('constellation');
};
