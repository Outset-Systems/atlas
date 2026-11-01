/* Atlas — the command palette: press `/` to summon a
   surveyor's finding-glass. Fuzzy-find any place or service, arrow to it, Enter
   to glide there / open it. The biggest daily-use win, zero dependencies. */

import { A, CFG, $, esc, host, zoneById, FALLBACK_HUE } from './config.js';

let root, input, listEl;
let items = [];       // full searchable index: {kind, label, sub, hue, run}
let shown = [];       // current filtered results
let active = 0;       // highlighted index into `shown`

/** Build the flat search index once the dataset + DOM exist. */
function buildIndex() {
  items = [];

  for (const n of A.DATA.nodes) {
    const zone = zoneById(n.zone);
    const hue = zone ? zone.hue : FALLBACK_HUE;
    items.push({
      kind: 'place',
      label: n.name,
      sub: `${zone ? zone.name : ''}${n.ip && n.ip !== '—' ? ' · ' + n.ip : ''}`.trim(),
      hue,
      hay: `${n.name} ${n.role || ''} ${n.ip || ''} ${zone ? zone.name : ''}`.toLowerCase(),
      run: () => { close(); A.focusNode(n.id); },
    });
    for (const l of n.links || []) {
      items.push({
        kind: 'service',
        label: l.label,
        sub: `${n.name} · ${host(l.url)}`,
        hue: l.hue || hue,
        hay: `${l.label} ${n.name} ${l.url}`.toLowerCase(),
        // Enter shows it over the map (THE VIEWING GLASS) and falls back to a
        // new tab when the service refuses to be framed — same rule everywhere.
        run: () => {
          close();
          A.openHere(l.url, l.label, { sub: `a service of ${n.name}`, openIn: l.open_in });
        },
      });
    }
  }
}

/** Subsequence fuzzy match with a light score (contiguous + word-start win). */
function score(hay, q) {
  if (!q) return 0;
  let hi = 0, s = 0, streak = 0;
  for (const ch of q) {
    const at = hay.indexOf(ch, hi);
    if (at === -1) return -1;              // not a subsequence → drop
    if (at === hi) streak++; else streak = 0;
    s += 1 + streak * 2 + (at === 0 || hay[at - 1] === ' ' ? 3 : 0);
    hi = at + 1;
  }
  return s;
}

function render() {
  const q = input.value.trim().toLowerCase();
  shown = (q
    ? items.map((it) => ({ it, sc: score(it.hay, q) }))
        .filter((r) => r.sc >= 0)
        .sort((a, b) => b.sc - a.sc || a.it.label.length - b.it.label.length)
        .map((r) => r.it)
    : items.slice()                        // empty query → everything (places first)
  ).slice(0, CFG.PALETTE_MAX);
  active = 0;

  listEl.innerHTML = shown.length
    ? shown.map((it, i) => (
        `<button class="pal-row${i === 0 ? ' active' : ''}" data-i="${i}" role="option">` +
        `<span class="pal-dot" style="background:${esc(it.hue)}"></span>` +
        `<span class="pal-kind">${it.kind === 'place' ? '◆' : '›'}</span>` +
        `<span class="pal-label">${esc(it.label)}</span>` +
        `<span class="pal-sub">${esc(it.sub)}</span></button>`
      )).join('')
    : `<div class="pal-empty">No place or service by that name.</div>`;

  for (const row of listEl.children) {
    if (!row.dataset) continue;
    row.addEventListener?.('mousemove', () => setActive(Number(row.dataset.i)));
    row.addEventListener?.('click', () => shown[Number(row.dataset.i)]?.run());
  }
}

function setActive(i) {
  if (!shown.length) return;
  active = (i + shown.length) % shown.length;
  for (const row of listEl.children) {
    if (row.dataset) row.classList.toggle('active', Number(row.dataset.i) === active);
  }
  listEl.children[active]?.scrollIntoView({ block: 'nearest' });
}

function open() {
  if (!root) return;
  buildIndex();                 // rebuild so late data / future scenes are included
  root.classList.add('open');
  root.setAttribute('aria-hidden', 'false');
  input.value = '';
  render();
  input.focus();
}

function close() {
  if (!root) return;
  root.classList.remove('open');
  root.setAttribute('aria-hidden', 'true');
  input.blur();
}
A.openPalette = open;
A.closePalette = close;

let paletteWired = false;
A.buildPalette = function buildPalette() {
  root = $('palette');
  input = $('pal-input');
  listEl = $('pal-list');
  if (!root) return;
  // the palette reads A.DATA live, so a rebuild only needs to not re-bind
  if (paletteWired) return;
  paletteWired = true;

  input.addEventListener('input', render);
  input.addEventListener('keydown', (e) => {
    switch (e.key) {
      case 'ArrowDown': e.preventDefault(); setActive(active + 1); break;
      case 'ArrowUp': e.preventDefault(); setActive(active - 1); break;
      case 'Enter': e.preventDefault(); shown[active]?.run(); break;
      case 'Escape': e.preventDefault(); close(); break;
    }
  });
  // click on the scrim (not the panel) closes
  root.addEventListener('pointerdown', (e) => { if (e.target === root) close(); });
};
