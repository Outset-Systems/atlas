
import { A, CFG, $, esc, host, zoneById, FALLBACK_HUE } from './config.js';
import { rank } from './palette-model.js';

let root, input, listEl;
let items = [];
let shown = [];
let active = 0;

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
      if (!l?.url) continue;
      items.push({
        kind: 'service',
        label: l.label,
        sub: `${n.name} · ${host(l.url)}`,
        hue: l.hue || hue,
        hay: `${l.label} ${n.name} ${l.url}`.toLowerCase(),
        run: () => {
          close();
          A.openHere(l.url, l.label, { sub: `a service of ${n.name}`, openIn: l.open_in });
        },
      });
    }
  }
}

function render() {
  const q = input.value.trim().toLowerCase();
  shown = rank(items, q, CFG.PALETTE_MAX);
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
  buildIndex();
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
  root.addEventListener('pointerdown', (e) => { if (e.target === root) close(); });
};
