/* Atlas — ACCOUNTS: who can get into each place, and how far in.

   A weekly access audit (a rite) can diff accounts,
   keys, sudoers and domain-join against each host's committed baseline — and
   the Atlas tracked only that the rite BEAT. "Who holds a key to the app host" was
   a question the map could not answer, which is a strange gap in a map whose
   whole job is to say what is where.

   ⚑ FILE NAME. Every other scene is one word (`seals.js`, `stones.js`), but
   `account.js` already exists in this directory and owns the SIGNED-IN VIEWER's
   own panel — the seal you carry, the admin ledgers, the directory. Two files
   a character apart, about different nouns, would be a trap for every future
   reader and every grep. The scene keeps the plain name; the file spells out
   which one it is.

   WHAT THIS SCENE IS FOR, and therefore what it colours. An account roster is
   long and almost entirely uninteresting: `link` can sudo on every host, and
   that is the design. The one fact worth walking across the room for is an
   account that elevates WITHOUT BEING ASKED — a key that is also a skeleton
   key. So `nopasswd` is the only loud thing on the page, spent once, per this
   design's own "if everything glows, nothing does". Everything else is the
   warm neutral it deserves to be.

   THE HEAD MUST NOT DRAW CALM OVER A GAP. "No place has a passwordless
   account" and "almost nothing is charted yet" look identical if you only
   count findings — the same trap THE DECOYS exists to avoid. So the
   head states COVERAGE first (how many charted places carry a roster at all)
   and the finding second, and an empty scene says it is empty rather than
   saying all is well.

   It is an INVENTORY, not a live read — surveyed by hand from the audit's
   baseline, exactly as THE SEALS is surveyed from the hosts. So it says so,
   rather than implying the map went and looked just now. */

import { A, $, esc, zoneById } from './config.js';
import { makeScene } from './scene.js';

let root, listEl, headEl;

/* The three sudo states, loudest first. `nopasswd` takes the map's existing
   alarm tone (`--sem-down`); `password` is ordinary and quiet; `none` is the
   most common and gets no colour at all. No new colours — the semantic tokens
   the markers already use. */
const SUDO = {
  nopasswd: { rank: 0, cls: 'acc-nopass', word: 'sudo · no password' },
  password: { rank: 1, cls: 'acc-sudo', word: 'sudo' },
  none: { rank: 2, cls: 'acc-plain', word: 'no sudo' },
};
const SUDO_UNKNOWN = { rank: 1.5, cls: 'acc-unknown', word: 'sudo not charted' };

/* What the account IS, which is not the same question as what it can do. An
   `agent` that can elevate silently is a different sentence from a human who
   can — both are worth seeing, and only the roster says which is which. */
const SOURCE_WORD = {
  local: 'local', domain: 'directory', service: 'service', agent: 'agent',
};

const sudoOf = (a) => SUDO[a && a.sudo] || (a && a.sudo ? SUDO_UNKNOWN : SUDO.none);

/** Places that can hold accounts at all, in the order the map lists them.
    An `off_map` place still counts: it is charted, it just is not drawn, and
    an account on it is exactly as real. */
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
  // a place with an EMPTY roster is not the same as one with no roster: the
  // first is a surveyed "nobody but root", the second is simply unsurveyed.
  const charted = all.filter((n) => Array.isArray(n.accounts) && n.accounts.length);
  const accounts = charted.flatMap((n) => n.accounts);
  const loud = accounts.filter((a) => sudoOf(a) === SUDO.nopasswd).length;

  if (headEl) {
    if (!charted.length) {
      headEl.innerHTML =
        `<span class="rt-waiting">nothing charted yet — `
        + `${all.length} place${all.length === 1 ? '' : 's'} could hold a roster</span>`;
    } else {
      // coverage FIRST: a finding count means nothing until you know how much
      // of the realm it was counted over
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

  // Places carrying the finding sort first — a roster you have to scroll to
  // find the one dangerous line in is a roster nobody reads twice.
  const blocks = charted
    .map((n) => ({
      node: n,
      loud: n.accounts.filter((a) => sudoOf(a) === SUDO.nopasswd).length,
      rows: n.accounts.slice().sort((a, z) => sudoOf(a).rank - sudoOf(z).rank
        || String(a.name || '').localeCompare(String(z.name || ''))),
    }))
    .sort((a, z) => z.loud - a.loud || a.node.name.localeCompare(z.node.name));

  listEl.innerHTML = blocks.map(({ node, rows, loud: n }) => {
    const hue = zoneById(node.zone)?.hue || '#C9A554';
    return `<div class="ldg-block" style="--z-hue:${esc(hue)}">
      <div class="ldg-zhead">
        <span class="ldg-zname">${esc(node.name)}</span>
        <span class="ldg-zsub">${esc(node.role || '')}</span>
        <span class="ldg-zcount">${rows.length} account${rows.length === 1 ? '' : 's'}${
          n ? ` · <b class="acc-flag">${n} silent</b>` : ''}</span>
      </div>
      ${rows.map(accountHTML).join('')}
    </div>`;
  }).join('') || `<div class="ldg-note">no accounts charted — add them in the Desk,
    on each place's own form. Surveyed by hand from the access baseline the
    weekly audit already diffs; chart the posture, never a credential.</div>`;
}

const scene = makeScene({ id: 'accounts', closeId: 'acc-close', build: () => build() });
const { open, close } = scene;
A.openAccounts = open;
A.closeAccounts = close;

A.buildAccountsScene = function buildAccountsScene() {
  root = scene.mount();
  if (!root) return;
  listEl = $('acc-list');
  headEl = $('acc-head');
};
