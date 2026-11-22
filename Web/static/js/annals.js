
import { A, $, esc, themeText, ago, getJSON } from './config.js';
import { say } from './words.js';
import { makeScene } from './scene.js';
import { ALERTS_TEXT, fill, sentNote } from './alerts-model.js';

let listEl, headEl;
let showAll = true;

const GRAVITY_CLASS = { grave: 'ann-grave', warn: 'ann-warn', planned: 'ann-planned',
                        consequence: 'ann-consequence', clear: 'ann-clear', quiet: 'ann-quiet' };

const PHRASE = {
  down: 'went dark', degraded: 'began to falter', healthy: 'answered again',
  maintenance: 'closed for repair', slumbering: 'went to sleep',
  tripped: 'was touched',
};

function when(iso) {
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return iso || '';
  return ago(Date.now() - then.getTime());
}

const sentTo = (sent) => sentNote(sent, (key, vars) => fill(themeText(key, ALERTS_TEXT[key] || key), vars));

function rowHTML(e) {
  const phrase = e.gravity === 'consequence'
    ? 'went dark with it' : (PHRASE[e.to] || `became ${e.to}`);
  const sent = Array.isArray(e.sent) ? sentTo(e.sent) : '';
  const behind = e.cause
    ? `<span class="ann-behind"> behind ${esc(e.cause)}</span>` : '';
  const ack = e.ack
    ? `<span class="ann-ack">seen${e.ack.by ? ` by ${esc(e.ack.by)}` : ''}${e.ack.note ? ` — ${esc(e.ack.note)}` : ''}</span>`
    : (A.editorReady?.() && (e.gravity === 'grave' || e.gravity === 'warn')
        ? `<button class="ann-ack-btn" data-id="${esc(e.id)}">acknowledge</button>` : '');
  return `<div class="ann-row ${GRAVITY_CLASS[e.gravity] || ''}">
    <span class="ann-when" title="${esc(e.at)}">${esc(when(e.at))}</span>
    <span class="ann-what"><strong>${esc(e.name)}</strong> ${esc(phrase)}${behind}` +
    (e.kind === 'tripwire' ? '' : `<span class="ann-from"> (from ${esc(e.from)})</span>`) +
    (sent ? `<span class="ann-from ann-sent"${e.sent[0]?.at ? ` title="${esc(String(e.sent[0].at))}"` : ''}> · ${esc(sent)}</span>` : '') + `</span>
    <span class="ann-kind">${esc(e.kind)}</span>
    ${ack}
  </div>`;
}

async function build() {
  listEl.innerHTML = `<div class="ldg-note">${say('reading the annals…')}</div>`;
  let body;
  try {
    body = await getJSON(`api/v2/events?limit=200${showAll ? '' : '&unacked=1'}`);
  } catch {
    listEl.innerHTML = `<div class="ldg-note">${say('the annals could not be read.')}</div>`;
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
      const note = prompt('What was it? (optional)');
      if (note === null) return;
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
  if (!scene.mount()) return;
  listEl = $('ann-list');
  headEl = $('ann-head');
};
