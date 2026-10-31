/* THE SURVEYOR'S DESK — where the map is written.

   One panel, twelve sections, all rendered from the field catalogue. The
   sidebar lists the sections plus the two things that aren't sections: THE
   SURVEY (devices found on the wire, waiting to be charted) and THE CHRONICLE
   OF CHANGES (who altered what, and the way back).

   Nothing here knows what a rack slot or a rite *is*. If it looks like it
   handles twelve kinds of thing, it handles one kind of thing twelve times. */

import { A, $, esc } from '../config.js';
import Editor, { EditorError } from './store.js';
import { buildForm, makeEl as el } from './form.js';

let root, sideEl, bodyEl, titleEl, subEl;
let active = 'nodes';
let booted = false;

const VIRTUAL = {
  survey: { label: 'THE SURVEY', lore: 'strangers on the wire, not yet charted' },
  changes: { label: 'THE CHRONICLE OF CHANGES', lore: 'every alteration, and the way back' },
};

/* ── chrome ───────────────────────────────────────────────────────────── */

function setHead(label, lore) {
  titleEl.textContent = label;
  subEl.textContent = lore || '';
}

function drawSidebar() {
  sideEl.innerHTML = '';
  for (const key of Editor.sectionKeys()) {
    const section = Editor.section(key);
    const count = section.kind === 'object' ? '' : String(Editor.entries(key).length);
    const btn = el('button', `dsk-nav${key === active ? ' on' : ''}`,
      `<span class="dsk-nav-name">${esc(section.plural.toUpperCase())}</span>` +
      `<span class="dsk-nav-n">${count}</span>`);
    btn.addEventListener('click', () => show(key));
    sideEl.append(btn);
  }
  sideEl.append(el('div', 'dsk-nav-rule'));
  for (const [key, meta] of Object.entries(VIRTUAL)) {
    const btn = el('button', `dsk-nav${key === active ? ' on' : ''}`,
      `<span class="dsk-nav-name">${esc(meta.label)}</span><span class="dsk-nav-n" ` +
      `id="dsk-n-${key}"></span>`);
    btn.addEventListener('click', () => show(key));
    sideEl.append(btn);
  }
}

function notice(message, kind = 'info') {
  return el('div', `dsk-notice dsk-notice-${kind}`, esc(message));
}

function problemList(err) {
  const box = el('div', 'dsk-notice dsk-notice-bad');
  box.append(el('div', 'dsk-notice-head', esc(err.message || 'that could not be saved')));
  const problems = err.problems || [];
  if (problems.length && problems[0] !== err.message) {
    box.append(el('ul', 'dsk-problems',
      problems.map((p) => `<li>${esc(p)}</li>`).join('')));
  }
  return box;
}

async function run(action, okMessage) {
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
      show(active);
      return null;
    }
    throw err;
  }
}

/* ── the table ────────────────────────────────────────────────────────── */

/** The four or five fields worth a column, chosen from the catalogue.
    Positions, lore and nested lists are all real fields and all useless in a
    table — the identity, the name and the next few scalars are what you scan
    a list for. */
function columnsFor(section) {
  const skip = new Set(['objects', 'longtext', 'json', 'percent', 'strings']);
  const preferred = [section.id_field, section.title_field].filter(Boolean);
  const rest = section.fields
    .filter((f) => !skip.has(f.type) && !preferred.includes(f.name))
    .map((f) => f.name);
  return [...new Set([...preferred, ...rest])].slice(0, 5)
    .map((name) => section.fields.find((f) => f.name === name))
    .filter(Boolean);
}

function cellText(field, value) {
  if (value === undefined || value === null || value === '') return '—';
  if (field.type === 'bool') return value ? 'yes' : '—';
  if (Array.isArray(value)) return value.join(', ');
  return String(value);
}

