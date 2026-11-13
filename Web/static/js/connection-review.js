/* CONNECTIONS — the review: what a connected system knows, listed for an admin
   to tick.

   REVIEW is the Network Sonar shape: read what a system knows, list it, and let an
   admin tick what to add or mark things ignored. Nothing is ticked to begin with,
   a tick only ever adds, and the import is one change-log entry with an Undo. It
   runs when someone presses the button, never in the background.

   connections.js draws the system cards and calls `reviewSystem` from each
   card's Review button. Which rows can be ticked, what a tick brings with it and
   what ignoring a host does are connections-model.js; this draws the list and
   sends the choices. `post` is here because both files send JSON the same way
   and this one cannot import the other. */

import { A, esc, postJSON } from './config.js';
import { say } from './words.js';
import { follow, groupsOf, ignoreLocally, tickable } from './connections-model.js';

export async function post(url, body) {
  const r = await postJSON(url, body);
  return { r, j: await r.json().catch(() => ({})) };
}

/* ── the review ───────────────────────────────────────────────────────── */

const FILTER_FROM = 12;   // below this a list is short enough to read

function rowState(r, zones) {
  // a charted row can still disagree with the map about a name, and says so
  if (r.status === 'charted') return `on the map as ${esc(r.matched)}${r.note ? `. ${esc(r.note)}` : ''}`;
  if (r.note) return esc(r.note);
  if (r.type === 'zone') return say('a new realm');
  if (r.type === 'service') return 'a service on its host';
  if (r.type === 'port') return 'a port on its device';
  if (r.type === 'route') return 'a link between them';
  if (r.type === 'fact') return 'adds to what the map has';
  const zone = zones.find((z) => z.id === r.zone);
  return zone ? `lands in ${esc(zone.name)}` : say('no realm yet');
}

function reviewRow(r, zones) {
  const off = !tickable(r);
  const worry = r.status === 'clash' || r.blocked;
  const act = r.status === 'ignored'
    ? `<button class="sp-btn" type="button" data-unignore="${esc(r.key)}">Bring back</button>`
    : r.status === 'charted' ? ''
      : `<button class="sp-btn" type="button" data-ignore="${esc(r.key)}">Ignore</button>`;
  return `<div class="con-row${off ? ' con-off' : ''}" data-row="${esc(r.key)}">
      <input type="checkbox" class="con-pick" data-pick="${esc(r.key)}" aria-label="Add ${esc(r.name)}"${off ? ' disabled' : ''}>
      <span class="con-row-text">
        <span class="con-name">${esc(r.name)}</span>
        ${r.ip && r.ip !== '—' ? `<span class="con-ip">${esc(r.ip)}</span>` : ''}
        <span class="con-meta con-row-line">${[r.detail && esc(r.detail), `<span class="${worry ? 'con-worry' : ''}">${rowState(r, zones)}</span>`].filter(Boolean).join(' · ')}</span>
      </span>
      ${act}
    </div>`;
}

function reviewHTML(view) {
  const { rows, zones, notes } = view;
  const open = rows.filter((r) => r.status !== 'ignored');
  const ignored = rows.filter((r) => r.status === 'ignored');
  const fresh = rows.filter(tickable).length;
  const charted = rows.filter((r) => r.status === 'charted').length;
  if (!rows.length) return '<div class="acct-note">It answered, but it has nothing to list.</div>';
  const lists = [...groupsOf(open)].map(([group, members]) => {
    const all = members.some(tickable)
      ? `<label class="con-all"><input type="checkbox" data-all="${esc(group)}"> all</label>` : '';
    return `<div class="con-group"><div class="dir-label">${esc(group)} ${all}</div>
      ${members.map((r) => reviewRow(r, zones)).join('')}</div>`;
  }).join('');
  // Uncharted is the blank choice, made if the map has not got it
  const choices = zones.filter((z) => z.id !== 'uncharted').map((z) => `<option value="${esc(z.id)}">${esc(z.name)}</option>`).join('');
  return `<div class="acct-note">${fresh} new · ${charted} already on the map${ignored.length ? ` · ${ignored.length} ignored` : ''}.
      Nothing is added until you tick it.</div>
    ${notes.map((n) => `<div class="acct-note">${esc(n)}</div>`).join('')}
    ${rows.length > FILTER_FROM ? '<input class="dir-input con-filter" data-filter placeholder="filter by name or address" aria-label="Filter" autocomplete="off" spellcheck="false">' : ''}
    ${lists}
    ${ignored.length ? `<details class="con-ignored"><summary class="con-meta">Ignored (${ignored.length})</summary>
      ${ignored.map((r) => reviewRow(r, zones)).join('')}</details>` : ''}
    ${fresh ? `<label class="dir-row"><span class="dir-label">${say('Realm for a place whose address names none')}</span>
      <select class="dir-input" data-fallback><option value="">Uncharted</option>${choices}</select></label>
    <div class="sp-actions"><button class="sp-btn sp-btn-go" type="button" data-import disabled>Add to the map</button></div>` : ''}`;
}

function syncTicks(box, view) {
  const picks = [...box.querySelectorAll('[data-pick]:checked')];
  const go = box.querySelector('[data-import]');
  if (go) {
    go.disabled = !picks.length;
    go.textContent = picks.length ? `Add ${picks.length} to the map` : 'Add to the map';
  }
  for (const all of box.querySelectorAll('[data-all]')) {
    const boxes = view.rows.filter((r) => r.group === all.dataset.all && tickable(r)).map((r) => pickBox(box, r.key));
    all.checked = boxes.length > 0 && boxes.every((b) => b?.checked);
  }
}

