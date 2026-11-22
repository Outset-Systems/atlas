
import { A, esc, canAdminWrite } from './config.js';
import * as M from './menu-model.js';
import { t as nt } from './nodes-text.js';
import { T, t, addTool, lightPath, clearLight, stageEl, svgEl } from './topology-state.js';

const words = (item) => M.wordsOf(item, nt);

const mayAsk = () => canAdminWrite() && document.body.dataset.editable === '1';

const N = {
  el: null,
  light: null,
  seq: 0,
  pending: '',
  timer: 0,
  back: '',
};


let removeTool = null;

function syncTool() {
  if (mayAsk()) {
    if (!removeTool) removeTool = addTool({ id: 'diagnose', label: t('tp_dx'), title: t('tp_dx_title'), onPress: press });
    return;
  }
  if (removeTool) { removeTool(); removeTool = null; }
  hideNote();
}

async function press() {
  const id = T.selected;
  const th = id ? T.shown?.byId.get(id) : null;
  if (!th) { sayNote(t('tp_dx_pick')); return; }
  if (th.type !== 'place') { sayNote(t('tp_dx_not_place')); return; }
  const name = th.name || id;
  const held = M.diagnoseAsk(T.data || A.DATA, id);
  if (typeof held === 'string' && held) { sayNote(nt(`nodes_dx_${held}`), name, 'warn'); return; }
  if (N.pending === id) return;
  const seq = ++N.seq;
  N.pending = id;
  N.back = id;
  sayNote(nt('nodes_asking'), name, 'asking');
  const got = typeof A.askDiagnose === 'function' ? await A.askDiagnose(id) : { status: 0, ok: false, body: null };
  if (N.pending === id) N.pending = '';
  if (seq !== N.seq || !T.up) return;
  const { status, ok, body } = got || {};
  if (ok && body && typeof body === 'object' && Array.isArray(body.steps)) showAnswer(body);
  else sayNote(words(M.diagnoseRefusal(status || 0, body)), name, 'warn');
}


function showAnswer(answer) {
  const light = M.diagnoseLight(answer);
  lightPath(light.things, light.links, light.failedAt);
  N.light = T.path;
  N.back = typeof answer.id === 'string' ? answer.id : N.back;
  drawAnswer(answer);
}

function noteEl() {
  const stage = stageEl();
  if (!stage) return null;
  if (!N.el || !stage.contains(N.el)) {
    N.el = document.createElement('div');
    N.el.className = 'tp-dx';
    N.el.hidden = true;
    N.el.setAttribute('role', 'region');
    N.el.setAttribute('aria-label', t('tp_dx'));
    N.el.addEventListener('click', (e) => { if (e.target.closest('[data-dx-close]')) closeNote(true); });
    stage.append(N.el);
  }
  return N.el;
}

const head = (title) => '<div class="tp-dx-head">' +
  `<p class="tp-dx-name">${esc(title)}</p>` +
  `<button type="button" class="tp-btn" data-dx-close>${esc(t('tp_note_close'))}</button></div>`;

function sayNote(text, name = '', tone = '') {
  const note = noteEl();
  if (!note) return;
  if (tone !== 'asking') stopWatch();
  if (N.light && T.path === N.light) clearLight();
  N.light = null;
  note.innerHTML = head(name ? t('tp_dx_head', { name }) : t('tp_dx')) +
    `<p class="tp-dx-say${tone ? ` tp-dx-${tone}` : ''}" role="status">${esc(text)}</p>`;
  note.hidden = false;
}

function drawAnswer(answer) {
  const note = noteEl();
  if (!note) return;
  const sum = M.diagnoseSummary(answer);
  const lines = M.diagnoseLines(answer);
  const name = typeof answer.name === 'string' && answer.name ? answer.name : answer.id;
  note.innerHTML = head(t('tp_dx_head', { name })) +
    `<p class="tp-dx-sum${sum.tone ? ` tp-dx-${sum.tone}` : ''}" tabindex="-1">${esc(words(sum))}</p>` +
    `<ol class="tp-dx-steps">${lines.map((l) => `<li class="tp-dx-step${l.tone ? ` tp-dx-${l.tone}` : ' tp-dx-quiet'}` +
      `${l.broke ? ' tp-dx-broke' : ''}">${esc(l.parts.map(words).join(' · '))}</li>`).join('')}</ol>`;
  note.hidden = false;
  note.querySelector('.tp-dx-sum')?.focus({ preventScroll: true });
  watch();
}

function watch() {
  stopWatch();
  N.timer = setInterval(() => {
    if (!N.el || N.el.hidden || !N.light) { stopWatch(); return; }
    if (T.path !== N.light) hideNote();
  }, 300);
}
function stopWatch() { clearInterval(N.timer); N.timer = 0; }

function hideNote() {
  stopWatch();
  N.seq++;
  N.pending = '';
  N.light = null;
  if (N.el) { N.el.hidden = true; N.el.innerHTML = ''; }
}

function closeNote(focusBack) {
  const lit = N.light && T.path === N.light;
  const back = N.back;
  hideNote();
  if (lit) clearLight();
  if (!focusBack) return;
  const card = back ? svgEl()?.querySelector(`.tp-card[data-id="${CSS.escape(back)}"]`) : null;
  (card || document.querySelector('#view-topology [data-tool="diagnose"]'))?.focus({ preventScroll: true });
}


A.showDiagnosis = function showDiagnosis(answer) {
  if (!answer || typeof answer !== 'object' || typeof answer.id !== 'string' || !answer.id) return;
  hideNote();
  const seq = N.seq;
  const before = T.path;
  A.openTopology?.(answer.id);
  const start = performance.now();
  const land = () => {
    if (seq !== N.seq) return;
    const waited = performance.now() - start;
    if (!(T.up && T.path && T.path !== before) && waited < 2500) { requestAnimationFrame(land); return; }
    if (T.up) showAnswer(answer);
  };
  requestAnimationFrame(land);
};


addEventListener('keydown', (e) => {
  if (e.key !== 'Escape' || !T.up || !N.el || N.el.hidden || A.sceneOpen || A.cardOpen?.() || A.glassOpen?.()) return;
  const a = document.activeElement;
  if (a && a !== document.body && !document.getElementById('view-topology')?.contains(a)) return;
  if (e.target?.closest?.('input, textarea, select') && e.target.value) return;
  e.stopImmediatePropagation();
  closeNote(true);
}, true);

addEventListener('atlas:view', (e) => {
  if (e.detail?.view === 'topology') requestAnimationFrame(syncTool);
  else if (e.detail?.prev === 'topology') hideNote();
});
addEventListener('atlas:data', () => { if (T.up) requestAnimationFrame(syncTool); });
if (A.VIEW === 'topology' || document.body.dataset.view === 'topology') requestAnimationFrame(syncTool);
