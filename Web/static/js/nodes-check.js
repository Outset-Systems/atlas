
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


function checkSchema(kind) {
  const fields = Editor.section('nodes')?.fields || [];
  const list = kind === 'service' ? (fields.find((f) => f.name === 'links')?.of || []) : fields;
  return M.CHECK_FIELDS.map((name) => list.find((f) => f && f.name === name)).filter(Boolean);
}

function checkEntry(scope) {
  const nodes = Array.isArray(Editor.data?.nodes) ? Editor.data.nodes : [];
  if (scope.kind === 'place') return { node: nodes.find((n) => n && n.id === scope.id) || null, index: -1 };
  const node = nodes.find((n) => n && n.id === scope.place) || null;
  const links = Array.isArray(node?.links) ? node.links : [];
  const index = links.findIndex((l) => l && typeof l === 'object' && serviceKey(node.id, l) === scope.id);
  return { node: index < 0 ? null : node, index };
}

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