const pickBox = (box, key) => box.querySelector(`[data-pick="${CSS.escape(key)}"]`);

/** Ticking a service, a port or a link ticks what it stands on, and unticking a
    host unticks what stood on it. Which rows those are is the model's `follow`. */
function followTick(box, view, key, checked) {
  const { tick, untick } = follow(view.rows, key, checked);
  for (const end of tick) {
    const host = pickBox(box, end);
    if (host && !host.disabled) host.checked = true;
  }
  for (const stood of untick) {
    const child = pickBox(box, stood);
    if (child) child.checked = false;
  }
}

function resultLine(box, cls, text) {
  const line = box.querySelector('[data-review-result]');
  line.className = `dir-result ${cls}`;
  line.textContent = text;
  return line;
}

async function runImport(key, box, view) {
  const picks = [...box.querySelectorAll('[data-pick]:checked')].map((b) => b.dataset.pick);
  const go = box.querySelector('[data-import]');
  go.disabled = true;
  resultLine(box, '', 'Reading it again and adding…');
  let answer;
  try {
    answer = await post('api/v2/admin/connections/import',
      { key, picks, expect: view.stamp, zone: box.querySelector('[data-fallback]')?.value || '' });
  } catch {
    resultLine(box, 'dir-bad', 'It did not answer. Nothing was added.');
    go.disabled = false;
    return;
  }
  const { r, j } = answer;
  if (!r.ok) {
    resultLine(box, 'dir-bad', (j.problems || [j.error || 'Could not add those.']).join(' '));
    go.disabled = false;
    return;
  }
  await A.refreshData?.();
  // the list redraws from a fresh read, and if that fails the import still happened
  const next = await drawReview(key, box).catch(() => box);
  const line = resultLine(next, 'dir-ok', `Added ${j.added} to the map. It is in the change log. `);
  const undo = document.createElement('button');
  undo.className = 'sp-btn';
  undo.type = 'button';
  undo.textContent = 'Undo';
  undo.addEventListener('click', async () => {
    undo.disabled = true;
    const back = await post(`api/v2/admin/revisions/${j.revision}/revert`, { expect: j.stamp });
    if (!back.r.ok) {
      undo.disabled = false;
      resultLine(next, 'dir-bad', `${back.j.error || 'Could not undo that.'} `).append(undo);
      return;
    }
    await A.refreshData?.();
    const after = await drawReview(key, next).catch(() => next);
    resultLine(after, 'dir-ok', 'Undone. The map is as it was.');
  });
  line.append(undo);
}

function wireReview(key, box, view) {
  box.addEventListener('change', (e) => {
    const t = e.target;
    if (t.dataset.pick) followTick(box, view, t.dataset.pick, t.checked);
    if (t.dataset.all) {
      for (const r of view.rows) {
        if (r.group !== t.dataset.all || !tickable(r)) continue;
        const pick = pickBox(box, r.key);
        if (pick.closest('.con-row').hidden) continue;
        pick.checked = t.checked;
        followTick(box, view, r.key, t.checked);
      }
    }
    syncTicks(box, view);
  });
  box.querySelector('[data-filter]')?.addEventListener('input', (e) => {
    const want = e.target.value.trim().toLowerCase();
    for (const r of view.rows) {
      const row = box.querySelector(`[data-row="${CSS.escape(r.key)}"]`);
      if (row) row.hidden = !`${r.name} ${r.ip}`.toLowerCase().includes(want);
    }
  });
  box.addEventListener('click', async (e) => {
    const t = e.target.closest('button');
    if (!t) return;
    if (t.dataset.import !== undefined) { await runImport(key, box, view); return; }
    const ignoring = t.dataset.ignore !== undefined;
    if (!ignoring && t.dataset.unignore === undefined) return;
    const target = ignoring ? t.dataset.ignore : t.dataset.unignore;
    t.disabled = true;
    const { r } = await post('api/v2/admin/discovery/decide',
      { keys: [target], action: ignoring ? 'ignore' : 'unignore' });
    if (!r.ok) { t.disabled = false; return; }
    ignoreLocally(view, target, ignoring);
    paintReview(key, box, view);
  });
}

function paintReview(key, box, view) {
  // a fresh node each time, so a repaint cannot stack a second set of listeners
  const ticked = [...box.querySelectorAll('[data-pick]:checked')].map((b) => b.dataset.pick);
  const next = box.cloneNode(false);
  next.innerHTML = `${reviewHTML(view)}<div class="dir-result" data-review-result></div>`;
  box.replaceWith(next);
  wireReview(key, next, view);
  for (const pick of ticked) {
    const again = pickBox(next, pick);
    if (again && !again.disabled) again.checked = true;
  }
  syncTicks(next, view);
  return next;
}

async function drawReview(key, box) {
  const { j } = await post('api/v2/admin/connections/review', { key });
  if (!j.ok) throw new Error(j.error || 'It did not answer.');
  box.hidden = false;
  box.querySelectorAll('[data-pick]:checked').forEach((b) => { b.checked = false; });
  return paintReview(key, box, { rows: j.rows, zones: j.zones, notes: j.notes, stamp: j.stamp });
}

export async function reviewSystem(key, card, status, btn) {
  status.className = 'dir-result';
  status.textContent = 'Reading what it knows…';
  btn.disabled = true;
  try {
    await drawReview(key, card.querySelector('[data-review]'));
    status.textContent = '';
  } catch (e) {
    status.className = 'dir-result dir-bad';
    status.textContent = e.message || 'It did not answer.';
  } finally {
    btn.disabled = false;
  }
}
