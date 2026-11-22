
export const PHONE_MEDIA = '(max-width: 720px), (max-height: 500px) and (pointer: coarse)';

export const DECK_KEY = 'atlas.view';

export const VIEWS = ['map', 'overview', 'nodes', 'topology'];
export const ADMIN_VIEWS = Object.freeze([]);
export const ALIASES = Object.freeze({ charts: 'overview', alerts: 'nodes' });
export const PHONE_VIEWS = VIEWS.filter((v) => v !== 'map');

export const isView = (v) => VIEWS.includes(v);

export const mayOpen = (v, admin) => isView(v) && (admin === true || !ADMIN_VIEWS.includes(v));

const clean = (raw) => String(raw ?? '').trim().toLowerCase();

export function parseView(raw) {
  const v = clean(raw);
  if (Object.prototype.hasOwnProperty.call(ALIASES, v)) return ALIASES[v];
  return isView(v) || v === 'phone' ? v : null;
}

export const namesCharts = (raw) => clean(raw) === 'charts';

export function wantsPhone(viewParam, screenIsPhone) {
  const asked = parseView(viewParam);
  if (asked === 'phone') return true;
  if (asked) return false;
  return screenIsPhone === true;
}

const phoneDefault = (stored, admin) => {
  const s = parseView(stored);
  return s && s !== 'map' && s !== 'phone' && mayOpen(s, admin) ? s : 'overview';
};

export function openingView(viewParam, isPhone, stored, { admin = false, place = null } = {}) {
  const asked = parseView(viewParam);
  if (asked === 'phone') return phoneDefault(stored, admin);
  if (asked) return mayOpen(asked, admin) ? asked : (isPhone === true ? 'overview' : 'map');
  if (parsePlace(place)) return isPhone === true ? 'overview' : 'map';
  if (isPhone === true) return phoneDefault(stored, admin);
  const s = parseView(stored);
  return s && s !== 'phone' && mayOpen(s, admin) ? s : 'map';
}

export function allowedView(name, isPhone, admin) {
  const next = mayOpen(name, admin) ? name : 'map';
  return isPhone === true && next === 'map' ? 'overview' : next;
}

export function opensAtCharts(viewParam, isPhone, stored, opts = {}) {
  const asked = parseView(viewParam);
  if (asked && asked !== 'phone') return namesCharts(viewParam);
  if (parsePlace(opts.place)) return false;
  return namesCharts(stored) && openingView(viewParam, isPhone, stored, opts) === 'overview';
}

export function parseCollection(raw) {
  const s = String(raw ?? '').trim();
  return /^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$/.test(s) ? s : null;
}

export function parsePlace(raw) {
  const s = String(raw ?? '').trim();
  return /^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$/.test(s) ? s : null;
}

export function readStored(storage) {
  try { return storage?.getItem(DECK_KEY) ?? null; } catch { return null; }
}
export function writeStored(storage, value) {
  try { storage?.setItem(DECK_KEY, value); return true; } catch { return false; }
}

export function withView(search, view) {
  const q = new URLSearchParams(search || '');
  q.set('view', view);
  return '?' + q.toString();
}

export function swipeStep(dx, dy, min = 48) {
  if (Math.abs(dx) < min || Math.abs(dx) <= Math.abs(dy) * 1.2) return 0;
  return dx < 0 ? 1 : -1;
}
