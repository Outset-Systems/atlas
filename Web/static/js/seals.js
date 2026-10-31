/* Atlas — THE SEALS: every certificate the realm presents, and the
   day it lapses.

   A cert is only interesting in one direction: how long until it stops working.
   So the list is ordered by expiry, soonest first, and the only colour on the
   page is time remaining — nothing is gold because it is important, only
   because it is close. A seal that names no renewer is called out in words
   rather than left to be inferred from a blank cell, because "nothing renews
   this" is the single fact this scene exists to workstation.

   Read from the dataset, not from the wire: the expiries were surveyed off the
   hosts when charted (openssl s_client / ssh-keygen -L). That makes this an
   inventory, and an inventory can go stale — so the head says how stale, rather
   than implying it is live. (2026-08-04) */

import { A, $, esc } from './config.js';
import { makeScene } from './scene.js';

let root, listEl, headEl;

const DAY = 86400000;
const GROUPS = [
  { key: 'tls', head: 'THE OUTER SEALS', sub: 'what the public edge presents' },
  { key: 'ssh-host', head: 'THE HOST SEALS', sub: 'what each host answers ssh with' },
  { key: 'ca', head: 'THE ROOT SEALS', sub: 'what signs the rest' },
];

/* Bands, not a gradient: the eye should sort these into "fine / soon / act"
   without reading a number. 14 days is the step-ca renewal window plus slack. */
function band(days) {
  if (days == null) return { cls: 's-unknown', word: 'no date charted' };
  if (days < 0) return { cls: 's-lapsed', word: `lapsed ${-days}d ago` };
  if (days <= 14) return { cls: 's-soon', word: `${days}d left` };
  if (days <= 45) return { cls: 's-watch', word: `${days}d left` };
  return { cls: 's-calm', word: `${days}d left` };
}

function daysUntil(iso) {
  if (!iso) return null;
  const t = Date.parse(`${iso}T00:00:00Z`);
  if (Number.isNaN(t)) return null;
  return Math.round((t - Date.now()) / DAY);
}

function sealHTML(c) {
  const days = daysUntil(c.expires);
  const b = band(days);
  // a blank `renews` is the finding, not a gap in the record
  const renews = c.renews
    ? `<span class="seal-renews">${esc(c.renews)}</span>`
    : `<span class="seal-renews seal-manual">nothing renews this — by hand</span>`;
  return `<div class="seal ${b.cls}">
    <span class="seal-name">${esc(c.name)}
      ${c.host ? `<i class="seal-host">${esc(c.host)}</i>` : ''}</span>
    <span class="seal-mid">
      <span class="seal-issuer">${esc(c.issuer || 'unsigned')}</span>${renews}
      ${c.note ? `<span class="seal-note">${esc(c.note)}</span>` : ''}
    </span>
    <span class="seal-when">
      <span class="seal-days">${esc(b.word)}</span>
      <span class="seal-date">${esc(c.expires || '—')}</span>
    </span>
  </div>`;
}

function build() {
  const certs = (A.DATA.certs || []).slice()
    .sort((a, z) => (daysUntil(a.expires) ?? 1e9) - (daysUntil(z.expires) ?? 1e9));

  if (headEl) {
    const soon = certs.filter((c) => {
      const d = daysUntil(c.expires);
      return d != null && d <= 14;
    }).length;
    const manual = certs.filter((c) => !c.renews).length;
    headEl.innerHTML = soon
      ? `<span class="rt-alarm">${soon} seal${soon > 1 ? 's lapse' : ' lapses'} within a fortnight</span>`
      : `<span class="rt-calm">no seal lapses within a fortnight</span>`
        + (manual ? `<span class="rt-waiting"> · ${manual} renewed by hand</span>` : '');
  }

  // Groups are ordered by their most urgent member, not by a fixed kind order.
  // Sorting only WITHIN a group put the five host seals at 21 days underneath
  // five edge seals with 51–74 days left — technically "soonest first", and
  // exactly backwards for the one question this scene answers.
  const ordered = GROUPS
    .map((g) => ({ ...g, members: certs.filter((c) => c.kind === g.key) }))
    .filter((g) => g.members.length)
    .sort((a, z) => (daysUntil(a.members[0].expires) ?? 1e9)
                  - (daysUntil(z.members[0].expires) ?? 1e9));

  listEl.innerHTML = ordered.map(({ head, sub, members: group }) => {
    return `<div class="ldg-block" style="--z-hue:#C9A554">
      <div class="ldg-zhead">
        <span class="ldg-zname">${head}</span>
        <span class="ldg-zsub">${sub}</span>
        <span class="ldg-zcount">${group.length} seal${group.length > 1 ? 's' : ''}</span>
      </div>
      ${group.map(sealHTML).join('')}
    </div>`;
  }).join('') || '<div class="ldg-note">no seals charted — add them in the map editor.</div>';
}

const scene = makeScene({ id: 'seals', closeId: 'sl-close', build: () => build() });
const { open, close } = scene;
A.openSeals = open;
A.closeSeals = close;

A.buildSealsScene = function buildSealsScene() {
  root = scene.mount();
  if (!root) return;
  listEl = $('sl-list');
  headEl = $('sl-head');
};
