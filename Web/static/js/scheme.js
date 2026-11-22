
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
try { store = localStorage; } catch {   }

migrateOnce(store);
let picked = readStored(store);

function paintPanels() {
  const next = panelScheme(picked, media?.matches, document.body?.classList);
  if (root.dataset.scheme !== next) root.dataset.scheme = next;
}

let closing = 0;
export function sceneChanged(open) {
  clearTimeout(closing);
  if (open || REDUCED) { paintPanels(); return; }
  closing = setTimeout(paintPanels, 420);
}

function paint() {
  paintPanels();
  root.dataset.schemePick = pickAttr(picked);
  const want = pickAttr(picked);
  for (const r of document.querySelectorAll('input[name="sp-scheme"]')) r.checked = r.value === want;
}

export function setPick(pick) {
  picked = parsePick(pick);
  writeStored(store, picked);
  paint();
  dispatchEvent(new CustomEvent('atlas:scheme', { detail: { pick: picked } }));
}
A.setScheme = setPick;

function press() {
  setPick(nextChoice(picked, media?.matches, whereFrom(document.body.classList)));
}

paint();
addEventListener('keydown', (e) => {
  if (!isToggleKey(e)) return;
  e.preventDefault();
  press();
});
document.getElementById('settings-panel')?.addEventListener('change', (e) => {
  const r = e.target;
  if (!(r instanceof HTMLInputElement) || r.name !== 'sp-scheme' || !r.checked) return;
  setPick(r.value === 'auto' ? null : r.value);
});
media?.addEventListener?.('change', () => {
  if (picked) return;
  paintPanels();
});
