/* THE SURVEYOR'S DESK — THE CHRONICLE OF CHANGES: who altered what, and the
   way back. The panel itself is reached through `desk` (desk-kit.js). */

import { esc } from '../config.js';
import Editor from './store.js';
import { makeEl as el } from './form.js';
import { VIRTUAL, desk, notice, problemList, run } from './desk-kit.js';

/* ── the change log ───────────────────────────────────────────────────── */

export async function drawChanges() {
  desk.setHead(VIRTUAL.changes.label, VIRTUAL.changes.lore);
  desk.body.innerHTML = '';
  const { revisions, kept } = await Editor.revisions();
  if (!revisions.length) {
    desk.body.append(notice('Nothing has been changed in the map editor yet.'));
    return;
  }
  desk.body.append(el('div', 'dsk-bar',
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
          desk.show('changes');
        } catch (err) {
          desk.body.prepend(problemList(err));
          undo.disabled = false;
        }
      });
      row.append(undo);
    } else {
      row.append(el('span', 'dsk-dim', 'pruned'));
    }
    list.append(row);
  }
  desk.body.append(list);
}
