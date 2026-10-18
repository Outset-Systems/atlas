/* Atlas — THE NAMING DEEP: whois, asked from the Depths.

   It lives INSIDE the abyss's TOP CLIENTS slide now (2026-08-15, moved from
   its own panel below the carousel): that panel names the busiest client IPs
   at the edge, and "who holds this address" is the question every one of
   those rows raises. chronicle.js renders the pane whenever a watching carries
   `whois: true` (slideHTML), so this module binds by DELEGATION — the
   carousel re-renders its slides on every dataset edit, and a listener tied
   to one render would quietly die with it.

   A browser cannot speak port 43, so `/api/whois` (api_data.py) asks the
   registries on the viewer's behalf; this module only carries the asking and
   the showing. Same-origin fetch — the CSP's `default-src 'self'` covers it. */

import { A, $ } from './config.js';

const MAX_SHOWN = 20000;   // whois text is unbounded prose; the pane is not

let asking = false;

async function ask(q) {
  const out = $('aw-out');
  const go = $('aw-go');
  if (!out || asking) return;
  asking = true;
  if (go) { go.disabled = true; go.textContent = '…'; }
  out.hidden = false;
  out.textContent = `asking the deep about ${q}…`;
  try {
    const r = await fetch('api/v2/whois?q=' + encodeURIComponent(q), { cache: 'no-store' });
    const j = await r.json().catch(() => null);
    if (!r.ok || !j || j.error) {
      out.textContent = `the deep would not answer: ${j?.error || `it refused (${r.status})`}`;
    } else {
      const via = (j.servers || []).join(' › ');
      const text = (j.text || '').trim() || 'the registries had nothing to say about it.';
      out.textContent = (via ? `— asked ${via} —\n\n` : '') +
        (text.length > MAX_SHOWN ? text.slice(0, MAX_SHOWN) + '\n… (trimmed)' : text);
    }
  } catch {
    out.textContent = 'the deep did not answer — the Atlas could not be reached.';
  } finally {
    asking = false;
    const goNow = $('aw-go');   // the carousel may have re-rendered mid-ask
    if (goNow) { goNow.disabled = false; goNow.textContent = 'ASK'; }
  }
}

/* the form submit IS the wiring — Enter in the input and the ASK button both
   arrive here, however many times the slide has been rebuilt */
document.addEventListener('submit', (e) => {
  if (e.target?.id !== 'aw-form') return;
  e.preventDefault();
  e.stopPropagation();
  const q = ($('aw-input')?.value || '').trim();
  if (q) ask(q);
}, true);

/* a click inside the pane must not fall through to the viewport's
   card-closing listener — working the whois is not "clicking the map".
   Capture, so it runs before the viewport; nothing inside the pane carries
   data-glass or carousel controls, so nothing real is starved. */
document.addEventListener('click', (e) => {
  if (e.target?.closest?.('.aw-side')) e.stopPropagation();
}, true);

