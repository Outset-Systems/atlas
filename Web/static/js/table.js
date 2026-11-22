
import { A, CFG, $, esc, canAdminWrite, getJSON } from './config.js';
import { say, setStyleWords } from './words.js';

const WALLPAPER_KEY = 'atlas-wallpaper';
const TILT_KEY = 'atlas-tilt';

const THEMABLE = [
  'abyss', 'surface', 'surface-2', 'ink-line', 'ink-soft',
  'parchment', 'parchment-dim', 'card-ink', 'card-ink-soft',
  'gilt', 'gilt-bright', 'gilt-rgb', 'text', 'text-dim',
  'discover', 'discover-hover', 'depth', 'depth-rgb',
];
const VALUE_OK = /^[#a-zA-Z0-9(),.\s%-]{1,64}$/;

const stored = () => {
  try {
    return JSON.parse(localStorage.getItem(WALLPAPER_KEY) || 'null') || CFG.DEFAULT_STYLE;
  } catch { return CFG.DEFAULT_STYLE; }
};
export const chosenStyle = () => stored()?.name || null;
export const styleName = () => stored()?.label || null;
const store = (v) => {
  try {
    if (v) localStorage.setItem(WALLPAPER_KEY, JSON.stringify(v));
    else localStorage.removeItem(WALLPAPER_KEY);
  } catch {   }
};

const veilTitle = document.querySelector('.veil-title');
const realmName = { tab: document.title, veil: veilTitle?.textContent || '' };

function wear(style) {
  A.stylePlaces = Object.keys(style?.places || {}).length ? style.places : null;
  A.styleZones = style?.zones || null;
  A.styleLogos = style?.logos || null;
  A.styleArt = style?.name || null;
  A.styleLabel = style?.label || null;
  document.body.classList.toggle('on-style', Boolean(style));
  document.body.classList.toggle('style-bright', style?.bright === true);
  setStyleWords(style?.words);
  document.body.classList.toggle('tripwire-eye', (style ? style.tripwire : CFG.THEME?.tripwire) === 'eye');
  const label = style?.label;
  document.title = label ? `${label} Atlas` : realmName.tab;
  if (veilTitle) veilTitle.textContent = label ? label.toUpperCase() : realmName.veil;
}

const styleOf = (m) => ({
  name: m.name, url: m.url, theme: m.theme || null,
  label: m.label || null, bright: m.bright === true, places: m.places || {}, zones: m.zones || {},
  words: m.words || {}, tripwire: m.tripwire || 'bird', logos: m.logos || {},
});

export function refreshStyle(m) {
  const had = stored();
  if (!m || !had || m.name !== had.name) return;
  const now = styleOf(m);
  if (JSON.stringify([had.label, had.bright, had.places, had.zones, had.words, had.tripwire, had.logos]) ===
      JSON.stringify([now.label, now.bright, now.places, now.zones, now.words, now.tripwire, now.logos])) return;
  store({ ...had, ...now });
  wear(now);
  A.buildWorld?.();
}

function applyTheme(theme) {
  const root = document.documentElement;
  for (const key of THEMABLE) root.style.removeProperty('--' + key);
  if (!theme) return;
  for (const key of THEMABLE) {
    const val = theme[key];
    if (typeof val === 'string' && VALUE_OK.test(val)) root.style.setProperty('--' + key, val);
  }
}

const mapBase = $('map-base');
(function applyEarly() {
  const pick = stored();
  wear(pick);
  if (!mapBase || !pick?.url) { if (pick?.theme) applyTheme(pick.theme); return; }
  mapBase.dataset.realmSrc = mapBase.src;
  mapBase.src = pick.url;
  applyTheme(pick.theme || null);
  mapBase.addEventListener('error', () => {
    store(null);
    applyTheme(null);
    wear(null);
    mapBase.src = mapBase.dataset.realmSrc;
    if (A.MAPW && !mapBase.naturalWidth) {
      try {
        if (!sessionStorage.getItem('atlas-wallpaper-retry')) {
          sessionStorage.setItem('atlas-wallpaper-retry', '1');
          location.reload();
        }
      } catch {   }
    }
  }, { once: true });
})();

async function buildTable() {
  const holder = $('sp-maps');
  if (!holder) return;
  let maps = [];
  try {
    const r = await fetch('api/v2/maps', { cache: 'no-store' });
    if (r.ok) maps = ((await r.json()).maps || []).filter((m) => !m.zoom || m.name === stored()?.name);
  } catch {   }
  if (!maps.length) {
    holder.innerHTML = '<div class="sp-hint">No map images found. Using the default background.</div>';
    return;
  }
  const current = stored();
  const admin = canAdminWrite() && Boolean(A.editorReady?.());
  let builtIn = null;
  if (admin) {
    try {
      const { Editor } = await import('./editor/index.js');
      builtIn = new Set(((await Editor.mapArt()).images || []).filter((i) => i.bundled).map((i) => i.name));
    } catch {   }
  }
  const acts = (m) => {
    if (!admin) return '';
    const why = !builtIn ? 'The list of map images could not be read'
      : builtIn.has(m.name) ? 'Built into the Atlas: it cannot be deleted here'
        : m.default ? 'This is the map’s own background: choose another under Records first'
          : m.name === CFG.DEFAULT_STYLE?.name ? 'This Atlas shows this map to everyone to start with (ATLAS_DEFAULT_STYLE)' : '';
    return '<span class="spm-acts">' +
      `<button type="button" class="spm-act" data-rename="${esc(m.name)}" title="Rename ${esc(m.label)}" aria-label="Rename ${esc(m.label)}">✎\uFE0E</button>` +
      `<button type="button" class="spm-act spm-del" data-delete="${esc(m.name)}"${why ? ' disabled' : ''} ` +
        `title="${esc(why || `Delete ${m.label}`)}" aria-label="Delete ${esc(m.label)}">✕\uFE0E</button></span>`;
  };
  holder.innerHTML = maps.map((m) =>
    `<div class="spm-item" data-item="${esc(m.name)}">` +
    `<button class="spm-row${(current ? current.name === m.name : m.default) ? ' on' : ''}" data-name="${esc(m.name)}">` +
      `<img class="spm-thumb" src="${esc(m.url)}" alt="" loading="lazy">` +
      `<span class="spm-label">${esc(m.label)}</span>` +
      (m.default ? `<span class="spm-tag">${say('the realm’s')}</span>` : '') +
      (m.theme ? `<span class="spm-tag spm-tag-theme">theme</span>` : '') +
    `</button>${acts(m)}</div>`
  ).join('');
  for (const row of holder.querySelectorAll('.spm-row')) {
    row.addEventListener('click', () => {
      const m = maps.find((x) => x.name === row.dataset.name);
      if (m) pick(m);
    });
  }
  for (const b of holder.querySelectorAll('[data-rename]')) {
    b.addEventListener('click', () => startRename(holder, maps.find((x) => x.name === b.dataset.rename)));
  }
  for (const b of holder.querySelectorAll('[data-delete]')) {
    b.addEventListener('click', () => pressDelete(b, maps.find((x) => x.name === b.dataset.delete)));
  }
  buildProvisioners(holder);
}
A.buildCartographer = buildTable;

function startRename(holder, m) {
  const item = m && holder.querySelector(`.spm-item[data-item="${CSS.escape(m.name)}"]`);
  if (!item) return;
  item.innerHTML =
    `<input class="dir-input spm-name" type="text" maxlength="60" autocomplete="off" spellcheck="false" value="${esc(m.label)}" aria-label="The map's name">` +
    '<button type="button" class="sp-btn sp-btn-go spm-save">Save</button>' +
    '<button type="button" class="sp-btn spm-cancel">Cancel</button>';
  const input = item.querySelector('.spm-name');
  const save = async () => {
    const label = input.value.trim().replace(/\s+/g, ' ');
    try {
      const { Editor } = await import('./editor/index.js');
      await Editor.load();
      const list = (Array.isArray(Editor.data?.meta?.map_art) ? Editor.data.meta.map_art : [])
        .filter((e) => e && typeof e === 'object');
      const had = list.find((e) => e.name === m.name);
      const entry = { ...(had || { name: m.name }) };
      if (label) entry.label = label; else delete entry.label;
      const rest = list.filter((e) => e.name !== m.name);
      const next = Object.keys(entry).length > 1 ? [...rest, entry] : rest;
      await Editor.apply([{ op: 'upsert', section: 'meta', body: { map_art: next.length ? next : null } }],
        label ? `the map ${m.name} is named ${label} (MAP EDITOR)` : `the map ${m.name} has its own name back (MAP EDITOR)`);
      A.showToast?.(label ? `It is ${label} now.` : 'It has its own name back.');
      await buildTable();
      try {
        refreshStyle(((await getJSON('api/v2/maps')).maps || []).find((x) => x.name === m.name));
      } catch {   }
    } catch (err) {
      A.showToast?.(`Not renamed: ${err.message || err}`);
    }
  };
  item.querySelector('.spm-save').addEventListener('click', save);
  item.querySelector('.spm-cancel').addEventListener('click', () => buildTable());
  input.addEventListener('keydown', (e) => {
    e.stopPropagation();
    if (e.key === 'Enter') { e.preventDefault(); save(); }
    else if (e.key === 'Escape') buildTable();
  });
  input.focus();
  input.select();
}

function pressDelete(b, m) {
  if (!m || b.disabled) return;
  if (!b.classList.contains('armed')) {
    b.classList.add('armed');
    b.textContent = 'Delete?';
    b.title = `Press again to delete ${m.label} for everyone. This cannot be undone.`;
    setTimeout(() => { if (b.isConnected) buildTable(); }, 5000);
    return;
  }
  b.disabled = true;
  (async () => {
    try {
      const { Editor } = await import('./editor/index.js');
      await Editor.deleteMapArt(m.name);
      A.showToast?.(`${m.label} is deleted.`);
      try {
        await Editor.load();
        const list = Array.isArray(Editor.data?.meta?.map_art) ? Editor.data.meta.map_art : [];
        if (list.some((e) => e?.name === m.name)) {
          const rest = list.filter((e) => e?.name !== m.name);
          await Editor.apply([{ op: 'upsert', section: 'meta', body: { map_art: rest.length ? rest : null } }],
            `the deleted map ${m.name} no longer has a name kept (MAP EDITOR)`);
        }
      } catch {   }
      if (stored()?.name === m.name && !CFG.DEFAULT_STYLE) {
        store(null);
        location.reload();
        return;
      }
    } catch (err) {
      A.showToast?.(`Not deleted: ${err.message || err}`);
    }
    buildTable();
  })();
}

function buildProvisioners(holder) {
  if (!canAdminWrite()) {
    const off = document.createElement('div');
    off.className = 'spm-new';
    off.innerHTML =
      `<div class="sp-actions"><button class="sp-btn" type="button" disabled>Upload a map image…</button></div>` +
      `<div class="sp-hint">Upload is off here: it needs an admin, on an Atlas that takes changes.</div>`;
    holder.append(off);
    return;
  }
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

  const editor = () => import('./editor/index.js').then((m) => m.Editor);

  const file = wrap.querySelector('#spm-file');
  wrap.querySelector('#spm-upload').addEventListener('click', () => file.click());
  file.addEventListener('change', async () => {
    const f = file.files?.[0];
    if (!f) return;
    try {
      const j = await (await editor()).uploadMapArt(f);
      A.showToast?.(`${j.name} joins the gallery.`);
      buildTable();
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

let pending = null;

function pick(m) {
  A.leaveRegion?.();
  if (m.default && !CFG.DEFAULT_STYLE) { store(null); applyTheme(null); }
  else { store(styleOf(m)); applyTheme(m.theme || null); }
  wear(stored());
  const target = m.default && !CFG.DEFAULT_STYLE ? (mapBase.dataset.realmSrc || m.url) : m.url;
  if (mapBase && mapBase.src !== new URL(target, location.href).href) {
    pending?.abort();
    const done = new AbortController();
    pending = done;
    const { signal } = done;
    mapBase.addEventListener('load', () => {
      done.abort();
      if (mapBase.naturalWidth === A.MAPW && mapBase.naturalHeight === A.MAPH) {
        A.buildWorld?.();
        A.onStyleChange?.();
        A.showToast?.('The table is redressed.');
      } else {
        location.reload();
      }
    }, { signal });
    mapBase.addEventListener('error', () => {
      done.abort();
      A.showToast?.('That map could not be loaded. The table is as it was.');
    }, { signal });
    mapBase.src = target;
  } else {
    A.showToast?.(m.default ? 'The map’s own backdrop stands.' : 'The table is redressed.');
  }
  buildTable();
}

const tiltOn = () => { try { return localStorage.getItem(TILT_KEY) === '1'; } catch { return false; } };
function applyTilt(on) {
  document.body.classList.toggle('tilted', on);
}
applyTilt(tiltOn());

const spTilt = $('sp-tilt');
if (spTilt) {
  spTilt.checked = tiltOn();
  spTilt.addEventListener('change', (e) => {
    try { localStorage.setItem(TILT_KEY, e.target.checked ? '1' : '0'); } catch {   }
    applyTilt(e.target.checked);
    if (e.target.checked) {
      A.showToast?.('The table tilts — the sand table seen at an angle.');
    }
  });
}
