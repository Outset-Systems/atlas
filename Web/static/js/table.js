/* Atlas — THE CARTOGRAPHER'S TABLE: the viewer's own backdrop,
   the theme that rides it, and the tilt of the table itself.

   The server half has existed since mapart.py: renders are uploaded at the
   Desk, `meta.map_image` names the realm's default, and places are positioned
   in FRACTIONS of the image, so swapping the picture keeps every marker where
   it stands. This module is the viewer's half — a per-browser choice stored
   in localStorage, applied before the map is measured, never written to the
   dataset. The Desk decides what the realm looks like; settings decides what
   YOUR window onto it looks like.

   THE BOOT ORDER RULE. atlas.js measures #map-base's natural size before
   anything draws, so the override must be on the src BEFORE that await — this
   module runs at import (all of atlas.js's imports evaluate before boot()),
   swaps the src synchronously, and that is the whole trick. If the override's
   art has been deleted since it was chosen, the error handler clears the
   choice and restores the realm's own src; the one pathological interleaving
   (error lands after boot measured a zero-size image) is answered with a
   single guarded reload rather than a permanently mis-sized world.

   THEMES are token sets, not stylesheets: a render entry in `meta.map_art`
   may carry {theme: {"gilt": "...", "workstation": "..."}}, and only the tokens
   named in THEMABLE are ever applied — the semantic colours (red means down)
   are deliberately not in the list, and a junk value is dropped by the value
   gate rather than reaching the style engine. Clearing the override removes
   the inline tokens and the stylesheet's own :root wins again. */

import { A, $, esc, CFG, canAdminWrite } from './config.js';

const WALLPAPER_KEY = 'atlas-wallpaper';
const TILT_KEY = 'atlas-tilt';

