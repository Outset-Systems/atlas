/* Atlas — the living layer: poll /api/signals and let the map breathe
   with the real health of the realm.

   Principle: the map never dies with its sources. Healthy — and
   *no signal at all* — is the untouched v1.0.0 look (zone-hue breathing). Only
   trouble repaints: amber for degraded, a slow red pulse + beacon for the dark,
   grey for the slumbering. If the feed can't be read, the map goes quietly static
   and the colophon whispers "the watchers are silent" — never an error. */

import { A, CFG, $, esc, themeText } from './config.js';

const STATE_CLASS = { degraded: 's-degraded', down: 's-down', slumbering: 's-slumber', maintenance: 's-maint' };
// A place that is down *behind* something else that is down keeps its red — it
// genuinely is down — but drops the beacon, so one fault raises one flare
// instead of ten. See Web/dependencies.py.
const CAUSED_CLASS = 's-caused';
const ALL_STATE_CLASSES = Object.values(STATE_CLASS);
// full hue swap by state (inline style beats the CSS class, so we set it here).
// The map is a night map in both schemes (atlas.css THE LIGHT SCHEME), so the
// semantic vars are resolved ONCE instead of a getComputedStyle per marker per
// poll (2026-07-11 perf pass).
const STATE_VAR = { down: '--sem-down', degraded: '--sem-warn', slumbering: '--sem-slumber', maintenance: '--sem-warn' };
let _hueCache = null;
function stateHue(state) {
  if (!_hueCache) {
    const cs = getComputedStyle(document.body);
    _hueCache = {};
    for (const [st, v] of Object.entries(STATE_VAR)) _hueCache[st] = cs.getPropertyValue(v).trim() || '#fb4934';
  }
  return _hueCache[state] || '#fb4934';
}
/* THE CONSTELLATION paints its own dots by health too, and must use these exact
   colours — one alarm language for the whole map, resolved once. */
A.stateHue = stateHue;
const colophon = $('colophon');
const COLOPHON_DEFAULT = colophon ? colophon.textContent : themeText('colophon', '— charted by Atlas —');

let misses = 0;
let live = false;          // have we ever successfully applied a feed?
A.signalsFeed = null;      // latest feed, so the card can show uptime (K5)
// Source health is kept SEPARATE from the feed: goStatic() nulls signalsFeed,
// but "which sources are silent" is exactly what you want to read at that
// moment. Settings surfaces these (null = the server itself is unreachable).
A.signalsSources = null;   // { kuma: 'ok' | 'silent', ... }
A.signalsAt = 0;           // Date.now() of the last successful read

const markersEl = () => $('markers');

const SVC_HEALTH_CLASS = {
  healthy: 'h-up', degraded: 'h-degraded', down: 'h-down',
  maintenance: 'h-maint', slumbering: 'h-slumber',
};
// The one state→dot-class map for the whole app, exported like its sibling
// A.stateHue — the card, the Index, THE LEDGER and THE PATH all read this
// instead of keeping a private copy (they had drifted into five identical ones).
A.svcHealthClass = SVC_HEALTH_CLASS;

/** Paint per-service health dots (K4) on any [data-kuma] element from the feed.
    Called on every poll and whenever a card/list is (re)built. */
A.paintServiceHealth = function paintServiceHealth(rootEl) {
  const svcs = A.signalsFeed?.services || {};
  for (const el of (rootEl || document).querySelectorAll('.svc-health[data-kuma]')) {
    const st = svcs[el.dataset.kuma]?.state;
    el.className = 'svc-health' + (st ? ' ' + (SVC_HEALTH_CLASS[st] || '') : '');
    el.title = st ? `health: ${st}` : 'no monitor data';
  }
};

