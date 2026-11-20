/* THE COLOUR SCHEME — Settings › YOU › COLOURS and the T key (v1.52.0; three
   picks, stage 1, 2026-11-13). The band's ☀/☾ button went on 2026-11-14 (the
   owner: the colours live in Settings; the sky and the depths took its place).

   Writes two attributes on <html>, and only on a pick, an OS change, or a
   scene opening or closing (ui.js calls sceneChanged: under Light/Dark a
   scene over the Sky is light and one over the Depths dark, 2026-11-20):
   `data-scheme="light|dark"` (the scheme the panels draw) and
   `data-scheme-pick="auto|light|dark"` (the viewer's pick; auto is
   Light/Dark). The bar follows the camera through atlas.css on body's
   `in-sky` / `depths` classes, so nothing here runs on a camera move and
   nothing here writes <html> or <body> because of one. The rules are in
   scheme-model.js. Imported FIRST by atlas.js so the attributes are standing
   before any panel can open (they are all closed at boot, behind the veil). */

import { A, REDUCED } from './config.js';
import {
  isToggleKey, migrateOnce, nextChoice, panelScheme, parsePick, pickAttr, readStored,
  whereFrom, writeStored,
} from './scheme-model.js';

const root = document.documentElement;
const media = (() => {
  try { return matchMedia('(prefers-color-scheme: light)'); } catch { return null; }
})();
let store = null;
try { store = localStorage; } catch { /* blocked site data: Light/Dark each visit */ }

migrateOnce(store);                      // the 2026-11 reset, before the first read
let picked = readStored(store);          // null = Light/Dark

/** `data-scheme` alone, written only when it changes. */
function paintPanels() {
  const next = panelScheme(picked, media?.matches, document.body?.classList);
  if (root.dataset.scheme !== next) root.dataset.scheme = next;
}

/** A scene opened, changed or closed (ui.js, after `body.scene-open` is set).
    Opening paints at once, so the panel comes up in its scheme. Closing waits
    out the panel's own fade, so a light scene over the Sky does not turn dark
    on its way out. */
let closing = 0;
export function sceneChanged(open) {
  clearTimeout(closing);
  if (open || REDUCED) { paintPanels(); return; }
  closing = setTimeout(paintPanels, 420);
}

/** Everything that shows the pick: the two attributes and the Settings
    radios. Never called on a camera move. */
function paint() {
  paintPanels();
  root.dataset.schemePick = pickAttr(picked);
  const want = pickAttr(picked);
  for (const r of document.querySelectorAll('input[name="sp-scheme"]')) r.checked = r.value === want;
}

/** The one way a pick changes: T and the Settings row both come here. 'light' | 'dark', or null for Light/Dark. */
export function setPick(pick) {
  picked = parsePick(pick);
  writeStored(store, picked);
  paint();
  dispatchEvent(new CustomEvent('atlas:scheme', { detail: { pick: picked } }));
}
A.setScheme = setPick;

/** T: pin the scheme the bar is not showing where the camera is
    now. Reading body's classes is a read, at press time only. */
function press() {
  setPick(nextChoice(picked, media?.matches, whereFrom(document.body.classList)));
}

paint();
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
// data-scheme moves; the pick and the radios do not.
media?.addEventListener?.('change', () => {
  if (picked) return;
  paintPanels();
});
