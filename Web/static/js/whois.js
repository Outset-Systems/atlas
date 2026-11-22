
import { say } from './words.js';

const MAX_SHOWN = 20000;

let asking = false;

async function ask(side, q) {
  const out = side.querySelector('.aw-out');
  const go = side.querySelector('.aw-go');
  if (!out || asking) return;
  asking = true;
  if (go) { go.disabled = true; go.textContent = '…'; }
  out.hidden = false;
  out.textContent = `${say('asking the deep about')} ${q}…`;
  try {
    const r = await fetch('api/v2/whois?q=' + encodeURIComponent(q), { cache: 'no-store' });
    const j = await r.json().catch(() => null);
    if (!r.ok || !j || j.error) {
      out.textContent = `${say('the deep would not answer')}: ${j?.error || `it refused (${r.status})`}`;
    } else {
      const via = (j.servers || []).join(' › ');
      const text = (j.text || '').trim() || 'the registries had nothing to say about it.';
      out.textContent = (via ? `— asked ${via} —\n\n` : '') +
        (text.length > MAX_SHOWN ? text.slice(0, MAX_SHOWN) + '\n… (trimmed)' : text);
    }
  } catch {
    out.textContent = say('the deep did not answer — the Atlas could not be reached.');
  } finally {
    asking = false;
    const goNow = side.isConnected ? go : null;
    if (goNow) { goNow.disabled = false; goNow.textContent = 'ASK'; }
  }
}

document.addEventListener('submit', (e) => {
  const side = e.target?.closest?.('.aw-side');
  if (!side || !e.target.classList.contains('aw-form')) return;
  e.preventDefault();
  e.stopPropagation();
  const q = (side.querySelector('.aw-input')?.value || '').trim();
  if (q) ask(side, q);
}, true);

document.addEventListener('click', (e) => {
  if (e.target?.closest?.('.aw-side')) e.stopPropagation();
}, true);

