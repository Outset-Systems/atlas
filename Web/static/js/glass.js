
import { A, CFG, $, esc, host, isMixed } from './config.js';

const MEM_KEY = 'atlas-glass-verdicts';
let memo = {};
try { memo = JSON.parse(sessionStorage.getItem(MEM_KEY) || '{}'); } catch { memo = {}; }
function remember(url, ok) {
  memo[url] = ok;
  try { sessionStorage.setItem(MEM_KEY, JSON.stringify(memo)); } catch {   }
}
function forget(url) {
  delete memo[url];
  try { sessionStorage.setItem(MEM_KEY, JSON.stringify(memo)); } catch {   }
}

const sameOrigin = (abs) => {
  try { return new URL(abs, location.href).origin === location.origin; } catch { return false; }
};

function toTab(abs) {
  window.open(abs, '_blank', 'noopener');
}

let root, frame, titleEl, subEl, noteEl, openEl, urlEl;
let watchdog = 0, current = null;

function clearWatchdog() { clearTimeout(watchdog); watchdog = 0; }

function framePainted(f) {
  try {
    const doc = f.contentDocument;
    if (!doc) return null;
    if (doc.location && doc.location.href === 'about:blank') return false;
    return Boolean(doc.body && doc.body.childElementCount);
  } catch {
    return null;
  }
}

function setState(state) {
  if (!root) return;
  root.dataset.state = state;
}

function reveal(caveat) {
  clearWatchdog();
  setState('shown');
  if (current && caveat) urlEl.textContent = `${host(current.abs)} · ${caveat}`;
}

function refuse(reason, { keep = true, ours = false } = {}) {
  clearWatchdog();
  if (!current) return;
  if (keep) remember(current.key, false);
  frame.src = 'about:blank';
  noteEl.innerHTML =
    `<div class="gl-refuse-head">${esc(current.title)} will not be shown here</div>` +
    `<p class="gl-refuse-why">${esc(reason)}.` + (ours ? '' : ' Some services refuse to be drawn ' +
    'inside another page — a sensible thing for them to do, and not something ' +
    'this map can talk them out of.') + '</p>' +
    `<button class="gl-refuse-go" id="gl-refuse-go">OPEN IN A NEW TAB ›</button>`;
  noteEl.querySelector('#gl-refuse-go')
    ?.addEventListener('click', () => { const u = current.abs; close(); toTab(u); });
  setState('refused');
}

let showing = 0;
function show(entry) {
  showing += 1;
  current = entry;
  entry.loaded = false;
  root.hidden = false;
  titleEl.textContent = entry.title || '';
  subEl.textContent = entry.sub || '';
  urlEl.textContent = host(entry.abs);
  openEl.href = entry.abs;
  noteEl.innerHTML = '';
  setState('reaching');
  frame.src = entry.abs;

  clearWatchdog();
  watchdog = setTimeout(() => {
    if (root.dataset.state !== 'reaching') return;
    if (current?.loaded) reveal('shown without a verdict — the Atlas never got an answer');
    else refuse('it never answered');
  }, CFG.GLASS_TIMEOUT_MS);
}

function close() {
  clearWatchdog();
  current = null;
  if (!root || root.hidden) return;
  root.hidden = true;
  frame.src = 'about:blank';
}
A.closeGlass = close;
A.glassOpen = () => Boolean(root) && !root.hidden;

A.openHere = function openHere(url, title, opts = {}) {
  const abs = new URL(url, location.href).href;
  const key = opts.key || url;
  const mode = opts.openIn || 'auto';

  if (mode === 'tab') return toTab(abs);
  if (mode !== 'here') {
    if (isMixed(abs)) {
      A.showToast?.('That one answers over plain http — a secure page may not draw it. Opened in a new tab.');
      return toTab(abs);
    }
    if (memo[key] === false) return toTab(abs);
  }

  if (!root) return toTab(abs);
  show({ abs, key, title: title || abs, sub: opts.sub || '', loaded: false });

  if (sameOrigin(abs)) return;
  if (mode === 'here') return reveal();
  if (memo[key] === true) return reveal();

  fetch('api/v2/embeddable?url=' + encodeURIComponent(key), { cache: 'no-store' })
    .then((r) => (r.ok ? r.json() : null))
    .then((v) => {
      if (!v || current?.key !== key) return;
      if (v.ours) {
        if (root.dataset.state === 'refused') remember(key, false);
        else reveal('shown without a verdict: this map has more services than the glass asks about');
        return;
      }
      if (root.dataset.state === 'refused') return;
      if (v.embeddable === false) return refuse(v.reason || 'it refuses to be framed');
      if (v.embeddable === true) { remember(key, true); return reveal(); }
      reveal(v.reason || 'shown without a verdict');
    })
    .catch(() => { if (current?.key === key) reveal('shown without a verdict'); });
};

document.addEventListener('click', (e) => {
  const a = e.target?.closest?.('a[data-glass]');
  if (!a) return;
  if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  e.preventDefault();
  A.openHere(a.getAttribute('href'), a.dataset.glassTitle || a.textContent.trim(), {
    sub: a.dataset.glassSub || '',
    openIn: a.dataset.openIn || 'auto',
  });
}, true);

A.buildGlass = function buildGlass() {
  root = $('glass');
  if (!root) return;
  frame = $('gl-frame');
  titleEl = $('gl-title');
  subEl = $('gl-sub');
  noteEl = $('gl-note');
  openEl = $('gl-open');
  urlEl = $('gl-url');

  frame.addEventListener('load', () => {
    if (!current || root.dataset.state === 'refused') return;
    if (frame.src === 'about:blank') return;
    current.loaded = true;
    const painted = framePainted(frame);
    if (painted === null) return;
    if (painted) { remember(current.key, true); reveal(); return; }
    if (sameOrigin(current.abs)) { refuse('it refused to be drawn inside another page'); return; }
    const was = showing;
    setTimeout(() => {
      if (showing === was && root.dataset.state === 'reaching') refuse('it refused to be drawn inside another page');
    }, 150);
  });

  document.addEventListener('securitypolicyviolation', (e) => {
    if (!current || root.dataset.state === 'refused') return;
    if ((e.effectiveDirective || e.violatedDirective) !== 'frame-src') return;
    let blocked = null;
    try { blocked = new URL(e.blockedURI).origin; } catch { return; }
    if (blocked !== new URL(current.abs).origin) return;
    if (memo[current.key] === true) forget(current.key);
    refuse('this page was not given leave to show it: a very large map, or a service added since the page loaded', { keep: false, ours: true });
  });

  $('gl-close')?.addEventListener('click', close);
  $('gl-reload')?.addEventListener('click', () => { if (current) show(current); });
  openEl?.addEventListener('click', () => close());
  root.addEventListener('pointerdown', (e) => { if (e.target === root) close(); });
};