/** Apply a feed to the markers + colophon. Pure DOM, never throws. */
function apply(feed) {
  A.signalsFeed = feed;
  const nodes = feed?.nodes || {};
  let dark = 0;            // faults that are their own cause
  let caused = 0;          // faults explained by one of those
  const darkNames = [];

  for (const mk of markersEl().children) {
    const info = nodes[mk.dataset.id];
    mk.classList.remove(...ALL_STATE_CLASSES, CAUSED_CLASS);
    mk.title = '';   // "behind …" belongs to one poll, not to the marker forever
    if (!info || !info.state || info.state === 'healthy') {
      restoreBase(mk);
      continue;
    }
    const cls = STATE_CLASS[info.state];
    if (cls) mk.classList.add(cls);
    const sh = stateHue(info.state) || mk.dataset.hue;         // fully recolour (blue → red, etc.)
    mk.style.setProperty('--mk-hue', sh);
    mk.style.setProperty('--mk-glow', sh + '66');
    if (info.state === 'down') {
      if (info.cause) {
        // a consequence: still red, but not its own alarm
        caused++;
        mk.classList.add(CAUSED_CLASS);
        mk.title = `behind ${info.cause}`;
      } else {
        dark++;
        const label = mk.querySelector('.mk-label');
        if (label) darkNames.push(label.textContent);
      }
    }
  }

  A.paintServiceHealth();   // K4 — refresh per-service dots
  A.paintConstellationHealth?.();   // a split ring reddens where it stands
  A.paintDecoys?.();       // the decoy feed eyes follow the same poll
  A.paintRoutes?.();        // amber-in the roads that lead to trouble
  A.refreshStonesScene?.(); // a stone that starts speaking lights up where it
                            // stands, even with the list already open — the
                            // scene where a stale "all quiet" is the worst lie
                            // (it was defined for this
                            // and never called, so the list went stale for 30s
                            // exactly when it mattered most). No-op when shut.
  paintDrift(feed?.drift);  // Z3 — surface monitors not yet on the map

  // K3 — the colophon becomes a beacon: warn when places are dark. It counts
  // CAUSES, not craters: "the gateway fell, and nine places with it" is one
  // thing to go and fix, where "ten places are dark" is ten.
  if (colophon) {
    if (dark > 0) {
      // "it" or "them" follows the number of CAUSES, not of consequences:
      // one dead hypervisor with six vassals behind *it*, not behind *them*.
      const behind = caused
        ? ` — ${caused} place${caused === 1 ? '' : 's'} behind ${dark === 1 ? 'it' : 'them'}`
        : '';
      colophon.textContent = dark === 1
        ? `⚠ ${darkNames[0]} has gone dark${behind}`
        : `⚠ ${dark} places are dark${behind}`;
      colophon.classList.add('alarm');
    } else if (caused > 0) {
      // every fault is explained by something that is no longer faulted —
      // rare, but saying nothing at all would be wrong
      colophon.textContent = `⚠ ${caused} place${caused === 1 ? '' : 's'} still unreachable`;
      colophon.classList.add('alarm');
    } else {
      colophon.textContent = COLOPHON_DEFAULT;
      colophon.classList.remove('alarm');
    }
  }
}

/* Z3 survey drift — a quiet chip when Kuma watches services the map hasn't charted.

   ⚑ It used to read "the survey is stale", which was wrong twice over. This is a
   COVERAGE fact, not an age one: nothing here is stale, something is simply
   missing from the map. And `card.js` uses that exact phrase for a genuinely
   different thing — a machine whose weekly PATCH survey is old — so one wording
   stood for two unrelated states. Reworded 2026-08-26 to say what it means.
   (`card.js` keeps the phrase; there it is accurate.) */
const driftNote = $('drift-note');
function paintDrift(drift) {
  if (!driftNote) return;
  const list = drift?.uncharted || [];
  if (!list.length) { driftNote.hidden = true; return; }
  $('drift-count').textContent = String(list.length);
  $('drift-list').innerHTML = list.map((n) => `<span class="drift-item">${esc(n)}</span>`).join('');
  const arriving = driftNote.hidden;
  driftNote.hidden = false;
  if (arriving) wakeDrift();     // only on arrival: every poll lands here
}
/* It says its piece and goes (owner, 2026-11-01): fully clear by six seconds, and
   back when the view returns to the middle of the map (world.js updateShades).
   `.resting` is separate from `hidden`, which the poll keeps setting. It waits
   under the pointer and while the list is open, and `mouseleave` restarts it. */
