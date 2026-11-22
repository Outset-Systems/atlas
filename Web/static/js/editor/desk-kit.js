
import { A, esc } from '../config.js';
import Editor, { EditorError } from './store.js';
import { makeEl as el } from './form.js';

export const VIRTUAL = {
  survey: { label: 'THE SURVEY', lore: 'strangers on the wire, not yet charted' },
  changes: { label: 'THE CHRONICLE OF CHANGES', lore: 'every alteration, and the way back' },
};

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
    if (!result?.unread && okMessage !== false) {
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
