
export const DAY_MIN = 1440;

const DAY_NAMES = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const DAY_INDEX = { sun: 0, mon: 1, tue: 2, wed: 3, thu: 4, fri: 5, sat: 6 };
const ALL_DAYS = new Set([0, 1, 2, 3, 4, 5, 6]);

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

export function parseWindow(between) {
  const s = String(between ?? '').trim();
  const m = /^(\d{1,2}):(\d{2})\s*[-–—]\s*(\d{1,2}):(\d{2})$/.exec(s);
  if (!m) return null;
  const from = +m[1] * 60 + +m[2], to = +m[3] * 60 + +m[4];
  if (from >= DAY_MIN || to >= DAY_MIN) return null;
  return { from, to };
}

export function inWindow(win, t) {
  if (!win) return true;
  if (win.from === win.to) return true;
  return win.from < win.to ? (t >= win.from && t < win.to) : (t >= win.from || t < win.to);
}

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

export function everyOf(rite) {
  const m = /\bevery\s*(\d+)\s*(minutes?|mins?|hours?|hrs?|days?|[mhd])\b/i.exec(String(rite?.when ?? ''));
  if (!m) return null;
  const unit = _UNIT_MIN[m[2].toLowerCase().replace(/s$/, '')];
  return unit ? +m[1] * unit : null;
}

export function daysOf(rite) {
  const declared = String(rite?.days ?? '').trim();
  if (declared) return parseDays(declared);
  if (String(rite?.cadence ?? '').toLowerCase() === 'weekly') {
    const m = /\b(sun|mon|tue|wed|thu|fri|sat)[a-z]*\b/i.exec(String(rite?.when ?? ''));
    if (m) return new Set([DAY_INDEX[m[1].toLowerCase()]]);
  }
  return new Set(ALL_DAYS);
}

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
    every: !clock && cadence === 'continuous' ? everyIn(rite, DAY_MIN) : null,
    ghost: Boolean(clock) && cadence === 'monthly',
  };
}

function daysMeet(a, b) { for (const d of a) if (b.has(d)) return true; return false; }

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

function byClock(p, q) {
  return (Number(p.hourly) - Number(q.hourly))
    || (p.blocks[0].start - q.blocks[0].start) || p.name.localeCompare(q.name);
}

export function layoutForge(rites, nodeId) {
  const all = (rites || []).filter((r) => r && r.asks === nodeId).map((r, i) => laneOf(r, i));
  const lanes = all.filter((l) => l.blocks.length);
  const unclocked = all.filter((l) => !l.blocks.length);
  const hits = meetings(lanes);
  lanes.sort(byClock);
  return { lanes, unclocked, hits };
}

const TURNINGS = [
  { key: 'daily', title: 'THE DAILY RITES', sub: 'what the lab does for itself every morning' },
  { key: 'weekly', title: 'THE WEEKLY RITES', sub: 'each on its own day of the week' },
  { key: 'monthly', title: 'THE MONTHLY RITES', sub: 'once around the moon' },
  { key: 'continuous', title: 'THE EVER-TURNING', sub: 'the lab’s pulse, minute by minute' },
];

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
      key: `forge:${id}`, kind: 'forge', place: id, title: null,
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
  for (const lane of all) { lane.today = lane.days.has(dow) ? lane.blocks : []; }
  return { groups, lanes: all, hits: groups.flatMap((g) => g.hits),
           drawn: all.filter((l) => l.today.length || l.every) };
}

export const fmtClock = (min) => {
  const m = ((min % DAY_MIN) + DAY_MIN) % DAY_MIN;
  return `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`;
};

export const dayName = (d) => DAY_NAMES[((d % 7) + 7) % 7];

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
    if (best) return best;
  }
  return null;
}


export function every(seconds) {
  if (!seconds) return '';
  if (seconds % 604800 === 0) return `every ${seconds / 604800}w`;
  if (seconds % 86400 === 0) return `every ${seconds / 86400}d`;
  if (seconds % 3600 === 0) return `every ${seconds / 3600}h`;
  return `every ${Math.round(seconds / 60)}m`;
}

export function clockPhrase(lane) {
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

export function inWords(min) {
  if (min < 60) return `${min}m`;
  const h = Math.floor(min / 60), m = min % 60;
  if (h < 24) return m ? `${h}h ${m}m` : `${h}h`;
  const d = Math.floor(h / 24);
  return `${d}d ${h % 24}h`;
}

export const isSilent = (verdict) => ['missed', 'failed'].includes(verdict);

export const offDay = (lane) => Boolean(lane.blocks.length && !lane.today.length && !lane.every);

export function foldDay(group) {
  const loud = (l) => isSilent(l.rite?.verdict) || l.rite?.verdict === 'late';
  const folds = group.kind === 'listed' ? (l) => !loud(l) : (l) => offDay(l) && !loud(l);
  return {
    shown: group.lanes.filter((l) => !folds(l)),
    folded: group.lanes.filter(folds),
  };
}

export function weekOf(rites, date) {
  const sinceMonday = (date.getUTCDay() + 6) % 7;
  const out = [];
  for (let i = 0; i < 7; i++) {
    const d = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate() - sinceMonday + i));
    const view = layoutDay(rites, { dow: d.getUTCDay() });
    out.push({ date: d, iso: d.toISOString().slice(0, 10), dow: d.getUTCDay(),
               drawn: view.drawn.length, hits: view.hits.length });
  }
  return out;
}

export function tally(rites) {
  const t = { total: 0, kept: 0, late: 0, silent: 0, awaited: 0, unwatched: 0 };
  for (const r of rites || []) {
    t.total++;
    if (isSilent(r.verdict)) t.silent++;
    else if (r.verdict === 'kept') t.kept++;
    else if (r.verdict === 'late') t.late++;
    else if (r.verdict === 'awaited') t.awaited++;
    else t.unwatched++;
  }
  return t;
}

export function nextParts(next, now) {
  return {
    clock: fmtClock(next.start),
    day: next.dayOffset ? dayName(now.getUTCDay() + next.dayOffset) : '',
    wait: inWords(next.inMin),
  };
}