let driftTimer = null;
function wakeDrift() {
  if (!driftNote || driftNote.hidden) return;
  driftNote.classList.remove('resting');
  clearTimeout(driftTimer);
  driftTimer = setTimeout(() => {
    if (!driftNote.matches(':hover') && !driftNote.classList.contains('open')) {
      driftNote.classList.add('resting');
    }
  }, CFG.DRIFT_REST_MS);
}
A.wakeDrift = wakeDrift;
driftNote?.addEventListener('mouseleave', wakeDrift);
driftNote?.addEventListener('click', () => {
  const l = $('drift-list');
  l.hidden = !l.hidden;
  driftNote.classList.toggle('open', !l.hidden);
  if (l.hidden) wakeDrift();
});

/** A marker's resting look: its zone hue and glow, no state colour over it. */
function restoreBase(mk) {
  mk.style.setProperty('--mk-hue', mk.dataset.hue);
  mk.style.setProperty('--mk-glow', mk.dataset.hue + '55');
}

/** Wipe all live state — the map returns to its static self. */
function goStatic(note) {
  for (const mk of markersEl().children) {
    mk.classList.remove(...ALL_STATE_CLASSES, CAUSED_CLASS);
    mk.title = '';
    restoreBase(mk);   // the inline state hue goes too, not just the class
  }
  A.signalsFeed = null;
  A.paintServiceHealth?.();   // clear service dots too
  A.paintRoutes?.();          // roads back to their resting VLAN colours
  A.paintDecoys?.();         // the eyes grey out — the watch cannot be heard
  paintDrift(null);           // drop the drift chip too
  if (colophon) {
    colophon.classList.remove('alarm');
    colophon.classList.toggle('silent', Boolean(note));
    colophon.textContent = note || COLOPHON_DEFAULT;
  }
}

async function poll() {
  try {
    const res = await fetch('api/v2/signals', { cache: 'no-store' });
    if (!res.ok) throw new Error(`signals ${res.status}`);
    const feed = await res.json();
    const sources = feed.sources || {};
    const anyLive = Object.values(sources).some((s) => s === 'ok');
    misses = 0;
    A.signalsSources = sources;   // kept even when we fall through to goStatic()
    A.signalsAt = Date.now();
    if (!anyLive) {
      // server reachable but no source is reporting — the watchers are silent
      goStatic(live ? themeText('silent', '— the watch is silent —') : null);
      return;
    }
    live = true;
    apply(feed);
  } catch (err) {
    // never surface an error onto the map; fade to static after a few misses
    A.signalsSources = null;      // the server itself is unreachable, not a source
    if (++misses >= CFG.SIGNALS_MAX_MISSES && live) {
      goStatic(themeText('silent', '— the watch is silent —'));
      live = false;
    }
  }
}

/** Poll once, right now — used after a change that alters the feed (opening a
    maintenance window should grey the marker without waiting 30s). */
A.refreshSignals = function refreshSignals() { return poll(); };

/** Re-apply the last feed to freshly built markers.
    An edit rebuilds the world, which throws away every marker's live state —
    without this, saving a change makes the whole map look healthy until the
    next 30-second poll. */
A.repaintSignals = function repaintSignals() {
  if (A.signalsFeed) apply(A.signalsFeed);
};

/** Begin the heartbeat. Called by boot once the world exists. */
A.startSignals = function startSignals() {
  if (!CFG.SIGNALS_POLL_MS) return;   // polling disabled
  poll();                             // first read immediately
  setInterval(poll, CFG.SIGNALS_POLL_MS);
};

/** Uptime string for the card (K5), or '' when unknown. */
A.nodeUptime = function nodeUptime(id) {
  const info = A.signalsFeed?.nodes?.[id];
  if (!info || typeof info.uptime_30d !== 'number') return '';
  return `${info.uptime_30d.toFixed(2)}% · 30d`;
};
