
export const FOLD_KEY = 'atlas.fold.';
export const MAX_KEYS = 200;
export const CROWDED = 8;

const okKey = (k) => typeof k === 'string' && k.length > 0 && k.length <= 200;

export function readFolds(storage, page) {
  try {
    const raw = storage?.getItem(FOLD_KEY + page);
    const v = raw ? JSON.parse(raw) : null;
    if (!v || typeof v !== 'object' || Array.isArray(v)) return {};
    const out = {};
    for (const [k, b] of Object.entries(v)) if (okKey(k) && typeof b === 'boolean') out[k] = b;
    return out;
  } catch { return {}; }
}

export function writeFolds(storage, page, state) {
  const kept = Object.entries(state || {}).filter(([k, b]) => okKey(k) && typeof b === 'boolean').slice(-MAX_KEYS);
  try { storage?.setItem(FOLD_KEY + page, JSON.stringify(Object.fromEntries(kept))); return true; }
  catch { return false; }
}

export const isOpen = (state, key, fallback = true) =>
  (state && typeof state[key] === 'boolean' ? state[key] : fallback === true);

export function choose(state, key, open) {
  const next = { ...(state || {}) };
  delete next[key];
  next[key] = open === true;
  return next;
}

export const flip = (state, key, fallback = true) => choose(state, key, !isOpen(state, key, fallback));

export const opensAtFirst = (loud, sections) => (loud | 0) > 0 || (sections | 0) <= CROWDED;

export function sealsDue(days) {
  let lapsed = 0, soon = 0;
  for (const d of days || []) {
    if (typeof d !== 'number' || Number.isNaN(d)) continue;
    if (d < 0) lapsed++;
    else if (d <= 14) soon++;
  }
  return { lapsed, soon };
}

export function tripsLoud(rows) {
  let tripped = 0, unacked = 0, dead = 0, expiring = 0;
  for (const r of rows || []) {
    if (r?.voice === 'speaking') tripped++;
    unacked += Math.max(0, Number(r?.unacked) | 0);
    if (r?.retired) continue;
    if (r?.planted === false) dead++;
    if (typeof r?.expires_in_days === 'number' && r.expires_in_days <= 14) expiring++;
  }
  return { tripped, unacked, dead, expiring };
}

export const sealsByHand = (certs) => (certs || []).filter((c) => c && !c.renews).length;
