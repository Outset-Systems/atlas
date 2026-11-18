/* NODES, the Check… form (2026-11-17): a place's or a service's check, in
   the scope bar. Moved unchanged out of nodes-forms.js, which imports
   `checkForm` back for its FORMS table and still exports `openCheck`. The
   two import each other, which is safe because neither calls the other
   while it loads. */

import { refusalHTML } from './config.js';
import { input, select } from './alert-forms.js';
import * as M from './menu-model.js';
import { serviceKey } from './alerts-model.js';
import Editor, { EditorError } from './editor/store.js';
import { numberValue } from './editor/form-model.js';
import { t } from './nodes-text.js';
import { S, shared } from './nodes-state.js';
import {
  tell, done, ready, busy, applyOps, openScope, field, formBox, noteBox,
} from './nodes-forms.js';
import { focusMore, forgetCheck } from './nodes-menu.js';

/* ── Check… (2026-11-17): a check's own fields, in the scope bar ──────────
   A place's or a service's menu opens its check's fields here: the Desk
   form's own (menu-model CHECK_FIELDS: type, address, port, expects,
   every), with their labels, options, limits and help read from the
   schema the editor's store loads, so they are written once, in
   schema.py. Saved through the ops path every NODES write takes (undo,
   revisions and the conflict rule come with it); a place's fields are a
   patch on the place, a service's are laid on its link and its place's
   `links` written whole, as unmanaged is. What the server refuses is said
   inside the form, which stays open. */

/** The schema's fields for a place's check, or a service link's. */
function checkSchema(kind) {
  const fields = Editor.section('nodes')?.fields || [];
  const list = kind === 'service' ? (fields.find((f) => f.name === 'links')?.of || []) : fields;
  return M.CHECK_FIELDS.map((name) => list.find((f) => f && f.name === name)).filter(Boolean);
}

/** The place, or the service's link, as it is on disk; null when gone.
    A service is found by its key on its place (`scope.place`). */
function checkEntry(scope) {
  const nodes = Array.isArray(Editor.data?.nodes) ? Editor.data.nodes : [];
  if (scope.kind === 'place') return { node: nodes.find((n) => n && n.id === scope.id) || null, index: -1 };
  const node = nodes.find((n) => n && n.id === scope.place) || null;
  const links = Array.isArray(node?.links) ? node.links : [];
  const index = links.findIndex((l) => l && typeof l === 'object' && serviceKey(node.id, l) === scope.id);
  return { node: index < 0 ? null : node, index };
}

/** Open the Check… form for one place or service: the editor's store (its
    schema and the map on disk) is read first, since the form is built from
    them. */
export async function openCheck(scope) {
  if (!Editor.loaded) {
    try { await Editor.load(); } catch (err) {
      tell(t('nodes_editor_failed', { why: err.message || String(err) }), 'bad');
      return;
    }
  }
  openScope({ ...scope, form: 'check' });
}

export function checkForm(scope) {
  const fields = scope ? checkSchema(scope.kind) : [];
  if (!fields.length) return noteBox(t('nodes_check_none'));
  const { node, index } = checkEntry(scope);
  const entry = scope.kind === 'place' ? node : node?.links?.[index];
  if (!entry) return noteBox(t('nodes_check_gone'));
  const read = {};
  const parts = fields.map((fld) => {
    const had = entry[fld.name];
    let control;
    if (fld.type === 'select') {
      const options = (fld.options || []).map((o) => [o, o || t('nodes_check_default')]);
      // a hand edit's value the list does not offer stays, so a save of
      // another field never quietly changes it
      if (typeof had === 'string' && had && !(fld.options || []).includes(had)) options.unshift([had, had]);
      control = select(options, had ?? '');
      read[fld.name] = () => control.value;
    } else if (fld.type === 'int' || fld.type === 'number') {
      control = input('number', had ?? '', 'dsk-input dsk-num');
      control.step = fld.type === 'int' ? '1' : 'any';
      if (fld.min !== undefined) control.min = fld.min;
      if (fld.max !== undefined) control.max = fld.max;
      read[fld.name] = () => numberValue(control.value);
    } else {
      control = input('text', typeof had === 'string' ? had : (had ?? ''));
      control.maxLength = 500;
      read[fld.name] = () => control.value.trim();
    }
    if (fld.help) control.title = fld.help;
    return field(fld.label || fld.name, control);
  });
  const problems = document.createElement('div');
  problems.className = 'nv-form-problems';
  problems.setAttribute('aria-live', 'polite');
  const typeHelp = fields.find((f) => f.name === 'check')?.help || '';
  const box = formBox(parts, t('nodes_check_go'), () => {
    const values = Object.fromEntries(Object.entries(read).map(([name, fn]) => [name, fn()]));
    saveCheck(scope, values, problems);
  }, typeHelp);
  box.insertBefore(problems, box.querySelector('.nv-form-bar'));
  return box;
}

/** What the server refused, inside the form: its words, and each problem. */
function showProblems(host, err) {
  if (!err) { host.innerHTML = ''; return; }
  host.innerHTML = refusalHTML(err);
}

async function saveCheck(scope, values, problems) {
  showProblems(problems, null);
  let saved = false;
  let refused = false;
  await busy(async () => {
    if (!(await ready())) return;
    // read again under the fresh stamp: the patch is from what is on disk now
    const { node, index } = checkEntry(scope);
    if (!node) { tell(t('nodes_check_gone'), 'warn'); return; }
    let ops;
    if (scope.kind === 'place') {
      const patch = M.checkPatch(node, values);
      if (!Object.keys(patch).length) { tell(t('nodes_already')); return; }
      ops = [{ op: 'upsert', section: 'nodes', id: node.id, body: patch }];
    } else {
      const patch = M.checkPatch(node.links[index], values);
      if (!Object.keys(patch).length) { tell(t('nodes_already')); return; }
      const links = node.links.map((l, i) => (i === index ? M.patched(l, patch) : l));
      ops = [{ op: 'upsert', section: 'nodes', id: node.id, body: { links } }];
    }
    try {
      const { stopped } = await applyOps(ops, scope.kind === 'place' ? 'changed a check' : "changed a service's check");
      if (stopped) return;
    } catch (err) {
      // the server's words for a value it will not take, in the form
      if (err instanceof EditorError && (err.status === 400 || err.status === 422)) {
        showProblems(problems, err);
        refused = true;
        return;
      }
      throw err;
    }
    saved = true;
    S.form = '';
    S.scope = null;
    shared.formEl = null;
    shared.formFor = '';
    forgetCheck(scope.id);
    done(t('nodes_check_saved', { name: scope.name }));
  });
  if (saved) focusMore(scope.kind, scope.id);
  else if (refused) problems.closest('form')?.querySelector('input, select')?.focus();
}
