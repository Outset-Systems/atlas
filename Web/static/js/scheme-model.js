/* THE COLOUR SCHEME's rules, with no DOM (v1.52.0; the design notes 2026-10-19).

   Two schemes, "light" and "dark". Panels follow the scheme; the map is a night
   map in both, which is atlas.css's job, not this file's. What lives here is
   the choosing: a scheme the viewer picked is remembered and wins; with no
   pick, the operating system's preference decides, and keeps deciding when it
   changes. Unit-tested by tests/test_scheme_model.mjs under plain node.

   THREE CHOICES, TWO SCHEMES (owner, 10-20): "dark", "light" and "auto" (no
   pick: follow the system). The button cycles them, and the first click
   always flips what you see: from auto it goes to the scheme the system is
   NOT showing, then to the other one, then back to auto. Without the third
   state a single click was a one-way door out of following the system. */

export const SCHEMES = ['dark', 'light'];
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

/** The next choice after `choice` ('dark' | 'light' | null = auto), given the
    system preference. auto → the other scheme → the system's own → auto. */
export function nextChoice(choice, prefersLight) {
  const sys = prefersLight === true ? 'light' : 'dark';
  const order = [null, otherScheme(sys), sys];
  const at = order.indexOf(parseStored(choice));
  return order[(at + 1) % order.length];
}

const WORD = { light: 'Light', dark: 'Dark' };

/** What the round chrome button shows and says. ☾ dark and ☀ light when the
    viewer picked one; ◐ while following the system. The title says what is
    in force and what a click does; `pressed` marks the light scheme. */
export function buttonFace(choice, prefersLight) {
  const pick = parseStored(choice);
  const scheme = resolveScheme(pick, prefersLight);
  const next = nextChoice(pick, prefersLight);
  const after = next ? `switch to ${next}` : 'follow your system';
  return {
    glyph: pick === 'light' ? '☀' : pick === 'dark' ? '☾' : '◐',
    icon: pick === 'light' ? 'sun' : pick === 'dark' ? 'moon' : 'auto',   // scheme.js draws it
    title: pick ? `${WORD[pick]} panels — ${after} (T)`
                : `${WORD[scheme]} panels, following your system — ${after} (T)`,
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
