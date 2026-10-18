/* Atlas — THE CALENDAR, the model (v1.45.0; grown out of
   `forge-model.js`, v1.40.0).

   Until v1.45.0 the realm's timers were read in two places that never met.
   THE RITES listed them by turning and said whether each one actually turned;
   THE FORGE drew the five that ask the GPU box for a model on one UTC day, so the
   meetings over the single GPU could be SEEN. Two scenes, two shapes, one
   fact — and a rite re-timed in the Desk moved on one page while the other
   still read yesterday. They are one page now, and this is the model behind
   it: rite rows in, a drawable day out.

   The rules it keeps:

   * A rite's clock is `at` (`13:45`, `:35` hourly) when it has one, and
     otherwise the FIRST clock in the surveyor's own `when` prose — the same
     best-effort read `api/v2/manifest` already publishes to the Hub, so the
     Atlas's own page and the fleet's calendar cannot disagree about when a
     rite turns. The prose reading is marked (`lane.from === 'when'`, drawn as
     a dotted rule under the clock) and the sentence it was read out of is the
     row's own title, so a misread is checkable rather than authoritative.
   * A rite with no clock anywhere is LISTED, never drawn. Inventing a time
     for "every 7 days from the worker's last boot" would be the prettiest lie
     on the page, which is the thing THE RITES was rebuilt to stop telling.
   * A meeting is two lanes wanting the same forge at once. It is the only
     alarm the strip spends.

   Pure functions over rite rows — no DOM, no `A`, no fetch — so
   `tests/test_calendar_model.mjs` can pin the clock parsing, the day sets,
   the meeting finding and "what turns next" without a browser. calendar.js
   renders what this returns; card.js only asks calendar.js for HTML. */

export const DAY_MIN = 1440;

const DAY_NAMES = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const DAY_INDEX = { sun: 0, mon: 1, tue: 2, wed: 3, thu: 4, fri: 5, sat: 6 };
const ALL_DAYS = new Set([0, 1, 2, 3, 4, 5, 6]);

/** `13:45` → { hourly: false, minute: 825 } · `:35` → { hourly: true, minute: 35 }
    · anything else → null (the rite has no clock — on request, or "a week
    after boot" — and is listed, not drawn). A trailing `Z`/`UTC` is tolerated
    because that is how people write it; every clock here is UTC regardless. */
export function parseClock(at) {
  const s = String(at ?? '').trim().replace(/\s*(z|utc)$/i, '');
  let m = /^:(\d{1,2})$/.exec(s);
  if (m) { const min = +m[1]; return min < 60 ? { hourly: true, minute: min } : null; }
  m = /^(\d{1,2}):(\d{2})$/.exec(s);
  if (m) {
    const h = +m[1], mi = +m[2];
    return h < 24 && mi < 60 ? { hourly: false, minute: h * 60 + mi } : null;
  }
  return null;
}

/** `Mon–Fri`, `Sun`, `Sat, Sun`, `weekdays`, `weekend`; blank or unreadable =
    every day (an unreadable day list must never make a rite vanish). */
export function parseDays(days) {
  const s = String(days ?? '').trim().toLowerCase();
  if (!s) return new Set(ALL_DAYS);
  if (/^(daily|every ?day|all)$/.test(s)) return new Set(ALL_DAYS);
  if (/^weekdays?$/.test(s)) return new Set([1, 2, 3, 4, 5]);
  if (/^weekends?$/.test(s)) return new Set([0, 6]);
  const out = new Set();
  for (const part of s.split(/[,;/]|\band\b/)) {
    const tok = part.trim();
    if (!tok) continue;
    const range = /^([a-z]{3})[a-z]*\s*[-–—]\s*([a-z]{3})[a-z]*$/.exec(tok);
    if (range) {
      const a = DAY_INDEX[range[1]], b = DAY_INDEX[range[2]];
      if (a === undefined || b === undefined) return new Set(ALL_DAYS);
      for (let d = a; ; d = (d + 1) % 7) { out.add(d); if (d === b) break; }
      continue;
    }
    const one = DAY_INDEX[tok.slice(0, 3)];
    if (one === undefined || tok.length > 3 && !DAY_NAMES.some((n) => tok.startsWith(n.toLowerCase()))) {
      return new Set(ALL_DAYS);
    }
    out.add(one);
  }
  return out.size ? out : new Set(ALL_DAYS);
}

