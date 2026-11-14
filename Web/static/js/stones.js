/* THE TRIPWIRES scene (v1.52.0; THE DECOYS before it, and the owner's theme
   keeps its own name for it): bait with no legitimate caller, and which of it
   has been touched.

   A tripwire is bait. It has no legitimate caller, so anything that touches
   one is an event rather than a maybe — which is why this scene spends its only
   loud colour on the tripwires that have been touched and leaves everything
   else quiet. A quiet one is the ordinary case and the one we hope for; it
   should look like the background, not like a result.

   TWO FAMILIES, ONE ROSTER. Honeypots answer (a fake host, a fake share);
   canary tokens call home when used (a document, a URL, a cloud key) and may
   expire. Both are `stones[]` in the dataset, so where each is planted is a
   charted fact that survives every source being down.

   SOURCES, AND THE FAILURE THIS SCENE MUST NOT HIDE. Trips arrive from the
   decoy feed and from the webhook any tool can call (OpenCanary,
   Canarytokens, a script). "Nothing has been touched" and "nothing is
   listening" look identical in a list, so the head names each source and
   says CONTACT LOST outright for one that is not answering. A deception layer
   that cannot say it has lost contact is exactly as useless as one that never
   fires. (2026-08-14, and per source since v1.52.0.)

   The read is `GET /api/v2/tripwires` (admin-only: where bait sits is the
   deception layout itself). Without it — not an admin, an older server — the
   scene falls back to the chart and the decoy feed, as it always did. The
   rules live in tripwire-model.js; nothing a trip's sender wrote is ever
   drawn except through esc(). */

import { A, $, esc, themeText, canAdminWrite } from './config.js';
import { makeScene } from './scene.js';
import {
  byFamily, expiryNote, legacySources, listening, roster, tripLine, ago,
} from './tripwire-model.js';

let root, listEl, headEl;
let setupOpen = false;
let setupData = null;

/* The words are theme text; the plain theme's are below, the owner's theme
   restates them in its own voice. */
const word = {
  speaking: () => themeText('tw_lit', 'TRIPPED'),
  stirred: () => themeText('tw_stirred', 'acknowledged'),
  silent: () => themeText('tw_quiet', 'quiet'),
  unheard: () => 'no word',
};
const plural = () => themeText('stones', 'Tripwires');

/* One read, shared with the map layer (decoys.js) through A. A 403 means this
   viewer is not an admin: remember it and stop asking. */
let notAdmin = false;
A.loadTripwires = async function loadTripwires() {
  if (notAdmin) return null;
  try {
    const r = await fetch('api/v2/tripwires', { cache: 'no-store' });
    if (r.status === 401 || r.status === 403) { notAdmin = true; return null; }
    if (!r.ok) return A.tripwires || null;
    A.tripwires = await r.json();
    return A.tripwires;
  } catch {
    return A.tripwires || null;
  }
};

function rowHTML(t) {
  const v = t.voice;
  const cls = { speaking: 'gs-speaking', stirred: 'gs-stirred', silent: 'gs-silent' }[v] || 'gs-unheard';
  const guards = t.host ? `guards <span class="gs-host">${esc(t.host)}</span>` : 'unplaced';
  const planted = t.planted && typeof t.planted === 'string'
    ? `<span class="gs-meta">planted in ${esc(t.planted)}</span>` : '';
  /* `planted: false` from the decoy feed = a charted stone with no token
     behind it: it CANNOT speak. */
  const armed = t.planted === false ? '<span class="gs-flag">not planted — cannot trip</span>' : '';
  const retired = t.retired ? '<span class="gs-flag">retired</span>' : '';
  const exp = expiryNote(t);
  const expiry = exp ? `<span class="gs-${exp.level === 'later' ? 'meta' : 'flag'}">${esc(exp.text)}</span>` : '';
  const trips = Array.isArray(t.trips) ? t.trips : [];
  const latest = trips[0];
  const legacy = !Array.isArray(t.trips) && t.last_spoke
    ? `<span class="gs-spoke" title="${esc(t.last_spoke)}">last spoke ${esc(ago(t.last_spoke) || '')}</span>` : '';
  const unacked = (t.unacked | 0) > 0
    ? `<span class="gs-trips">${t.unacked | 0} to acknowledge</span>` : '';
  const tripRows = trips.slice(0, 3).map((x) => `<div class="gs-trip">
      <span class="gs-trip-line">${esc(tripLine(x))}</span>
      ${x.event && !x.ack && canAdminWrite()
        ? `<button class="gs-ack" type="button" data-event="${esc(x.event)}">acknowledge</button>` : ''}
      ${x.ack ? `<span class="gs-meta">seen by ${esc(x.ack.by || 'someone')}</span>` : ''}
    </div>`).join('');

  return `<div class="gs-row ${cls}">
    <div class="gs-voice" aria-hidden="true"><span class="gs-dot"></span></div>
    <div class="gs-body">
      <div class="gs-line1">
        <span class="gs-name">${esc(t.name || t.id)}</span>
        <span class="gs-state">${esc(word[v] ? word[v]() : v)}</span>
      </div>
      <div class="gs-line2">
        <span class="gs-mimics">${esc(t.mimics || t.placement || t.kind || '')}</span>
      </div>
      <div class="gs-line3">
        <span class="gs-meta">${guards}</span>
        <span class="gs-meta gs-zone">${esc(t.zone || '')}</span>
        ${planted}${unacked}${legacy}${expiry}${armed}${retired}
      </div>
      ${latest ? tripRows : ''}
    </div>
  </div>`;
}

