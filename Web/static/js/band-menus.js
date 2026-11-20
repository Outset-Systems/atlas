/* THE BAND'S MENUS OF LOCATIONS (2026-11-20; owner: "When you hover over
   hardware, it should show a drop down of locations, like home office or
   wherever there's compute", and the same for RESOURCES).

   HARDWARE, RESOURCES and TOPOLOGY each drop a menu of the map's locations,
   when the scene has more than one to offer, the way THE ATLAS drops the
   views: a mouse over the button, or the keyboard reaching it, shows it, and
   the mouse leaving closes it (ui.js `hoverReveal`; no fade and no waiting
   about, which are THE INDEX's alone: owner, 2026-11-20). A pick shows that
   location in the scene, opening the scene if it is shut. The button itself
   is still the whole: pressed, it shows everything (ui.js, and each scene's
   own `atlas:scene-place` listener).

   A location is listed only when the scene has something to draw there, and
   each rack that has stands under its location, a step in: a pick of one
   shows that rack alone (owner, the same day: "if there isn't any
   equipment/hardware at a location that location shouldn't be displayed in
   the drop down", and "you should be able to see the resources of a specific
   device, (Rack a or rack B) that is associated with a specific location").
   What is offered is scene-places.js `offerFor`, the list the picker inside
   the scene reads too.

   The menus are siblings of the band, never inside it, for the reason the
   views' menu is (the band's backdrop-filter would position and clip them),
   and they wear the views menu's own class, so they are the same pane and
   follow the bar with it. Their items carry `data-place`, never `data-scene`
   (the band binds every `[data-scene]` as a scene button).

   A menu needs a pointer that can hover or a keyboard. A touch screen and a
   phone have neither over the band, so each scene also draws the same
   locations as a picker of its own (scene-places.js `drawPlacePicker`). */

import { A, $, esc } from './config.js';
import { hoverReveal } from './ui.js';
import { askPlace, offerFor, placeName } from './scene-places.js';

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

  /** What the scene offers on the map now in the browser: its locations, each
      with its racks under it; what is on show is marked. With one location
      there is nothing to choose between, so the menu is empty and is never
      shown (owner, 2026-11-20: "only show the dropdown if there are more
      than one site/location"); the racks of a single location are chosen
      inside the scene. */
  function fill() {
    const at = button.dataset.place || '';
    const offer = A.DATA ? offerFor(scene, at) : [];
    if (offer.length < 2) { menu.innerHTML = ''; return; }
    const rack = button.dataset.rack;        // undefined when the whole location is shown
    const cur = (on) => (on ? ' aria-current="true"' : '');
    menu.innerHTML = offer.map(({ loc, racks }) =>
      `<button type="button" role="menuitem" data-place="${esc(loc.key)}"${cur(loc.key === at && rack === undefined)}>`
      + `${esc(placeName(loc))}</button>`
      + racks.map((r) => `<button type="button" role="menuitem" class="band-rack" data-place="${esc(loc.key)}"`
        + ` data-rack="${esc(r.id)}"${cur(loc.key === at && rack === r.id)}>${esc(r.name)}</button>`).join('')).join('');
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
    // the scene takes the location, or the one rack at it…
    askPlace(scene, item.dataset.place, item.dataset.rack === undefined ? null : item.dataset.rack);
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
bandMenu('path', 'topology-menu');
