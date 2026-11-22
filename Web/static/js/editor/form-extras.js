
import { A, esc } from '../config.js';
import Editor from './store.js';
import { makeEl as el } from './form.js';
import { desk, iconBtn, problemList } from './desk-kit.js';

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

export function seatRegionView(form) {
  const anchor = form.row('x');
  if (!anchor) return;
  const row = el('div', 'dsk-field dsk-field-wide');
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
