/* Atlas — THE decoy feed WATCH: the decoys drawn where they
   stand, as a map layer.

   THE DECOYS scene answers "what stones exist and which has spoken" as
   a LIST; this layer answers the map's own version of that question — WHERE
   the watch is. Toggled like the network layer (👁 in the control column, G),
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

import { A, $, esc, themeText } from './config.js';

let on = false;

/* the eye, drawn once — currentColor, so the badge's voice class colours it */
const EYE_SVG =
  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">` +
  `<path d="M2.5 11 C 6 6.4, 18 6.4, 21.5 11 C 18 15.6, 6 15.6, 2.5 11 Z"/>` +
  `<circle cx="12" cy="11" r="3"/>` +
  `<circle cx="12" cy="11" r="1.1" fill="currentColor" stroke="none"/>` +
  `<path d="M12 14.6 L12 19.6 M12 19.6 l-1.7 -1.5"/>` +
  `<path d="M5.6 7.6 L4.2 5.8 M12 6.1 L12 4 M18.4 7.6 L19.8 5.8"/>` +
  `</svg>`;

/* loudest voice wins when a place carries several stones */
const RANK = { speaking: 0, stirred: 1, unheard: 2, silent: 3 };
const voiceOf = (s) => (s in RANK ? s : 'unheard');

/** stones per place: node id → loudest voice + count. Same merge the scene
    does (roster ∪ feed, feed wins), minus retired stones — schema: "they
    leave the map". A stone with no `host` guards nowhere drawable; it still
    counts in the toast so the layer never silently under-reports. */
function watchByNode() {
  const byId = new Map();
  for (const s of A.DATA?.stones || []) if (s?.id) byId.set(s.id, { ...s });
  for (const [id, info] of Object.entries(A.signalsFeed?.stones || {})) {
    byId.set(id, { ...(byId.get(id) || { id }), ...info, id });
  }
  const lost = A.signalsSources ? A.signalsSources.deception !== 'ok' : true;
  const nodes = new Map();
  let unplaced = 0, speaking = 0;
  for (const s of byId.values()) {
    if (s.retired) continue;
    const voice = lost ? 'unheard' : voiceOf(s.state);
    if (voice === 'speaking') speaking++;
    if (!s.host) { unplaced++; continue; }
    const cur = nodes.get(s.host);
    if (!cur || RANK[voice] < RANK[cur.voice]) {
      nodes.set(s.host, { voice, count: (cur?.count || 0) + 1 });
    } else {
      cur.count++;
    }
  }
  return { nodes, unplaced, speaking, total: byId.size, lost };
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
      eye.innerHTML = EYE_SVG;
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
    eye.title = `${esc(String(watch.count))} stone${watch.count === 1 ? '' : 's'} · ${watch.voice} — open THE ${esc(themeText('stones', 'Decoys').toUpperCase())}`;
  }
}
A.paintDecoys = paint;

A.toggleDecoys = function toggleDecoys(force) {
  on = typeof force === 'boolean' ? force : !on;
  document.body.classList.toggle('decoys-on', on);
  $('btn-decoys')?.classList.toggle('lit', on);
  if (!on) return;
  paint();
  // say what the layer is showing the moment it opens — the same three
  // verdicts the scene's head gives, in one line
  const { nodes, unplaced, speaking, total, lost } = watchByNode();
  if (!total) {
    A.showToast?.(`No ${themeText('stones', 'decoys').toLowerCase()} are known — none charted, and ${themeText('decoy_source', 'the decoy feed')} names none.`);
  } else if (lost) {
    A.showToast?.('CONTACT LOST — the watch is not answering. The eyes are drawn from the chart, not the wire.');
  } else if (speaking) {
    A.showToast?.(`${speaking} stone${speaking === 1 ? ' is' : 's are'} SPEAKING — the eyes show where.`);
  } else {
    A.showToast?.(`All quiet — ${nodes.size} place${nodes.size === 1 ? '' : 's'} under the watch` +
      (unplaced ? ` (+${unplaced} stone${unplaced === 1 ? '' : 's'} unplaced)` : '') + '.');
  }
};

$('btn-decoys')?.addEventListener('click', () => A.toggleDecoys());
