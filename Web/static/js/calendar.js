/* Atlas — THE CALENDAR (v1.45.0).

   One page for the realm's day. It replaces two scenes that were always about
   the same twenty-eight rows:

     THE RITES (2026-07-11, told the truth 2026-07-28) listed every recurring
     automation by its turning and said whether it actually turned — the scene
     that stopped the map telling "daily 02:00" about a backup that died in
     April.
     THE FORGE'S DAY (v1.40.0, its own scene v1.42.0) drew the five rites that
     ask the GPU box for a model on one UTC day, so the meetings over the single GPU
     could be seen instead of deduced.

   Two scenes meant a rite re-timed in the Desk moved on one page and not the
   other, and neither page could answer the question a person actually walks up
   with at 2am — "what is supposed to happen today, and did it?". THE CALENDAR
   answers it in one row: WHAT and WHERE on the left, the day across the middle,
   WHEN and WHETHER on the right, a verdict glyph in the gutter you can scan
   down without reading.

   The colour is spent per the design notes's "if everything glows, nothing does", and
   the ladder changed when the page grew from five rows to twenty-eight: an
   ordinary rite is now an INK bar (the day's substrate), the gilt is kept for
   the rites that ask the forge for a model — the scarce, contended thing — the
   heavy model that never fit the GPU box's 16 GB takes the warning tone, a MEETING is
   the only alarm on the page, and "now" is one info-hued hairline.

   calendar-model.js decides what is where; this only paints. */

import { A, $, esc, ago, nodeById } from './config.js';
import { makeScene } from './scene.js';
import {
  DAY_MIN, layoutDay, layoutForge, nextTurning, fmtClock, dayName,
} from './calendar-model.js';

const pct = (min) => `${(min / DAY_MIN * 100).toFixed(3)}%`;

/* Read at 2am by someone who wants to know if it ran, not what enum it is. */
const VERDICT = {
  kept: { cls: 'v-kept', mark: '✓' },
  late: { cls: 'v-late', mark: '◔' },
  missed: { cls: 'v-missed', mark: '✕' },
  failed: { cls: 'v-failed', mark: '✕' },
  awaited: { cls: 'v-awaited', mark: '·' },
  unwatched: { cls: 'v-unwatched', mark: '·' },
};

const elapsed = (seconds) => ago(seconds * 1000);

/* How long ago the rite last turned.

   Deliberately the server's `age_s` and not the browser's arithmetic on
   `last.at`. The verdict is computed from the stored epoch, so deriving the
   phrasing from the timestamp string instead lets the two disagree — a store
   restored from backup, or a clock that moved, produced the genuinely absurd
   "MISSED — last turned 1m ago". One number decides both, or neither can be
   trusted. Falls back to the timestamp only when the row carries no age,
   which is the never-reported case that prints no time at all. */
function when(r) {
  if (typeof r.age_s === 'number') return elapsed(r.age_s);
  const then = new Date(r.last?.at);
  if (Number.isNaN(then.getTime())) return r.last?.at || '';
  return elapsed((Date.now() - then.getTime()) / 1000);
}

function every(seconds) {
  if (!seconds) return '';
  if (seconds % 604800 === 0) return `every ${seconds / 604800}w`;
  if (seconds % 86400 === 0) return `every ${seconds / 86400}d`;
  if (seconds % 3600 === 0) return `every ${seconds / 3600}h`;
  return `every ${Math.round(seconds / 60)}m`;
}

/* The sentence the row is actually for. */
function told(r) {
  const last = r.last;
  switch (r.verdict) {
    case 'kept':
      return `turned ${when(r)}`;
    case 'late':
      return `late — last turned ${when(r)}, ${every(r.expect_every)}`;
    case 'missed':
      return `MISSED — last turned ${when(r)}, expected ${every(r.expect_every)}`;
    case 'failed':
      return `FAILED ${when(r)}${last.note ? ` — ${last.note}` : ''}`;
    case 'awaited':
      return 'not yet reporting';
    default:
      return 'not timed';
  }
}

/** The row's clock, in one short phrase. The surveyor's own `when` can run to
    a paragraph ("04:00 CDT the download host + the media host · 08:00 UTC the edge · 10:00 UTC
    The app host") and a 200px column truncates it into something no more checkable
    than a guess — so the column carries the clock this page actually DREW and
    the prose rides in the row's title, one hover away. A clock read out of that
    prose wears a dotted rule (`.cal-row.read`) to say which. Hours are UTC and
    the axis says so once, so no row repeats it. */