function drawTable(key) {
  const section = Editor.section(key);
  setHead(section.plural.toUpperCase(), section.lore);
  bodyEl.innerHTML = '';

  if (section.kind === 'object') return drawObjectForm(key, section);

  const bar = el('div', 'dsk-bar');
  bar.append(el('span', 'dsk-bar-sub', esc(section.subtitle)));
  const search = el('input', 'dsk-input dsk-search');
  search.type = 'search';
  search.placeholder = `Search ${section.plural}…`;
  const add = el('button', 'dsk-btn dsk-btn-go', `+ new ${esc(section.singular)}`);
  add.addEventListener('click', () => drawForm(key, null, null));
  bar.append(search, add);
  bodyEl.append(bar);

  const entries = Editor.entries(key);
  if (!entries.length) {
    bodyEl.append(notice(`No ${section.plural} yet. Add the first one.`));
    return;
  }

  const columns = columnsFor(section);
  const overridden = new Set(Editor.overridden[key] || []);
  const table = el('table', 'dsk-table');
  table.innerHTML =
    `<thead><tr>${columns.map((c) => `<th>${esc(c.label)}</th>`).join('')}` +
    `<th class="dsk-th-act"></th></tr></thead>`;
  const tbody = el('tbody');

  entries.forEach((entry, index) => {
    const id = section.id_field ? entry[section.id_field] : null;
    const tr = el('tr');
    tr.dataset.find = JSON.stringify(entry).toLowerCase();
    for (const column of columns) {
      const td = el('td', column.type === 'color' ? 'dsk-td-color' : '');
      if (column.type === 'color' && entry[column.name]) {
        td.innerHTML = `<span class="dsk-dot" style="background:${esc(entry[column.name])}"></span>` +
                       `<code>${esc(entry[column.name])}</code>`;
      } else {
        td.innerHTML = `<span${['ip', 'cidr', 'slug'].includes(column.type) ? ' class="dsk-mono"' : ''}>` +
                       `${esc(cellText(column, entry[column.name]))}</span>`;
      }
      tr.append(td);
    }
    const act = el('td', 'dsk-td-act');
    const ref = section.id_field ? { id } : { index };
    act.append(
      iconBtn('✎', 'Edit', () => drawForm(key, entry, ref)),
      iconBtn('⧉', 'Duplicate', () => duplicate(key, entry)),
      iconBtn('✕', `Remove this ${section.singular}`, () => confirmDelete(key, entry, ref), 'warn'));
    tr.append(act);
    if (entry.state) tr.classList.add(`dsk-w-${entry.state}`);
    if (section.id_field && overridden.has(id)) {
      tr.classList.add('dsk-overridden');
      tr.title = 'The map is drawing this somewhere else — a saved layout overrides it.';
    }
    tbody.append(tr);
  });

  table.append(tbody);
  bodyEl.append(table);

  search.addEventListener('input', () => {
    const q = search.value.trim().toLowerCase();
    for (const tr of tbody.children) tr.hidden = q && !tr.dataset.find.includes(q);
  });
}

function iconBtn(glyph, title, onClick, kind) {
  const btn = el('button', `dsk-icon${kind ? ' dsk-icon-' + kind : ''}`, glyph);
  btn.title = title;
  btn.addEventListener('click', (e) => { e.stopPropagation(); onClick(); });
  return btn;
}

/* ── the form ─────────────────────────────────────────────────────────── */

function drawForm(key, entry, ref) {
  const section = Editor.section(key);
  const editing = Boolean(ref);
  setHead(`${editing ? 'EDIT' : 'NEW'} ${section.singular.toUpperCase()}`, section.subtitle);
  bodyEl.innerHTML = '';

  const form = buildForm(key, entry);
  const errors = el('div', 'dsk-form-errors');

  if (editing && section.id_field && (Editor.overridden[key] || []).includes(entry[section.id_field])) {
    bodyEl.append(notice(
      'A saved layout is currently placing this somewhere other than the position below. ' +
      'Changing the position here will clear that override.', 'warn'));
  }

  bodyEl.append(errors, form.el);
  if (key === 'regions') seatRegionView(form);

  const bar = el('div', 'dsk-formbar');
  const cancel = el('button', 'dsk-btn', 'Cancel');
  cancel.addEventListener('click', () => show(key));
  const save = el('button', 'dsk-btn dsk-btn-go', editing ? 'Save' : `Add ${esc(section.singular)}`);
  save.addEventListener('click', async () => {
    errors.innerHTML = '';
    let body;
    try {
      body = form.read();
    } catch (err) {
      errors.append(notice(err.message, 'bad'));
      return;
    }
    save.disabled = true;
    try {
      await run(() => Editor.saveEntry(key, editing ? ref : null, body));
      show(key);
    } catch (err) {
      errors.append(problemList(err));
    } finally {
      save.disabled = false;
    }
  });
  bar.append(cancel, save);
  bodyEl.append(bar);
  form.focus();
}

