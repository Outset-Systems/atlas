/* Atlas — THE DECOY WATCH: the decoys drawn where they
   stand, as a map layer.

   THE DECOYS scene answers "what stones exist and which has spoken" as
   a LIST; this layer answers the map's own version of that question — WHERE
   the watch is. Toggled with G, or the 👁 among the tools THE ATLAS drops on hover,
   it opens an eye over every place a stone guards: teal and quiet when the
   stone is silent, amber when stirred, alarm-red and pulsing when one is
   SPEAKING, and grey when the watch itself cannot be heard. Places outside
   the watch dim, the same reading the Depths use — what lights up is the
   coverage, and the gaps in it.

   Roster and voices follow the scene's own two-source rule (stones.js): the
   dataset charts where stones are planted (`stones[].host` names the place),
   the live feed says which are speaking, and `signals.sources.deception` is
   the only thing that distinguishes "all quiet" from "nobody is listening" —
   so this layer says CONTACT LOST out loud rather than drawing calm it cannot
   vouch for. Badges are repainted on every signals poll (signals.js calls
   A.paintDecoys), so a stone that starts speaking lights where it stands. */

import { A, $, themeText } from './config.js';
import { say } from './words.js';
import { legacySources, listening, roster, watchByNode as watchModel } from './tripwire-model.js';

let on = false;

/* the mark, drawn once — currentColor, so the badge's voice class colours it.
   Both go in and atlas.css shows one: the eye for a map that asks for it, the bird
   for every other (table.js sets `body.tripwire-eye`). */
const BIRD_SVG =
  `<svg class="tw-bird" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" ` +
  `stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">` +
  `<path d="M6 16 C4.5 12 7 7.5 12 7.5 C14.5 7.5 16.2 9 16.6 10.6 L20 11.4 L16.8 12.8 C16.4 16 13.4 18 10 18 C8.4 18 7 17.4 6 16 Z"/>` +
  `<path d="M8 12.6 C10 11 12.5 11.5 13.5 13.5 C11.5 15 9 14.8 8 12.6 Z"/>` +
  `<path d="M6 16 L2.6 19 M10.4 18 V21 M13 17.6 V21"/>` +
  `<circle cx="13.7" cy="10.2" r="0.9" fill="currentColor" stroke="none"/>` +
  `</svg>`;
const EYE_SVG =
  `<svg class="tw-eye" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">` +
  `<path d="M2.5 11 C 6 6.4, 18 6.4, 21.5 11 C 18 15.6, 6 15.6, 2.5 11 Z"/>` +
  `<circle cx="12" cy="11" r="3"/>` +
  `<circle cx="12" cy="11" r="1.1" fill="currentColor" stroke="none"/>` +
  `<path d="M12 14.6 L12 19.6 M12 19.6 l-1.7 -1.5"/>` +
  `<path d="M5.6 7.6 L4.2 5.8 M12 6.1 L12 4 M18.4 7.6 L19.8 5.8"/>` +
  `</svg>`;

/* Stones per place: node id → loudest voice + count (tripwire-model.js).
   With the admin read (`A.tripwires`, v1.52.0) the states include webhook
   trips and "lost" means a configured source is not answering; without it,
   the chart merged with the decoy feed, as before. Retired ones leave the
   map; a stone with no `host` still counts in the toast so the layer never
   silently under-reports. */
function watchByNode() {
  const ov = A.tripwires || null;
  const rows = roster({ overview: ov, charted: A.DATA?.stones || [], live: A.signalsFeed?.stones || {} });
  const { verdict } = listening(ov?.sources || legacySources(A.signalsSources));
  const lost = verdict !== 'ok';
  return { ...watchModel(rows, lost), lost, waiting: verdict === 'waiting' };
}

/** (Re)paint the eye badges. Runs on toggle, on every signals poll, and after
    a rebuild — cheap either way, and CSS gates visibility on body.decoys-on,
    so painting while the layer is down costs nothing visible. */
function paint() {
  const markers = $('markers');
  if (!markers) return;
  const { nodes } = watchByNode();
  for (const mk of markers.children) {
    const watch = nodes.get(mk.dataset.id);
    let eye = mk.querySelector('.mk-eye');
    mk.classList.toggle('has-stone', Boolean(watch));
    if (!watch) { eye?.remove(); continue; }
    if (!eye) {
      eye = document.createElement('button');
      eye.className = 'mk-eye';
      eye.innerHTML = EYE_SVG + BIRD_SVG;
      // The eye IS the marker while the watch is up (it stands where the dot
      // was, atlas.css), so its click does what the dot's does: centre the
      // map on the place and open its card (2026-09-02). THE GOSSIP
      // STONES scene is one scene-band click away; it used to open from
      // here, which meant the one thing you could not do from an eye was
      // look at the place under it.
      eye.addEventListener('click', (e) => {
        e.stopPropagation();
        A.toggleDrawer?.(false);
        A.focusNode?.(mk.dataset.id, true, false);
      });
      mk.querySelector('.mk-dot')?.appendChild(eye);
    }
    eye.dataset.voice = watch.voice;
    // a DOM property, not markup — no escaping wanted here
    eye.title = `${watch.count} ${say(watch.count === 1 ? 'stone' : 'stones')} · ${watch.voice} — open THE ${say(themeText('stones', 'Decoys')).toUpperCase()}`;
  }
}
/* The signals poll calls this every 30s. While the layer is UP, an admin's
   read is refreshed too (at most every 25s), so a webhook trip lights its eye
   without a reload; while it is down nothing is fetched. */
let lastLoad = 0;
A.paintDecoys = function paintDecoys() {
  paint();
  if (!on || Date.now() - lastLoad < 25000) return;
  lastLoad = Date.now();
  A.loadTripwires?.().then((ov) => { if (ov && on) paint(); });
};

A.toggleDecoys = function toggleDecoys(force) {
  on = typeof force === 'boolean' ? force : !on;
  document.body.classList.toggle('decoys-on', on);
  $('btn-decoys')?.classList.toggle('lit', on);
  if (!on) return;
  paint();
  // an admin's layer also hears the webhook: fetch the read, repaint when it lands
  A.loadTripwires?.().then((ov) => { if (ov && on) paint(); });
  // say what the layer is showing the moment it opens — the same three
  // verdicts the scene's head gives, in one line
  const { nodes, unplaced, speaking, total, lost, waiting } = watchByNode();
  if (!total) {
    A.showToast?.(`No ${say(themeText('stones', 'decoys')).toLowerCase()} are known — none charted, and ${themeText('decoy_source', 'the decoy feed')} names none.`);
  } else if (waiting) {
    A.showToast?.('The webhook has not heard from a sender yet. The marks are drawn from the chart, not the wire.');
  } else if (lost) {
    A.showToast?.('CONTACT LOST — the watch is not answering. The marks are drawn from the chart, not the wire.');
  } else if (speaking) {
    A.showToast?.(`${speaking} ${say(themeText('stones', 'tripwires')).toLowerCase()} ${themeText('tw_lit', 'TRIPPED')} — the marks show where.`);
  } else {
    A.showToast?.(`All quiet — ${nodes.size} place${nodes.size === 1 ? '' : 's'} under the watch` +
      (unplaced ? ` (+${unplaced} ${say(unplaced === 1 ? 'stone' : 'stones')} unplaced)` : '') + '.');
  }
};

$('btn-decoys')?.addEventListener('click', () => A.toggleDecoys());
