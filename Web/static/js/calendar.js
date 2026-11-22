
import { A, $, esc, ago, nodeById, getJSON } from './config.js';
import { say } from './words.js';
import { makeScene } from './scene.js';
import {
  DAY_MIN, layoutDay, layoutForge, nextTurning, fmtClock, dayName,
  every, clockPhrase, isSilent, nextParts, foldDay, weekOf, tally,
} from './calendar-model.js';

const pct = (min) => `${(min / DAY_MIN * 100).toFixed(3)}%`;

const VERDICT = {
  kept: { cls: 'v-kept', mark: '✓' },
  late: { cls: 'v-late', mark: '◔' },
  missed: { cls: 'v-missed', mark: '✕' },
  failed: { cls: 'v-failed', mark: '✕' },
  awaited: { cls: 'v-awaited', mark: '·' },
  unwatched: { cls: 'v-unwatched', mark: '·' },
};

const elapsed = (seconds) => ago(seconds * 1000);

function when(r) {
  if (typeof r.age_s === 'number') return elapsed(r.age_s);
  const then = new Date(r.last?.at);
  if (Number.isNaN(then.getTime())) return r.last?.at || '';
  return elapsed((Date.now() - then.getTime()) / 1000);
}

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

function rowHTML(lane, { nowMin, today }) {
  const r = lane.rite;
  const v = VERDICT[r.verdict] || VERDICT.unwatched;
  const last = r.last;
  const took = last && last.duration_s != null ? ` · took ${last.duration_s}s` : '';
  const title = [told(r), last ? `last beat ${last.at}${last.source ? ` via ${last.source}` : ''}` : '']
    .filter(Boolean).join(' · ');
  const runs = (r.runs || []).slice(-8).map((run) =>
    `<i class="cal-tick ${run.status === 'fail' ? 'bad' : 'good'}" title="${esc(run.at)}"></i>`).join('');

  let track = '';
  if (lane.every) {
    const teeth = lane.every >= 30;
    track = `<i class="cal-wash${teeth ? ' combed' : ''}" ` +
      `style="--cal-every:${(lane.every / DAY_MIN * 100).toFixed(4)}%" ` +
      `title="${esc(lane.name)} · every ${lane.every} min, all day"></i>`;
  } else {
    track = lane.today.map((b) => {
      const cls = ['cal-blk', b.hit ? 'hit' : '', lane.ghost ? 'ghost' : ''].filter(Boolean).join(' ');
      const tip = `${lane.name} · ${fmtClock(b.start)}–${fmtClock(b.end)}Z` +
        (lane.model ? ` · ${lane.model}` : '') + (b.hit ? say(' · MEETS ANOTHER RITE HERE') : '');
      return `<i class="${cls}" style="left:${pct(b.start)};width:${pct(b.end - b.start)}" title="${esc(tip)}"></i>`;
    }).join('');
  }
  const idle = lane.blocks.length && !lane.today.length && !lane.every
    ? '<i class="cal-idle">not on this day</i>' : '';
  const where = [lane.host, lane.model].filter(Boolean).join(' · ');
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

function groupHTML(group, ctx) {
  const place = group.kind === 'forge'
    ? (nodeById(group.place)?.name || group.place.toUpperCase())
    : null;
  const drawn = group.lanes.filter((l) => l.today.length || l.every).length;
  const silent = group.lanes.filter((l) => isSilent(l.rite.verdict)).length;
  let count = `${group.lanes.length} ${say(group.lanes.length === 1 ? 'rite' : 'rites')}`;
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
      const { clock, day, wait } = nextParts(next, ctx.now);
      const at = `${clock}Z${day ? ` ${day}` : ''}`;
      foot.push(`<span class="cal-next">next · <b>${esc(next.lane.name)}</b> at ${esc(at)} · in ${wait}</span>`);
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

  const { shown, folded } = foldDay(group);
  const open = opened.has(group.key);
  const rows = open ? group.lanes : shown;

  return `<div class="cal-grp k-${group.kind}">
    <div class="cal-ghead">
      <span class="cal-gname">${esc(place ? `${say('THE FORGE')} · ${place}` : say(group.title))}</span>
      <span class="cal-gsub">${esc(say(group.sub))}</span>
      <span class="cal-gcount">${count}</span>
    </div>
    ${rows.map((l) => rowHTML(l, ctx)).join('')}
    ${folded.length ? foldHTML(group, folded, open, ctx) : ''}
    ${foot.length ? `<div class="cal-gfoot">${foot.join('')}</div>` : ''}
  </div>`;
}

function foldHTML(group, folded, open, ctx) {
  const n = folded.length;
  let what;
  if (group.kind === 'listed') {
    const names = folded.slice(0, 3).map((l) => `<b>${esc(l.name)}</b>`).join(', ');
    what = `<span>${names}${n > 3 ? ` and ${n - 3} more` : ''}</span>`;
  } else {
    what = `<span>${n} ${say(n === 1 ? 'rite' : 'rites')} not on this day</span>`;
    const next = nextTurning(folded, ctx.now);
    if (next) {
      const { clock, day, wait } = nextParts(next, ctx.now);
      what += `<span>next · <b>${esc(next.lane.name)}</b> ${esc(day || 'today')} ${esc(clock)}Z · in ${esc(wait)}</span>`;
    }
  }
  return `<button class="cal-fold" data-fold="${esc(group.key)}" aria-expanded="${open}">
    ${what}<span class="cal-fold-do">${open ? 'FOLD ‹' : 'SHOW ›'}</span></button>`;
}


export function calendarPointerHTML(node, rites, { now = new Date() } = {}) {
  const { lanes, unclocked } = layoutForge(rites, node.id);
  if (!lanes.length && !unclocked.length) return '';
  const n = lanes.length + unclocked.length;
  const next = nextTurning(lanes, now);
  const { clock, day, wait } = next ? nextParts(next, now) : {};
  const line = next
    ? `next · <b>${esc(next.lane.name)}</b> at ${esc(clock)}Z` +
      `${day ? ` ${esc(day)}` : ''} · in ${wait}`
    : `${n} ${say(n === 1 ? 'rite' : 'rites')} ask it, none with a clock`;
  return `<div class="cv-head">${say('the forge')}'s day · utc</div>` +
    `<span class="cal-next">${line}</span>` +
    `<button class="card-link card-forge-link" id="btn-card-forge" title="${say("Every rite of the realm on one day — this forge's among them")}">` +
    `THE CALENDAR ›</button>`;
}


let listEl, headEl, RITES = null, offset = 0;
const opened = new Set();

function verdictHTML(t) {
  const quiet = (s) => `<span class="cal-quiet">${s}</span>`;
  const late = t.late ? ` · <span class="cal-warnish">${t.late} late</span>` : '';
  const waiting = t.awaited ? quiet(` · ${t.awaited} not yet reporting`) : '';
  if (t.silent) {
    return `<span class="cal-alarm">${t.silent} ${say(`${t.silent > 1 ? 'rites have' : 'rite has'} stopped turning`)}</span>${late}${waiting}`;
  }
  if (!t.kept && !t.late) {
    return t.awaited
      ? quiet(`${say('no rite has reported yet')} · ${t.awaited} awaited`)
      : quiet(say('the rites could not be asked — this is the chart, not what ran'));
  }
  if (!t.late && !t.awaited) return `<span class="cal-calm">${say('every timed rite is turning')}</span>`;
  return `<span class="cal-calm">${t.kept} turning</span>${late}${waiting}`;
}

function weekHTML(day) {
  const drawnIso = day.toISOString().slice(0, 10);
  const todayIso = new Date().toISOString().slice(0, 10);
  return `<nav class="cal-week" aria-label="The week">${weekOf(RITES, day).map((w) => {
    const on = w.iso === drawnIso;
    const cls = ['cal-wday', on ? 'on' : '', w.iso === todayIso ? 'today' : '', w.hits ? 'meets' : ''].filter(Boolean).join(' ');
    const tip = `${dayName(w.dow)} ${w.iso} · ${w.drawn} ${say(w.drawn === 1 ? 'rite' : 'rites')}` +
      (w.hits ? ` · ${w.hits} meeting${w.hits === 1 ? '' : 's'} at ${say('the forge')}` : '') +
      (w.iso === todayIso ? ' · today' : '');
    return `<button class="${cls}" data-day="${w.iso}" aria-pressed="${on}" title="${esc(tip)}">
      <b>${dayName(w.dow).toUpperCase()}</b><span>${w.date.getUTCDate()}</span>
      <i><em>${w.drawn}</em><s> ${say(w.drawn === 1 ? 'rite' : 'rites')}</s>${w.hits ? '<u> · meets</u>' : ''}</i></button>`;
  }).join('')}</nav>`;
}

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
    const meetings = view.hits.length
      ? ` · <span class="cal-alarm">${view.hits.length} meeting${view.hits.length === 1 ? '' : 's'} at ${say('the forge')}</span>`
      : '';
    headEl.innerHTML = `<span class="cal-verdict">${verdictHTML(tally(RITES))}</span>
      <span class="cal-count">${view.drawn.length} of ${view.lanes.length} ${say('rites')} fall on this day${meetings}</span>
      <span class="cal-step">
        <button class="cal-arrow" id="cal-prev" title="The day before" aria-label="The day before">‹</button>
        <b id="cal-when">${esc(`${dayName(day.getUTCDay()).toUpperCase()} ${day.toISOString().slice(0, 10)}`)}</b>
        <button class="cal-arrow" id="cal-next" title="The day after" aria-label="The day after">›</button>
        <button class="cal-today" id="cal-today" ${today ? 'disabled' : ''}>TODAY</button>
      </span>
      ${weekHTML(day)}`;
    $('cal-prev').onclick = () => { offset -= 1; paint(); };
    $('cal-next').onclick = () => { offset += 1; paint(); };
    $('cal-today').onclick = () => { offset = 0; paint(); };
    headEl.querySelectorAll('.cal-wday').forEach((b) => {
      b.onclick = () => {
        const todayUtc = Date.parse(`${new Date().toISOString().slice(0, 10)}T00:00:00Z`);
        offset = Math.round((Date.parse(`${b.dataset.day}T00:00:00Z`) - todayUtc) / 86400000);
        paint();
        headEl.querySelector(`.cal-wday[data-day="${b.dataset.day}"]`)?.focus();
      };
    });
  }

  listEl.innerHTML = view.groups.length
    ? rulerHTML(today ? 'UTC · the hairline is now' : `UTC · ${dayName(day.getUTCDay()).toUpperCase()} — not today`)
      + view.groups.map((g) => groupHTML(g, ctx)).join('')
    : `<div class="ldg-note">${say('no rites charted — add them in the map editor.')}</div>`;
}

async function build() {
  listEl.innerHTML = `<div class="ldg-note">${say('asking the rites what they did…')}</div>`;
  try {
    RITES = (await getJSON('api/v2/rites')).rites || [];
  } catch {
    RITES = (A.DATA.rites || []).map((r) => ({ ...r, verdict: 'unwatched' }));
  }
  paint();
  buildFleet();
}

async function buildFleet() {
  const host = $('cal-fleet');
  if (!host || !window.OutsetCalendar) return;
  let v = null;
  try {
    v = await getJSON('api/v2/calendar');
  } catch {   }
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
  listEl.addEventListener('click', (e) => {
    const b = e.target.closest('.cal-fold');
    if (!b) return;
    const key = b.dataset.fold;
    if (opened.has(key)) opened.delete(key); else opened.add(key);
    paint();
    listEl.querySelector(`.cal-fold[data-fold="${CSS.escape(key)}"]`)?.focus();
  });
};