/** `13:00–01:00` → { from: 780, to: 60 } (wraps past midnight) · blank → null. */
export function parseWindow(between) {
  const s = String(between ?? '').trim();
  const m = /^(\d{1,2}):(\d{2})\s*[-–—]\s*(\d{1,2}):(\d{2})$/.exec(s);
  if (!m) return null;
  const from = +m[1] * 60 + +m[2], to = +m[3] * 60 + +m[4];
  if (from >= DAY_MIN || to >= DAY_MIN) return null;
  return { from, to };
}

/** Is minute-of-day `t` inside the window (wrap-aware, half-open)? */
export function inWindow(win, t) {
  if (!win) return true;
  if (win.from === win.to) return true;                 // a zero-width window means "all day"
  return win.from < win.to ? (t >= win.from && t < win.to) : (t >= win.from || t < win.to);
}

/** The rite's clock, and where it was read from.

    `at` is the machine field the Desk writes and the manifest publishes. Most
    of the realm's rites predate it and carry their hour only in `when` — "Sun
    03:00 UTC", "daily 02:00", "04:00 CDT the download host · 08:00 UTC the edge". Reading
    the FIRST clock out of that prose is what `api/v2/manifest.cadence_of()`
    already does to build the Hub's calendar, so doing it here too is what
    makes one realm have one day. `from` says which it was, and the row carries
    the sentence as its title either way: the prose stays the authority, the
    strip is a reading of it. */
export function clockOf(rite) {
  const direct = parseClock(rite?.at);
  if (direct) return { ...direct, from: 'at' };
  const m = /\b(\d{1,2}):(\d{2})\b/.exec(String(rite?.when ?? ''));
  if (!m) return null;
  const h = +m[1], mi = +m[2];
  if (h > 23 || mi > 59) return null;
  return { hourly: false, minute: h * 60 + mi, from: 'when' };
}

const _UNIT_MIN = { min: 1, minute: 1, m: 1, hour: 60, hr: 60, h: 60, day: 1440, d: 1440 };

/** How often an ever-turning rite turns, in minutes, read from its own prose:
    "every 5 min", "every 15 min", "~every 60 days". `null` when it says
    something a clock cannot hold ("on every save").

    A continuous rite has no hour to draw a block at, and the heartbeat's
    `expect_every` is a WATCHDOG threshold, not a cadence — an hour, for
    everything continuous — so drawing from it would put the same lie on five
    different rows. The prose is what the surveyor actually asserted. The
    renderer washes the whole track rather than combing 288 ticks across it:
    the claim is "always, this often", not "at :00, :05, …". */
export function everyOf(rite) {
  const m = /\bevery\s*(\d+)\s*(minutes?|mins?|hours?|hrs?|days?|[mhd])\b/i.exec(String(rite?.when ?? ''));
  if (!m) return null;
  const unit = _UNIT_MIN[m[2].toLowerCase().replace(/s$/, '')];
  return unit ? +m[1] * unit : null;
}

/** The days a rite turns on. `days` when set; otherwise, for a weekly rite,
    the weekday it names in its `when` ("Sun 04:15" turns on Sundays). A daily
    or continuous rite with no `days` turns every day, as it always did. */
export function daysOf(rite) {
  const declared = String(rite?.days ?? '').trim();
  if (declared) return parseDays(declared);
  if (String(rite?.cadence ?? '').toLowerCase() === 'weekly') {
    const m = /\b(sun|mon|tue|wed|thu|fri|sat)[a-z]*\b/i.exec(String(rite?.when ?? ''));
    if (m) return new Set([DAY_INDEX[m[1].toLowerCase()]]);
  }
  return new Set(ALL_DAYS);
}

/** What the rite runs on, as a tone the CSS colours: the 30B briefing model
    never fit the GPU box's 16 GB and runs partly on the CPU (heavy); a 14B call is the
    ordinary warm lane; a rite that asks no model at all is cold. */
export function toneOf(model) {
  const m = String(model ?? '').toLowerCase();
  if (!m) return 'cold';
  return /\b30b\b|30b-|32b|70b/.test(m) ? 'heavy' : 'warm';
}

const everyIn = (rite, ceiling) => {
  const every = everyOf(rite);
  return every && every <= ceiling ? every : null;
};

const HOLD_DEFAULT = 10;

