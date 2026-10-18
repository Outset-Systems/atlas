/* Atlas — the one scene shell.

   Eight scene modules carried byte-identical `open()` / `close()` bodies and
   the same two lines of wiring (the × leaves and recentres; a click on the
   scrim leaves) — the 2026-08-21 survey counted ~110 duplicated lines, and the
   Escape chain in camera.js had quietly become a third enumeration of the
   scenes beside `closeAllScenes`. The shape lives here once. A module keeps
   its own `root` (its painters read it) and hands this two hooks: `build`,
   run on every open — rebuild, build-once, or a fresh signals read, the
   module decides — and `onClose`, for a scene with state to put down.

   THE PATH keeps its own open(): it takes arguments and does thirty lines of
   focus work between the class flip and the card close, and a hook for each
   of those would be the shell pretending the scene is simpler than it is. */

import { A, $ } from './config.js';

/** `id` = the scene's root element, `closeId` = its × button. Returns
    `{ open, close, mount }`; call `mount()` from the module's build step, and
    it returns the root (or null, so the module can bail the way it always has). */
export function makeScene({ id, closeId, build, onClose }) {
  let root = null;
  function open() {
    if (!root) return;
    build?.();
    root.classList.add('open');
    root.setAttribute('aria-hidden', 'false');
    A.closeCard?.();
  }
  function close() {
    if (!root) return;
    onClose?.();
    root.classList.remove('open');
    root.setAttribute('aria-hidden', 'true');
    A.setSceneActive?.('atlas');
  }
  function mount() {
    root = $(id);
    if (!root) return null;
    $(closeId)?.addEventListener('click', () => { close(); A.recenter?.(true); });
    root.addEventListener('pointerdown', (e) => { if (e.target === root) close(); });
    return root;
  }
  return { open, close, mount };
}
