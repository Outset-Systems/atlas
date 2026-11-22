
import './visit.js';
import { A, REDUCED, $, esc } from './config.js';
import './scheme.js';
import { panFloor } from './camera-model.js';
import './views.js';
import './table.js';
import './camera.js';
import './world.js';
import './ui.js';
import './card.js';
import './account.js';
import './glass.js';
import './palette.js';
import './signals.js';
import './reliquary.js';
import './tribute.js';
import './ledger.js';
import './path.js';
import './calendar.js';
import './seals.js';
import './stones.js';
import './annals.js';
import './accounts-scene.js';
import './trust.js';
import './whois.js';
import './decoys.js';
import './regions.js';
import { applyOverrides } from './places.js';
import './map-editor.js';
import './location-set.js';
import './map-box.js';
import './map-resize.js';
import './band-menus.js';
import './nodes.js';
import './overview.js';
import './topology.js';
import './alert-setup.js';
import './editor/index.js';

const mapBase = $('map-base');
const stage = $('stage');

async function loadData() {
  const [res, cat] = await Promise.all([
    fetch('api/v2/lab-data', { cache: 'no-cache' }),
    fetch('api/v2/charts', { cache: 'no-cache' }).catch(() => null),
  ]);
  if (!res.ok) throw new Error(`lab-data ${res.status}`);
  const data = await res.json();
  if (data.error) throw new Error(data.error);
  A.DATA = data;
  dispatchEvent(new CustomEvent('atlas:data'));
  A.CHARTS = {};
  try {
    if (cat?.ok) for (const e of (await cat.json()).charts || []) if (e.available) A.CHARTS[e.key] = e;
  } catch (e) { console.warn('chart catalogue unreadable — watchings will frame Grafana', e); }
}

A.refreshData = async function refreshData() {
  await loadData();
  if (!A.VIEW || A.VIEW === 'map') drawWorld();
  else {
    applyOverrides();
    worldStale = true;
  }
  A.buildUI();
  A.buildPalette();
  A.repaintSignals?.();
};

let worldStale = false;
function drawWorld() {
  worldStale = false;
  A.buildWorld();
  A.paintRoutes?.();
}
addEventListener('atlas:view', (e) => {
  if (e.detail?.view !== 'map' || !worldStale) return;
  drawWorld();
  A.repaintSignals?.();
  A.measureWorld?.();
});

A.sizeWorld = function sizeWorld(src, w, h) {
  if (src) mapBase.setAttribute('src', src);
  A.MAPW = w;
  A.MAPH = h;
  stage.style.width = w + 'px';
  stage.style.height = h + 'px';
  $('overlay').setAttribute('viewBox', `0 0 ${w} ${h}`);
  A.cam.min = panFloor(innerWidth, w, A.cam.min);
};

async function boot() {
  document.body.classList.add('pre');

  await loadData();

  await new Promise((ok) => {
    if (mapBase.complete && mapBase.naturalWidth) return ok();
    mapBase.addEventListener('load', ok, { once: true });
    mapBase.addEventListener('error', ok, { once: true });
  });
  A.sizeWorld(null, mapBase.naturalWidth || 2048, mapBase.naturalHeight || 2048);

  A.buildWorld();
  A.buildUI();
  A.measureWorld();
  A.buildGlass();
  A.buildPalette();
  A.buildReliquary();
  A.buildTributeScene();
  A.buildLedgerScene();
  A.buildPathScene();
  A.buildCalendarScene();
  A.buildSealsScene();
  A.buildStonesScene();
  A.buildAnnalsScene();
  A.buildAccountsScene();
  A.buildTrustScene();
  A.startSignals();

  if (REDUCED) {
    A.home(false);
  } else {
    A.cam.k = A.fitScale() * 1.5;
    A.cam.x = innerWidth / 2 - A.MAPW * A.cam.k * 0.5;
    A.cam.y = innerHeight / 2 - A.MAPH * A.cam.k * 0.42;
    A.clampCam();
    A.apply(false);
  }

  const veil = $('veil');
  const lift = () => {
    veil.classList.add('lifted');
    if (!REDUCED) requestAnimationFrame(() => setTimeout(() => A.home(true), 60));
    setTimeout(() => document.body.classList.remove('pre'), REDUCED ? 300 : 1600);
  };
  setTimeout(lift, REDUCED ? 250 : 2900);
  veil.addEventListener('click', lift, { once: true });
}

boot().catch(err => {
  console.error('atlas boot failed:', err);
  $('veil').innerHTML =
    `<div class="veil-inner veil-fail"><div class="veil-title">THE SURVEY COULD NOT BE READ</div>` +
    `<p>${esc(String(err))}</p></div>`;
});