/** One rite → one lane. `blocks` is empty for a rite with no clock. */
export function laneOf(rite, index = 0) {
  const clock = clockOf(rite);
  const hold = Math.max(1, Math.min(DAY_MIN, parseInt(rite.hold, 10) || HOLD_DEFAULT));
  const days = daysOf(rite);
  const win = parseWindow(rite.between);
  const blocks = [];
  if (clock && clock.hourly) {
    for (let h = 0; h < 24; h++) {
      const start = h * 60 + clock.minute;
      if (inWindow(win, start)) blocks.push({ start, end: Math.min(DAY_MIN, start + hold), hit: false });
    }
  } else if (clock) {
    blocks.push({ start: clock.minute, end: Math.min(DAY_MIN, clock.minute + hold), hit: false });
  }
  const cadence = String(rite.cadence || '').toLowerCase();
  return {
    index, key: rite.key || rite.name || `rite-${index}`, rite,
    name: rite.name || '—', host: rite.host || '', model: rite.model || '',
    asks: rite.asks || null, cadence,
    when: rite.when || '', note: rite.note || '', from: clock ? clock.from : null,
    tone: toneOf(rite.model), days, daysLabel: String(rite.days ?? '').trim(),
    hold, hourly: Boolean(clock && clock.hourly), window: win, blocks,
    /* An ever-turning rite has a rhythm instead of an hour. A rhythm longer
       than the day is not one — "~every 60 days" washed across today would
       claim it turns today, so it stays listed. */
    every: !clock && cadence === 'continuous' ? everyIn(rite, DAY_MIN) : null,
    /* … and a monthly one has an hour on a day this page does not model. Its
       block is drawn hollow: the hour is charted, the date is the rite's own
       ("1st, 02:00"), and pretending it turns every day would be the invention
       this page exists to refuse. */
    ghost: Boolean(clock) && cadence === 'monthly',
  };
}

function daysMeet(a, b) { for (const d of a) if (b.has(d)) return true; return false; }

/** Every pair of lanes whose blocks overlap, marking both blocks `hit`.

    `dow` null asks the standing question — "can these two ever collide?" —
    over any weekday the pair shares. A number asks it of one day only, which
    is what the drawn day needs: two lanes that meet on Mondays are not a
    meeting on the Sunday you are looking at. Same finder either way, so the
    day on the page and the standing answer can never drift apart. */
export function meetings(lanes, dow = null) {
  const hits = [];
  for (let i = 0; i < lanes.length; i++) {
    for (let j = i + 1; j < lanes.length; j++) {
      const a = lanes[i], b = lanes[j];
      if (dow === null ? !daysMeet(a.days, b.days) : !(a.days.has(dow) && b.days.has(dow))) continue;
      for (const x of a.blocks) {
        for (const y of b.blocks) {
          if (x.start < y.end && y.start < x.end) {
            x.hit = y.hit = true;
            hits.push({ at: Math.max(x.start, y.start), lanes: [a.name, b.name] });
          }
        }
      }
    }
  }
  hits.sort((p, q) => p.at - q.at);
  return hits;
}

/* fixed lanes in clock order, hourly ticks last — the ticks are the day's
   background, and a lane that starts at 00:35 would otherwise lead the list */
function byClock(p, q) {
  return (Number(p.hourly) - Number(q.hourly))
    || (p.blocks[0].start - q.blocks[0].start) || p.name.localeCompare(q.name);
}

/** The day for one asked place: the rites that name it (`asks`), as lanes,
    with every meeting marked. `hits` are pairs of lanes whose blocks overlap
    on a day they share — two rites wanting the forge at once. */
export function layoutForge(rites, nodeId) {
  const all = (rites || []).filter((r) => r && r.asks === nodeId).map((r, i) => laneOf(r, i));
  const lanes = all.filter((l) => l.blocks.length);
  const unclocked = all.filter((l) => !l.blocks.length);
  const hits = meetings(lanes);
  lanes.sort(byClock);
  return { lanes, unclocked, hits };
}

/* The order the day reads in. The forges come first — they are the contended
   thing, the only place a meeting can happen — and the rest by turning. The
   clockless close the page: present, listed, never drawn. */
const TURNINGS = [
  { key: 'daily', title: 'THE DAILY RITES', sub: 'what the realm does for itself every morning' },
  /* "THE SUNDAY RITES" was true of the list that never drew a day. Now that
     each row shows the weekday it actually keeps — three of the seven are
     Monday's — the old name is a caption contradicting the picture under it. */
  { key: 'weekly', title: 'THE WEEKLY RITES', sub: 'each on its own day of the week' },
  { key: 'monthly', title: 'THE MONTHLY RITES', sub: 'once around the moon' },
  { key: 'continuous', title: 'THE EVER-TURNING', sub: 'the realm’s pulse, minute by minute' },
];