/* the tokens a theme may retint — structure and accent, never semantics */
const THEMABLE = [
  'abyss', 'workstation', 'workstation-2', 'ink-line', 'ink-soft',
  'parchment', 'parchment-dim', 'card-ink', 'card-ink-soft',
  'gilt', 'gilt-bright', 'gilt-rgb', 'text', 'text-dim',
  'discover', 'discover-hover', 'depth', 'depth-rgb',
];
const VALUE_OK = /^[#a-zA-Z0-9(),.\s%-]{1,64}$/;

const stored = () => {
  try { return JSON.parse(localStorage.getItem(WALLPAPER_KEY) || 'null'); } catch { return null; }
};
const store = (v) => {
  try {
    if (v) localStorage.setItem(WALLPAPER_KEY, JSON.stringify(v));
    else localStorage.removeItem(WALLPAPER_KEY);
  } catch { /* private mode */ }
};

function applyTheme(theme) {
  const root = document.documentElement;
  for (const key of THEMABLE) root.style.removeProperty('--' + key);
  if (!theme) return;
  for (const key of THEMABLE) {
    const val = theme[key];
    if (typeof val === 'string' && VALUE_OK.test(val)) root.style.setProperty('--' + key, val);
  }
}

/* ── the early swap — runs at module import, before boot measures ────────── */
const mapBase = $('map-base');
(function applyEarly() {
  const pick = stored();
  if (!mapBase || !pick?.url) { if (pick?.theme) applyTheme(pick.theme); return; }
  mapBase.dataset.realmSrc = mapBase.src;      // the realm's own choice, kept for fallback
  mapBase.src = pick.url;
  applyTheme(pick.theme || null);
  mapBase.addEventListener('error', () => {
    // the chosen art is gone (deleted upload, renamed file): forget the choice
    // and go home. If boot already measured the failed image, one clean reload
    // beats a world sized to nothing — guarded so it can never loop.
    store(null);
    applyTheme(null);
    mapBase.src = mapBase.dataset.realmSrc;
    if (A.MAPW && !mapBase.naturalWidth) {
      try {
        if (!sessionStorage.getItem('atlas-wallpaper-retry')) {
          sessionStorage.setItem('atlas-wallpaper-retry', '1');
          location.reload();
        }
      } catch { /* private mode */ }
    }
  }, { once: true });
})();

/* ── the settings section ────────────────────────────────────────────────── */
async function buildTable() {
  const holder = $('sp-maps');
  if (!holder) return;
  let maps = [];
  try {
    const r = await fetch('api/v2/maps', { cache: 'no-store' });
    if (r.ok) maps = (await r.json()).maps || [];
  } catch { /* the rows below say so */ }
  if (!maps.length) {
    holder.innerHTML = '<div class="sp-hint">No map images found. Using the default background.</div>';
    return;
  }
  const current = stored();
  holder.innerHTML = maps.map((m) =>
    `<button class="spm-row${(current ? current.name === m.name : m.default) ? ' on' : ''}" data-name="${esc(m.name)}">` +
      `<img class="spm-thumb" src="${esc(m.url)}" alt="" loading="lazy">` +
      `<span class="spm-label">${esc(m.label)}</span>` +
      (m.default ? `<span class="spm-tag">the realm’s</span>` : '') +
      (m.theme ? `<span class="spm-tag spm-tag-theme">theme</span>` : '') +
    `</button>`
  ).join('');
  for (const row of holder.querySelectorAll('.spm-row')) {
    row.addEventListener('click', () => {
      const m = maps.find((x) => x.name === row.dataset.name);
      if (m) pick(m);
    });
  }
  buildProvisioners(holder);
}
A.buildCartographer = buildTable;

/* ── new renders, from a file or from the real world (2026-08-16) ────
   Two admin-only rows under the gallery. UPLOAD posts to the same
   /api/admin/map-art the Desk uses (multipart, byte-sniffed server-side);
   THE REAL-WORLD SURVEY hands an address to the server, which geocodes it,
   pulls the surrounding buildings from OpenStreetMap and paints an isometric
   block-city into the gallery. Admin-gated on the SERVER — hiding the rows
   here is courtesy, not security. */
function buildProvisioners(holder) {
  if (!canAdminWrite()) return;
  const wrap = document.createElement('div');
  wrap.className = 'spm-new';
  wrap.innerHTML =
    `<div class="sp-actions">` +
      `<button class="sp-btn" id="spm-upload">Upload a map image…</button>` +
      `<input type="file" id="spm-file" accept="image/png,image/jpeg,image/gif,image/webp" hidden>` +
    `</div>` +
    `<div class="sp-actions spm-survey-row">` +
      `<input class="dir-input spm-grow" id="spm-query" type="text" autocomplete="off" spellcheck="false"` +
        ` placeholder="an address or a zip code…" aria-label="Build a map from an address or zip code">` +
      `<button class="sp-btn sp-btn-go" id="spm-survey">Build map</button>` +
    `</div>` +
    `<div class="sp-hint">Upload adds an image to the list for everyone. Build map draws the real` +
      ` buildings around an address from OpenStreetMap.</div>`;
  holder.append(wrap);

  /* both actions ride the Desk's own client (editor/store.js) — the third
     hand-rolled fetch of api/admin/map-art* was already drifting from the
     Desk's refusal handling. Dynamic import, the annals.js idiom: the editor
     module only loads when an admin actually reaches for these. */
  const editor = () => import('./editor/index.js').then((m) => m.Editor);

  const file = wrap.querySelector('#spm-file');
  wrap.querySelector('#spm-upload').addEventListener('click', () => file.click());
  file.addEventListener('change', async () => {
    const f = file.files?.[0];
    if (!f) return;
    try {
      const j = await (await editor()).uploadMapArt(f);
      A.showToast?.(`${j.name} joins the gallery.`);
      buildTable();   // the new render appears; picking it is one click away
    } catch (e) { A.showToast?.(e.message || 'the upload did not arrive'); }
    finally { file.value = ''; }
  });

  const q = wrap.querySelector('#spm-query');
  const go = wrap.querySelector('#spm-survey');
  const runSurvey = async () => {
    const query = q.value.trim();
    if (!query) { q.focus(); return; }
    go.disabled = true;
    const label = go.textContent;
    go.textContent = 'Surveying…';
    try {
      const j = await (await editor()).surveyMapArt(query);
      A.showToast?.(`Surveyed ${j.surveyed} — ${j.name} joins the gallery.`);
      q.value = '';
      buildTable();
    } catch (e) { A.showToast?.(e.message || 'the survey did not answer'); }
    finally { go.disabled = false; go.textContent = label; }
  };
  go.addEventListener('click', runSurvey);
  q.addEventListener('keydown', (e) => { if (e.key === 'Enter') runSurvey(); });
}

function pick(m) {
  // choosing the realm's default = clearing the override, so a later Desk
  // change of the default follows this browser too
  if (m.default) { store(null); applyTheme(null); }
  else { store({ name: m.name, url: m.url, theme: m.theme || null }); applyTheme(m.theme || null); }
  const target = m.default ? (mapBase.dataset.realmSrc || m.url) : m.url;
  if (mapBase && mapBase.src !== new URL(target, location.href).href) {
    mapBase.addEventListener('load', () => {
      // same canvas → live redress; a different-sized render changes the whole
      // coordinate space, and one honest reload is the correct re-boot for that
      if (mapBase.naturalWidth === A.MAPW && mapBase.naturalHeight === A.MAPH) {
        A.showToast?.('The table is redressed.');
      } else {
        location.reload();
      }
    }, { once: true });
    mapBase.src = target;
  } else {
    A.showToast?.(m.default ? 'The map’s own backdrop stands.' : 'The table is redressed.');
  }
  buildTable();   // repaint the ON marks
}

/* ── the tilt (Arc T, v2) ───────────────────────────────────────
   Pure CSS perspective on #viewport (body.tilted in atlas.css). The *view* was
   always one CSS rule, and that part was right and cheap. What v1 lacked was
   the other direction: the camera solved in screen pixels while the eye saw
   tilted ones, so aim during drag and zoom was admittedly APPROXIMATE, and the
   toggle said so out loud.

   Step two closed it (project.js): pointer input is unprojected through the
   exact inverse of the browser's own transform before it reaches `cam`, so
   what you point at is what you get, and the warning is gone. Markers, labels
   and roads never needed routing — they are DOM children of the transformed
   element, so the browser projects them for free. While tilted, the ambient
   animations pause with the same discipline the Depths learned. */
const tiltOn = () => { try { return localStorage.getItem(TILT_KEY) === '1'; } catch { return false; } };
function applyTilt(on) {
  document.body.classList.toggle('tilted', on);
}
applyTilt(tiltOn());

const spTilt = $('sp-tilt');
if (spTilt) {
  spTilt.checked = tiltOn();
  spTilt.addEventListener('change', (e) => {
    try { localStorage.setItem(TILT_KEY, e.target.checked ? '1' : '0'); } catch { /* private mode */ }
    applyTilt(e.target.checked);
    if (e.target.checked) {
      A.showToast?.('The table tilts — the sand table seen at an angle.');
    }
  });
}
