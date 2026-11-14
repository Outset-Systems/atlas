/* OVERVIEW's rules, with no DOM (2026-11-13, the views' stage 3).

   OVERVIEW is one page of what only Atlas holds: places by state, what is
   down and what depends on it, events nobody has acknowledged, maintenance
   this week, certificates lapsing within 30 days, places nobody has checked,
   recent changes, whether each source answers, the map against its sources
   (an admin's), and the fullest address ranges. The server builds and
   redacts the facts (`GET api/v2/overview`); the ranges are worked out here
   from the dataset already in the browser, with the Addresses scene's own
   maths (ipam.js), so there is one way of counting an address.

   This file decides the order of the tiles, what each one says, and what it
   says when there is nothing to say: a tile never vanishes (the layout must
   not jump on a wall), and "could not be read" is never drawn as calm.
   overview.js draws; this file only words. Every visible phrase is a theme
   key with its plain fallback in OVERVIEW_TEXT, filled by a `t` the caller
   passes (overview.js passes one that reads the theme first).
   Unit-tested by tests/test_overview_model.mjs under plain node. */

import { chartedAddresses, countLabel, occupancy, prefixesOf } from './ipam.js';

/** Every visible string, by theme key, with its plain fallback. */
export const OVERVIEW_TEXT = {
  ov_sub: 'what the map knows, at a glance',
  ov_loading: 'Reading…',
  ov_failed: 'The overview could not be read: {why}',
  ov_stale: 'Not refreshed since {when}: {why}',
  ov_updated: 'as of {when}',
  ov_more: '+{n} more',
  ov_open: 'Open its card',
  ov_not_drawn: 'That place is not on the map yet. Try again in a moment.',

  ov_t_states: 'Places by state',
  ov_t_down: 'Down now',
  ov_t_unacked: 'Not acknowledged',
  ov_t_maintenance: 'Maintenance this week',
  ov_t_certs: 'Certificates within 30 days',
  ov_t_review: 'Not checked',
  ov_t_changes: 'Recent changes',
  ov_t_sources: 'Sources',
  ov_t_drift: 'Map against the sources',
  ov_t_ranges: 'Fullest address ranges',

  ov_state_healthy: 'Up',
  ov_state_degraded: 'Degraded',
  ov_state_down: 'Down',
  ov_state_maintenance: 'In maintenance',
  ov_state_slumbering: 'Asleep',
  ov_state_unknown: 'Not known',
  ov_states_none: 'There are no places on the map yet.',
  ov_states_all_one: 'The one place is up.',
  ov_states_all: 'All {total} places are up.',
  ov_states_down_one: '{n} of {total} places is down.',
  ov_states_down: '{n} of {total} places are down.',
  ov_states_degraded_one: 'No place is down; {n} of {total} is degraded.',
  ov_states_degraded: 'No place is down; {n} of {total} are degraded.',
  ov_states_unknown: 'The state of every place is not known yet.',
  ov_states_quiet: 'No place is down; {n} of {total} are up.',

  ov_down_none: 'Nothing is down.',
  ov_down_undeclared: 'Nothing is declared to depend on these.',
  ov_down_undeclared_it: 'Nothing is declared to depend on it.',
  ov_down_alone: 'Nothing depends on it.',
  ov_down_takes: 'Depends on it:',

  ov_unacked_none: 'Every event has been acknowledged.',
  ov_unacked_count_one: '1 event is waiting.',
  ov_unacked_count: '{n} events are waiting.',
  ov_unacked_open: 'Acknowledge in the ANNALS ›',
  ov_unacked_see: 'Read them in the ANNALS ›',

  ov_maint_none: 'No maintenance in the next 7 days.',
  ov_maint_now: 'now, until {end}',
  ov_maint_next: '{start} to {end}',

  ov_certs_none: 'No certificate lapses within 30 days.',
  ov_days_lapsed: 'lapsed',
  ov_days_today: 'today',
  ov_days_one: '1 day',
  ov_days: '{n} days',

  ov_review_none: 'Every place has been checked in the last 90 days.',
  ov_review_unchecked_one: '1 place is waiting to be checked.',
  ov_review_unchecked: '{n} places are waiting to be checked.',
  ov_review_stale_one: '1 place has not been checked in 90 days.',
  ov_review_stale: '{n} places have not been checked in 90 days.',
  ov_review_never: 'never checked',
  ov_review_ago: 'checked {n} days ago',

  ov_changes_none: 'No changes this week.',
  ov_changes_count_none: 'No place changed this week.',
  ov_changes_count_one: '1 place changed this week.',
  ov_changes_count: '{n} places changed this week.',

  ov_sources_ok: 'Every source is answering.',
  ov_sources_silent_one: '1 source is silent.',
  ov_sources_silent: '{n} sources are silent.',
  ov_sources_unset: 'No live source is set up; the map is all there is.',
  ov_source_ok: 'answering',
  ov_source_silent: 'silent',
  ov_source_last: 'last answered {when}',
  ov_source_never: 'has not answered',

  ov_drift_none: 'The map agrees with its sources.',
  ov_drift_one: '1 place differs from its sources.',
  ov_drift: '{n} places differ from their sources.',

  ov_ranges_loading: 'Reading the map…',
  ov_ranges_none: 'No address ranges are described yet.',
  ov_ranges_used: '{used} of {size}',
};

