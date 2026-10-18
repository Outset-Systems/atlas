/* Atlas — THE TRUST: who is allowed to speak for a client.

   THE QUESTION THIS SCENE EXISTS TO ANSWER. Every app in the suite decides
   who its caller is, and behind a proxy that decision comes from a header the
   caller can write. So each app names the proxies whose word it takes. Get
   that list wrong and the app is either blind — everyone keyed to the proxy,
   one lockout bucket for the whole internet — or credulous: anything that can
   open a socket to it can claim to be anyone. On 2026-09-09 four apps were
   wrong in one of those two ways, and every one of them was invisible until
   someone read three config files side by side. This is the side-by-side.

   WHY IT IS NOT DRAWN ON THE MAP. Trust is not a place and it is not a road.
   A road says traffic CAN flow; this says whose claim about that traffic is
   believed, which is a different graph over the same hosts — the Hub reaches
   the Ledger, and the Ledger believes the Hub, but neither fact implies the
   other. Drawn as roads the two would be confused, and confusing them is
   exactly the mistake that produced the bugs.

   IT IS GENERATED, NOT SURVEYED. the trust-map generator derives it from the
   compose files and the nginx vhosts and bakes `trust.json` into the image, so
   the view is exactly as old as the running build and cannot drift into a
   comfortable fiction the way a hand-drawn copy would. That is also why the
   head says when it was generated rather than implying a live read.

   THE HEAD MUST NOT DRAW CALM OVER A GAP — the ACCOUNTS lesson. "No findings"
   and "the file did not ship" look identical if you only count findings, so
   coverage is stated first and a missing file is loud. Colour is spent only on
   findings: a scene where every row glows is a scene nobody reads twice. */

import { A, $, esc } from './config.js';
import { makeScene } from './scene.js';

let root, listEl, headEl;
let loaded = null;          // the last good payload; a reopen should not blank
let failure = null;

/* Loudest first. These are the map's existing semantic tokens — no new
   colours (the design notes: reuse the zone hues, gold stays rare). */
const LEVEL = {
  critical: { rank: 0, cls: 'tr-critical', word: 'critical' },
  warn: { rank: 1, cls: 'tr-warn', word: 'worth fixing' },
  note: { rank: 2, cls: 'tr-note', word: 'noted' },
};
const levelOf = (f) => LEVEL[f && f.level] || LEVEL.note;

/* What the VALUE is, which is the whole diagnosis in one word. A list of
   addresses is the only correct form; the others each name a specific failure. */
const FORM = {
  addresses: { cls: 'tr-form-ok', word: 'names its proxies' },
  'hop-count': { cls: 'tr-form-bad', word: 'counts hops' },
  malformed: { cls: 'tr-form-bad', word: 'unreadable' },
  unset: { cls: 'tr-form-none', word: 'trusts nobody' },
};
const formOf = (a) => FORM[a && a.form] || FORM.unset;

async function load() {
  try {
    const res = await fetch('api/v2/trust', { cache: 'no-store' });
    if (res.status === 403) { failure = 'admins only'; return; }
    const body = await res.json().catch(() => ({}));
    if (!res.ok) { failure = body.error || `the trust map answered ${res.status}`; return; }
    loaded = body; failure = null;
  } catch (e) {
    failure = 'the trust map could not be read';
  }
}

function proxyHTML(p) {
  return `<div class="tr-proxy">
    <span class="tr-proxy-name">${esc(p.name)}</span>
    <span class="tr-addr">${esc(p.address)}</span>
    <span class="tr-proxy-note">${p.pinned
      ? 'pinned — cannot be handed to anything else'
      : esc(p.role || 'named by address')}</span>
  </div>`;
}

