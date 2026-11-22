
import { A, $, esc } from './config.js';
import { makeScene } from './scene.js';

let listEl, headEl;
let loaded = null;
let failure = null;
let absent = false;

const LEVEL = {
  critical: { cls: 'tr-critical', word: 'critical' },
  warn: { cls: 'tr-warn', word: 'worth fixing' },
  note: { cls: 'tr-note', word: 'noted' },
};
const levelOf = (f) => LEVEL[f && f.level] || LEVEL.note;

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
    if (res.status === 503) { absent = true; return; }
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

  if (absent && !loaded) {
    if (headEl) headEl.innerHTML = '<span class="rt-waiting">No trust map on this instance: nothing has been checked here</span>';
    listEl.innerHTML = `<div class="ldg-note">This page is generated from a deployment's own
      compose and proxy files when its image is built, and those files stay with that
      deployment, so a published image carries none. An empty page here does not mean every
      app is safe; it means no one has looked.</div>`;
    return;
  }

  if (failure || !loaded) {
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
  if (!scene.mount()) return;
  listEl = $('tr-list');
  headEl = $('tr-head');
};

