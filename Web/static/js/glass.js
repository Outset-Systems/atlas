/* Atlas — THE VIEWING GLASS: a service shown *over* the map instead
   of in a tab you have to come back from.

   Every outward button used to be `target="_blank"`. That is honest — it always
   works — but it ends the session: you leave the world, and the map you were
   reading is now one window behind whatever you went to look at. The glass
   keeps you in the atlas, and falls back to the tab the moment framing won't
   work, which is often. Three separate things decide that:

     1. **Our CSP.** `frame-src` is widened server-side to the origins the
        dataset links to (Web/embeddable.py, ATLAS_EMBED_SERVICES).
     2. **Their X-Frame-Options / frame-ancestors.** Asked once per service via
        `/api/v2/embeddable` and cached. A browser cannot see this for itself: a
        refused frame paints nothing and fires no error a cross-origin parent
        can read, which is why the watchdog below exists as a second line.
     3. **Mixed content.** An http:// service inside an https:// Atlas is dead
        on arrival. Checked here, synchronously, because it is free and certain.

   The rule the whole module obeys: **never take away the tab.** Middle-click,
   ctrl-click and the ⧉ button always open the real thing in a real window, and
   anything the glass cannot show says so and hands you that button. */

import { A, CFG, $, esc, host, isMixed } from './config.js';

/* Verdicts we've learned this session: url -> true (frames) | false (refuses).
   sessionStorage, not local: a dashboard that gains `allow_embedding` should be
   noticed on the next visit, not remembered as broken for a month. */
const MEM_KEY = 'atlas-glass-verdicts';
let memo = {};
try { memo = JSON.parse(sessionStorage.getItem(MEM_KEY) || '{}'); } catch { memo = {}; }
function remember(url, ok) {
  memo[url] = ok;
  try { sessionStorage.setItem(MEM_KEY, JSON.stringify(memo)); } catch { /* private mode */ }
}

const sameOrigin = (abs) => {
  try { return new URL(abs, location.href).origin === location.origin; } catch { return false; }
};
// (`isMixed` lived here as a private one-liner; it is config.js's now, shared
// with the carousels and the card's vitals — 2026-08-21)

/** Open in a real tab. Only ever called straight out of a click, so the popup
    blocker never sees it as programmatic. */
function toTab(abs) {
  window.open(abs, '_blank', 'noopener');
}

/* ── The pane ──────────────────────────────────────────────────────────────── */
let root, frame, titleEl, subEl, noteEl, openEl, urlEl;
let watchdog = 0, current = null;

function clearWatchdog() { clearTimeout(watchdog); watchdog = 0; }

/** Did the frame land? true / false / null = the browser will not say.

    Measured, not assumed (2026-07-31, Chrome): for a **cross-origin** frame,
    a page that rendered, a page blocked by `X-Frame-Options` and a host that
    refused the connection outright are *byte-for-byte identical* from here —
    `load` fires for all three, `contentDocument` is null for all three,
    `contentWindow.length` is 0 for all three. There is no clever probe; the
    same-origin policy is doing exactly its job. An earlier version of this
    file guessed from `about:blank` and would have recorded a dead host as
    "frames fine", so the guess is gone: cross-origin returns null and the
    server's verdict decides. Same-origin is genuinely readable, and that is
    the only case answered here. */
function framePainted(f) {
  try {
    const doc = f.contentDocument;
    if (!doc) return null;                        // cross-origin — unknowable
    if (doc.location && doc.location.href === 'about:blank') return false;
    return Boolean(doc.body && doc.body.childElementCount);
  } catch {
    return null;                                  // cross-origin throw — unknowable
  }
}

function setState(state) {
  if (!root) return;
  root.dataset.state = state;                    // reaching | shown | refused
}

/** Show it, with an optional caveat in the footer. */
function reveal(caveat) {
  clearWatchdog();
  setState('shown');
  if (current && caveat) urlEl.textContent = `${host(current.abs)} · ${caveat}`;
}

/** The glass gives up: say why, and hand over the button that always works. */
function refuse(reason) {
  clearWatchdog();
  if (!current) return;
  remember(current.key, false);
  frame.src = 'about:blank';
  noteEl.innerHTML =
    `<div class="gl-refuse-head">${esc(current.title)} will not be shown here</div>` +
    `<p class="gl-refuse-why">${esc(reason)}. Some services refuse to be drawn ` +
    `inside another page — a sensible thing for them to do, and not something ` +
    `this map can talk them out of.</p>` +
    `<button class="gl-refuse-go" id="gl-refuse-go">OPEN IN A NEW TAB ›</button>`;
  noteEl.querySelector('#gl-refuse-go')
    ?.addEventListener('click', () => { const u = current.abs; close(); toTab(u); });
  setState('refused');
}

function show(entry) {
  current = entry;
  root.hidden = false;
  titleEl.textContent = entry.title || '';
  subEl.textContent = entry.sub || '';
  urlEl.textContent = host(entry.abs);
  openEl.href = entry.abs;
  noteEl.innerHTML = '';
  setState('reaching');
  frame.src = entry.abs;

  // The backstop, not the mechanism. `load` fires even for a refused or dead
  // frame, so this only catches a load that never resolves at all — and if the
  // frame did load while the verdict never arrived, showing it beats hiding it.
  clearWatchdog();
  watchdog = setTimeout(() => {
    if (root.dataset.state !== 'reaching') return;
    if (current?.loaded) reveal('shown without a verdict — the Atlas never got an answer');
    else refuse('it never answered');
  }, CFG.GLASS_TIMEOUT_MS);
}

