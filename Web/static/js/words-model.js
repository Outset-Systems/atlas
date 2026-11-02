/* THE WORDS — the rule behind words.js, with no DOM in it.

   The Atlas speaks in lore: rites, realms, the annals. A viewer can ask for
   standard words instead, and a map style can bring words of its own. Both are
   the same operation, a table of word → word, so there is one regex and no key
   for every sentence. `say` only ever gets the Atlas's own strings, never a
   name out of the data: a host called "realm" stays "realm". */

const KEY = 'atlas-words';
const WORD_KEY_OK = /^[\p{L}' ’-]{2,30}$/u;
const WORD_OK = /^[\p{L}\p{N}' ’-]{1,30}$/u;
const MAX_WORDS = 40;

/** Longest match wins, so whole phrases go in before the words inside them. */
export const STANDARD = {
  'enter the realm': 'sign in',
  'the realm above the realm': 'the zone above the map',
  'the realm’s': 'default',
  'scried from the deep': 'live',
  'scried live': 'live',
  'the deep': 'the registry',
  'the scribe is not answering': 'the chart did not load',
  'chronicle of changes': 'change log',
  'but the chronicle remembers': 'but the change log keeps it',
  'stopped turning': 'stopped running',
  'is turning': 'is running',
  'a fortnight': 'two weeks',
  'vassal of the hypervisor': 'guest of the host',
  'once around the moon': 'once a month',
  chronicle: 'charts',
  realm: 'zone', realms: 'zones',
  rite: 'job', rites: 'jobs',
  vassal: 'guest', vassals: 'guests',
  watching: 'chart', watchings: 'charts',
  scrying: 'loading', scryings: 'reports',
  forge: 'model host',
  seal: 'certificate', seals: 'certificates',
  annals: 'history',
  stone: 'tripwire', stones: 'tripwires',
};

/** A style's or theme's table, keeping only plain words: they reach innerHTML. */
export function cleanWords(raw) {
  const out = {};
  if (!raw || typeof raw !== 'object') return out;
  for (const [from, to] of Object.entries(raw).slice(0, MAX_WORDS)) {
    const key = String(from).trim().toLowerCase();
    if (WORD_KEY_OK.test(key) && typeof to === 'string' && WORD_OK.test(to.trim())) out[key] = to.trim();
  }
  return out;
}

const shaped = (to, hit) => {
  if (hit.length > 1 && hit === hit.toUpperCase()) return to.toUpperCase();
  if (hit[0] !== hit[0].toLowerCase()) return to[0].toUpperCase() + to.slice(1);
  return to;
};

/** A function that puts `table`'s words into a string, in the case it found. */
export function makeSay(table) {
  const keys = Object.keys(table).sort((a, z) => z.length - a.length);
  if (!keys.length) return (text) => text;
  const alts = keys.map((k) => k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|');
  const re = new RegExp(`(?<![\\p{L}\\p{N}])(?:${alts})(?![\\p{L}\\p{N}])`, 'giu');
  return (text) => String(text).replace(re, (hit) => shaped(table[hit.toLowerCase()], hit));
}

export function readMode(store) {
  try { return store?.getItem(KEY) === 'standard' ? 'standard' : 'lore'; } catch { return 'lore'; }
}

export function writeMode(store, mode) {
  try { store?.setItem(KEY, mode); } catch { /* blocked site data: this visit only */ }
}
