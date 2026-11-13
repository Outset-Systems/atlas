/* THE SURVEYOR'S DESK — the two helpers that sit beside a form and fill its
   fields for you: the backdrop gallery under the map's own settings, and "use
   the current view" above a region's rectangle. Neither saves anything; each
   writes into the form, and the form's one Save writes the entry. */

import { A, esc } from '../config.js';
import Editor from './store.js';
import { makeEl as el } from './form.js';
import { desk, iconBtn, problemList } from './desk-kit.js';

/** THE BACKDROP — choose or upload the picture the map is drawn on.
    Selecting writes the filename into the form's own map_image field rather
    than saving behind the user's back, so one Save still means one write and
    the change log still gets one row. */
export async function drawMapArt(form) {
  const wrap = el('div', 'dsk-mapart');
  wrap.append(el('div', 'dsk-mapart-head',
    '<strong>THE BACKDROP</strong><span>the picture the map is drawn on — '
    + 'places are positioned in fractions of it, so swapping keeps every marker '
    + 'where it is</span>'));
  const gallery = el('div', 'dsk-mapart-grid');
  const errors = el('div', 'dsk-form-errors');
  wrap.append(errors, gallery);
  desk.body.append(wrap);

  // Which tile reads as chosen when `map_image` is blank is the *server's*
  // default, not a filename typed in here. This was hard-coded to one lab's
  // render, so changing the shipped backdrop silently highlighted a tile that
  // no longer existed — the same trap the deployment notes records for the Grafana base
  // and the vault root. `/api/v2/admin/map-art` has always returned `default`.
  let fallback = '';
  const current = () => (form.get('map_image') || '').trim() || fallback;

  async function paint(images) {
    gallery.innerHTML = '';
    for (const img of images) {
      const chosen = img.name === current();
      const src = img.bundled ? `static/map/${img.name}` : `map-art/${img.name}`;
      const tile = el('button', `dsk-mapart-tile${chosen ? ' on' : ''}`,
        `<img src="${esc(src)}" alt="" loading="lazy">
         <span class="dsk-mapart-name">${esc(img.name)}</span>
         <span class="dsk-mapart-meta">${img.bundled ? 'built in'
           : `${Math.max(1, Math.round(img.bytes / 1024))} KB`}</span>`);
      tile.type = 'button';
      tile.addEventListener('click', () => {
        form.set('map_image', img.name);
        paint(images);
      });
      if (!img.bundled) {
        // iconBtn already stops the click reaching the tile behind it
        const drop = iconBtn('✕', `Delete ${img.name}`, async () => {
          errors.innerHTML = '';
          try {
            const res = await Editor.deleteMapArt(img.name);
            if (current() === img.name) form.set('map_image', '');
            paint(res.images);
          } catch (err) { errors.append(problemList(err)); }
        }, 'bad');
        drop.classList.add('dsk-mapart-drop');
        tile.append(drop);
      }
      gallery.append(tile);
    }
  }

  const picker = el('div', 'dsk-mapart-upload');
  const input = el('input', 'dsk-mapart-file');
  input.type = 'file';
  input.accept = 'image/png,image/jpeg,image/gif,image/webp';
  input.addEventListener('change', async () => {
    const file = input.files?.[0];
    if (!file) return;
    errors.innerHTML = '';
    try {
      const res = await Editor.uploadMapArt(file, file.name);
      form.set('map_image', res.name);
      paint(res.images);
    } catch (err) { errors.append(problemList(err)); }
    input.value = '';
  });
  picker.append(el('span', 'dsk-mapart-hint',
    'PNG, JPEG, GIF or WEBP. SVG is refused — it can carry script.'), input);
  wrap.append(picker);

  try {
    const res = await Editor.mapArt();
    fallback = res.default || '';
    paint(res.images || []);
  } catch (err) {
    errors.append(problemList(err));
  }
}

/** REGIONS — "use the current view": fill the rectangle from what the map
    behind the Desk shows, instead of typing four percentages. The Desk opens
    over the map without moving it, so the view is the one you left: frame
    the area, open the Desk, press. The map it reads is the open region's
    detailed map when one is open (carried onto the "Inside" map through the
    rectangles between them), else the main map — regions.js does the
    reading (`A.regionViewFor`), region-model.js the maths. Nothing is saved;
    the four fields change and one Save writes them, as with the backdrop. */
export function seatRegionView(form) {
  const anchor = form.row('x');
  if (!anchor) return;
  const row = el('div', 'dsk-field dsk-field-wide');   // a heading for the four fields, not a fifth
  const btn = el('button', 'dsk-btn dsk-btn-sm', 'Use the current view');
  btn.type = 'button';
  const help = el('span', 'dsk-help');
  help.setAttribute('aria-live', 'polite');

  const read = () => {
    const parentId = String(form.get('parent') || '');
    const parent = parentId ? Editor.entries('regions').find((r) => r.id === parentId) : null;
    const onto = parentId ? `the detailed map of ${parent?.name || parentId}` : 'the main map';
    const view = A.regionViewFor?.(parentId) || null;
    const source = !view ? 'the map'
      : view.fromLens ? `the detailed map of ${view.from}` : 'the main map';
    let title = `Fill Left, Top, Width and Height with what ${source} behind the editor shows now`;
    if (view && !view.direct) {
      title += `, carried onto ${onto} through its rectangle` +
        (parentId ? `. To frame it on that map itself, open ${parent?.name || parentId} first` : '');
    }
    return { view, onto, source, title: title + '.' };
  };
  const retitle = () => { btn.title = read().title; };
  btn.addEventListener('pointerenter', retitle);
  btn.addEventListener('focus', retitle);
  btn.addEventListener('click', () => {
    const { view, onto, source } = read();
    if (!view) { help.textContent = 'The map is not drawn yet.'; return; }
    if (!view.rect) {
      help.textContent = `The view shows none of ${onto}. Close the editor, frame the area, and open it again.`;
      return;
    }
    const { x, y, w, h } = view.rect;
    form.set('x', x); form.set('y', y); form.set('w', w); form.set('h', h);
    help.textContent = `From ${source}: ${w} × ${h} % at ${x}, ${y}. Save to keep it.`;
  });
  retitle();
  help.textContent = 'Frame the area on the map before opening the editor, then fill the rectangle from it.';
  const hold = el('div');
  hold.append(btn);
  row.append(el('span', 'dsk-label', 'The rectangle'), hold, help);
  anchor.before(row);
}