function sourceLine(name, s) {
  if (!s) return '';
  const label = name === 'decoys' ? themeText('decoy_source', 'Decoy feed') : 'Webhook';
  const state = { ok: 'answering', lost: 'CONTACT LOST', waiting: 'on, never heard from' }[s.contact] || 'off';
  const heard = s.last_heard ? ` · heard ${esc(ago(s.last_heard) || '')}` : '';
  const trip = s.last_trip ? ` · last trip ${esc(ago(s.last_trip) || '')}` : '';
  return `<span class="gs-src gs-src-${esc(s.contact || 'off')}"><b>${esc(label)}</b> ${state}${heard}${trip}</span>`;
}

function headHTML(rows, sources, counts) {
  const { verdict, lost, waiting } = listening(sources);
  const lit = rows.filter((r) => r.voice === 'speaking').length;
  const srcs = `<span class="gs-sources">${sourceLine('decoys', sources.decoys)}${sourceLine('webhook', sources.webhook)}</span>`;
  if (verdict === 'unset') {
    return `<div class="gs-head gs-head-dark">
      <span class="gs-verdict">${esc(themeText('tw_unset', 'NOTHING IS LISTENING'))}</span>
      <span class="gs-verdict-sub">No source is configured, so the map cannot know whether
        a tripwire has been touched. The ones below are charted, not listened to —
        SET UP below says how to connect OpenCanary, Canarytokens or any script.</span>
      ${srcs}</div>`;
  }
  if (verdict === 'waiting') {
    return `<div class="gs-head gs-head-dark">
      <span class="gs-verdict">WAITING FOR A FIRST SIGNAL</span>
      <span class="gs-verdict-sub">The webhook is on, but nothing has reached it yet, so the map
        cannot know whether a tripwire has been touched. Send the test under ANY SCRIPT in
        SET UP below: when it lands, this line changes.</span>
      ${srcs}</div>`;
  }
  const extras = [];
  if (waiting) {
    extras.push(`<span class="gs-warn">the webhook has not heard from a sender yet</span>`);
  }
  if (verdict === 'lost') {
    extras.push(`<span class="gs-warn">CONTACT LOST with ${lost.map((n) => n === 'decoys'
      ? esc(themeText('decoy_source', 'the decoy feed')) : 'the webhook').join(' and ')}: silence
      from it means nothing — a tripwire could be touched right now and this map would not know.</span>`);
  }
  if ((counts?.unmatched | 0) > 0) {
    extras.push(`<span class="gs-warn">${counts.unmatched | 0} trip${counts.unmatched > 1 ? 's' : ''}
      from a tripwire this map has never charted</span>`);
  }
  const line = lit
    ? `<span class="gs-verdict gs-verdict-loud">${lit} ${esc(plural().toUpperCase())} ${esc(word.speaking())}</span>`
    : `<span class="gs-verdict gs-verdict-calm">${verdict === 'lost' ? 'PARTLY HEARD' : 'ALL QUIET'}</span>`;
  return `<div class="gs-head${verdict === 'lost' ? ' gs-head-lost' : ''}">${line}
    <span class="gs-verdict-sub">${verdict === 'ok'
      ? `every source is answering${lit || extras.length ? '' : ' — nothing has been touched'}`
      : 'one source is not answering'}</span>
    ${extras.join('')}${srcs}</div>`;
}