function drawObjectForm(key, section) {
  const form = buildForm(key, Editor.data?.[key] || {});
  const errors = el('div', 'dsk-form-errors');
  bodyEl.append(el('div', 'dsk-bar', `<span class="dsk-bar-sub">${esc(section.subtitle)}</span>`),
                errors, form.el);
  const bar = el('div', 'dsk-formbar');
  const save = el('button', 'dsk-btn dsk-btn-go', 'Save');
  save.addEventListener('click', async () => {
    errors.innerHTML = '';
    let body;
    try { body = form.read(); } catch (err) { errors.append(notice(err.message, 'bad')); return; }
    try {
      await run(() => Editor.upsert(key, null, body));
      show(key);
    } catch (err) { errors.append(problemList(err)); }
  });
  bar.append(save);
  bodyEl.append(bar);
  // The realm's own settings are where the backdrop belongs: picking one is
  // setting `meta.map_image`, and doing it from a gallery beats typing a
  // filename you have to remember exactly.
  if (key === 'meta') drawMapArt(form);
}

/** THE BACKDROP — choose or upload the picture the map is drawn on.
    Selecting writes the filename into the form's own map_image field rather
    than saving behind the user's back, so one Save still means one write and
    the change log still gets one row. */
async function drawMapArt(form) {
  const wrap = el('div', 'dsk-mapart');
  wrap.append(el('div', 'dsk-mapart-head',
    '<strong>THE BACKDROP</strong><span>the picture the map is drawn on — '
    + 'places are positioned in fractions of it, so swapping keeps every marker '
    + 'where it is</span>'));
  const gallery = el('div', 'dsk-mapart-grid');
  const errors = el('div', 'dsk-form-errors');
  wrap.append(errors, gallery);
  bodyEl.append(wrap);

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
function seatRegionView(form) {
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

async function duplicate(key, entry) {
  const section = Editor.section(key);
  const copy = JSON.parse(JSON.stringify(entry));
  if (section.id_field) {
    const taken = new Set(Editor.entries(key).map((e) => e[section.id_field]));
    let candidate = `${copy[section.id_field]}-copy`;
    let n = 2;
    while (taken.has(candidate)) candidate = `${copy[section.id_field]}-copy-${n++}`;
    copy[section.id_field] = candidate;
  }
  if (copy.name) copy.name = `${copy.name} (COPY)`;
  drawForm(key, copy, null);
}

/** Never delete without saying what else it takes with it. */
async function confirmDelete(key, entry, ref) {
  const section = Editor.section(key);
  const id = section.id_field ? entry[section.id_field] : null;
  const label = id || entry[section.title_field] || `#${ref.index + 1}`;

  let deps = [];
  if (id) {
    try { deps = (await Editor.dependents(key, id)).dependents || []; } catch { /* best effort */ }
  }

  bodyEl.innerHTML = '';
  setHead(`REMOVE ${String(label).toUpperCase()}`, 'this cannot be undone from here — but the chronicle remembers');
  bodyEl.append(notice(`Remove the ${section.singular} “${label}”?`, 'warn'));

  let cascade = false;
  if (deps.length) {
    const box = el('div', 'dsk-deps');
    box.append(el('div', 'dsk-deps-head',
      `${deps.length} other ${deps.length === 1 ? 'thing points' : 'things point'} at it:`));
    box.append(el('ul', 'dsk-problems', deps.map((d) => {
      const target = Editor.section(d.section);
      return `<li><strong>${esc(target ? target.noun || target.singular : d.section)} ` +
             `${esc(d.label)}</strong> <span class="dsk-dim">(${esc(d.field)})</span></li>`;
    }).join('')));
    const check = el('label', 'dsk-field dsk-field-bool');
    const input = el('input', 'dsk-check');
    input.type = 'checkbox';
    input.addEventListener('change', () => { cascade = input.checked; });
    check.append(input, el('span', 'dsk-label',
      'Also remove or unhook everything above (otherwise the removal is refused)'));
    box.append(check);
    bodyEl.append(box);
  }

  const bar = el('div', 'dsk-formbar');
  const cancel = el('button', 'dsk-btn', 'Keep it');
  cancel.addEventListener('click', () => show(key));
  const go = el('button', 'dsk-btn dsk-btn-warn', 'Remove');
  const errors = el('div', 'dsk-form-errors');
  go.addEventListener('click', async () => {
    errors.innerHTML = '';
    try {
      await run(() => Editor.removeEntry(key, ref, cascade));
      show(key);
    } catch (err) { errors.append(problemList(err)); }
  });
  bar.append(cancel, go);
  bodyEl.append(errors, bar);
}

/* ── the change log ───────────────────────────────────────────────────── */

async function drawChanges() {
  setHead(VIRTUAL.changes.label, VIRTUAL.changes.lore);
  bodyEl.innerHTML = '';
  const { revisions, kept } = await Editor.revisions();
  if (!revisions.length) {
    bodyEl.append(notice('Nothing has been changed in the map editor yet.'));
    return;
  }
  bodyEl.append(el('div', 'dsk-bar',
    `<span class="dsk-bar-sub">The last ${kept} changes can be undone; older ones are ` +
    `remembered but their snapshots have been pruned.</span>`));

  const list = el('div', 'dsk-revs');
  for (const rev of revisions) {
    const row = el('div', 'dsk-rev');
    row.append(el('span', 'dsk-rev-when', `${esc(rev.at)}`));
    row.append(el('span', 'dsk-rev-who', esc(rev.actor)));
    row.append(el('span', 'dsk-rev-what',
      (rev.summary || []).map((s) => esc(s)).join(' · ') + (rev.note ? ` — ${esc(rev.note)}` : '')));
    if (rev.revertable) {
      const undo = el('button', 'dsk-btn dsk-btn-sm', 'Undo to here');
      undo.title = `Put the map back to how it was before change #${rev.id}`;
      undo.addEventListener('click', async () => {
        undo.disabled = true;
        try {
          await run(() => Editor.revert(rev.id), 'The map is back to how it was.');
          show('changes');
        } catch (err) {
          bodyEl.prepend(problemList(err));
          undo.disabled = false;
        }
      });
      row.append(undo);
    } else {
      row.append(el('span', 'dsk-dim', 'pruned'));
    }
    list.append(row);
  }
  bodyEl.append(list);
}

/* ── the discovery inbox ──────────────────────────────────────────────── */

/** Where a newcomer's router keeps its leases. Shared with the first survey. */
export const LEASE_HELP =
  'Or your router\'s DHCP leases — the devices that asked it for an address, with the ' +
  'names they gave themselves. Copy the file and paste it whole: ' +
  '<code>/var/dhcpd/var/db/dhcpd.leases</code> on pfSense or OPNsense, ' +
  '<code>kea-leases4.csv</code> where they run Kea, <code>/etc/pihole/dhcp.leases</code> ' +
  'on Pi-hole, <code>/tmp/dhcp.leases</code> on OpenWrt, or on Windows Server ' +
  '<code>Get-DhcpServerv4Lease -ScopeId 10.0.0.0 | ConvertTo-Csv</code>.';

async function drawSurvey() {
  setHead(VIRTUAL.survey.label, VIRTUAL.survey.lore);
  bodyEl.innerHTML = '';

  const { observed, undocumented } = await Editor.discovery();
  const badge = $('dsk-n-survey');
  if (badge) badge.textContent = undocumented ? String(undocumented) : '';

  bodyEl.append(el('div', 'dsk-bar',
    `<span class="dsk-bar-sub">The Atlas never probes the network itself. Run a sweep ` +
    `where you already have the rights, or copy your router's DHCP leases, and hand it ` +
    `the result.</span>`));

  const paste = el('details', 'dsk-drop');
  paste.innerHTML = `<summary>Bring in a survey (nmap XML) or DHCP leases</summary>` +
    `<p class="dsk-help">A sweep, on a machine that can see the segment:<br>` +
    `<code>nmap -sn -oX - 192.0.2.0/24</code><br>A ping sweep is enough — a port scan is ` +
    `not required and not advised on someone else's network.</p>` +
    `<p class="dsk-help">${LEASE_HELP}</p>`;
  const area = el('textarea', 'dsk-input dsk-area dsk-mono');
  area.rows = 5;
  area.placeholder = '<?xml version="1.0"?><nmaprun …>   or a lease file';
  const go = el('button', 'dsk-btn dsk-btn-go', 'File this survey');
  go.addEventListener('click', async () => {
    if (!area.value.trim()) return;
    go.disabled = true;
    try {
      const res = await Editor.fileSurvey(area.value);
      A.showToast?.(res.format
        ? `${res.seen} ${res.format} leases · ${res.new} new to the survey.`
        : `${res.seen} answered · ${res.new} new to the survey.`);
      area.value = '';
      show('survey');
    } catch (err) {
      paste.append(problemList(err));
    } finally { go.disabled = false; }
  });
  paste.append(area, go);
  bodyEl.append(paste);

  if (!observed.length) {
    bodyEl.append(notice('Nothing surveyed yet.'));
    return;
  }

  const chosen = new Set();
  const boxes = [];
  const table = el('table', 'dsk-table');
  table.innerHTML = '<thead><tr><th class="dsk-th-pick"></th><th>Address</th><th>Name</th>' +
    '<th>Vendor</th><th>Open ports</th><th>Looks like</th><th>Realm</th><th>State</th>' +
    '<th class="dsk-th-act"></th></tr></thead>';
  // a first survey is often dozens of strangers: one box takes them all
  const all = el('input', 'dsk-check');
  all.type = 'checkbox';
  all.title = 'Choose every uncharted device';
  all.setAttribute('aria-label', 'Choose every uncharted device');
  table.querySelector('.dsk-th-pick').append(all);
  const sync = () => {
    chart.disabled = chosen.size === 0;
    chart.textContent = chosen.size ? `Chart ${chosen.size} of these ›` : 'Chart the chosen ›';
    const open = boxes.filter((b) => !b.box.disabled);
    all.checked = open.length > 0 && open.every((b) => b.box.checked);
    all.disabled = open.length === 0;
  };
  all.addEventListener('change', () => {
    for (const { box, key } of boxes) {
      if (box.disabled) continue;
      box.checked = all.checked;
      all.checked ? chosen.add(key) : chosen.delete(key);
    }
    sync();
  });
  const tbody = el('tbody');
  for (const row of observed) {
    const tr = el('tr', row.ignored ? 'dsk-dim-row' : '');
    const pick = el('td', 'dsk-td-pick');
    const box = el('input', 'dsk-check');
    box.type = 'checkbox';
    box.disabled = !row.undocumented || row.ignored;
    boxes.push({ box, key: row.key });
    box.addEventListener('change', () => {
      box.checked ? chosen.add(row.key) : chosen.delete(row.key);
      sync();
    });
    pick.append(box);
    tr.append(pick);
    tr.append(el('td', '', `<span class="dsk-mono">${esc(row.ip || row.mac || '—')}</span>`));
    tr.append(el('td', '', esc(row.hostname || '—')));
    tr.append(el('td', '', esc(row.vendor || '—')));
    tr.append(el('td', '', esc((row.ports || []).map((p) => p.port).slice(0, 8).join(' ') || '—')));
    // a suggestion, with its reason on hover; the draft says it again
    const guess = row.suggestion;
    const looks = el('td', '', guess
      ? `${esc(guess.role)} <span class="dsk-dim">${esc(guess.kind)}</span>` : '—');
    if (guess) looks.title = `A guess: ${guess.because}. Check it when you chart it.`;
    tr.append(looks);
    tr.append(el('td', '', esc(row.suggested_zone || '—')));
    const seenBy = row.source ? ` <span class="dsk-dim">· ${esc(row.source)}</span>` : '';
    tr.append(el('td', '', row.ignored
      ? '<span class="dsk-dim">silenced</span>'
      : row.undocumented
        ? `<span class="dsk-warn">uncharted</span>${seenBy}`
        : `<span class="dsk-ok">charted as ${esc(row.matched_node)}</span>`));
    const act = el('td', 'dsk-td-act');
    act.append(iconBtn(row.ignored ? '👁' : '🚫',
      row.ignored ? 'Bring it back into the survey' : "Silence it — I don't want this charted",
      async () => {
        await Editor.decide([row.key], row.ignored ? 'unignore' : 'ignore');
        show('survey');
      }));
    tr.append(act);
    tbody.append(tr);
  }
  table.append(tbody);
  bodyEl.append(table);

  const bar = el('div', 'dsk-formbar');
  const chart = el('button', 'dsk-btn dsk-btn-go', 'Chart the chosen ›');
  chart.addEventListener('click', () => draftReview([...chosen]));
  bar.append(chart);
  bodyEl.append(bar);
  sync();
}

/** The review step: drafts are shown and corrected before anything is written. */
async function draftReview(keys) {
  const { nodes } = await Editor.draftsFrom(keys);
  drawDrafts(nodes, `${nodes.length} place${nodes.length === 1 ? '' : 's'} from the survey`,
    'A survey can say a thing answered, not what it is: each lands as <code>unknown</code> ' +
    'unless its maker or its own name suggests a type, and then its role line says why. ' +
    'Check those, give them names and realms now, or later.');
}

function drawDrafts(nodes, headline, caveat) {
  setHead('CHART THESE PLACES', 'nothing is written until you say so');
  bodyEl.innerHTML = '';
  if (!nodes.length) { bodyEl.append(notice('Nothing to chart.')); return; }
  bodyEl.append(el('div', 'dsk-bar', `<span class="dsk-bar-sub">${esc(headline)}. ` +
    (caveat || 'Correct anything that came through wrong, then chart them.') + `</span>`));

  const forms = nodes.map((node) => {
    const wrap = el('details', 'dsk-draft');
    wrap.open = nodes.length <= 3;
    wrap.append(el('summary', '', `${esc(node.name)} <span class="dsk-mono">${esc(node.ip)}</span>`));
    const form = buildForm('nodes', node);
    wrap.append(form.el);
    bodyEl.append(wrap);
    return form;
  });

  const errors = el('div', 'dsk-form-errors');
  const bar = el('div', 'dsk-formbar');
  const cancel = el('button', 'dsk-btn', 'Not yet');
  cancel.addEventListener('click', () => show('survey'));
  const go = el('button', 'dsk-btn dsk-btn-go', `Chart ${forms.length}`);
  go.addEventListener('click', async () => {
    errors.innerHTML = '';
    let ops;
    try {
      ops = forms.map((f) => ({ op: 'insert', section: 'nodes', body: f.read() }));
    } catch (err) { errors.append(notice(err.message, 'bad')); return; }
    go.disabled = true;
    try {
      // One batch: either every discovered place lands or none does, so a
      // typo in the fourth doesn't leave three half-charted strangers.
      await run(() => Editor.apply(ops, 'charted from a survey'));
      show('nodes');
    } catch (err) {
      errors.append(problemList(err));
      go.disabled = false;
    }
  });
  bar.append(cancel, go);
  bodyEl.append(errors, bar);
}

/* ── routing ──────────────────────────────────────────────────────────── */

async function show(key) {
  active = key;
  drawSidebar();
  bodyEl.scrollTop = 0;
  try {
    if (key === 'changes') return await drawChanges();
    if (key === 'survey') return await drawSurvey();
    return drawTable(key);
  } catch (err) {
    bodyEl.innerHTML = '';
    bodyEl.append(problemList(err));
  }
}

export async function openDesk(sectionKey) {
  if (!root) return;
  root.classList.add('open');
  root.setAttribute('aria-hidden', 'false');
  A.closeCard?.();
  if (!booted) {
    bodyEl.innerHTML = '<div class="dsk-notice">Opening the map editor…</div>';
    try {
      await Editor.load();
      await Editor.loadRepairs();
      booted = true;
    } catch (err) {
      bodyEl.innerHTML = '';
      bodyEl.append(problemList(err));
      return;
    }
    if (!Editor.writable()) {
      bodyEl.prepend(notice(
        Editor.ctx.read_only
          ? 'This Atlas is read-only (ATLAS_READONLY=1). You can look, but nothing here will save.'
          : 'The dataset is not writable by this process — check the mount and its permissions.',
        'warn'));
    }
  } else {
    await Editor.reload();
  }
  try {
    await Editor.loadRepairs();
  } catch { /* the repairs endpoint is admin-only and may legitimately fail */ }
  await show(sectionKey || active);
}

export function closeDesk() {
  if (!root) return;
  root.classList.remove('open');
  root.setAttribute('aria-hidden', 'true');
}

export function deskOpen() {
  return root?.classList.contains('open') ?? false;
}

/** Offer the drafts from a pasted CSV — used by the first-run wizard. */
export async function reviewCsv(text) {
  const { nodes } = await Editor.importCsv(text);
  await openDesk();
  drawDrafts(nodes, `${nodes.length} place${nodes.length === 1 ? '' : 's'} from your list`,
    'Positions default to the middle of the map — drag them where they belong afterwards, ' +
    'or set them here.');
}

export function buildDesk() {
  root = $('desk');
  if (!root) return;
  sideEl = $('dsk-nav');
  bodyEl = $('dsk-body');
  titleEl = $('dsk-title');
  subEl = $('dsk-sub');
  $('dsk-close')?.addEventListener('click', () => { closeDesk(); A.recenter?.(true); });
  root.addEventListener('pointerdown', (e) => { if (e.target === root) closeDesk(); });
}
