/* THE COLOUR SCHEME — ☀/☾ in the band, beside ⚙, and the T key (v1.52.0).

   Sets `data-scheme="light|dark"` on <html>; atlas.css restates the panel
   tokens under it (the map stays a night map in both). The rules are in
   scheme-model.js. Imported FIRST by atlas.js so the attribute is standing
   before any panel can open (they are all closed at boot, behind the veil). */

import {
  buttonFace, isToggleKey, otherScheme, readStored, resolveScheme, writeStored,
} from './scheme-model.js';

const root = document.documentElement;
const media = (() => {
  try { return matchMedia('(prefers-color-scheme: light)'); } catch { return null; }
})();
let store = null;
try { store = localStorage; } catch { /* blocked site data: the OS decides each visit */ }

let picked = readStored(store);          // null = follow the OS
let scheme = resolveScheme(picked, media?.matches);

function paint() {
  root.dataset.scheme = scheme;
  const btn = document.getElementById('btn-scheme');
  if (!btn) return;
  const face = buttonFace(scheme);
  btn.textContent = face.glyph;
  btn.title = face.title;
  btn.setAttribute('aria-label', face.title.replace(/ \(T\)$/, ''));
  btn.setAttribute('aria-pressed', face.pressed ? 'true' : 'false');
}

function toggle() {
  scheme = otherScheme(scheme);
  picked = scheme;
  writeStored(store, scheme);
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