function unmatchedHTML(list) {
  if (!Array.isArray(list) || !list.length) return '';
  return `<div class="gs-family"><div class="gs-family-head">UNMATCHED TRIPS
      <span class="gs-family-sub">a sender named something this map has not charted</span></div>
    ${list.slice(0, 8).map((x) => `<div class="gs-trip gs-trip-loose">
      <span class="gs-trip-line">${esc(x.sensor ? `${x.sensor} — ` : '')}${esc(tripLine(x))}</span>
      ${x.event && !x.ack && canAdminWrite()
        ? `<button class="gs-ack" type="button" data-event="${esc(x.event)}">acknowledge</button>` : ''}
    </div>`).join('')}</div>`;
}

const FAMILY = {
  honeypot: ['HONEYPOTS', 'fake hosts and services that answer'],
  token: ['CANARY TOKENS', 'files, links and keys that call home when used'],
};

/* A note from the setup read, escaped, with its `backticked` names set as
   code (the server writes field names that way). */
const note = (n) => esc(n).replace(/`([^`]+)`/g, '<code>$1</code>');

function codeBlock(text, label) {
  return `<div class="gs-code"><div class="gs-code-head"><span>${esc(label)}</span>
      <button class="gs-copy" type="button">copy</button></div>
    <pre>${esc(text)}</pre></div>`;
}

function setupHTML() {
  const s = setupData;
  if (!s) return '<div class="ldg-note">reading the setup…</div>';
  const parts = [];
  if (!s.enabled) {
    parts.push(`<p class="gs-setup-p">The webhook is <b>off</b>. Add these two lines to the
      container's environment, with a random secret of at least 16 characters
      (<code>openssl rand -hex 24</code> prints one). If you installed from the guide, that means
      <code>.env</code>, then <code>docker compose -f compose.public.yaml up -d</code>:</p>`);
    parts.push(codeBlock(s.enable.join('\n'), 'environment'));
  }
  parts.push(`<p class="gs-setup-p">Every sender posts to one address. Its key is derived from
    the secret; print it inside the container with <code>${esc(s.key_command)}</code>${s.token_command
      ? `, or mint a site token with <code>${esc(s.token_command)}</code>` : ''}. From the guide's
    install, put <code>${esc(s.compose_exec)}</code> in front.</p>`);
  if (s.loopback) {
    parts.push(`<p class="gs-setup-p"><b>This address only works on this machine.</b> It is the
      one your browser used, so a sender elsewhere would be calling itself. Open the Atlas through
      your reverse proxy and come back here, and the blocks below will carry the right address.</p>`);
  }
  parts.push(codeBlock(s.url, 'webhook URL'));
  parts.push(`<div class="gs-family-head">OPENCANARY</div>`);
  parts.push(codeBlock(s.opencanary.config, 'opencanary.conf — logger'));
  parts.push(`<ul class="gs-notes">${s.opencanary.notes.map((n) => `<li>${note(n)}</li>`).join('')}</ul>`);
  parts.push(`<div class="gs-family-head">CANARYTOKENS</div>`);
  parts.push(codeBlock(s.canarytokens.webhook_url, 'the token\'s webhook URL'));
  parts.push(`<ul class="gs-notes">${s.canarytokens.notes.map((n) => `<li>${note(n)}</li>`).join('')}</ul>`);
  parts.push(`<div class="gs-family-head">ANY SCRIPT</div>`);
  parts.push(codeBlock(s.generic.curl, 'curl'));
  parts.push(`<div class="gs-family-head">HOW A TRIP FINDS ITS TRIPWIRE</div>
    <ul class="gs-notes">${s.matching.map((n) => `<li>${note(n)}</li>`).join('')}</ul>
    <p class="gs-setup-p">The Atlas never plants bait itself, just as it never scans your network:
    you run the honeypot or mint the token, and chart it here.</p>`);
  return parts.join('');
}

function setupBlock(adminRead) {
  if (!adminRead) return '';
  const add = canAdminWrite()
    ? '<button class="gs-add" type="button">+ add a honeypot or a canary token</button>' : '';
  return `<div class="gs-setup">
    <div class="gs-setup-bar">
      <button class="gs-setup-toggle" type="button" aria-expanded="${setupOpen}">SET UP ${setupOpen ? '▾' : '▸'}</button>
      ${add}
    </div>
    ${setupOpen ? `<div class="gs-setup-body">${setupHTML()}</div>` : ''}
  </div>`;
}

function wire() {
  for (const btn of listEl.querySelectorAll('.gs-ack')) {
    btn.addEventListener('click', async () => {
      // Cancel is "not now", never an empty note: only OK acknowledges (the
      // 11-12 audit; an empty OK still acknowledges with no note)
      const note = prompt('What was it? (optional)');
      if (note === null) return;
      btn.disabled = true;
      try {
        const { Editor } = await import('./editor/index.js');
        await Editor.ackEvent(Number(btn.dataset.event), note);
        await refresh(true);
      } catch (err) {
        A.showToast?.(`Could not acknowledge: ${err.message || err}`);
        btn.disabled = false;
      }
    });
  }
  listEl.querySelector('.gs-setup-toggle')?.addEventListener('click', async () => {
    setupOpen = !setupOpen;
    paint();
    if (setupOpen && !setupData) {
      try {
        const r = await fetch('api/v2/tripwires/setup', { cache: 'no-store' });
        setupData = r.ok ? await r.json() : null;
      } catch { setupData = null; }
      paint();
    }
  });
  listEl.querySelector('.gs-add')?.addEventListener('click', async () => {
    const { openDesk } = await import('./editor/panel.js');
    openDesk('stones');
  });
  for (const btn of listEl.querySelectorAll('.gs-copy')) {
    btn.addEventListener('click', async () => {
      const text = btn.closest('.gs-code')?.querySelector('pre')?.textContent || '';
      try { await navigator.clipboard.writeText(text); btn.textContent = 'copied'; }
      catch {
        const sel = getSelection(); const range = document.createRange();
        range.selectNodeContents(btn.closest('.gs-code').querySelector('pre'));
        sel.removeAllRanges(); sel.addRange(range);
        btn.textContent = 'selected — copy it';
      }
      setTimeout(() => { btn.textContent = 'copy'; }, 1600);
    });
  }
}

function paint() {
  if (!listEl) return;
  const ov = A.tripwires || null;
  const rows = roster({ overview: ov, charted: A.DATA?.stones || [], live: A.signalsFeed?.stones || {} });
  const sources = ov?.sources || legacySources(A.signalsSources);
  if (headEl) headEl.innerHTML = headHTML(rows, sources, ov?.counts);
  const fam = byFamily(rows);
  const groups = ['honeypot', 'token'].filter((k) => fam[k].length).map((k) => `<div class="gs-family">
      <div class="gs-family-head">${FAMILY[k][0]} <span class="gs-family-sub">${FAMILY[k][1]}</span></div>
      ${fam[k].map(rowHTML).join('')}</div>`).join('');
  const at = listEl.scrollTop;
  listEl.innerHTML = unmatchedHTML(ov?.unmatched) + (groups
    || `<div class="ldg-note">no ${esc(plural().toLowerCase())} charted yet — add a honeypot or a
        canary token in the map editor.</div>`)
    + setupBlock(Boolean(ov));
  listEl.scrollTop = at;
  wire();
}

/* `withSignals` only on open and after an acknowledgement: the signals poll
   itself calls refreshStonesScene, and asking it for signals again from
   there would be a loop. */
let busy = false;   // a refresh in flight; the poll's echo of it is dropped
async function refresh(withSignals = false) {
  busy = true;
  try {
    await Promise.all([A.loadTripwires(),
                       withSignals ? A.refreshSignals?.().catch(() => {}) : null]);
  } finally { busy = false; }
  paint();
  A.paintDecoys?.();
}

/* Ask for a fresh read on open rather than showing whatever the last poll
   left behind: this is the one scene where a stale "all quiet" is a lie worth
   avoiding. */
const scene = makeScene({ id: 'stones', closeId: 'gs-close', build: () => { paint(); refresh(true); } });
const { open, close } = scene;

A.openStones = open;
A.closeStones = close;
/* Called by the signals poll (signals.js) so an OPEN scene repaints — a
   tripwire touched while you are looking lights where it stands. The scroll
   position survives the repaint (paint keeps it). */
A.refreshStonesScene = function refreshStonesScene() {
  if (!root?.classList.contains('open') || busy) return;   // busy: opening asked
  refresh();                                               // for signals, which land here
};

A.buildStonesScene = function buildStonesScene() {
  root = scene.mount();
  if (!root) return;
  listEl = $('gs-list');
  headEl = $('gs-head');
};
