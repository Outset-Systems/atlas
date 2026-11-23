
import { A, $, esc } from './config.js';
import { hoverReveal } from './ui.js';
import { askPlace, offerFor, placeName } from './scene-places.js';

function bandMenu(scene, menuId) {
  const button = document.querySelector(`.scene[data-scene="${scene}"]`);
  const menu = $(menuId);
  if (!button || !menu) return;
  const items = () => [...menu.querySelectorAll('[role="menuitem"]')];
  const shown = () => menu.classList.contains('peek');
  let hush = false;

  function fill() {
    const at = button.dataset.place || '';
    const offer = A.DATA ? offerFor(scene, at) : [];
    if (offer.length < 2) { menu.innerHTML = ''; return; }
    const pathOf = (loc) => (Array.isArray(loc.path) ? loc.path.join(' › ') : '');
    const order = offer.map((o, i) => ({ ...o, i, path: pathOf(o.loc), premise: Boolean(o.loc.premise) }))
      .sort((a, b) => (a.premise !== b.premise ? (a.premise ? -1 : 1)
        : a.path.localeCompare(b.path, undefined, { numeric: true, sensitivity: 'base' }) || a.i - b.i));
    let last = null;
    menu.innerHTML = order.map(({ loc, path, premise }) => {
      const head = premise && path && path !== last ? `<div class="band-menu-head" aria-hidden="true">${esc(path)}</div>` : '';
      last = premise ? path : null;
      return head + `<button type="button" role="menuitem" data-place="${esc(loc.key)}"${premise ? ' data-premise' : ''}`
        + `${loc.key === at ? ' aria-current="true"' : ''}>${esc(placeName(loc))}</button>`;
    }).join('');
  }
  function paint() {
    button.setAttribute('aria-expanded', String(shown()));
    if (!shown()) return;
    const r = button.getBoundingClientRect();
    const room = Math.max(8, innerWidth - menu.offsetWidth - 8);
    menu.style.setProperty('--view-menu-x', `${Math.min(room, Math.max(8, Math.round(r.left)))}px`);
  }
  button.addEventListener('pointerenter', fill);
  button.addEventListener('focusin', fill);
  button.setAttribute('aria-haspopup', 'menu');
  button.setAttribute('aria-controls', menuId);

  const reveal = hoverReveal(button, menu, {
    onChange: paint,
    refuse: (how) => A.PHONE || !menu.childElementCount || (how === 'focus' && hush),
  });
  const handBack = () => { hush = true; reveal.close(); button.focus(); };
  for (const el of [button, menu]) {
    el.addEventListener('focusout', (e) => {
      if (!button.contains(e.relatedTarget) && !menu.contains(e.relatedTarget)) hush = false;
    });
  }

  button.addEventListener('keydown', (e) => {
    if (e.key !== 'ArrowDown' || !shown()) return;
    e.preventDefault(); e.stopPropagation();
    items()[0]?.focus();
  });
  menu.addEventListener('keydown', (e) => {
    if (e.key === 'Tab') return;
    e.stopPropagation();
    const list = items();
    const i = list.indexOf(document.activeElement);
    const go = (n) => { e.preventDefault(); list[(n + list.length) % list.length]?.focus(); };
    if (e.key === 'ArrowDown') go(i + 1);
    else if (e.key === 'ArrowUp') go(i < 0 ? list.length - 1 : i - 1);
    else if (e.key === 'Home') go(0);
    else if (e.key === 'End') go(list.length - 1);
    else if (e.key === 'Escape') { e.preventDefault(); handBack(); }
  });
  menu.addEventListener('click', (e) => {
    const item = e.target.closest('[data-place]');
    if (!item) return;
    e.stopPropagation();
    const keyboard = e.detail === 0;
    askPlace(scene, item.dataset.place);
    if (!button.classList.contains('active')) button.click();
    if (keyboard) handBack();
    else {
      reveal.close();
      if (menu.contains(document.activeElement)) document.activeElement.blur();
    }
  });
}

bandMenu('rack', 'hardware-menu');
bandMenu('tribute', 'resources-menu');
bandMenu('path', 'topology-menu');
