/* FOLDS: the open-and-shut sections of the admin pages, with no DOM
   (2026-11-15, stage 4 of the NODES plan; the owner: the same
   navigate-and-expand "for accounts/api/breaches").

   ACCOUNTS, SEALS, the tripwires and the token list in Settings each list
   their things in sections; a section's head opens and shuts it, and the
   choice is remembered in this browser, per page (`atlas.fold.<page>`), as
   NODES' rail remembers its sections. THE LEDGER's folds stay per visit: its
   default is the opinion there, not a memory.

   A SHUT SECTION KEEPS ITS LOUD FACT. Each of these pages exists so that calm
   is never drawn over a gap, so the head of a shut section still says what
   the rows inside would have shouted: an account that elevates without a
   password, a certificate lapsed or lapsing within a fortnight, a tripwire
   touched or a trip to acknowledge. The counts below are those facts.

   fold.js does the showing; this file only decides.
   Unit-tested by tests/test_fold_model.mjs under plain node. */

export const FOLD_KEY = 'atlas.fold.';
/** The most choices one page keeps: the latest win, so a map that lost a
    thousand places does not carry their folds forever. */
export const MAX_KEYS = 200;
/** A page with more sections than this opens with the quiet ones shut:
    past it, a list of every row is longer than anyone reads. */
export const CROWDED = 8;

const okKey = (k) => typeof k === 'string' && k.length > 0 && k.length <= 200;

/** The choices stored for `page`: {key: open?}. Anything else in storage
    (a hand edit, another version, blocked storage) is read as none. */
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

/** Store `state` for `page`, the latest MAX_KEYS choices. False when the
    browser refuses (a private window): the page still works, unremembered. */
export function writeFolds(storage, page, state) {
  const kept = Object.entries(state || {}).filter(([k, b]) => okKey(k) && typeof b === 'boolean').slice(-MAX_KEYS);
  try { storage?.setItem(FOLD_KEY + page, JSON.stringify(Object.fromEntries(kept))); return true; }
  catch { return false; }
}

/** Open? A stored choice wins; otherwise the page's own default. */
export const isOpen = (state, key, fallback = true) =>
  (state && typeof state[key] === 'boolean' ? state[key] : fallback === true);

/** `state` with `key` set to `open`, moved to the end (the latest choice).
    Keys are always prefixed by the caller (`place:`, `kind:`): an all-digit
    key would sort before the rest in an object and be the first trimmed. */
export function choose(state, key, open) {
  const next = { ...(state || {}) };
  delete next[key];
  next[key] = open === true;
  return next;
}

/** `state` with `key` turned the other way from how it shows now. */
export const flip = (state, key, fallback = true) => choose(state, key, !isOpen(state, key, fallback));

/** How a section first shows, before anyone chooses: open when it carries
    the page's finding, or when the page is short enough to read whole. */
export const opensAtFirst = (loud, sections) => (loud | 0) > 0 || (sections | 0) <= CROWDED;

/** SEALS: how many of these days-left are past (lapsed) and how many fall
    within the fortnight (14 days, the renewal window plus slack). A seal
    with no date counts in neither. */
export function sealsDue(days) {
  let lapsed = 0, soon = 0;
  for (const d of days || []) {
    if (typeof d !== 'number' || Number.isNaN(d)) continue;
    if (d < 0) lapsed++;
    else if (d <= 14) soon++;
  }
  return { lapsed, soon };
}

/** TRIPWIRES: in these rows, how many are touched (`speaking`), how many
    trips wait to be acknowledged, how many cannot trip at all (charted but
    not planted: a calm row over a gap, review 2026-11-15) and how many
    tokens are expired or expire within the fortnight. A retired one counts
    in none of the last two: it is meant to be silent. */
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

/** SEALS: how many of these certificates nothing renews (a blank `renews`),
    the finding the page exists to workstation. */
export const sealsByHand = (certs) => (certs || []).filter((c) => c && !c.renews).length;