/** Fill `{name}` in a phrase from `vars`; an unknown name is left as written. */
export function fill(text, vars = {}) {
  return String(text ?? '').replace(/\{(\w+)\}/g, (m, k) => (k in vars ? String(vars[k]) : m));
}

/** The plain words, for a caller (and the tests) with no theme. */
export const plainT = (key, vars) => fill(OVERVIEW_TEXT[key] ?? key, vars);

/** The tiles, in the page's order. `drift` is an admin's and the server only
    sends it to one, so it is the one tile that may be absent. */
export const TILES = ['states', 'down', 'unacked', 'maintenance', 'certs', 'review',
  'changes', 'sources', 'drift', 'ranges'];

/** The tiles this answer draws, in order. Every tile but drift is always
    drawn, saying so when it has nothing to report, so the page never jumps. */
export function tileOrder(body) {
  const hasDrift = Boolean(body && typeof body === 'object'
    && Object.prototype.hasOwnProperty.call(body, 'drift') && body.drift);
  return TILES.filter((k) => k !== 'drift' || hasDrift);
}

/** The states, in the order NODES uses (worst first after up). */
export const STATES = ['healthy', 'degraded', 'down', 'maintenance', 'slumbering', 'unknown'];

const num = (v) => (Number.isFinite(Number(v)) && Number(v) > 0 ? Math.floor(Number(v)) : 0);
const list = (v) => (Array.isArray(v) ? v : []);

/** The state counts as rows for the big numbers: every state that has a
    place, in STATES order. */
export function stateRows(states) {
  const s = states || {};
  return STATES.map((state) => ({ state, n: num(s[state]) })).filter((r) => r.n > 0);
}

/** One plain sentence for the counts. */
export function stateSummary(states, t = plainT) {
  const s = states || {};
  const total = num(s.total) || STATES.reduce((sum, k) => sum + num(s[k]), 0);
  if (!total) return t('ov_states_none');
  const down = num(s.down);
  const degraded = num(s.degraded);
  const healthy = num(s.healthy);
  if (down) return t(down === 1 ? 'ov_states_down_one' : 'ov_states_down', { n: down, total });
  if (degraded) return t(degraded === 1 ? 'ov_states_degraded_one' : 'ov_states_degraded', { n: degraded, total });
  if (healthy >= total) return total === 1 ? t('ov_states_all_one') : t('ov_states_all', { total });
  if (num(s.unknown) >= total) return t('ov_states_unknown');
  return t('ov_states_quiet', { n: healthy, total });
}

/** Days to a certificate's end, in words: lapsed, today, 1 day, N days. */
export function daysPhrase(days, t = plainT) {
  if (typeof days !== 'number' || Number.isNaN(days)) return '';
  if (days < 0) return t('ov_days_lapsed');
  if (days === 0) return t('ov_days_today');
  if (days === 1) return t('ov_days_one');
  return t('ov_days', { n: Math.floor(days) });
}

/** A certificate's tone: 'down' at 7 days or fewer (lapsed too), 'warn' at
    30 or fewer, '' beyond that or when the days are not known. */
export function certClass(days) {
  if (typeof days !== 'number' || Number.isNaN(days)) return '';
  if (days <= 7) return 'down';
  if (days <= 30) return 'warn';
  return '';
}

/** The certificates, soonest first (a lapsed one at the top). */
export function certRows(certs, t = plainT) {
  return list(certs)
    .filter((c) => c && c.name)
    .map((c) => ({ ...c, phrase: daysPhrase(c.days, t), tone: certClass(c.days) }))
    .sort((a, b) => (num1(a.days) - num1(b.days)) || String(a.name).localeCompare(String(b.name)));
}
const num1 = (v) => (typeof v === 'number' && !Number.isNaN(v) ? v : Infinity);

