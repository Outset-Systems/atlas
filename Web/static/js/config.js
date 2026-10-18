/* Atlas — shared config, context, and helpers.
   All tuning knobs live in CFG; modules attach their public API to A. */

/* may this viewer use the admin write surface? ONE spelling — the server
   enforces regardless; this only decides which chrome is drawn */
export const canAdminWrite = () =>
  CFG.AUTH.admin || document.body.dataset.editable === '1';

export const CFG = {
  // camera (the glide's duration is CSS: `#stage.gliding` in atlas.css)
  ZOOM_MAX: 4,
  ZOOM_WHEEL: 1.18,
  ZOOM_BTN: 1.35,
  ZOOM_KEY: 1.25,
  ZOOM_DBLCLICK: 1.7,
  ZOOM_PULLBACK: 1.45,   // the card's ⊖ — a bigger step than +/−, since it re-centres too
  PAN_KEY_PX: 90,
  WHEEL_PAN: 1.0,        // wheel scrolls vertically (Ctrl+wheel zooms)
  INERTIA_DECAY: 0.92,
  DRAG_THRESHOLD_PX: 3,

  // the world beyond the table — the two shores MIRROR each other (2026-07-12):
  // content anchored 0.48 past either edge, glide target 0.44 past either edge
  VOID_DEPTH: 0.90,      // scrollable blackness below (room to see the whole abyss carousel)
  SKY_NORTH: 0.60,       // scrollable sky above (clouds, Upper Deck, Chronicle head at -0.48)
  DEPTHS_ENGAGE: 1.22,   // auto-descend when view bottom passes this × map height (user
                         // moves only — see checkVoid). 1.22 sits just shy of the abyss
                         // head (1.26): descent begins as the charts arrive, not the
                         // moment the table's edge shows (1.045 was table edge + 4.5%,
                         // inside the bottom-margin of an ordinary split/focus frame)
  DEPTHS_RELEASE: 0.96,  // …and surface again below this (wide hysteresis = no flicker)
  DESCEND_TO: 1.50,      // ☾ glide target — lands ON the abyss charts (head is at 1.26), × map height
  ASCEND_TO: 0.44,       // rise target above the top edge (frames the Chronicle), × map height

  // the floating vision orb (where it hovers; the cloud/islet is pure CSS now)
  MESA_POS: { x: 57.5, y: 27.0 },
  MESA_W: 0.13,          // orb size, × map dimensions
  MESA_H: 0.095,

  // presentation
  ZONE_LABEL_PX: 26,
  ZONE_LABEL_MAX_OPACITY: 0.8,
  CLOSEUP_T: 0.55,       // zoom fraction past which location labels appear
  FOCUS_ZOOM: 2.1,       // × fit scale when gliding to a node
  BREATHE_S: 3.2,
  TOAST_MS: 2600,

  // live signals (the "alive" layer — /api/signals)
  SIGNALS_POLL_MS: 30000,   // matches the server-side 30s cache; 0 disables polling
  SIGNALS_MAX_MISSES: 3,    // consecutive fetch failures before the map goes quietly static

  // THE CONSTELLATION — a place scattered into the services it carries
  CONSTELLATION_R: 4.6,        // ring radius, % of map width (grows past 6 services)
  CONSTELLATION_TWO_RING: 8,   // past this many, alternate dots onto a second ring
  CONSTELLATION_OUTER: 1.55,   // × the base radius, for the alternating outer dots
  CONSTELLATION_ZOOM: 1.35,    // × fit scale — close enough to read, wide enough for the ring

  // THE VIEWING GLASS — a service shown over the map instead of in a new tab
  GLASS_TIMEOUT_MS: 8000,      // silence past this is treated as a refusal to be framed

  // command palette
  PALETTE_MAX: 8,           // results shown at once

  // Chronicle/Abyss: embed live dashboards inline (carousel) vs. show them as buttons.
  // Grafana embedding + anonymous Viewer are enabled (2026-07-09), so embeds render
  // over LAN-HTTP. (Mixed content still blocks them if the Atlas is opened over the
  // public HTTPS hub — the buttons cover that case.)
  CHRONICLE_EMBEDS: true,
  // The window a native watching draws by default, and the one ⧗ expands it
  // to (2026-09-03: three weeks, and "all time — not more than a
  // year"). Both are keys of the server's WINDOWS allow-list; a source that
  // cannot answer a year (Loki's month) is clamped there and the slide says so.
  CHART_RANGE: '21d',
  CHART_RANGE_ALL: '1y',
  CHRONICLE_ROTATE_MS: 180000,   // auto-advance the report carousels every 3 minutes
  // How many slides either side of the visible one stay loaded. 0 = the old
  // behaviour (a cold Grafana load, spinner and all, on every ‹ ›). 1 keeps
  // paging instant while never holding more than 3 of ~20 dashboards live.
  CHRONICLE_WARM: 1,
  // How long the realm's own "scrying…" holds after a dashboard's iframe fires
  // `load`. Grafana is a single-page app: the document lands quickly and *then*
  // it renders and fetches, so revealing on `load` alone just hands you its
  // spinner instead of ours. A short settle makes it a crossfade. Only cold
  // loads ever see this — a slide already in the warm window is never covered.
  EMBED_SETTLE_MS: 650,
  // How long a NATIVE watching's figure (v1.35.0, chronicle.js + charts.js)
  // is trusted before the slide asks the catalogue again. The server holds
  // its own 60 s cache, so a shorter value here would only redraw the same
  // answer; a visible slide is refreshed on this beat, a parked one on return.
  CHART_STALE_MS: 60000,

  // ── Set by the server, not here (see settings.client_config) ──────────
  // These are deployment facts, not tuning knobs. GRAFANA used to be a
  // constant holding one particular lab's internal address, which shipped
  // inside every copy of this file; SCROLL_ROOT likewise held one person's
  // drive letter. Empty means "this deployment has no Grafana / no vault
  // prefix", and the features that need them simply don't draw.
  // (GRAFANA / GRAFANA_TOKEN / GRAFANA_TOKEN_TTL lived here until v1.36.0 —
  // Grafana was decommissioned 2026-09-03; the watchings draw themselves.)
  SCROLL_ROOT: '',
  // Who the viewer is and what this deployment can offer them — see
  // settings.auth_config(). `mode` is the load-bearing field: hub/accounts/
  // standalone differ in kind, and the account surface draws per mode rather
  // than assuming one. Empty mode = the server told us nothing; draw nothing.
  AUTH: { mode: '', user: '', admin: false, mfa: false },
  HUB_URL: '',
  // THE THEME (v1.48.0): the words and emblems that name one lab — themes/*.json,
  // chosen by ATLAS_THEME on the server. Empty here = the plain theme's own wording
  // is used wherever a module falls back.
  THEME: { name: 'plain', text: {}, nodeLogos: {}, foldedZones: [], forgeNames: [], gatewayNodes: [] },
};

