
import { A, $, esc, zoneById, FALLBACK_HUE } from './config.js';
import { makeScene } from './scene.js';
import { folds } from './fold.js';
import { opensAtFirst } from './fold-model.js';

let listEl, headEl;
const F = folds('accounts');

const SUDO = {
  nopasswd: { rank: 0, cls: 'acc-nopass', word: 'sudo · no password' },
  password: { rank: 1, cls: 'acc-sudo', word: 'sudo' },
  none: { rank: 2, cls: 'acc-plain', word: 'no sudo' },
};
const SUDO_UNKNOWN = { rank: 1.5, cls: 'acc-unknown', word: 'sudo not charted' };

const SOURCE_WORD = {
  local: 'local', domain: 'directory', service: 'service', agent: 'agent',
};

const sudoOf = (a) => SUDO[a && a.sudo] || (a && a.sudo ? SUDO_UNKNOWN : SUDO.none);

function hosts() {
  return (A.DATA.nodes || []).filter((n) => n.kind !== 'network');
}

function accountHTML(a) {
  const s = sudoOf(a);
  const groups = (a.groups || []).filter(Boolean);
  return `<div class="acc-row ${s.cls}">
    <span class="acc-name">${esc(a.name || '—')}
      <i class="acc-src">${esc(SOURCE_WORD[a.source] || a.source || 'local')}</i></span>
    <span class="acc-mid">
      <span class="acc-sudo">${esc(s.word)}</span>
      ${groups.length
        ? `<span class="acc-groups">${groups.map((g) =>
            `<span class="acc-group">${esc(g)}</span>`).join('')}</span>`
        : ''}
      ${a.note ? `<span class="acc-note">${esc(a.note)}</span>` : ''}
    </span>
  </div>`;
}

function build() {
  if (!listEl) return;
  const all = hosts();
  const charted = all.filter((n) => Array.isArray(n.accounts) && n.accounts.length);
  const accounts = charted.flatMap((n) => n.accounts);
  const loud = accounts.filter((a) => sudoOf(a) === SUDO.nopasswd).length;

  if (headEl) {
    if (!charted.length) {
      headEl.innerHTML =
        `<span class="rt-waiting">nothing charted yet — `
        + `${all.length} place${all.length === 1 ? '' : 's'} could hold a roster</span>`;
    } else {
      const gap = all.length - charted.length;
      const cover = `<span class="rt-calm">${charted.length} of ${all.length} `
        + `place${all.length === 1 ? '' : 's'} surveyed</span>`
        + (gap ? `<span class="rt-waiting"> · ${gap} not yet charted</span>` : '');
      headEl.innerHTML = cover + (loud
        ? `<span class="rt-alarm"> · ${loud} account${loud === 1 ? '' : 's'} `
          + `elevate${loud === 1 ? 's' : ''} without a password</span>`
        : `<span class="rt-waiting"> · none elevates without a password</span>`);
    }
  }

  const blocks = charted
    .map((n) => ({
      node: n,
      loud: n.accounts.filter((a) => sudoOf(a) === SUDO.nopasswd).length,
      rows: n.accounts.slice().sort((a, z) => sudoOf(a).rank - sudoOf(z).rank
        || String(a.name || '').localeCompare(String(z.name || ''))),
    }))
    .sort((a, z) => z.loud - a.loud || a.node.name.localeCompare(z.node.name));

  const bar = blocks.length > 1
    ? `<div class="fold-bar"><button type="button" class="dsk-btn dsk-btn-sm" data-fold-all="open">Open all</button>
        <button type="button" class="dsk-btn dsk-btn-sm" data-fold-all="shut">Shut all</button></div>`
    : '';
  listEl.innerHTML = bar + blocks.map(({ node, rows, loud: n }) => {
    const hue = zoneById(node.zone)?.hue || FALLBACK_HUE;
    const key = `place:${node.id}`;
    const first = opensAtFirst(n, blocks.length);
    return `<div class="ldg-block${F.shut(key, first)}" data-fold-box style="--z-hue:${esc(hue)}">
      <div class="ldg-zhead" ${F.head(key, first, `${node.name}'s accounts`)}>
        <span class="ldg-fold" aria-hidden="true">▾</span>
        <span class="ldg-zname">${esc(node.name)}</span>
        <span class="ldg-zsub">${esc(node.role || '')}</span>
        <span class="ldg-zcount">${rows.length} account${rows.length === 1 ? '' : 's'}${
          n ? ` · <b class="acc-flag">${n} silent</b>` : ''}</span>
      </div>
      ${rows.map(accountHTML).join('')}
    </div>`;
  }).join('') || `<div class="ldg-note">no accounts charted — add them in the map editor,
    on each place's own form. Chart the posture, never a credential.</div>`;
}

const scene = makeScene({ id: 'accounts', closeId: 'acc-close', build: () => build() });
const { open, close } = scene;
A.openAccounts = open;
A.closeAccounts = close;

A.buildAccountsScene = function buildAccountsScene() {
  if (!scene.mount()) return;
  listEl = $('acc-list');
  headEl = $('acc-head');
  F.wire(listEl);
};
