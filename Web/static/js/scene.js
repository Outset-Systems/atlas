
import { A, $ } from './config.js';

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
    if (!root?.classList.contains('open')) return;
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
