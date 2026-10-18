/* Atlas — THE DECOYS: the realm's silent watchers, and which
   of them has spoken.

   A decoy is bait. It has no legitimate caller, so anything that touches
   one is an event rather than a maybe — which is why this scene spends its only
   loud colour on the stones that are speaking and leaves everything else quiet.
   A silent stone is the ordinary case and the one we hope for; it should look
   like the background, not like a result.

   TWO SOURCES, ON PURPOSE. The roster comes from the dataset (`stones[]`) —
   where each stone is planted is a charted fact and survives the decoy feed being
   down. The VOICES come from the live feed (`signals.stones`). So the scene can
   always draw the realm's tripwires, and separately say whether anyone is
   listening to them.

   THE FAILURE THIS SCENE MUST NOT HIDE. "No stone is speaking" and "I cannot
   reach the engine that would tell me" are identical in the data: both are an
   empty `stones` map. `signals.sources.deception` is the only thing that tells
   them apart, so the head reads it and says CONTACT LOST outright. A deception
   layer that cannot say it has lost contact is exactly as useless as one that
   never fires — drawing calm for both would be the single worst thing this
   scene could do. (2026-08-14) */

import { A, $, esc } from './config.js';
import { makeScene } from './scene.js';

let root, listEl, headEl;

/* The three voices, ordered loudest first. A scene about intrusion opens on the
   thing that is happening, never on the inventory. */
const VOICES = {
  speaking: { rank: 0, cls: 'gs-speaking', word: 'SPEAKING' },
  stirred:  { rank: 1, cls: 'gs-stirred',  word: 'stirred' },
  silent:   { rank: 2, cls: 'gs-silent',   word: 'silent' },
};
const UNHEARD = { rank: 1.5, cls: 'gs-unheard', word: 'no word' };

function voiceOf(state) {
  return VOICES[state] || UNHEARD;
}

/* "3 minutes ago" beats an ISO stamp for the one question asked here — how
   fresh is this? The exact stamp stays in the title attribute for anyone who
   needs to correlate against a log. */