function appHTML(app, findings) {
  const f = formOf(app);
  const mine = findings.filter((x) => x.app === app.name);
  const loud = mine.filter((x) => x.level !== 'note');
  // What it believes, spelled out — an address whose holder we cannot name is
  // the finding, so it is rendered as one rather than as a bare string.
  const believes = (app.believes || []).length
    ? (app.believes || []).map((b) => `<span class="tr-believe${b.who ? '' : ' tr-unknown'}">
        <span class="tr-addr">${esc(b.value)}</span>
        <i>${esc(b.who || 'not a proxy we know')}</i></span>`).join('')
    : `<span class="tr-believe tr-none"><i>${esc(f.word)}</i></span>`;

  return `<div class="ldg-block tr-app${loud.length ? ' tr-flagged' : ''}">
    <div class="ldg-zhead">
      <span class="ldg-zname">${esc(app.name)}</span>
      <span class="ldg-zsub">${esc(app.host)}</span>
      <span class="ldg-zcount ${esc(f.cls)}">${esc(f.word)}</span>
    </div>
    <div class="tr-row">
      <span class="tr-key">believes</span>
      <span class="tr-vals">${believes}</span>
    </div>
    <div class="tr-row">
      <span class="tr-key">reachable</span>
      <span class="tr-vals">${(app.published || []).length
        ? (app.published || []).map((p) => `<span class="tr-addr">${esc(p)}</span>`).join('')
          + `<i class="tr-hint">published — anything that can route to the host
             can knock, so the header must only be believed from a named peer</i>`
        : `<i class="tr-hint">no host port — only what shares its network</i>`}</span>
    </div>
    ${mine.map((x) => `<div class="tr-finding ${esc(levelOf(x).cls)}">
      <span class="tr-level">${esc(levelOf(x).word)}</span>
      <span class="tr-text">${esc(x.text)}</span>
    </div>`).join('')}
  </div>`;
}

function build() {
  if (!listEl) return;

  if (failure || !loaded) {
    // Loud, not blank. A trust view that fails quietly is worse than none:
    // an empty panel reads as "nothing to see".
    if (headEl) {
      headEl.innerHTML = `<span class="rt-alarm">${esc(failure || 'not loaded')}</span>`;
    }
    listEl.innerHTML = `<div class="ldg-note">${esc(failure === 'admins only'
      ? 'THE TRUST is admin-only: it is the shortest description of where to aim a forged header.'
      : 'Generate the trust map and rebuild the image — the view is baked in at build, so an image without one has nothing to show.')}</div>`;
    return;
  }

  const apps = (loaded.apps || []).slice();
  const findings = loaded.findings || [];
  const loud = findings.filter((f) => f.level !== 'note');
  const crit = findings.filter((f) => f.level === 'critical');

  if (headEl) {
    // COVERAGE first: a finding count means nothing until you know how much
    // of the fleet it was counted over.
    const cover = `<span class="rt-calm">${apps.length} app${apps.length === 1 ? '' : 's'}`
      + ` read a forwarded header · ${(loaded.proxies || []).length} proxies named</span>`;
    const verdict = crit.length
      ? `<span class="rt-alarm"> · ${crit.length} critical</span>`
      : loud.length
        ? `<span class="rt-warn"> · ${loud.length} worth fixing</span>`
        : `<span class="rt-waiting"> · every app names its proxies</span>`;
    headEl.innerHTML = cover + verdict
      + `<span class="rt-waiting"> · generated from ${esc((loaded.sources || []).length)} config files, `
      + `baked into ${esc(loaded.version || 'this build')}</span>`;
  }

  // Flagged apps first — the one wrong line is the reason to open this at all.
  apps.sort((a, z) => {
    const la = findings.filter((f) => f.app === a.name && f.level !== 'note').length;
    const lz = findings.filter((f) => f.app === z.name && f.level !== 'note').length;
    return lz - la || String(a.name).localeCompare(String(z.name));
  });

  listEl.innerHTML = `
    <div class="tr-proxies">
      <div class="tr-proxies-head">WHO MAY SPEAK FOR A CLIENT</div>
      ${(loaded.proxies || []).map(proxyHTML).join('')}
    </div>
    ${apps.map((a) => appHTML(a, findings)).join('')
      || '<div class="ldg-note">no app in the fleet reads a forwarded header.</div>'}`;
}

const scene = makeScene({
  id: 'trust',
  closeId: 'tr-close',
  build: () => { build(); load().then(build); },
});
const { open, close } = scene;
A.openTrust = open;
A.closeTrust = close;

A.buildTrustScene = function buildTrustScene() {
  root = scene.mount();
  if (!root) return;
  listEl = $('tr-list');
  headEl = $('tr-head');
};

export { open, close };
