
export const canAdminWrite = () =>
  CFG.AUTH.admin || document.body.dataset.editable === '1';

export const CFG = {
  ZOOM_MAX: 4,
  ZOOM_WHEEL: 1.18,
  ZOOM_BTN: 1.35,
  ZOOM_KEY: 1.25,
  ZOOM_DBLCLICK: 1.7,
  ZOOM_PULLBACK: 1.45,
  PAN_KEY_PX: 90,
  WHEEL_PAN: 1.0,
  INERTIA_DECAY: 0.92,
  DRAG_THRESHOLD_PX: 3,

  VOID_DEPTH: 0.45,
  VOID_FOOT_PX: 56,
  SKY_NORTH: 0.60,
  SKY_TOP: 0.48,
  SKY_GAP: 0.06,
  DEPTHS_ENGAGE: 1.10,
  DEPTHS_RELEASE: 0.96,
  SKY_ENGAGE: 0.5,
  SKY_RELEASE: 0.3,

  MESA_POS: { x: 50.0, y: 25.0 },
  MESA_W: 0.13,
  MESA_H: 0.095,

  ZONE_LABEL_PX: 26,
  ZONE_LABEL_MAX_OPACITY: 0.8,
  CLOSEUP_T: 0.55,
  FOCUS_ZOOM: 2.1,
  BREATHE_S: 3.2,
  TOAST_MS: 2600,
  DRIFT_REST_MS: 5000,
  CENTRE_ENTER: 0.15,
  CENTRE_LEAVE: 0.25,

  SIGNALS_POLL_MS: 30000,
  SIGNALS_MAX_MISSES: 3,

  CONSTELLATION_R: 4.6,
  CONSTELLATION_TWO_RING: 8,
  CONSTELLATION_OUTER: 1.55,
  CONSTELLATION_ZOOM: 1.35,

  GLASS_TIMEOUT_MS: 8000,

  PALETTE_MAX: 8,

  CHRONICLE_EMBEDS: true,
  CHART_RANGE: '21d',
  CHART_RANGE_ALL: '1y',
  CHRONICLE_ROTATE_MS: 180000,
  CHRONICLE_WARM: 1,
  EMBED_SETTLE_MS: 650,
  CHART_STALE_MS: 60000,

  SCROLL_ROOT: '',
  NOTES_HOME: '',
  AUTH: { mode: '', user: '', admin: false, mfa: false },
  WHOIS: true,
  HUB_URL: '',
  THEME: { name: 'plain', text: {}, nodeLogos: {}, sceneryLogos: [], foldedZones: [], forgeNames: [], gatewayNodes: [] },
};

export const themeText = (key, fallback = '') => CFG.THEME.text?.[key] || fallback;

(function readServerConfig() {
  const block = document.getElementById('atlas-config');
  if (!block) return;
  try {
    const given = JSON.parse(block.textContent || '{}');
    if (given.hubUrl) CFG.HUB_URL = String(given.hubUrl).replace(/\/+$/, '');
    if (given.scrollRoot) CFG.SCROLL_ROOT = String(given.scrollRoot);
    CFG.NOTES_HOME = typeof given.notesHome === 'string' ? given.notesHome : '';
    if (given.auth) Object.assign(CFG.AUTH, given.auth);
    if (given.whois === false) CFG.WHOIS = false;
    CFG.DEMO_TRUST = given.demoTrust === true;
    CFG.DEMO_LINK = typeof given.demoLink === 'string' && given.demoLink.startsWith('https://') ? given.demoLink : '';
    CFG.DEFAULT_STYLE = given.defaultStyle || null;
    if (given.theme && typeof given.theme === 'object') Object.assign(CFG.THEME, given.theme);
  } catch {
  }
})();


export const REDUCED = matchMedia('(prefers-reduced-motion: reduce)').matches;

export const A = {
  DATA: null,
  MAPW: 0,
  MAPH: 0,
};

export const $ = (id) => document.getElementById(id);

export const zoneById = (id) => A.DATA.zones.find(z => z.id === id);
export const nodeById = (id) => A.DATA.nodes.find(n => n.id === id);

export const FALLBACK_HUE = '#C9A554';

export const DRAG_END = ['pointerup', 'pointercancel', 'lostpointercapture'];

export const HEALTH_DOT = Object.freeze({
  healthy: 'h-up', degraded: 'h-degraded', down: 'h-down',
  maintenance: 'h-maint', slumbering: 'h-slumber',
});

export function ago(ms) {
  const s = Math.max(0, Math.round((Number(ms) || 0) / 1000));
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

export const WRITE_HEADERS = Object.freeze({ 'Content-Type': 'application/json', 'X-Atlas-Write': '1' });

export const postJSON = (path, body, opts = {}) => fetch(path, {
  method: 'POST',
  ...opts,
  headers: { ...WRITE_HEADERS, ...(opts.headers || {}) },
  ...(body === undefined ? {} : { body: JSON.stringify(body) }),
});

export const readJSON = (res) => res.json().catch(() => null);

export async function sendJSON(path, body, { method = 'POST', button = null } = {}) {
  if (button) button.disabled = true;
  try {
    const res = await postJSON(path, body, { method });
    const j = await readJSON(res);
    return { ok: res.ok, status: res.status, body: j && typeof j === 'object' ? j : {} };
  } catch {
    return { ok: false, status: 0, body: { error: 'The request did not reach the server.' } };
  } finally {
    if (button) button.disabled = false;
  }
}

export async function getJSON(url) {
  const res = await fetch(url, { cache: 'no-store' });
  const body = await readJSON(res);
  if (!res.ok) throw new Error(body?.error || `${res.status} ${res.statusText}`);
  if (body === null || typeof body !== 'object') throw new Error('the answer was not JSON');
  return body;
}

export function esc(s) {
  return String(s ?? '')
    .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;').replaceAll("'", '&#39;');
}

export const noticeHTML = (m) => (!m ? '' : `<div class="dsk-notice dsk-notice-${m.kind}">${esc(m.text)}` +
  (m.problems?.length ? `<ul class="dsk-problems">${m.problems.map((p) => `<li>${esc(p)}</li>`).join('')}</ul>` : '') +
  '</div>');

export function refusalHTML(err) {
  const msg = typeof err === 'string' ? err : (err.message || '');
  return noticeHTML({ kind: 'bad', text: msg, problems: (err.problems || []).filter((p) => p && p !== msg) });
}

export const isMixed = (abs) => location.protocol === 'https:' && /^http:\/\//i.test(String(abs || ''));

export const host = (u) => String(u ?? '').replace(/^https?:\/\//, '');

export const svcKey = (link, nodeId) => link?.kuma || `${nodeId}/${link?.label || ''}`;

export function glassAttrs(title, sub, openIn) {
  return ` data-glass data-glass-title="${esc(title)}" data-glass-sub="${esc(sub)}"` +
    (openIn ? ` data-open-in="${esc(openIn)}"` : '') +
    ` title="Open it over the map (ctrl-click for a new tab)"`;
}
