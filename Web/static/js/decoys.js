
import { A, $, themeText } from './config.js';
import { say } from './words.js';
import { legacySources, listening, roster, watchByNode as watchModel } from './tripwire-model.js';

let on = false;

const BIRD_SVG =
  `<svg class="tw-bird" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" ` +
  `stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">` +
  `<path d="M6 16 C4.5 12 7 7.5 12 7.5 C14.5 7.5 16.2 9 16.6 10.6 L20 11.4 L16.8 12.8 C16.4 16 13.4 18 10 18 C8.4 18 7 17.4 6 16 Z"/>` +
  `<path d="M8 12.6 C10 11 12.5 11.5 13.5 13.5 C11.5 15 9 14.8 8 12.6 Z"/>` +
  `<path d="M6 16 L2.6 19 M10.4 18 V21 M13 17.6 V21"/>` +
  `<circle cx="13.7" cy="10.2" r="0.9" fill="currentColor" stroke="none"/>` +
  `</svg>`;
const EYE_SVG =
  `<svg class="tw-eye" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">` +
  `<path d="M2.5 11 C 6 6.4, 18 6.4, 21.5 11 C 18 15.6, 6 15.6, 2.5 11 Z"/>` +
  `<circle cx="12" cy="11" r="3"/>` +
  `<circle cx="12" cy="11" r="1.1" fill="currentColor" stroke="none"/>` +
  `<path d="M5.6 7.6 L4.2 5.8 M12 6.1 L12 4 M18.4 7.6 L19.8 5.8"/>` +
  `</svg>`;

function watchByNode() {
  const ov = A.tripwires || null;
  const rows = roster({ overview: ov, charted: A.DATA?.stones || [], live: A.signalsFeed?.stones || {} });
  const { verdict } = listening(ov?.sources || legacySources(A.signalsSources));
  const lost = verdict !== 'ok';
  return { ...watchModel(rows, lost), lost, waiting: verdict === 'waiting' };
}

function paint() {
  const markers = $('markers');
  if (!markers) return;
  const { nodes } = watchByNode();
  for (const mk of markers.children) {
    const watch = nodes.get(mk.dataset.id);
    let eye = mk.querySelector('.mk-eye');
    mk.classList.toggle('has-stone', Boolean(watch));
    if (!watch) { eye?.remove(); continue; }
    if (!eye) {
      eye = document.createElement('button');
      eye.className = 'mk-eye';
      eye.innerHTML = EYE_SVG + BIRD_SVG;
      eye.addEventListener('click', (e) => {
        e.stopPropagation();
        A.toggleDrawer?.(false);
        A.focusNode?.(mk.dataset.id, true, false);
      });
      mk.querySelector('.mk-dot')?.appendChild(eye);
    }
    eye.dataset.voice = watch.voice;
    eye.title = `${watch.count} ${say(watch.count === 1 ? 'stone' : 'stones')} · ${watch.voice} — open THE ${say(themeText('stones', 'Decoys')).toUpperCase()}`;
  }
}
let lastLoad = 0;
A.paintDecoys = function paintDecoys() {
  paint();
  if (!on || Date.now() - lastLoad < 25000) return;
  lastLoad = Date.now();
  A.loadTripwires?.().then((ov) => { if (ov && on) paint(); });
};

A.toggleDecoys = function toggleDecoys(force) {
  on = typeof force === 'boolean' ? force : !on;
  document.body.classList.toggle('decoys-on', on);
  $('btn-decoys')?.classList.toggle('lit', on);
  $('btn-decoys')?.setAttribute('aria-pressed', String(on));
  if (!on) return;
  paint();
  A.loadTripwires?.().then((ov) => { if (ov && on) paint(); });
  const { nodes, unplaced, speaking, total, lost, waiting } = watchByNode();
  if (!total) {
    A.showToast?.(`No ${say(themeText('stones', 'decoys')).toLowerCase()} are known — none charted, and ${themeText('decoy_source', 'the decoy feed')} names none.`);
  } else if (waiting) {
    A.showToast?.('The webhook has not heard from a sender yet. The marks are drawn from the chart, not the wire.');
  } else if (lost) {
    A.showToast?.('CONTACT LOST — the watch is not answering. The marks are drawn from the chart, not the wire.');
  } else if (speaking) {
    A.showToast?.(`${speaking} ${say(themeText('stones', 'tripwires')).toLowerCase()} ${themeText('tw_lit', 'TRIPPED')} — the marks show where.`);
  } else {
    A.showToast?.(`All quiet — ${nodes.size} place${nodes.size === 1 ? '' : 's'} under the watch` +
      (unplaced ? ` (+${unplaced} ${say(unplaced === 1 ? 'stone' : 'stones')} unplaced)` : '') + '.');
  }
};

$('btn-decoys')?.addEventListener('click', () => A.toggleDecoys());
