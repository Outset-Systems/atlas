/* THE COLOUR SCHEME — ☀/☾/◐ in the band, beside ⚙, and the T key (v1.52.0).

   Sets `data-scheme="light|dark"` on <html>; atlas.css restates the panel
   tokens under it (the map stays a night map in both). The rules are in
   scheme-model.js. Imported FIRST by atlas.js so the attribute is standing
   before any panel can open (they are all closed at boot, behind the veil). */

import {
  buttonFace, isToggleKey, nextChoice, readStored, resolveScheme, writeStored,
} from './scheme-model.js';

const root = document.documentElement;
const media = (() => {
  try { return matchMedia('(prefers-color-scheme: light)'); } catch { return null; }
})();
let store = null;
try { store = localStorage; } catch { /* blocked site data: the OS decides each visit */ }

// The button's face, drawn in the band's line-icon hand (stroke 1.6, round
// caps) — the Unicode glyphs rendered in whatever font the OS had.
const SVG = '<svg class="ci-glyph" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
  + 'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">';
const ICONS = {
  sun: SVG + '<circle cx="12" cy="12" r="4"/><path d="M12 2.8v2.4M12 18.8v2.4M2.8 12h2.4M18.8 12h2.4'
    + 'M5.5 5.5l1.7 1.7M16.8 16.8l1.7 1.7M18.5 5.5l-1.7 1.7M7.2 16.8l-1.7 1.7"/></svg>',
  moon: SVG + '<path d="M19.5 14.6A7.8 7.8 0 1 1 9.4 4.5a6.2 6.2 0 0 0 10.1 10.1Z"/></svg>',
  auto: SVG + '<circle cx="12" cy="12" r="8"/><path d="M12 4a8 8 0 0 1 0 16Z" fill="currentColor" stroke="none"/></svg>',
};

let picked = readStored(store);          // null = follow the OS
let scheme = resolveScheme(picked, media?.matches);

function paint() {
  root.dataset.scheme = scheme;
  const btn = document.getElementById('btn-scheme');
  if (!btn) return;
  const face = buttonFace(picked, media?.matches);
  btn.innerHTML = ICONS[face.icon];   // our own constant markup, never data
  btn.title = face.title;
  btn.setAttribute('aria-label', face.title.replace(/ \(T\)$/, ''));
  btn.setAttribute('aria-pressed', face.pressed ? 'true' : 'false');
}

function toggle() {
  picked = nextChoice(picked, media?.matches);   // dark | light | null = follow the system
  scheme = resolveScheme(picked, media?.matches);
  writeStored(store, picked);
  paint();
}

paint();
document.getElementById('btn-scheme')?.addEventListener('click', (e) => {
  e.stopPropagation();
  toggle();
});
addEventListener('keydown', (e) => {
  if (!isToggleKey(e)) return;
  e.preventDefault();
  toggle();
});
// With no pick of its own, the page follows the OS as it changes (an evening
// switch to dark mode reaches an always-on wall display without a reload).
media?.addEventListener?.('change', (e) => {
  if (picked) return;
  scheme = resolveScheme(null, e.matches);
  paint();
});