function clockPhrase(lane) {
  if (lane.every) return lane.every % 60 === 0 ? `every ${lane.every / 60}h` : `every ${lane.every} min`;
  if (!lane.blocks.length) return 'no hour charted';
  const at = fmtClock(lane.blocks[0].start);
  if (lane.hourly) {
    return `hourly at :${String(lane.blocks[0].start % 60).padStart(2, '0')}`
      + (lane.window ? ` · ${fmtClock(lane.window.from)}–${fmtClock(lane.window.to)}` : '');
  }
  if (lane.ghost) return `${at} · its own date`;
  const days = lane.daysLabel || (lane.cadence === 'weekly' ? dayName([...lane.days][0]) : '');
  return days ? `${days} ${at}` : at;
}

function inWords(min) {
  if (min < 60) return `${min}m`;
  const h = Math.floor(min / 60), m = min % 60;
  if (h < 24) return m ? `${h}h ${m}m` : `${h}h`;
  const d = Math.floor(h / 24);
  return `${d}d ${h % 24}h`;
}

/* ── the day, drawn ───────────────────────────────────────────────────────── */

/** The hour axis every row hangs off. Labelled every three hours, and the
    track's own ground is divided on the same three (`.cal-track` in
    atlas.css) — so the ruler carries numbers and nothing else, and every
    division under it has a number above it. */
function rulerHTML(zoneNote) {
  let marks = '';
  for (let h = 0; h < 24; h += 3) marks += `<span style="left:${pct(h * 60)}">${String(h).padStart(2, '0')}</span>`;
  return `<div class="cal-ruler">
    <i class="cal-mark"></i>
    <span class="cal-name"><b>THE HOURS</b><i>${esc(zoneNote)}</i></span>
    <div class="cal-hours">${marks}</div>
    <span class="cal-meta"></span>
  </div>`;
}

/** One rite: the gutter glyph, what and where, the day, when and whether. */
function rowHTML(lane, { nowMin, today }) {
  const r = lane.rite;
  const v = VERDICT[r.verdict] || VERDICT.unwatched;
  const last = r.last;
  const took = last && last.duration_s != null ? ` · took ${last.duration_s}s` : '';
  const title = last ? `last beat ${last.at}${last.source ? ` via ${last.source}` : ''}` : '';
  // the last few turnings as a sparkline of ticks — three reds in a row is a
  // different story from one, and the count is what tells them apart
  const runs = (r.runs || []).slice(-8).map((run) =>
    `<i class="cal-tick ${run.status === 'fail' ? 'bad' : 'good'}" title="${esc(run.at)}"></i>`).join('');

  let track = '';
  if (lane.every) {
    /* An ever-turning rite has a rhythm, not an hour: the whole track, never a
       block — there is no minute to point at. It is COMBED at its own interval
       only while the teeth still mean something; "every 5 min" is 288 of them,
       a solid hatch that shouted over every real block on the page and inverted
       the whole hierarchy. Below half an hour the honest drawing is a plain
       band — the claim is "always, this often", and the phrase beside it
       carries the "how often". */
    const teeth = lane.every >= 30;
    track = `<i class="cal-wash${teeth ? ' combed' : ''}" ` +
      `style="--cal-every:${(lane.every / DAY_MIN * 100).toFixed(4)}%" ` +
      `title="${esc(lane.name)} · every ${lane.every} min, all day"></i>`;
  } else {
    track = lane.today.map((b) => {
      const cls = ['cal-blk', b.hit ? 'hit' : '', lane.ghost ? 'ghost' : ''].filter(Boolean).join(' ');
      const tip = `${lane.name} · ${fmtClock(b.start)}–${fmtClock(b.end)}Z` +
        (lane.model ? ` · ${lane.model}` : '') + (b.hit ? ' · MEETS ANOTHER RITE HERE' : '');
      return `<i class="${cls}" style="left:${pct(b.start)};width:${pct(b.end - b.start)}" title="${esc(tip)}"></i>`;
    }).join('');
  }
  // "not on this day" is worth saying — the rite HAS an hour and this is not
  // its day. "no hour charted" is not: the meta column says exactly that a
  // centimetre to the right, and an empty track is already the whole answer.
  const idle = lane.blocks.length && !lane.today.length && !lane.every
    ? '<i class="cal-idle">not on this day</i>' : '';
  const where = [lane.host, lane.model].filter(Boolean).join(' · ');
  // the surveyor's own phrasing rides the whole row, so the clock beside the
  // strip can always be checked against the sentence it was read out of
  const said = [lane.when, lane.note].filter(Boolean).join(' — ')
    || `${lane.name}${where ? ` · ${where}` : ''}`;

  return `<div class="cal-row ${v.cls} tone-${lane.tone}${lane.from === 'when' ? ' read' : ''}" title="${esc(said)}">
    <span class="cal-mark" title="${esc(r.verdict || 'unwatched')}">${v.mark}</span>
    <span class="cal-name"><b>${esc(lane.name)}</b><i>${esc(where)}</i></span>
    <div class="cal-track">${track}${idle}${today
      ? `<i class="cal-now" style="left:${pct(nowMin)}" title="now · ${fmtClock(nowMin)}Z"></i>` : ''}</div>
    <span class="cal-meta"><em>${esc(clockPhrase(lane))}</em>
      <i class="cal-truth" title="${esc(title)}">${esc(told(r))}${esc(took)}<span class="cal-ticks">${runs}</span></i></span>
  </div>`;
}

