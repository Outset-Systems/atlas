/* THE COLOUR SCHEME's rules, with no DOM (v1.52.0; the design notes 2026-10-19).

   Two schemes, "light" and "dark". Panels follow the scheme; the table is a
   night map in all of them, which is atlas.css's job, not this file's. What
   lives here is the choosing: a scheme the viewer picked is remembered and
   wins; with no pick, the operating system's preference decides for the
   panels, and keeps deciding when it changes. The bar (the band, the round
   buttons, the crumbs) follows the map under no pick: light in the Sky, dark
   in the Depths. atlas.css draws that from body classes; barScheme() below is
   the same table as a function, for the button and the tests. Unit-tested by
   tests/test_scheme_model.mjs under plain node.

   THREE PICKS (stage 1, 2026-11-13): Light, Dark, and Light/Dark, the default
   (nothing stored). The button is still a plain two-way switch (owner,
   2026-11-01). From Light/Dark a press pins the scheme the bar is not showing
   where you are, and only Settings > YOU > COLOURS returns to Light/Dark.
   Stored picks were cleared once, 2026-11 (migrateOnce), so every browser
   started on Light/Dark. */

const SCHEMES = ['dark', 'light'];
export const SCHEME_KEY = 'atlas.scheme';
export const RESET_KEY = 'atlas.scheme.reset';
export const RESET_MARK = '2026-11';

/** A pick: 'light' | 'dark', or null for Light/Dark (nothing usable stored). */
export function parsePick(raw) {
  const v = String(raw ?? '').trim().toLowerCase();
  return SCHEMES.includes(v) ? v : null;
}
/** The old name, kept for callers that still say it. */
export const parseStored = parsePick;

/** The scheme the panels draw (`data-scheme`): the viewer's pick, else the OS
    preference, else dark (the Atlas was dark-only until v1.52.0, so no signal
    means no surprise). */
export function resolveScheme(stored, prefersLight) {
  return parsePick(stored) || (prefersLight === true ? 'light' : 'dark');
}

export const otherScheme = (s) => (s === 'light' ? 'dark' : 'light');

/** `data-scheme-pick` on <html>: 'auto' is Light/Dark. */
export const pickAttr = (pick) => parsePick(pick) || 'auto';

/** The bar's scheme. `where` is 'sky', 'depths', 'table' or 'other' (a scene
    open, the Deck, or a phone). A pick holds everywhere; under Light/Dark the
    Sky is light, the Depths dark, and the table and 'other' follow the OS. */
export function barScheme(pick, prefersLight, where) {
  const p = parsePick(pick);
  if (p) return p;
  if (where === 'sky') return 'light';
  if (where === 'depths') return 'dark';
  return prefersLight === true ? 'light' : 'dark';
}

/** Where the camera is, from body's classes (a read; anything with
    `.contains`). Scene, Deck and phone outrank the Sky and the Depths, as the
    CSS's `:not(.scene-open, .deck, .phone)` does. */
export function whereFrom(classList) {
  const has = (c) => { try { return Boolean(classList?.contains?.(c)); } catch { return false; } };
  if (has('scene-open') || has('deck') || has('phone')) return 'other';
  if (has('in-sky')) return 'sky';
  if (has('depths')) return 'depths';
  return 'table';
}

/** The pick a press of the button makes: the scheme the bar is NOT showing
    where you are. Never null, so the button never returns to Light/Dark.
    With no `where`, 'other' (the OS), which is the two-way rule of 11-01. */
export function nextChoice(pick, prefersLight, where = 'other') {
  return otherScheme(barScheme(pick, prefersLight, where));
}

const FACES = {
  auto: 'Light/Dark: the bar follows the map. A press pins the other one (T)',
  light: 'Light: press for Dark (T)',
  dark: 'Dark: press for Light (T)',
};

/** What the band's button says. Its icon is not here: the button carries the
    sun and the moon, and atlas.css shows the one that matches the bar. No
    pressed state: with three picks and a two-way button it would lie.
    (`prefersLight` is taken for the old signature; the words do not need it.) */
// eslint-disable-next-line no-unused-vars
export function buttonFace(pick, prefersLight) {
  const title = FACES[pickAttr(pick)];
  return { title, label: title.replace(/ \(T\)$/, '') };
}

/** Storage that may be absent or throw (private windows, blocked site data). */
export function readStored(storage) {
  try { return parsePick(storage?.getItem(SCHEME_KEY)); } catch { return null; }
}

/** Remember a pick; null (Light/Dark) forgets it. */
export function writeStored(storage, scheme) {
  if (!storage) return false;
  try {
    if (parsePick(scheme)) storage.setItem(SCHEME_KEY, scheme);
    else storage.removeItem(SCHEME_KEY);
    return true;
  } catch { return false; }
}

/** Clear stored picks once (2026-11), so every browser starts on Light/Dark.
    The mark is written FIRST and the pick removed only if that write held: a
    browser that cannot keep the mark keeps its pick rather than losing it on
    every visit. Never throws. True when it ran the clear (mark written, key
    removed), whether or not a pick was stored. */
export function migrateOnce(storage) {
  if (!storage) return false;
  try { if (storage.getItem(RESET_KEY) === RESET_MARK) return false; } catch { return false; }
  try { storage.setItem(RESET_KEY, RESET_MARK); } catch { return false; }
  try { storage.removeItem(SCHEME_KEY); return true; } catch { return false; }
}

/** Whether a keydown should flip the scheme: a bare `t`, never while typing. */
export function isToggleKey(e) {
  if (!e || e.ctrlKey || e.metaKey || e.altKey) return false;
  const tag = String(e.target?.tagName || '').toUpperCase();
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || e.target?.isContentEditable) return false;
  return e.key === 't' || e.key === 'T';
}