/** What is down, each with what depends on it. When nothing declares a
    dependency for any of them, the tile says so once (`note`) instead of
    leaving the reader to wonder whether the walk ran. */
export function downTile(down, t = plainT) {
  const items = list(down).filter((d) => d && d.id);
  const allUndeclared = items.length > 0 && items.every((d) => !d.declared);
  return {
    empty: items.length === 0 ? t('ov_down_none') : '',
    note: allUndeclared ? t('ov_down_undeclared') : '',
    items: items.map((d) => {
      const downstream = list(d.downstream).filter((x) => x && x.id);
      let line = '';
      if (!d.declared) line = allUndeclared ? '' : t('ov_down_undeclared_it');
      else if (!downstream.length) line = t('ov_down_alone');
      // the server names a cause only when it is the place itself (a root):
      // another place's fallout is listed under that place, not here
      const cause = d.cause && d.cause !== d.id ? String(d.cause) : '';
      return { id: d.id, name: d.name || d.id, state: d.state || 'down', cause,
               downstream, line, takes: downstream.length ? t('ov_down_takes') : '' };
    }),
  };
}

/** "3m ago" from a stamp, or '' when it is not one. The app-wide shape
    (config.js `ago`), kept here so the tests need no document. */
export function agoPhrase(iso, now = Date.now()) {
  const at = Date.parse(iso);
  if (!iso || Number.isNaN(at)) return '';
  const s = Math.max(0, Math.round((now - at) / 1000));
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

/** A moment in UTC, to the minute: "2026-11-14 02:00 UTC". */
export function utcPhrase(iso) {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? String(iso ?? '') : `${d.toISOString().slice(0, 16).replace('T', ' ')} UTC`;
}

/** The events nobody has acknowledged: a count line and the rows. */
export function unackedTile(unacked, t = plainT, now = Date.now()) {
  const u = unacked || {};
  const items = list(u.items).filter((e) => e && (e.id !== undefined && e.id !== null));
  const count = Math.max(num(u.count), items.length);
  return {
    count,
    empty: count === 0 ? t('ov_unacked_none') : '',
    line: count === 0 ? '' : t(count === 1 ? 'ov_unacked_count_one' : 'ov_unacked_count', { n: count }),
    items: items.map((e) => ({
      id: e.id, kind: e.kind || '', target: e.target || '', name: e.name || e.target || '',
      move: e.from && e.to ? `${e.from} → ${e.to}` : (e.to || e.from || e.kind || ''),
      when: agoPhrase(e.at, now),
    })),
    more: Math.max(0, count - items.length),
  };
}

/** The windows in the next 7 days: open ones first, then by start. */
export function maintenanceTile(windows, t = plainT) {
  const items = list(windows).filter((w) => w && (w.window || w.reason))
    .slice()
    .sort((a, b) => (Number(Boolean(b.now)) - Number(Boolean(a.now)))
      || String(a.starts || '').localeCompare(String(b.starts || '')));
  return {
    empty: items.length === 0 ? t('ov_maint_none') : '',
    items: items.map((w) => ({
      window: w.window || '', reason: w.reason || w.window || '', now: Boolean(w.now),
      when: w.now ? t('ov_maint_now', { end: utcPhrase(w.ends) })
                  : t('ov_maint_next', { start: utcPhrase(w.starts), end: utcPhrase(w.ends) }),
      places: list(w.places).filter((p) => p && p.id),
    })),
  };
}

/** Places nobody has checked: waiting to be checked (never, or changed by
    an import since), or not in 90 days. The two counts can share places, so
    they are said apart and never added; the rows are the 90-day ones. */
export function reviewTile(review, t = plainT, now = Date.now()) {
  const r = review || {};
  const unchecked = num(r.unchecked);
  const stale = num(r.stale);
  const lines = [];
  if (unchecked) lines.push(t(unchecked === 1 ? 'ov_review_unchecked_one' : 'ov_review_unchecked', { n: unchecked }));
  if (stale) lines.push(t(stale === 1 ? 'ov_review_stale_one' : 'ov_review_stale', { n: stale }));
  const items = list(r.items).filter((x) => x && x.id).map((x) => {
    const at = Date.parse(x.reviewed_at);
    const days = x.reviewed_at && !Number.isNaN(at) ? Math.floor((now - at) / 86400000) : null;
    return { id: x.id, name: x.name || x.id,
             when: days === null ? t('ov_review_never') : t('ov_review_ago', { n: days }) };
  });
  return {
    empty: !unchecked && !stale && !items.length ? t('ov_review_none') : '',
    lines,
    items,
    count: Math.max(unchecked, stale),
    more: Math.max(0, stale - items.length),
  };
}

/** Recent changes. An admin gets who did what; anyone else only a count,
    since a change names a person. */
export function changesTile(changes, t = plainT, now = Date.now()) {
  const c = changes || {};
  if (Array.isArray(c.items)) {
    const items = c.items.filter(Boolean).map((x) => ({
      summary: x.summary || '', by: x.by || '', when: agoPhrase(x.at, now),
    }));
    return { admin: true, empty: items.length ? '' : t('ov_changes_none'), line: '', items };
  }
  const n = num(c.count_7d);
  return {
    admin: false, empty: '', items: [],
    line: t(n === 0 ? 'ov_changes_count_none' : n === 1 ? 'ov_changes_count_one' : 'ov_changes_count', { n }),
  };
}

/** Whether the sources answer. Everyone gets the sentence; an admin also
    gets each source by name (the server sends no names to anyone else). */
export function sourcesTile(sources, admin = false, t = plainT, now = Date.now()) {
  const s = sources || {};
  const items = list(s.items).filter((x) => x && x.name);
  const silent = Math.max(num(s.silent), items.filter((x) => !x.ok).length);
  let line;
  if (silent) line = t(silent === 1 ? 'ov_sources_silent_one' : 'ov_sources_silent', { n: silent });
  else if (admin && !items.length) line = t('ov_sources_unset');
  else line = t('ov_sources_ok');
  return {
    tone: silent ? 'warn' : '',
    line,
    items: items.map((x) => ({
      name: x.name, ok: Boolean(x.ok),
      state: x.ok ? t('ov_source_ok') : t('ov_source_silent'),
      when: x.last_ok ? t('ov_source_last', { when: agoPhrase(x.last_ok, now) }) : t('ov_source_never'),
    })).sort((a, b) => (Number(a.ok) - Number(b.ok)) || a.name.localeCompare(b.name)),
  };
}

/** The map against its sources (an admin's): a count and the names. */
export function driftTile(drift, t = plainT) {
  const d = drift || {};
  const names = list(d.items).map((x) => (typeof x === 'string' ? x : x?.name || x?.id || '')).filter(Boolean);
  const n = Math.max(num(d.count), names.length);
  return {
    tone: n ? 'warn' : '',
    line: n === 0 ? t('ov_drift_none') : t(n === 1 ? 'ov_drift_one' : 'ov_drift', { n }),
    items: names,
    more: Math.max(0, n - names.length),
  };
}

/** The fullest address ranges in the dataset, worked out with the Addresses
    scene's own maths: every range that holds its own addresses (one split
    into smaller ranges is counted in them, as `freeV4` does), fullest first,
    ties to the one with more in use, then by address. `null` data (the map
    is not read yet) gives null, which the page says as "reading". */
export function fullestRanges(data, n = 5) {
  if (!data || typeof data !== 'object') return null;
  const prefixes = prefixesOf(data);
  const charted = chartedAddresses(data);
  const rows = [];
  for (const p of prefixes) {
    if (p.children?.length) continue;
    const o = occupancy(p, charted);
    if (o.total <= 0n) continue;
    rows.push({
      name: p.name || p.description || p.cidr,
      cidr: p.cidr,
      used: Number(o.used),
      size: Number(o.total),
      sizeLabel: countLabel(o.total),
      usedLabel: countLabel(o.used),
      pct: o.percent,
      order: p.net.network,
      version: p.net.version,
    });
  }
  rows.sort((a, b) => (b.pct - a.pct) || (b.used - a.used) || (a.version - b.version)
    || (a.order < b.order ? -1 : a.order > b.order ? 1 : 0));
  return rows.slice(0, n).map(({ order, version, ...r }) => r);
}

/** The ranges tile's words. */
export function rangesTile(ranges, t = plainT) {
  if (ranges === null || ranges === undefined) return { empty: t('ov_ranges_loading'), items: [], loading: true };
  return {
    empty: ranges.length ? '' : t('ov_ranges_none'),
    items: ranges.map((r) => ({ ...r, line: t('ov_ranges_used', { used: r.usedLabel ?? r.used, size: r.sizeLabel ?? r.size }),
                               tone: r.pct >= 90 ? 'down' : r.pct >= 75 ? 'warn' : '' })),
  };
}

/** At most `cap` rows on a wall, and how many more there are. */
export function capped(items, cap = 6) {
  const all = list(items);
  return { shown: all.slice(0, cap), more: Math.max(0, all.length - cap) };
}
