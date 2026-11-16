/* FOLDS on the page (2026-11-15, stage 4 of the NODES plan): the heads that
   open and shut ACCOUNTS', SEALS' and the tripwires' sections and the token
   rows in Settings. The rules (what is remembered, what opens first, the loud
   counts a shut head keeps) are fold-model.js.

   A section is a box (`data-fold-box`) holding a head (`data-fold="<key>"`).
   Pressing the head, or Enter or Space on it, adds or takes away the box's
   shut class: `data-fold-class` names it (THE LEDGER's `ldg-folded` unless
   said), so each page keeps the CSS it already has. The change is made in
   place, never by a repaint, so the keyboard stays on the head; a page that
   repaints on its own (the tripwires, on each signals poll) draws from the
   remembered state and calls `keepFocus` around its repaint. ONE listener per
   container, so a container whose insides are redrawn is wired once. */

import { esc } from './config.js';
import { choose, isOpen, readFolds, writeFolds } from './fold-model.js';

const storage = () => { try { return window.localStorage; } catch { return null; } };

/** The fold state of one page. */
export function folds(page) {
  let state = readFolds(storage(), page);

  const open = (key, fallback = true) => isOpen(state, key, fallback);

  // Each write starts from what is stored now, so a choice made in another
  // tab is not erased by the next one made here (review). What this tab
  // shows is unchanged until it draws again.
  const fresh = () => ({ ...state, ...readFolds(storage(), page) });

  function set(key, value) {
    state = choose(fresh(), key, value);
    writeFolds(storage(), page, state);
  }

  /** Attributes for a head: put them on the element that is pressed. */
  function head(key, fallback, what) {
    const o = open(key, fallback);
    return `role="button" tabindex="0" data-fold="${esc(key)}" data-fold-first="${fallback ? 1 : 0}" ` +
      `aria-expanded="${o}" title="${o ? 'Shut' : 'Open'} ${esc(what)}"`;
  }

  /** The box's class while shut (with its leading space), or ''. */
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
    // the other way from how it SHOWS (another tab may have stored otherwise)
    const value = headEl.getAttribute('aria-expanded') !== 'true';
    set(key, value);
    show(headEl, value);
  }

  /** Every head in `container` open (true) or shut (false). */
  function all(container, value) {
    state = fresh();
    for (const h of container.querySelectorAll('[data-fold]')) { state = choose(state, h.dataset.fold, value); show(h, value); }
    writeFolds(storage(), page, state);
  }

  /** One listener on `container` for every head inside it, now and after
      any redraw; and the Open all / Shut all buttons (`data-fold-all`). */
  function wire(container) {
    if (!container || container.dataset.foldWired === page) return;
    container.dataset.foldWired = page;
    container.addEventListener('click', (e) => {
      const every = e.target.closest('[data-fold-all]');
      if (every && container.contains(every)) { all(container, every.dataset.foldAll === 'open'); return; }
      const h = e.target.closest('[data-fold]');
      if (!h || !container.contains(h)) return;
      // a control inside a head keeps its own meaning
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

/** Run `paint`, then give the keyboard back to the head it was on (by its
    key), when the repaint replaced it. */
export function keepFocus(container, paint) {
  const was = document.activeElement;
  const key = container && was && container.contains(was) ? was.dataset?.fold : null;
  paint();
  if (!key || document.activeElement === was) return;
  const again = [...container.querySelectorAll('[data-fold]')].find((h) => h.dataset.fold === key);
  again?.focus({ preventScroll: true });
}
