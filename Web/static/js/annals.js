/* Atlas — THE ANNALS: what befell the realm, and when.

   The map only ever showed the present tense. A place went dark, the marker
   turned red, someone fixed it, and nothing remembered. This is the memory:
   every state change the watchers witnessed, newest first, with somewhere to
   write down what it turned out to be.

   Acknowledging is the difference between a log and an operations tool — it
   says a human looked, and leaves the reason for the next person. Admins only;
   everyone else reads. Events inherit the map's redaction server-side, so a
   place a viewer cannot see never appears here either. */

import { A, $, esc, themeText, ago } from './config.js';
import { makeScene } from './scene.js';

let root, listEl, headEl;
let showAll = true;

const GRAVITY_CLASS = { grave: 'ann-grave', warn: 'ann-warn', planned: 'ann-planned',
                        consequence: 'ann-consequence', clear: 'ann-clear', quiet: 'ann-quiet' };

/* "gone dark", not "healthy -> down": the annals are read by a person at 2am. */
const PHRASE = {
  down: 'went dark', degraded: 'began to falter', healthy: 'answered again',
  maintenance: 'closed for repair', slumbering: 'went to sleep',
  tripped: 'was touched',          // a tripwire (v1.52.0): bait has no legitimate caller
};

function when(iso) {
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return iso || '';
  return ago(Date.now() - then.getTime());
}

function rowHTML(e) {
  // a consequence reads as what it is: not its own incident
  const phrase = e.gravity === 'consequence'
    ? 'went dark with it' : (PHRASE[e.to] || `became ${e.to}`);
  const behind = e.cause
    ? `<span class="ann-behind"> behind ${esc(e.cause)}</span>` : '';
  const ack = e.ack
    ? `<span class="ann-ack">seen by ${esc(e.ack.by)}${e.ack.note ? ` — ${esc(e.ack.note)}` : ''}</span>`
    : (A.editorReady?.() && (e.gravity === 'grave' || e.gravity === 'warn')
        ? `<button class="ann-ack-btn" data-id="${esc(e.id)}">acknowledge</button>` : '');
  return `<div class="ann-row ${GRAVITY_CLASS[e.gravity] || ''}">
    <span class="ann-when" title="${esc(e.at)}">${esc(when(e.at))}</span>
    <span class="ann-what"><strong>${esc(e.name)}</strong> ${esc(phrase)}${behind}` +
    (e.kind === 'tripwire' ? '' : `<span class="ann-from"> (from ${esc(e.from)})</span>`) + `</span>
    <span class="ann-kind">${esc(e.kind)}</span>
    ${ack}
  </div>`;
}

async function build() {
  listEl.innerHTML = '<div class="ldg-note">reading the annals…</div>';
  let body;
  try {
    body = await (await fetch(`api/v2/events?limit=200${showAll ? '' : '&unacked=1'}`,
                              { cache: 'no-store' })).json();
  } catch {
    listEl.innerHTML = '<div class="ldg-note">the annals could not be read.</div>';
    return;
  }
  const { events = [], counts = {} } = body;
  if (headEl) {
    headEl.innerHTML =
      `<button class="ann-filter${showAll ? ' on' : ''}" data-all="1">everything</button>` +
      `<button class="ann-filter${showAll ? '' : ' on'}" data-all="0">unacknowledged` +
      `${counts.unacked ? ` (${counts.unacked})` : ''}</button>` +
      `<span class="ann-counts">${counts.total || 0} remembered · ` +
      `${counts.last_24h || 0} in the last day</span>`;
    for (const btn of headEl.querySelectorAll('.ann-filter')) {
      btn.addEventListener('click', () => { showAll = btn.dataset.all === '1'; build(); });
    }
  }

  listEl.innerHTML = events.length
    ? events.map(rowHTML).join('')
    : `<div class="ldg-note">${showAll
        ? esc(themeText('annals_empty', 'nothing has happened on the map yet.'))
        : 'nothing is waiting to be acknowledged.'}</div>`;

  for (const btn of listEl.querySelectorAll('.ann-ack-btn')) {
    btn.addEventListener('click', async () => {
      const note = prompt('What was it? (optional)') ?? '';
      btn.disabled = true;
      try {
        const { Editor } = await import('./editor/index.js');
        await Editor.ackEvent(Number(btn.dataset.id), note);
        build();
      } catch (err) {
        A.showToast?.(`Could not acknowledge: ${err.message || err}`);
        btn.disabled = false;
      }
    });
  }
}

const scene = makeScene({ id: 'annals', closeId: 'ann-close', build: () => build() });
const { open, close } = scene;
A.openAnnals = open;
A.closeAnnals = close;

A.buildAnnalsScene = function buildAnnalsScene() {
  root = scene.mount();
  if (!root) return;
  listEl = $('ann-list');
  headEl = $('ann-head');
};
