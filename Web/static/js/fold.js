
import { esc } from './config.js';
import { choose, isOpen, readFolds, writeFolds } from './fold-model.js';

const storage = () => { try { return window.localStorage; } catch { return null; } };

export function folds(page) {
  let state = readFolds(storage(), page);

  const open = (key, fallback = true) => isOpen(state, key, fallback);

  const fresh = () => ({ ...state, ...readFolds(storage(), page) });

  function set(key, value) {
    state = choose(fresh(), key, value);
    writeFolds(storage(), page, state);
  }

  function head(key, fallback, what) {
    const o = open(key, fallback);
    return `role="button" tabindex="0" data-fold="${esc(key)}" data-fold-first="${fallback ? 1 : 0}" ` +
      `aria-expanded="${o}" title="${o ? 'Shut' : 'Open'} ${esc(what)}"`;
  }

  const shut = (key, fallback, cls = 'ldg-folded') => (open(key, fallback) ? '' : ` ${cls}`);

  function show(headEl, value) {
    const box = headEl.closest('[data-fold-box]');
    if (!box) return;
    box.classList.toggle(box.dataset.foldClass || 'ldg-folded', !value);
    headEl.setAttribute('aria-expanded', String(value));
    headEl.title = headEl.title.replace(/^(Shut|Open) /, `${value ? 'Shut' : 'Open'} `);
  }

  function press(headEl) {
    const key = headEl.dataset.fold;
    const value = headEl.getAttribute('aria-expanded') !== 'true';
    set(key, value);
    show(headEl, value);
  }

  function all(container, value) {
    state = fresh();
    for (const h of container.querySelectorAll('[data-fold]')) { state = choose(state, h.dataset.fold, value); show(h, value); }
    writeFolds(storage(), page, state);
  }

  function wire(container) {
    if (!container || container.dataset.foldWired === page) return;
    container.dataset.foldWired = page;
    container.addEventListener('click', (e) => {
      const every = e.target.closest('[data-fold-all]');
      if (every && container.contains(every)) { all(container, every.dataset.foldAll === 'open'); return; }
      const h = e.target.closest('[data-fold]');
      if (!h || !container.contains(h)) return;
      const ctl = e.target.closest('button, a, input, select, textarea, label');
      if (ctl && ctl !== h && h.contains(ctl)) return;
      press(h);
    });
    container.addEventListener('keydown', (e) => {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      const h = e.target.closest('[data-fold]');
      if (!h || h !== e.target) return;
      e.preventDefault();
      press(h);
    });
  }

  return { open, head, shut, set, wire, all };
}

export function keepFocus(container, paint) {
  const was = document.activeElement;
  const key = container && was && container.contains(was) ? was.dataset?.fold : null;
  paint();
  if (!key || document.activeElement === was) return;
  const again = [...container.querySelectorAll('[data-fold]')].find((h) => h.dataset.fold === key);
  again?.focus({ preventScroll: true });
}
