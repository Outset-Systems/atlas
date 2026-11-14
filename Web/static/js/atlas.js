/* Atlas — entry point: load the survey, raise the world, lift the veil.
   Modules: config.js (CFG + shared context A) · camera.js · world.js · ui.js.
   Hub contract: relative paths only. */

import { A, REDUCED, $, esc } from './config.js';
import './scheme.js';   // THE COLOUR SCHEME (v1.52.0): first, so data-scheme stands before any panel opens
import './views.js';    // THE VIEWS (2026-11-13; the Deck, v1.66.0/v1.67.0, is CHARTS): before every sibling, so a page that opens on a view has it first
// table.js FIRST among the siblings: it swaps the backdrop src at import time,
// and boot() below measures whatever src is standing when the image settles
import './table.js';
import './camera.js';
import './world.js';
import './ui.js';
import './card.js';        // the ivory card, extracted from ui.js (ALIVE #7)
import './account.js';     // the account/admin/directory surface (ALIVE #7)
import './glass.js';
import './palette.js';
import './signals.js';
import './reliquary.js';
import './tribute.js';
import './ledger.js';
import './path.js';
import './calendar.js';   // THE CALENDAR — the realm's day: THE RITES and THE FORGE, one page (v1.45.0)
import './seals.js';
import './stones.js';
import './annals.js';
import './accounts-scene.js';   // the ACCOUNTS scene (not account.js — see its header)
import './trust.js';           // THE TRUST scene (generated view; admin only)
import './whois.js';
import './decoys.js';
import './regions.js';   // REGIONS (v1.49.0): after world.js — it wraps buildWorld + onCameraMove
import './nodes.js';     // NODES (2026-11-13): the table view; reads A.VIEW on load and hears `atlas:view`
import './overview.js';  // OVERVIEW (2026-11-13): the facts above the Deck's charts; reads A.VIEW on load too
import './alerts.js';    // ALERTS (2026-11-13, stage 4): rules and destinations, an admin's; reads A.VIEW on load too
import './editor/index.js';

const mapBase = $('map-base');
const stage = $('stage');

async function loadData() {
  // The chart catalogue rides beside the map (v1.35.0): the Chronicle needs
  // to know which watchings it can draw itself BEFORE it builds its slides.
  // A missing or failing catalogue is an empty one — every watching then
  // takes the iframe path it always had, nothing is lost but the ink.
  const [res, cat] = await Promise.all([
    fetch('api/v2/lab-data', { cache: 'no-cache' }),
    fetch('api/v2/charts', { cache: 'no-cache' }).catch(() => null),
  ]);
  if (!res.ok) throw new Error(`lab-data ${res.status}`);
  const data = await res.json();
  if (data.error) throw new Error(data.error);
  A.DATA = data;
  A.CHARTS = {};
  try {
    if (cat?.ok) for (const e of (await cat.json()).charts || []) if (e.available) A.CHARTS[e.key] = e;
  } catch (e) { console.warn('chart catalogue unreadable — watchings will frame Grafana', e); }
}

/** Re-read the map and redraw everything that came from it.
    The Desk calls this after every write, so an edit is visible behind the
    panel the moment it saves — the map is the confirmation. */
A.refreshData = async function refreshData() {
  await loadData();
  A.buildWorld();
  A.buildUI();
  A.buildPalette();
  A.paintRoutes?.();
  A.repaintSignals?.();
};

/** The stage takes a picture of this size. A region's map comes through here too. */
A.sizeWorld = function sizeWorld(src, w, h) {
  if (src) mapBase.setAttribute('src', src);
  A.MAPW = w;
  A.MAPH = h;
  stage.style.width = w + 'px';
  stage.style.height = h + 'px';
  $('overlay').setAttribute('viewBox', `0 0 ${w} ${h}`);
  A.cam.min = innerWidth / w;
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
  A.startSignals();   // begin the heartbeat; degrades to static if no source answers

  // opening shot: start pushed-in, settle to the full survey as the veil lifts.
  // min zoom keeps the map filling the width — never zoom out past its left/right edges.
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