/** THE CALENDAR's day: every rite of the realm laid on one clock.

    `dow` is the weekday being drawn (0 = Sunday, defaulting to today in UTC).
    Groups come back in reading order: one per place any rite `asks` for a
    model — the forge, where meetings happen — then the four turnings, then
    the rites with no clock at all. A lane keeps its place in its group
    whether or not it turns on `dow`; a weekly rite must be visible on the six
    days it does not run, or the page answers "nothing on Tuesday" when the
    truth is "nothing until Sunday". `lane.today` is what the row's strip
    draws, and `standing` is the forge's meetings across the whole week — the
    warning that survives stepping the day off the collision. */
export function layoutDay(rites, { dow = new Date().getUTCDay() } = {}) {
  const all = (rites || []).filter(Boolean).map((r, i) => laneOf(r, i));
  const groups = [];
  const asked = [];
  for (const lane of all) if (lane.asks && !asked.includes(lane.asks)) asked.push(lane.asks);
  const taken = new Set();
  for (const id of asked) {
    const mine = all.filter((l) => l.asks === id);
    mine.forEach((l) => taken.add(l));
    const clocked = mine.filter((l) => l.blocks.length).sort(byClock);
    groups.push({
      key: `forge:${id}`, kind: 'forge', place: id, title: null,   // the renderer names the place
      sub: 'one model, one queue — every rite that asks it, in turn',
      lanes: clocked.concat(mine.filter((l) => !l.blocks.length)),
      hits: meetings(clocked.filter((l) => l.days.has(dow)), dow),
      standing: meetings(clocked.map((l) => laneOf(l.rite, l.index))),
    });
  }
  for (const t of TURNINGS) {
    const mine = all.filter((l) => !taken.has(l) && l.cadence === t.key && (l.blocks.length || l.every));
    mine.forEach((l) => taken.add(l));
    if (!mine.length) continue;
    const clocked = mine.filter((l) => l.blocks.length).sort(byClock);
    groups.push({ ...t, kind: 'turning', hits: [], standing: [],
                  lanes: clocked.concat(mine.filter((l) => !l.blocks.length)) });
  }
  /* A rite with an hour but a cadence none of the four turnings names still
     has an hour. Grouping it with the clockless would say "this page cannot
     time it" about a rite that told us exactly when it turns — the quiet lie
     the whole page exists to refuse — so it gets a group of its own. */
  const odd = all.filter((l) => !taken.has(l) && (l.blocks.length || l.every));
  odd.forEach((l) => taken.add(l));
  if (odd.length) {
    groups.push({
      key: 'other', kind: 'turning', title: 'THE OTHER TURNINGS',
      sub: 'an hour charted, under no turning this page groups by',
      lanes: odd.sort(byClock), hits: [], standing: [],
    });
  }
  const rest = all.filter((l) => !taken.has(l));
  if (rest.length) {
    groups.push({
      key: 'unclocked', kind: 'listed', title: 'NOT ON THE CLOCK',
      sub: 'charted and watched, turning to no hour this page can draw',
      lanes: rest, hits: [], standing: [],
    });
  }
  /* `today` is set AFTER the meetings are found, because `meetings` marks the
     very block objects the strip draws — set it first and the outline would
     land on a copy nobody paints. */
  for (const lane of all) { lane.dow = dow; lane.today = lane.days.has(dow) ? lane.blocks : []; }
  return { dow, groups, lanes: all, hits: groups.flatMap((g) => g.hits),
           drawn: all.filter((l) => l.today.length || l.every) };
}

export const fmtClock = (min) => {
  const m = ((min % DAY_MIN) + DAY_MIN) % DAY_MIN;
  return `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`;
};

export const dayName = (d) => DAY_NAMES[((d % 7) + 7) % 7];

/** The next block to start after `now` (UTC), across up to a week of days.
    Returns { lane, start, dayOffset, inMin } or null when nothing is clocked. */
export function nextTurning(lanes, now = new Date()) {
  const nowMin = now.getUTCHours() * 60 + now.getUTCMinutes();
  const dow = now.getUTCDay();
  let best = null;
  for (let offset = 0; offset <= 7; offset++) {
    const day = (dow + offset) % 7;
    for (const lane of lanes) {
      if (!lane.days.has(day)) continue;
      for (const b of lane.blocks) {
        if (offset === 0 && b.start <= nowMin) continue;
        const inMin = offset * DAY_MIN + b.start - nowMin;
        if (!best || inMin < best.inMin) best = { lane, start: b.start, dayOffset: offset, inMin };
      }
    }
    if (best) return best;   // the first day with a candidate holds the soonest one
  }
  return null;
}
