
const SCHEMES = ['dark', 'light'];
export const SCHEME_KEY = 'atlas.scheme';
export const RESET_KEY = 'atlas.scheme.reset';
export const RESET_MARK = '2026-11';

export function parsePick(raw) {
  const v = String(raw ?? '').trim().toLowerCase();
  return SCHEMES.includes(v) ? v : null;
}
export const parseStored = parsePick;

export function resolveScheme(stored, prefersLight) {
  return parsePick(stored) || (prefersLight === true ? 'light' : 'dark');
}

export const otherScheme = (s) => (s === 'light' ? 'dark' : 'light');

export const pickAttr = (pick) => parsePick(pick) || 'auto';

export function barScheme(pick, prefersLight, where) {
  const p = parsePick(pick);
  if (p) return p;
  if (where === 'sky') return 'light';
  if (where === 'depths') return 'dark';
  return prefersLight === true ? 'light' : 'dark';
}

const hasClass = (classList, c) => { try { return Boolean(classList?.contains?.(c)); } catch { return false; } };

export function whereFrom(classList) {
  const has = (c) => hasClass(classList, c);
  if (has('deck') || has('phone')) return 'other';
  if (has('in-sky')) return 'sky';
  if (has('depths')) return 'depths';
  return has('scene-open') ? 'other' : 'table';
}

export function panelScheme(pick, prefersLight, classList) {
  if (parsePick(pick) || !hasClass(classList, 'scene-open')) return resolveScheme(pick, prefersLight);
  return barScheme(null, prefersLight, whereFrom(classList));
}

export function nextChoice(pick, prefersLight, where = 'other') {
  return otherScheme(barScheme(pick, prefersLight, where));
}

export function readStored(storage) {
  try { return parsePick(storage?.getItem(SCHEME_KEY)); } catch { return null; }
}

export function writeStored(storage, scheme) {
  if (!storage) return false;
  try {
    if (parsePick(scheme)) storage.setItem(SCHEME_KEY, scheme);
    else storage.removeItem(SCHEME_KEY);
    return true;
  } catch { return false; }
}

export function migrateOnce(storage) {
  if (!storage) return false;
  try { if (storage.getItem(RESET_KEY) === RESET_MARK) return false; } catch { return false; }
  try { storage.setItem(RESET_KEY, RESET_MARK); } catch { return false; }
  try { storage.removeItem(SCHEME_KEY); return true; } catch { return false; }
}

export function isToggleKey(e) {
  if (!e || e.ctrlKey || e.metaKey || e.altKey) return false;
  const tag = String(e.target?.tagName || '').toUpperCase();
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || e.target?.isContentEditable) return false;
  return e.key === 't' || e.key === 'T';
}
