
import { A, CFG, $, esc, themeText, HEALTH_DOT } from './config.js';
import { tally, colophonText, colophonLook } from './signals-model.js';

const STATE_CLASS = { degraded: 's-degraded', down: 's-down', slumbering: 's-slumber', maintenance: 's-maint' };
const CAUSED_CLASS = 's-caused';
const ALL_STATE_CLASSES = Object.values(STATE_CLASS);
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
A.stateHue = stateHue;
const colophon = $('colophon');
const COLOPHON_DEFAULT = colophon ? colophon.textContent : themeText('colophon', '— charted by Atlas —');

let misses = 0;
let live = false;
A.signalsFeed = null;
A.signalsSources = null;
A.signalsAt = 0;

const markersEl = () => $('markers');

const SVC_HEALTH_CLASS = HEALTH_DOT;
A.svcHealthClass = SVC_HEALTH_CLASS;

A.paintServiceHealth = function paintServiceHealth(rootEl) {
  const svcs = A.signalsFeed?.services || {};
  for (const el of (rootEl || document).querySelectorAll('.svc-health[data-kuma]')) {
    const st = svcs[el.dataset.kuma]?.state;
    el.className = 'svc-health' + (st ? ' ' + (SVC_HEALTH_CLASS[st] || '') : '');
    el.title = st ? `health: ${st}` : 'no monitor data';
  }
};

function apply(feed) {
  A.signalsFeed = feed;
  const nodes = feed?.nodes || {};
  const darkNames = [];
  const unmanaged = new Set(Array.isArray(feed?.unmanaged) ? feed.unmanaged : []);

  for (const mk of markersEl().children) {
    const info = nodes[mk.dataset.id];
    mk.classList.remove(...ALL_STATE_CLASSES, CAUSED_CLASS);
    mk.classList.toggle('s-unmanaged', unmanaged.has(mk.dataset.id));
    mk.title = '';
    if (!info || !info.state || info.state === 'healthy') {
      restoreBase(mk);
      continue;
    }
    const cls = STATE_CLASS[info.state];
    if (cls) mk.classList.add(cls);
    const sh = stateHue(info.state) || mk.dataset.hue;
    mk.style.setProperty('--mk-hue', sh);
    mk.style.setProperty('--mk-glow', sh + '66');
    if (info.state === 'down' && info.cause) {
      mk.classList.add(CAUSED_CLASS);
      mk.title = `behind ${info.cause}`;
    }
  }
  const charted = (A.DATA?.nodes || []).filter((n) => !n.off_map);
  for (const n of charted) {
    const info = nodes[n.id];
    if (info?.state === 'down' && !info.cause) darkNames.push(n.name);
  }
  const { dark, caused } = tally(charted.map((n) => n.id), nodes);

  A.paintServiceHealth();
  A.paintConstellationHealth?.();
  A.paintDecoys?.();
  A.paintRoutes?.();
  A.paintFolds?.();
  A.paintTopology?.();
  A.refreshStonesScene?.();
  paintDrift(feed?.drift);

  if (colophon) {
    paintColophon(colophonLook({ warning: colophonText(dark, caused, darkNames[0]), fallback: COLOPHON_DEFAULT }));
  }
}

const driftNote = $('drift-note');
function paintDrift(drift) {
  if (!driftNote) return;
  const list = drift?.uncharted || [];
  if (!list.length) { driftNote.hidden = true; return; }
  $('drift-count').textContent = String(list.length);
  $('drift-list').innerHTML = list.map((n) => `<span class="drift-item">${esc(n)}</span>`).join('');
  const arriving = driftNote.hidden;
  driftNote.hidden = false;
  if (arriving) wakeDrift();
}
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

function restoreBase(mk) {
  mk.style.setProperty('--mk-hue', mk.dataset.hue);
  mk.style.setProperty('--mk-glow', mk.dataset.hue + '55');
}

function goStatic(note) {
  for (const mk of markersEl().children) {
    mk.classList.remove(...ALL_STATE_CLASSES, CAUSED_CLASS);
    mk.title = '';
    restoreBase(mk);
  }
  A.signalsFeed = null;
  A.paintServiceHealth?.();
  A.paintRoutes?.();
  A.paintFolds?.();
  A.paintTopology?.();
  A.paintDecoys?.();
  paintDrift(null);
  if (colophon) paintColophon(colophonLook({ silentNote: note, fallback: COLOPHON_DEFAULT }));
}

function paintColophon(look) {
  colophon.textContent = look.text;
  colophon.classList.toggle('alarm', look.alarm);
  colophon.classList.toggle('silent', look.silent);
}

async function poll() {
  try {
    const res = await fetch('api/v2/signals', { cache: 'no-store' });
    if (!res.ok) throw new Error(`signals ${res.status}`);
    const feed = await res.json();
    const sources = feed.sources || {};
    const anyLive = Object.values(sources).some((s) => s === 'ok');
    misses = 0;
    A.signalsSources = sources;
    A.signalsAt = Date.now();
    if (!anyLive) {
      goStatic(live ? themeText('silent', '— the watch is silent —') : null);
      return;
    }
    live = true;
    apply(feed);
  } catch (err) {
    A.signalsSources = null;
    if (++misses >= CFG.SIGNALS_MAX_MISSES && live) {
      goStatic(themeText('silent', '— the watch is silent —'));
      live = false;
    }
  }
}

A.refreshSignals = function refreshSignals() { return poll(); };

A.repaintSignals = function repaintSignals() {
  if (A.signalsFeed) apply(A.signalsFeed);
};

A.startSignals = function startSignals() {
  if (!CFG.SIGNALS_POLL_MS) return;
  poll();
  setInterval(poll, CFG.SIGNALS_POLL_MS);
};