/** A group of rows under one head — a forge, a turning, or the listed. */
function groupHTML(group, ctx) {
  const place = group.kind === 'forge'
    ? (nodeById(group.place)?.name || group.place.toUpperCase())
    : null;
  const drawn = group.lanes.filter((l) => l.today.length || l.every).length;
  const silent = group.lanes.filter((l) => ['missed', 'failed'].includes(l.rite.verdict)).length;
  let count = `${group.lanes.length} rite${group.lanes.length === 1 ? '' : 's'}`;
  if (group.kind !== 'listed') count += ` · ${drawn} on this day`;
  if (group.kind === 'forge') {
    count += group.hits.length
      ? ` · <b class="cal-broken">${group.hits.length} meeting${group.hits.length === 1 ? '' : 's'}</b>`
      : (group.standing.length ? ' · <b class="cal-warnish">they meet on other days</b>' : ' · no two at once');
  }
  if (silent) count += ` · <b class="cal-broken">${silent} silent</b>`;

  const foot = [];
  if (group.kind === 'forge') {
    const next = nextTurning(group.lanes.filter((l) => l.blocks.length), ctx.now);
    if (next) {
      const at = `${fmtClock(next.start)}Z${next.dayOffset ? ` ${dayName(ctx.now.getUTCDay() + next.dayOffset)}` : ''}`;
      foot.push(`<span class="cal-next">next · <b>${esc(next.lane.name)}</b> at ${esc(at)} · in ${inWords(next.inMin)}</span>`);
    }
    if (group.hits.length) {
      foot.push(`<span class="cal-hits">${group.hits.slice(0, 3).map((h) =>
        `${fmtClock(h.at)}Z ${esc(h.lanes.join(' × '))}`).join(' · ')}${group.hits.length > 3 ? ' · …' : ''} — ` +
        `nothing arbitrates; the second call waits for a swap inside its own timeout</span>`);
    }
    const unclocked = group.lanes.filter((l) => !l.blocks.length);
    if (unclocked.length) {
      foot.push(`<span class="cal-quiet">${unclocked.map((l) => `<b>${esc(l.name)}</b>`).join(', ')} ` +
        `turn${unclocked.length === 1 ? 's' : ''} without a clock and cannot be planned around</span>`);
    }
  }

  return `<div class="cal-grp k-${group.kind}">
    <div class="cal-ghead">
      <span class="cal-gname">${esc(place ? `THE FORGE · ${place}` : group.title)}</span>
      <span class="cal-gsub">${esc(group.sub)}</span>
      <span class="cal-gcount">${count}</span>
    </div>
    ${group.lanes.map((l) => rowHTML(l, ctx)).join('')}
    ${foot.length ? `<div class="cal-gfoot">${foot.join('')}</div>` : ''}
  </div>`;
}

/* ── the card's pointer ───────────────────────────────────────────────────── */

/** What turns next on this place's forge, and the door to THE CALENDAR. '' for
    every place nobody asks, so the card of a NAS is exactly the card it was.
    Intent only — the dataset's clocks, never the beats. */
export function calendarPointerHTML(node, rites, { now = new Date() } = {}) {
  const { lanes, unclocked } = layoutForge(rites, node.id);
  if (!lanes.length && !unclocked.length) return '';
  const n = lanes.length + unclocked.length;
  const next = nextTurning(lanes, now);
  const line = next
    ? `next · <b>${esc(next.lane.name)}</b> at ${esc(fmtClock(next.start))}Z` +
      `${next.dayOffset ? ` ${esc(dayName(now.getUTCDay() + next.dayOffset))}` : ''} · in ${inWords(next.inMin)}`
    : `${n} rite${n === 1 ? '' : 's'} ask it, none with a clock`;
  return `<div class="cv-head">the forge's day · utc</div>` +
    `<span class="cal-next">${line}</span>` +
    `<button class="card-link card-forge-link" id="btn-card-forge" title="Every rite of the realm on one day — this forge's among them">` +
    `THE CALENDAR ›</button>`;
}

/* ── the scene ────────────────────────────────────────────────────────────── */

let listEl, headEl, RITES = null, offset = 0;

const drawnDate = () => {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() + offset);
  return d;
};