function ago(iso) {
  if (!iso) return null;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return null;
  const s = Math.max(0, Math.round((Date.now() - t) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

function stoneHTML(s) {
  const v = voiceOf(s.state);
  const spoke = ago(s.last_spoke);
  const guards = s.host ? `guards <span class="gs-host">${esc(s.host)}</span>` : 'unplaced';
  /* `planted: false` is a charted stone with no token behind it — it CANNOT
     speak. Saying so is the difference between a quiet watcher and one that was
     never actually armed. */
  const armed = s.planted === false
    ? '<span class="gs-flag">not planted — cannot speak</span>' : '';
  const retired = s.retired
    ? '<span class="gs-flag">retired</span>' : '';
  const trips = (s.trips | 0) > 0
    ? `<span class="gs-trips">${s.trips | 0} trip${s.trips === 1 ? '' : 's'}</span>` : '';
  const reason = s.last_reason
    ? `<span class="gs-reason">${esc(s.last_reason)}</span>` : '';

  return `<div class="gs-row ${v.cls}">
    <div class="gs-voice" aria-hidden="true"><span class="gs-dot"></span></div>
    <div class="gs-body">
      <div class="gs-line1">
        <span class="gs-name">${esc(s.name || s.id)}</span>
        <span class="gs-state">${v.word}</span>
      </div>
      <div class="gs-line2">
        <span class="gs-mimics">${esc(s.mimics || s.placement || s.kind || '')}</span>
      </div>
      <div class="gs-line3">
        <span class="gs-meta">${guards}</span>
        <span class="gs-meta gs-zone">${esc(s.zone || '')}</span>
        ${trips}
        ${spoke ? `<span class="gs-spoke" title="${esc(s.last_spoke)}">last spoke ${spoke}</span>` : ''}
        ${reason}
        ${armed}${retired}
      </div>
    </div>
  </div>`;
}

/* The roster is the dataset's; the voices are the feed's. A stone the feed
   knows about but the map has not charted is still shown — the engine is the
   authority on what is planted, and hiding one would be the map deciding a real
   tripwire does not exist. */
function merge() {
  const charted = (A.DATA?.stones || []).filter((s) => s && s.id);
  const live = A.signalsFeed?.stones || {};
  const byId = new Map();

  charted.forEach((s) => byId.set(s.id, { ...s }));
  Object.entries(live).forEach(([id, info]) => {
    byId.set(id, { ...(byId.get(id) || { id }), ...info, id });
  });

  return [...byId.values()].sort((a, z) => {
    const d = voiceOf(a.state).rank - voiceOf(z.state).rank;
    if (d) return d;
    return String(a.name || a.id).localeCompare(String(z.name || z.id));
  });
}

function headHTML(stones) {
  const src = A.signalsSources;
  const reachable = src && src.deception === 'ok';
  const configured = !!(src && 'deception' in src);
  const speaking = stones.filter((s) => s.state === 'speaking').length;
  const metrics = A.signalsFeed?.metrics || {};
  const unattributed = metrics.unattributed_trips | 0;
  const undelivered = metrics.undelivered_alerts | 0;

  /* THE distinction. An empty list under a head that says nothing would read as
     "all quiet" whether or not anyone is listening. */
  if (!configured) {
    return `<div class="gs-head gs-head-dark">
      <span class="gs-verdict">THE WATCH IS NOT SET</span>
      <span class="gs-verdict-sub">No deception source is configured, so the map
        cannot know whether a stone has spoken. The stones below are charted, not
        listened to.</span></div>`;
  }
  if (!reachable) {
    return `<div class="gs-head gs-head-lost">
      <span class="gs-verdict">CONTACT LOST</span>
      <span class="gs-verdict-sub">The watch is not answering. Silence here means
        nothing — a stone could be speaking right now and this map would not know.
        The states below are stale or absent.</span></div>`;
  }

  const line = speaking
    ? `<span class="gs-verdict gs-verdict-loud">${speaking} STONE${speaking > 1 ? 'S' : ''} SPEAKING</span>`
    : '<span class="gs-verdict gs-verdict-calm">ALL QUIET</span>';
  const extras = [];
  if (unattributed) {
    extras.push(`<span class="gs-warn">${unattributed} trip${unattributed > 1 ? 's' : ''}
      from a stone this map has never charted</span>`);
  }
  if (undelivered) {
    extras.push(`<span class="gs-warn">${undelivered} escalation${undelivered > 1 ? 's' : ''}
      reached nobody</span>`);
  }
  return `<div class="gs-head">${line}
    <span class="gs-verdict-sub">the watch is answering${
      extras.length ? '' : ' — nothing has been disturbed'}</span>
    ${extras.join('')}</div>`;
}

function build() {
  if (!listEl) return;
  const stones = merge();
  if (headEl) headEl.innerHTML = headHTML(stones);
  listEl.innerHTML = stones.map(stoneHTML).join('')
    || `<div class="ldg-note">no stones charted — add them in the Desk, and see
        DATA.md for what a stone may safely be called.</div>`;
}

/* Ask for a fresh read on open rather than showing whatever the 30s poll last
   left behind: this is the one scene where a stale "all quiet" is a lie worth
   avoiding. build() runs again when it lands. */
const scene = makeScene({ id: 'stones', closeId: 'gs-close', build: () => A.refreshSignals?.().then(build).catch(() => {}) });
const { open, close } = scene;

A.openStones = open;
A.closeStones = close;
/* Called by the signals poll (signals.js) so an OPEN scene repaints — a stone
   that starts speaking while you are looking at the list should light up where
   it stands, the way a split ring does (v1.10.7). It was defined for that and
   never wired, so the list sat stale for up to 30s in the one scene where that
   is a lie worth avoiding; wired 2026-08-25.

   `build()` replaces the list wholesale, and this now runs on a timer rather
   than only on open — so the reader's scroll position has to survive it, or a
   long roster jumps back to the top under their eyes every poll. */
A.refreshStonesScene = function refreshStonesScene() {
  if (!root?.classList.contains('open')) return;
  const at = listEl?.scrollTop || 0;
  build();
  if (listEl) listEl.scrollTop = at;
};

A.buildStonesScene = function buildStonesScene() {
  root = scene.mount();
  if (!root) return;
  listEl = $('gs-list');
  headEl = $('gs-head');
};
