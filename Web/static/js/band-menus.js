/* THE BAND'S MENUS OF LOCATIONS (2026-11-20; owner: "When you hover over
   hardware, it should show a drop down of locations, like home office or
   wherever there's compute", and the same for RESOURCES).

   HARDWARE and RESOURCES each drop a menu of the map's locations, the way
   THE ATLAS drops the views: a mouse over the button, or the keyboard
   reaching it, shows it (ui.js `hoverReveal`); it fades when the mouse
   leaves and rolls up a moment later (`idleRollup`). A pick shows that
   location in the scene, opening the scene if it is shut. The button itself
   is still the whole: pressed, it shows everything (ui.js, and each scene's
   own `atlas:scene-place` listener).

   The menus are siblings of the band, never inside it, for the reason the
   views' menu is (the band's backdrop-filter would position and clip them),
   and they wear the views menu's own class, so they are the same pane and
   follow the bar with it. Their items carry `data-place`, never `data-scene`
   (the band binds every `[data-scene]` as a scene button).

   A menu needs a pointer that can hover or a keyboard. A touch screen and a
   phone have neither over the band, so each scene also draws the same
   locations as a picker of its own (scene-places.js `drawPlacePicker`). */

import { A, $, esc } from './config.js';
import { hoverReveal, idleRollup } from './ui.js';
import { askPlace, placeName, whereNow } from './scene-places.js';

const MENU_ROLLUP_MS = 600;   // the views menu's own beat

function bandMenu(scene, menuId) {
  const button = document.querySelector(`.scene[data-scene="${scene}"]`);
  const menu = $(menuId);
  if (!button || !menu) return;
  const items = () => [...menu.querySelectorAll('[role="menuitem"]')];
  const shown = () => menu.classList.contains('peek');
  /* Focus handed back to the button (after Escape or a keyboard pick) must not
     open the menu again: hushed until the keyboard leaves the button and the
     menu, as the views' menu is (ui.js `viewHush`). */
  let hush = false;

  /** The locations of the map now in the browser; the one shown is marked. */
  function fill() {
    if (!A.DATA) { menu.innerHTML = ''; return; }
    const at = button.dataset.place || '';
    menu.innerHTML = whereNow().list.map((l) =>
      `<button type="button" role="menuitem" data-place="${esc(l.key)}"${l.key === at ? ' aria-current="true"' : ''}>`
      + `${esc(placeName(l))}</button>`).join('');
  }
  function paint() {
    button.setAttribute('aria-expanded', String(shown()));
    if (!shown()) return;
    // under its own button, wherever the band's label strip has scrolled it
    const r = button.getBoundingClientRect();
    const room = Math.max(8, innerWidth - menu.offsetWidth - 8);
    menu.style.setProperty('--view-menu-x', `${Math.min(room, Math.max(8, Math.round(r.left)))}px`);
  }
  // filled before it is shown: these listeners are added before hoverReveal's
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
  idleRollup(menu, [button, menu], { isUp: shown, after: MENU_ROLLUP_MS, rollUp: () => reveal.close() });

  // ↓ from the button goes into the menu; inside it the arrows move and never pan the map
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
    askPlace(scene, item.dataset.place);          // the scene takes the location…
    if (!button.classList.contains('active')) button.click();   // …and is opened if it is shut
    if (keyboard) handBack();
    else {
      reveal.close();
      if (menu.contains(document.activeElement)) document.activeElement.blur();
    }
  });
}

bandMenu('rack', 'hardware-menu');
bandMenu('tribute', 'resources-menu');