function paint() {
  const now = new Date();
  const day = drawnDate();
  const today = offset === 0;
  const view = layoutDay(RITES, { dow: day.getUTCDay() });
  const ctx = { now, today, nowMin: now.getUTCHours() * 60 + now.getUTCMinutes() };

  if (headEl) {
    const bad = RITES.filter((r) => ['missed', 'failed'].includes(r.verdict)).length;
    const waiting = RITES.filter((r) => r.verdict === 'awaited').length;
    const verdict = bad
      ? `<span class="cal-alarm">${bad} rite${bad > 1 ? 's have' : ' has'} stopped turning</span>`
      : `<span class="cal-calm">every timed rite is turning</span>${
        waiting ? `<span class="cal-quiet"> · ${waiting} not yet reporting</span>` : ''}`;
    const meetings = view.hits.length
      ? `<span class="cal-alarm">${view.hits.length} meeting${view.hits.length === 1 ? '' : 's'} at the forge</span>`
      : '<span class="cal-quiet">no two want one model at once</span>';
    headEl.innerHTML = `<span class="cal-verdict">${verdict}</span>
      <span class="cal-count">${view.drawn.length} of ${view.lanes.length} rites fall on this day · ${meetings}</span>
      <span class="cal-step">
        <button class="cal-arrow" id="cal-prev" title="The day before">‹</button>
        <b id="cal-when">${esc(`${dayName(day.getUTCDay()).toUpperCase()} ${day.toISOString().slice(0, 10)}`)}</b>
        <button class="cal-arrow" id="cal-next" title="The day after">›</button>
        <button class="cal-today" id="cal-today" ${today ? 'disabled' : ''}>TODAY</button>
      </span>`;
    $('cal-prev').onclick = () => { offset -= 1; paint(); };
    $('cal-next').onclick = () => { offset += 1; paint(); };
    $('cal-today').onclick = () => { offset = 0; paint(); };
  }

  listEl.innerHTML = view.groups.length
    ? rulerHTML(today ? 'UTC · the hairline is now' : `UTC · ${dayName(day.getUTCDay()).toUpperCase()} — not today`)
      + view.groups.map((g) => groupHTML(g, ctx)).join('')
    : '<div class="ldg-note">no rites charted — add them in the map editor.</div>';
}

async function build() {
  listEl.innerHTML = '<div class="ldg-note">asking the rites what they did…</div>';
  try {
    RITES = (await (await fetch('api/v2/rites', { cache: 'no-store' })).json()).rites || [];
  } catch {
    // the scene must still draw intent when the truth cannot be fetched — a
    // broken endpoint should degrade to the old behaviour, not to nothing
    RITES = (A.DATA.rites || []).map((r) => ({ ...r, verdict: 'unwatched' }));
  }
  paint();
  buildFleet();
}

/* THE FLEET'S DAY (v1.43.0, the calendar build plan): the shared Calendar
   component — the same one the Hub draws — showing every registered app's
   planned blocks with overlaps outlined. api/v2/calendar answers the Hub's
   fleet view when ATLAS_HUB_URL is set and the Hub answers, and the Atlas's
   own rites otherwise; only the fleet view is worth a second timeline here,
   so the block stays hidden standalone. */
async function buildFleet() {
  const host = $('cal-fleet');
  if (!host || !window.OutsetCalendar) return;
  let v = null;
  try {
    v = await (await fetch('api/v2/calendar', { cache: 'no-store' })).json();
  } catch { /* the realm's own day above is the whole story */ }
  if (!v?.fleet) { host.hidden = true; host.innerHTML = ''; return; }
  const n = (v.planned || []).length, o = (v.overlaps || []).length;
  host.hidden = false;
  host.innerHTML = `<div class="cal-grp k-fleet">
    <div class="cal-ghead">
      <span class="cal-gname">THE FLEET'S DAY · VIA THE HUB</span>
      <span class="cal-gsub">every registered app's manifest, as the Hub reads it — hours in your zone</span>
      <span class="cal-gcount">${n} planned block${n === 1 ? '' : 's'} across ${
        new Set((v.planned || []).map((p) => p.app)).size} apps${
        o ? ` · <b class="cal-broken">${o} overlap${o === 1 ? '' : 's'}</b>` : ' · no two want one model at once'}</span>
    </div>
    <div class="calendar-host" id="cal-fleet-cal"></div>
    <div class="cal-gfoot"><span class="cal-quiet">Run now and on/off live in the Hub — the Atlas charts, it does not command.</span></div>
  </div>`;
  window.OutsetCalendar.render($('cal-fleet-cal'), v, {});
}

const scene = makeScene({ id: 'calendar', closeId: 'cal-close', build: () => build() });
A.openCalendar = scene.open;
A.closeCalendar = scene.close;

A.buildCalendarScene = function buildCalendarScene() {
  if (!scene.mount()) return;
  listEl = $('cal-list');
  headEl = $('cal-head');
};
