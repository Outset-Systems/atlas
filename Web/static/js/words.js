
import { CFG } from './config.js';
import { STANDARD, cleanWords, makeSay, readMode, writeMode } from './words-model.js';

let store = null;
try { store = localStorage; } catch {   }

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