/** one themed phrase, with the module's own neutral fallback */
export const themeText = (key, fallback = '') => CFG.THEME.text?.[key] || fallback;

/** Merge the server's deployment values over the defaults above. */
(function readServerConfig() {
  const block = document.getElementById('atlas-config');
  if (!block) return;
  try {
    const given = JSON.parse(block.textContent || '{}');
    if (given.hubUrl) CFG.HUB_URL = String(given.hubUrl).replace(/\/+$/, '');
    if (given.scrollRoot) CFG.SCROLL_ROOT = String(given.scrollRoot);
    if (given.auth) Object.assign(CFG.AUTH, given.auth);
    if (given.theme && typeof given.theme === 'object') Object.assign(CFG.THEME, given.theme);
  } catch {
    // a malformed block must not stop the map from drawing
  }
})();

/* (`keepEmbedTokenFresh` lived here until v1.36.0 — the Grafana embed token
   went with Grafana, 2026-09-03.) */

export const REDUCED = matchMedia('(prefers-reduced-motion: reduce)').matches;

/** shared atlas context — modules attach their API here (no circular imports) */
export const A = {
  DATA: null,
  MAPW: 0,
  MAPH: 0,
};

export const $ = (id) => document.getElementById(id);

/** the zone an entry names — one lookup, not one per module */
export const zoneById = (id) => A.DATA.zones.find(z => z.id === id);

/** escape a data-file string for safe interpolation into innerHTML */
export function esc(s) {
  return String(s ?? '')
    .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;').replaceAll("'", '&#39;');
}

/** Would framing `abs` here be MIXED CONTENT — an http document inside an
    https Atlas, which the browser blocks silently? One spelling (2026-08-21):
    the glass and the carousels each had their own, and the card's vitals had
    the INVERSE one (`location.protocol === 'http:'`), which never looked at
    the Grafana URL's own scheme — so once Grafana grew TLS (2026-08-16) the
    https Atlas drew no gauges at all, for a block that was no longer there. */
export const isMixed = (abs) => location.protocol === 'https:' && /^http:\/\//i.test(String(abs || ''));

/** a URL the way the app displays one: scheme stripped, nothing else.
    The card, the Index, the palette and the glass footer all show addresses
    this way — one definition, so a future tweak isn't a five-file grep. */
export const host = (u) => String(u ?? '').replace(/^https?:\/\//, '');

/** the attribute string that routes an anchor through THE VIEWING GLASS
    (glass.js's delegated capture listener). One author for the contract —
    six surfaces emit it, and hand-copying it is how THE INDEX shipped with
    no subtitle while every sibling had one. */
export function glassAttrs(title, sub, openIn) {
  return ` data-glass data-glass-title="${esc(title)}" data-glass-sub="${esc(sub)}"` +
    (openIn ? ` data-open-in="${esc(openIn)}"` : '') +
    ` title="Open it over the map (ctrl-click for a new tab)"`;
}
