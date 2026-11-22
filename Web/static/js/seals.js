
import { A, $, esc } from './config.js';
import { say } from './words.js';
import { makeScene } from './scene.js';
import { folds } from './fold.js';
import { opensAtFirst, sealsByHand, sealsDue } from './fold-model.js';
import { seenFor } from './watch-model.js';

let listEl, headEl;
const F = folds('seals');

const DAY = 86400000;
const GROUPS = [
  { key: 'tls', head: 'THE OUTER SEALS', sub: 'what the public edge presents' },
  { key: 'ssh-host', head: 'THE HOST SEALS', sub: 'what each host answers ssh with' },
  { key: 'ca', head: 'THE ROOT SEALS', sub: 'what signs the rest' },
];

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

function seenHTML(c) {
  const seen = seenFor(c, A.DATA, A.signalsFeed?.services);
  if (!seen) return '';
  const words = seen.differs ? `seen ${seen.expires} · the chart is out of date` : `seen ${seen.expires}`;
  return `<span class="seal-seen${seen.differs ? ' seal-differs' : ''}" title="${esc(`${seen.issuer ? `${seen.issuer} · ` : ''}via ${seen.via}`)}">${esc(words)}</span>`;
}

function sealHTML(c) {
  const days = daysUntil(c.expires);
  const b = band(days);
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
      ${seenHTML(c)}
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
      ? `<span class="rt-alarm">${soon} ${say(`${soon > 1 ? 'seals lapse' : 'seal lapses'} within a fortnight`)}</span>`
      : `<span class="rt-calm">${say('no seal lapses within a fortnight')}</span>`
        + (manual ? `<span class="rt-waiting"> · ${manual} renewed by hand</span>` : '');
  }

  const ordered = GROUPS
    .map((g) => ({ ...g, members: certs.filter((c) => c.kind === g.key) }))
    .filter((g) => g.members.length)
    .sort((a, z) => (daysUntil(a.members[0].expires) ?? 1e9)
                  - (daysUntil(z.members[0].expires) ?? 1e9));

  listEl.innerHTML = ordered.map(({ key, head, sub, members: group }) => {
    const { lapsed, soon } = sealsDue(group.map((c) => daysUntil(c.expires)));
    const byHand = sealsByHand(group);
    const fold = `kind:${key}`;
    const first = opensAtFirst(lapsed + soon + byHand, ordered.length);
    return `<div class="ldg-block${F.shut(fold, first)}" data-fold-box style="--z-hue:var(--gilt)">
      <div class="ldg-zhead" ${F.head(fold, first, say(head).toLowerCase())}>
        <span class="ldg-fold" aria-hidden="true">▾</span>
        <span class="ldg-zname">${say(head)}</span>
        <span class="ldg-zsub">${sub}</span>
        <span class="ldg-zcount">${group.length} ${say(group.length > 1 ? 'seals' : 'seal')}${
          lapsed ? ` · <b class="acc-flag">${lapsed} lapsed</b>` : ''}${
          soon ? ` · <span class="rt-warn">${soon} within a fortnight</span>` : ''}${
          byHand ? ` · <span class="rt-warn">${byHand} by hand</span>` : ''}</span>
      </div>
      ${group.map(sealHTML).join('')}
    </div>`;
  }).join('') || `<div class="ldg-note">${say('no seals charted — add them in the map editor.')}</div>`;
}

const scene = makeScene({ id: 'seals', closeId: 'sl-close', build: () => build() });
const { open, close } = scene;
A.openSeals = open;
A.closeSeals = close;

A.buildSealsScene = function buildSealsScene() {
  if (!scene.mount()) return;
  listEl = $('sl-list');
  headEl = $('sl-head');
  F.wire(listEl);
};
