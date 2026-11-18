/* TOPOLOGY, Where does it break? on the canvas (2026-11-17). A part of the view: it reaches the
   canvas only through the doors in topology-state.js and never imports the
   conductor (topology.js), which imports it.

   For an admin on an Atlas that writes, on a wide screen and a phone alike
   (it writes nothing to the map), a tool in ARRANGE AND EXPORT asks the
   card selected (`T.selected`: a place, not a stub or a folded group) as
   NODES' "Where does it break?" asks it, through NODES' own asker
   (`A.askDiagnose`, nodes-menu.js: `POST api/v2/admin/diagnose`), so no
   part of this view sends anything but the drawing.
   The chain is lit from the head down as far as the step that failed, that
   card and the cable into it in the down colour (`lightPath`), and a small
   note beside the canvas lists the steps and a summary, in the words NODES
   uses (menu-model.js's diagnose lines, nodes-text.js's words: nothing is
   said twice). With nothing selected the note says to pick a place first.
   Escape, or the note's Close, puts the note away and lets go of the light.

   NODES' "Show on the canvas" hands an answer it already has to
   `A.showDiagnosis(answer)`: the view opens on the place (`A.openTopology`,
   which lights the plain way up a frame later), and once that light has
   landed this one is laid over it, with the note. Nothing is asked again
   (the route would answer "a moment ago" for 20 seconds).

   Two doors would make this plainer, for whoever next owns
   topology-state.js: "tell me when the light changes" (here the note
   watches `T.path` on a short timer while it is out, to go when a VLAN or
   another way is lit), and "open on a place with this chain lit" (here
   it waits for the conductor's own light, then replaces it). */

import { A, esc, canAdminWrite } from './config.js';
import * as M from './menu-model.js';
import { t as nt } from './nodes-text.js';
import { T, t, addTool, lightPath, clearLight, stageEl, svgEl } from './topology-state.js';

/** A line of the model's in NODES' words. */
const words = (item) => M.wordsOf(item, nt);

/** The Desk's gate (an admin on an Atlas that writes), on any screen. */
const mayAsk = () => canAdminWrite() && document.body.dataset.editable === '1';

const N = {
  el: null,          // the note beside the canvas
  light: null,       // the T.path this note lit; when T.path is no longer it, the note goes
  seq: 0,            // the latest ask or hand-over: an older one does not land
  pending: '',       // the place being asked now
  timer: 0,          // the note's watch on the light
  back: '',          // the card the keyboard goes back to on Close
};

/* ── the tool ─────────────────────────────────────────────────────────────── */

let removeTool = null;

/** Offer the tool to whoever may ask, and take it away from anyone else. */
function syncTool() {
  if (mayAsk()) {
    if (!removeTool) removeTool = addTool({ id: 'diagnose', label: t('tp_dx'), title: t('tp_dx_title'), onPress: press });
    return;
  }
  if (removeTool) { removeTool(); removeTool = null; }
  hideNote();
}

/** The tool pressed: ask the card selected. */
async function press() {
  const id = T.selected;
  const th = id ? T.shown?.byId.get(id) : null;
  if (!th) { sayNote(t('tp_dx_pick')); return; }
  if (th.type !== 'place') { sayNote(t('tp_dx_not_place')); return; }
  const name = th.name || id;
  // where the route would refuse it, said without asking
  const held = M.diagnoseAsk(T.data || A.DATA, id);
  if (typeof held === 'string' && held) { sayNote(nt(`nodes_dx_${held}`), name, 'warn'); return; }
  if (N.pending === id) return;
  const seq = ++N.seq;
  N.pending = id;
  N.back = id;
  sayNote(nt('nodes_asking'), name, 'asking');
  // asked through NODES' one asker (nodes-menu.js): the view's parts send nothing themselves
  const got = typeof A.askDiagnose === 'function' ? await A.askDiagnose(id) : { status: 0, ok: false, body: null };
  if (N.pending === id) N.pending = '';
  if (seq !== N.seq || !T.up) return;
  const { status, ok, body } = got || {};
  if (ok && body && typeof body === 'object' && Array.isArray(body.steps)) showAnswer(body);
  else sayNote(words(M.diagnoseRefusal(status || 0, body)), name, 'warn');
}

