/* THE COLOUR SCHEME's rules, with no DOM (v1.52.0; the design notes 2026-10-19).

   Two schemes, "light" and "dark". Panels follow the scheme; the map is a night
   map in both, which is atlas.css's job, not this file's. What lives here is
   the choosing: a scheme the viewer picked is remembered and wins; with no
   pick, the operating system's preference decides, and keeps deciding when it
   changes. Unit-tested by tests/test_scheme_model.mjs under plain node.

   TWO WAYS (owner, 2026-11-01): the button is a plain switch between dark and
   light. A first visit still follows the system until you press it. The third
   stop that went back to following the system (10-20) is gone: on every other
   click it looked like nothing had happened. */

const SCHEMES = ['dark', 'light'];
export const SCHEME_KEY = 'atlas.scheme';

/** A stored value, or null when nothing usable is stored. */
export function parseStored(raw) {
  const v = String(raw ?? '').trim().toLowerCase();
  return SCHEMES.includes(v) ? v : null;
}

/** The scheme to draw: the viewer's pick, else the OS preference, else dark
    (the Atlas was dark-only until v1.52.0, so no signal means no surprise). */
export function resolveScheme(stored, prefersLight) {
  return parseStored(stored) || (prefersLight === true ? 'light' : 'dark');
}

export const otherScheme = (s) => (s === 'light' ? 'dark' : 'light');

/** The next choice after `choice` ('dark' | 'light' | null = no pick yet),
    given the system preference: always the scheme not on screen. */
export function nextChoice(choice, prefersLight) {
  return otherScheme(resolveScheme(choice, prefersLight));
}

const WORD = { light: 'Light', dark: 'Dark' };

/** What the round chrome button shows and says: ☾ dark, ☀ light. The title
    says what is in force and what a click does; `pressed` marks light. */
export function buttonFace(choice, prefersLight) {
  const scheme = resolveScheme(choice, prefersLight);
  return {
    glyph: scheme === 'light' ? '☀' : '☾',
    icon: scheme === 'light' ? 'sun' : 'moon',   // scheme.js draws it
    title: `${WORD[scheme]} panels — switch to ${otherScheme(scheme)} (T)`,
    pressed: scheme === 'light',
  };
}

/** Storage that may be absent or throw (private windows, blocked site data). */
export function readStored(storage) {
  try { return parseStored(storage?.getItem(SCHEME_KEY)); } catch { return null; }
}

/** Remember a pick; null (auto) forgets it, so the system decides again. */
export function writeStored(storage, scheme) {
  if (!storage) return false;
  try {
    if (parseStored(scheme)) storage.setItem(SCHEME_KEY, scheme);
    else storage.removeItem(SCHEME_KEY);
    return true;
  } catch { return false; }
}

/** Whether a keydown should flip the scheme: a bare `t`, never while typing. */
export function isToggleKey(e) {
  if (!e || e.ctrlKey || e.metaKey || e.altKey) return false;
  const tag = String(e.target?.tagName || '').toUpperCase();
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || e.target?.isContentEditable) return false;
  return e.key === 't' || e.key === 'T';
}
