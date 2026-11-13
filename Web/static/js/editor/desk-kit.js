/* THE SURVEYOR'S DESK — what every part of the panel shares.

   panel.js routes between the Desk's views; survey.js, changes.js and
   form-extras.js each draw one. They all need the same few things: a notice, a
   list of problems, an icon button, the save wrapper that handles "someone
   else saved first" — and a way to reach the panel itself (set its head, draw
   into its body, go to another view) without importing it, which would be a
   circle. That way is `desk`: panel.js fills it in, the others only read it,
   and never before a function runs. */

import { A, esc } from '../config.js';
import Editor, { EditorError } from './store.js';
import { makeEl as el } from './form.js';

/** The two entries in the sidebar that are not sections of the dataset. */
export const VIRTUAL = {
  survey: { label: 'THE SURVEY', lore: 'strangers on the wire, not yet charted' },
  changes: { label: 'THE CHRONICLE OF CHANGES', lore: 'every alteration, and the way back' },
};

/** The panel, as its other files see it.
    body     the element a view draws into (set by buildDesk)
    setHead  (label, lore) — the panel's title and the line under it
    show     (key) — draw a section, THE SURVEY or the change log
    open     (sectionKey?) — open the panel, loading the editor if need be
    active   the key of the view on screen */
export const desk = { body: null, setHead: null, show: null, open: null, active: 'nodes' };

export function notice(message, kind = 'info') {
  return el('div', `dsk-notice dsk-notice-${kind}`, esc(message));
}

export function problemList(err) {
  const box = el('div', 'dsk-notice dsk-notice-bad');
  box.append(el('div', 'dsk-notice-head', esc(err.message || 'that could not be saved')));
  const problems = err.problems || [];
  if (problems.length && problems[0] !== err.message) {
    box.append(el('ul', 'dsk-problems',
      problems.map((p) => `<li>${esc(p)}</li>`).join('')));
  }
  return box;
}

export async function run(action, okMessage) {
  try {
    const result = await action();
    if (okMessage !== false) {
      A.showToast?.(okMessage || (result?.changed || []).join(' · ') || 'Saved.');
    }
    return result;
  } catch (err) {
    if (err instanceof EditorError && err.status === 409) {
      A.showToast?.(err.message);
      await Editor.reload();
      desk.show(desk.active);
      return null;
    }
    throw err;
  }
}

export function iconBtn(glyph, title, onClick, kind) {
  const btn = el('button', `dsk-icon${kind ? ' dsk-icon-' + kind : ''}`, glyph);
  btn.title = title;
  btn.addEventListener('click', (e) => { e.stopPropagation(); onClick(); });
  return btn;
}