/* ── the light and the note ───────────────────────────────────────────────── */

/** Light the chain as far as the step that failed, and list it. */
function showAnswer(answer) {
  const light = M.diagnoseLight(answer);
  lightPath(light.things, light.links, light.failedAt);
  N.light = T.path;
  N.back = typeof answer.id === 'string' ? answer.id : N.back;
  drawAnswer(answer);
}

/** The note, made once inside the stage (beside the conductor's own). */
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

/** A short note: pick a place first, "Asking…", or a refusal in words. */
function sayNote(text, name = '', tone = '') {
  const note = noteEl();
  if (!note) return;
  if (tone !== 'asking') stopWatch();
  // a note that is not the chain's lets go of the chain's light
  if (N.light && T.path === N.light) clearLight();
  N.light = null;
  note.innerHTML = head(name ? t('tp_dx_head', { name }) : t('tp_dx')) +
    `<p class="tp-dx-say${tone ? ` tp-dx-${tone}` : ''}" role="status">${esc(text)}</p>`;
  note.hidden = false;
}

/** The chain's note: the summary (where the keyboard lands), then a line
    per step, the one that broke marked. */
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

/** While the chain's note is out: when something else lights the canvas
    or lets go of it (a VLAN pressed, Escape on the canvas), the note goes. */
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

/** Close or Escape: the note goes, its light with it, and the keyboard goes
    back to the card it was about (else the tool). */
function closeNote(focusBack) {
  const lit = N.light && T.path === N.light;
  const back = N.back;
  hideNote();
  if (lit) clearLight();
  if (!focusBack) return;
  const card = back ? svgEl()?.querySelector(`.tp-card[data-id="${CSS.escape(back)}"]`) : null;
  (card || document.querySelector('#view-topology [data-tool="diagnose"]'))?.focus({ preventScroll: true });
}

/* ── NODES' "Show on the canvas" ──────────────────────────────────────────── */

/** Open TOPOLOGY on the answer's place and light its chain as far as the
    step that failed, with the note. `A.openTopology` lights the plain way
    up once the view is up (a frame or two later); this waits for that
    light, then lays its own over it. Bounded: after a few seconds it
    lights anyway, or gives up when the view never came up. */
A.showDiagnosis = function showDiagnosis(answer) {
  if (!answer || typeof answer !== 'object' || typeof answer.id !== 'string' || !answer.id) return;
  hideNote();
  const seq = N.seq;
  // lightPath always makes a new object: the conductor's light has landed
  // when T.path is no longer the one there before
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

/* ── Escape, and when to offer the tool ───────────────────────────────────── */

// on the window, in the capture phase, before the conductor's Escape (which
// would let go of the selection too); after the drawing's, which goes first
addEventListener('keydown', (e) => {
  if (e.key !== 'Escape' || !T.up || !N.el || N.el.hidden || A.sceneOpen || A.cardOpen?.() || A.glassOpen?.()) return;
  const a = document.activeElement;
  if (a && a !== document.body && !document.getElementById('view-topology')?.contains(a)) return;
  // a box with words in it empties first (the find box: the conductor's)
  if (e.target?.closest?.('input, textarea, select') && e.target.value) return;
  e.stopImmediatePropagation();
  closeNote(true);
}, true);

addEventListener('atlas:view', (e) => {
  if (e.detail?.view === 'topology') requestAnimationFrame(syncTool);
  else if (e.detail?.prev === 'topology') hideNote();
});
addEventListener('atlas:data', () => { if (T.up) requestAnimationFrame(syncTool); });
// a page that opens on the view chose it before anything here listened
if (A.VIEW === 'topology' || document.body.dataset.view === 'topology') requestAnimationFrame(syncTool);
