/* THE COLOUR SCHEME — ☀/☾ in the band, beside ⚙, the T key, and
   Settings › YOU › COLOURS (v1.52.0; three picks, stage 1, 2026-11-13).

   Writes two attributes on <html>, and only on a pick or an OS change:
   `data-scheme="light|dark"` (the scheme the panels draw) and
   `data-scheme-pick="auto|light|dark"` (the viewer's pick; auto is
   Light/Dark). The bar follows the camera through atlas.css on body's
   `in-sky` / `depths` classes, so nothing here runs on a camera move and
   nothing here writes <html> or <body> because of one. The rules are in
   scheme-model.js. Imported FIRST by atlas.js so the attributes are standing
   before any panel can open (they are all closed at boot, behind the veil). */

import { A } from './config.js';
import {
  buttonFace, isToggleKey, migrateOnce, nextChoice, parsePick, pickAttr, readStored,
  resolveScheme, whereFrom, writeStored,
} from './scheme-model.js';

const root = document.documentElement;
const media = (() => {
  try { return matchMedia('(prefers-color-scheme: light)'); } catch { return null; }
})();
let store = null;
try { store = localStorage; } catch { /* blocked site data: Light/Dark each visit */ }

// The button's faces, drawn in the band's line-icon hand (stroke 1.6, round
// caps). Both stand in the button; atlas.css shows the sun exactly when the
// bar is light (`--bar-sun` / `--bar-moon`), so a camera move needs no write.
const SVG = (cls) => `<svg class="ci-glyph ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" `
  + 'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">';
const ICONS = {
  sun: SVG('sch-sun') + '<circle cx="12" cy="12" r="4"/><path d="M12 2.8v2.4M12 18.8v2.4M2.8 12h2.4M18.8 12h2.4'
    + 'M5.5 5.5l1.7 1.7M16.8 16.8l1.7 1.7M18.5 5.5l-1.7 1.7M7.2 16.8l-1.7 1.7"/></svg>',
  moon: SVG('sch-moon') + '<path d="M19.5 14.6A7.8 7.8 0 1 1 9.4 4.5a6.2 6.2 0 0 0 10.1 10.1Z"/></svg>',
};

migrateOnce(store);                      // the 2026-11 reset, before the first read
let picked = readStored(store);          // null = Light/Dark

const btn = document.getElementById('btn-scheme');
if (btn) {
  btn.innerHTML = ICONS.sun + ICONS.moon;   // our own constant markup, never data; drawn once
  btn.removeAttribute('aria-pressed');
}

/** Everything that shows the pick: the two attributes, the button's words, the
    Settings radios. Never called on a camera move. */
function paint() {
  root.dataset.scheme = resolveScheme(picked, media?.matches);
  root.dataset.schemePick = pickAttr(picked);
  if (btn) {
    const face = buttonFace(picked, media?.matches);
    btn.title = face.title;
    btn.setAttribute('aria-label', face.label);
  }
  const want = pickAttr(picked);
  for (const r of document.querySelectorAll('input[name="sp-scheme"]')) r.checked = r.value === want;
}

/** The one way a pick changes: the button, T and the Settings row all come
    here. 'light' | 'dark', or null for Light/Dark. */
export function setPick(pick) {
  picked = parsePick(pick);
  writeStored(store, picked);
  paint();
  dispatchEvent(new CustomEvent('atlas:scheme', { detail: { pick: picked } }));
}
A.setScheme = setPick;

/** A press or T: pin the scheme the bar is not showing where the camera is
    now. Reading body's classes is a read, at press time only. */
function press() {
  setPick(nextChoice(picked, media?.matches, whereFrom(document.body.classList)));
}

paint();
btn?.addEventListener('click', (e) => {
  e.stopPropagation();
  press();
});
addEventListener('keydown', (e) => {
  if (!isToggleKey(e)) return;
  e.preventDefault();
  press();
});
// Settings › YOU › COLOURS: the only way back to Light/Dark.
document.getElementById('settings-panel')?.addEventListener('change', (e) => {
  const r = e.target;
  if (!(r instanceof HTMLInputElement) || r.name !== 'sp-scheme' || !r.checked) return;
  setPick(r.value === 'auto' ? null : r.value);
});
// Under Light/Dark the panels follow the OS as it changes (an evening switch
// to dark mode reaches an always-on wall display without a reload). Only
// data-scheme moves; the pick, the button's words and the radios do not.
media?.addEventListener?.('change', (e) => {
  if (picked) return;
  root.dataset.scheme = resolveScheme(null, e.matches);
});