function close() {
  clearWatchdog();
  current = null;
  if (!root || root.hidden) return;
  root.hidden = true;
  frame.src = 'about:blank';        // stop whatever it was doing behind the map
}
A.closeGlass = close;
A.glassOpen = () => Boolean(root) && !root.hidden;

/** Show `url` inside the map if it will render there, else in a new tab.

    `key` is the dataset's own spelling of the URL — `/api/v2/embeddable` will only
    answer for a URL that is actually on the map, so the raw href is what has to
    be asked about, not the browser's absolutised version. */
A.openHere = function openHere(url, title, opts = {}) {
  const abs = new URL(url, location.href).href;
  const key = opts.key || url;
  const mode = opts.openIn || 'auto';

  // The three synchronous outs. Each one happens inside the click, so the tab
  // opens without a popup fight.
  if (mode === 'tab') return toTab(abs);
  if (mode !== 'here') {
    if (isMixed(abs)) {
      A.showToast?.('That one answers over plain http — a secure page may not draw it. Opened in a new tab.');
      return toTab(abs);
    }
    if (memo[key] === false) return toTab(abs);
  }

  if (!root) return toTab(abs);                  // no glass in the page — never strand the click
  show({ abs, key, title: title || abs, sub: opts.sub || '', loaded: false });

  // Same-origin pages are ours: the frame is readable, so the load event
  // settles it and there is nobody to ask.
  if (sameOrigin(abs)) return;
  // `here` is an operator's explicit instruction (schema: open_in). Honour it
  // without a verdict — they have said they know what this service does.
  if (mode === 'here') return reveal();
  // …and a service this session already framed successfully needs no second
  // opinion: the answer is local, and the server keeps its own 15-min cache
  // for everyone else. sessionStorage scope still means a service that turns
  // hostile is re-noticed on the next visit.
  if (memo[key] === true) return reveal();

  // Everything else: the browser cannot tell us, so ask the service. The frame
  // is already loading in parallel, so a "yes" costs only the round trip.
  fetch('api/v2/embeddable?url=' + encodeURIComponent(key), { cache: 'no-store' })
    .then((r) => (r.ok ? r.json() : null))
    .then((v) => {
      if (!v || current?.key !== key) return;
      if (v.embeddable === false) return refuse(v.reason || 'it refuses to be framed');
      if (v.embeddable === true) { remember(key, true); return reveal(); }
      // Unknown — usually "the Atlas could not reach it". Deliberately NOT a
      // refusal: in this lab the admin VLAN and the DMZ do not see each other
      // symmetrically, so a service the *server* cannot reach is routinely one
      // the *browser* can. The browser's opinion is the one that decides what
      // renders. Shown, said out loud, and not remembered either way.
      reveal(v.reason || 'shown without a verdict');
    })
    .catch(() => { if (current?.key === key) reveal('shown without a verdict'); });
};

/* Every outward anchor in the app carries `data-glass`; this one delegated
   listener is the whole wiring. Modified clicks and middle-clicks are left
   entirely alone, so "open in a new tab" never stops being one gesture away.

   **Capture phase, on the document.** A listener on `window` runs last, so any
   handler between the anchor and the top that called `stopPropagation` would
   silently take the glass off that button and navigate the whole tab away
   instead — a failure that shows up as "this one link is different" months
   later. Capture cannot be pre-empted. Propagation is deliberately NOT stopped:
   the card, the carousel and the viewport all have click handlers of their own
   that must keep behaving exactly as they did. */
document.addEventListener('click', (e) => {
  const a = e.target?.closest?.('a[data-glass]');
  if (!a) return;
  if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  e.preventDefault();
  A.openHere(a.getAttribute('href'), a.dataset.glassTitle || a.textContent.trim(), {
    sub: a.dataset.glassSub || '',
    openIn: a.dataset.openIn || 'auto',
  });
}, true);

A.buildGlass = function buildGlass() {
  root = $('glass');
  if (!root) return;
  frame = $('gl-frame');
  titleEl = $('gl-title');
  subEl = $('gl-sub');
  noteEl = $('gl-note');
  openEl = $('gl-open');
  urlEl = $('gl-url');

  frame.addEventListener('load', () => {
    if (!current || root.dataset.state === 'refused') return;
    if (frame.src === 'about:blank') return;
    current.loaded = true;                        // the watchdog reads this
    const painted = framePainted(frame);
    if (painted === null) return;                 // cross-origin: the verdict decides
    if (painted) { remember(current.key, true); reveal(); }
    else refuse('it refused to be drawn inside another page');
  });

  $('gl-close')?.addEventListener('click', close);
  $('gl-reload')?.addEventListener('click', () => { if (current) show(current); });
  // the ⧉ escape hatch is a plain anchor: let the browser do exactly what it says
  openEl?.addEventListener('click', () => close());
  root.addEventListener('pointerdown', (e) => { if (e.target === root) close(); });
};
