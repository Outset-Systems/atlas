/* THE WORDS — lore, standard, or the worn map style's own (words-model.js).

   Lore is the default. Standard is a per-browser choice in THE MAP's settings,
   and it beats a style's words, because someone who asked for plain words
   asked for them on every map. The Atlas's own strings call `say`; a static
   one in the page carries `data-say`, or `data-say-title` for its tooltip. */

import { CFG } from './config.js';
import { STANDARD, cleanWords, makeSay, readMode, writeMode } from './words-model.js';

let store = null;
try { store = localStorage; } catch { /* blocked site data: lore, each visit */ }

let mode = readMode(store);
let styleWords = {};
let current = (text) => text;

function rebuild() {
  current = makeSay(mode === 'standard'
    ? { ...STANDARD, ...cleanWords(CFG.THEME?.standardWords) }
    : styleWords);
}

export const say = (text) => current(text);

function paint() {
  for (const el of document.querySelectorAll('[data-say]')) {
    el.dataset.say ||= el.textContent;
    el.textContent = say(el.dataset.say);
  }
  for (const el of document.querySelectorAll('[data-say-title]')) {
    el.dataset.sayTitle ||= el.title;
    el.title = say(el.dataset.sayTitle);
  }
}

/** The worn style's words, or nothing: table.js calls this from wear(). */
export function setStyleWords(raw) {
  styleWords = cleanWords(raw);
  rebuild();
  paint();
}

rebuild();
paint();

const box = document.getElementById('sp-words');
if (box) {
  box.checked = mode === 'standard';
  box.addEventListener('change', () => {
    mode = box.checked ? 'standard' : 'lore';
    writeMode(store, mode);
    rebuild();
    paint();
  });
}
