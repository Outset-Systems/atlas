
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
  ov_t_favin: 'Favourites · internal',
  ov_t_favout: 'Favourites · external',

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

  ov_face_list: 'Watch list',
  ov_face_chart: 'Chart table',
  ov_faces: 'Two ways to read it',
  ov_wants_none: 'Nothing wants you.',
  ov_quiet_lead: 'All quiet:',
  ov_more_nodes: '+{n} more in NODES ›',
  ov_more_chart: '+{n} more on the chart table ›',
  ov_chart_alt: 'The map, each place lit by its state',
  ov_chart_off_one: '1 place is not drawn on this map.',
  ov_chart_off: '{n} places are not drawn on this map.',
  ov_doors: 'Doors',

  ov_fav_none: 'No favourites yet.',
  ov_page_prev: 'The favourites before these',
  ov_page_next: 'The next favourites',
  ov_page_of: '{n} of {m}',
  ov_fav_how: 'Mark a service as a favourite in the map editor, under its place.',

  ov_face_critical: 'Critical',
  ov_face_critical_n: 'Critical {n}',
  ov_crit_title: 'Critical · last {n} days',
  ov_crit_windows: 'How far back',
  ov_crit_days: '{n} days',
  ov_crit_none: 'Nothing critical in {n} days.',
  ov_crit_none_since: 'Nothing critical since {date}.',
  ov_crit_since: 'The annals reach back only to {date}.',
  ov_crit_count_one: '1 critical alert, on 1 thing.',
  ov_crit_count: '{n} critical alerts, on {m} things.',
  ov_crit_count_one_thing: '{n} critical alerts, all on 1 thing.',
  ov_crit_open_one: '1 is still down.',
  ov_crit_open: '{n} are still down.',
  ov_crit_open_none: 'Every one has cleared.',
  ov_crit_trips_one: '1 trip is open.',
  ov_crit_trips: '{n} trips are open.',
  ov_crit_down: 'still down',
  ov_crit_cleared: 'cleared',
  ov_crit_eased: 'now {state}',
  ov_crit_unknown: 'not known',
  ov_crit_open_trip: 'open',
  ov_crit_acked: 'acknowledged',
  ov_crit_went: 'went down {when}',
  ov_crit_tripped: 'tripped {when}',
  ov_crit_after: 'cleared after {dur}',
  ov_crit_after_to: '{state} after {dur}',
  ov_crit_times: '{n} times',
  ov_crit_unwatched: 'no longer watched',
  ov_crit_kind_node: 'place',
  ov_crit_kind_service: 'service',
  ov_crit_kind_rite: 'job',
  ov_crit_kind_tripwire: 'tripwire',
  ov_more_annals: '+{n} more in the ANNALS ›',
  ov_crit_annals: 'Read them in the ANNALS ›',

  ov_notes: 'Open {vault}’s home note in Obsidian',
};

export function fill(text, vars = {}) {
  return String(text ?? '').replace(/\{(\w+)\}/g, (m, k) => (k in vars ? String(vars[k]) : m));
}

export const plainT = (key, vars) => fill(OVERVIEW_TEXT[key] ?? key, vars);

export const FACES = ['list', 'chart', 'critical'];

export function faceOr(stored) {
  return FACES.includes(stored) ? stored : FACES[0];
}

export function faceStep(face, step) {
  const i = Math.max(0, FACES.indexOf(face)) + (step > 0 ? 1 : step < 0 ? -1 : 0);
  return FACES[Math.min(FACES.length - 1, Math.max(0, i))];
}

export function cutOrder(stacked) {
  return stacked ? ['watch', 'doors'] : ['doors', 'watch'];
}

export function pageSlice(total, fits, page = 0) {
  const n = Math.max(0, Math.floor(total) || 0);
  const k = Math.max(1, Math.floor(fits) || 1);
  const pages = Math.max(1, Math.ceil(n / k));
  const p = (((Math.floor(page) || 0) % pages) + pages) % pages;
  return { page: p, pages, start: p * k, end: Math.min(n, p * k + k) };
}

export const FAV_CAP = 8;

export const STATES = ['healthy', 'degraded', 'down', 'maintenance', 'slumbering', 'unknown'];

const num = (v) => (Number.isFinite(Number(v)) && Number(v) > 0 ? Math.floor(Number(v)) : 0);
const list = (v) => (Array.isArray(v) ? v : []);

export function stateRows(states) {
  const s = states || {};
  return STATES.map((state) => ({ state, n: num(s[state]) })).filter((r) => r.n > 0);
}

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

export function daysPhrase(days, t = plainT) {
  if (typeof days !== 'number' || Number.isNaN(days)) return '';
  if (days < 0) return t('ov_days_lapsed');
  if (days === 0) return t('ov_days_today');
  if (days === 1) return t('ov_days_one');
  return t('ov_days', { n: Math.floor(days) });
}

export function certClass(days) {
  if (typeof days !== 'number' || Number.isNaN(days)) return '';
  if (days <= 7) return 'down';
  if (days <= 30) return 'warn';
  return '';
}

export function certRows(certs, t = plainT) {
  return list(certs)
    .filter((c) => c && c.name)
    .map((c) => ({ ...c, phrase: daysPhrase(c.days, t), tone: certClass(c.days) }))
    .sort((a, b) => (num1(a.days) - num1(b.days)) || String(a.name).localeCompare(String(b.name)));
}
const num1 = (v) => (typeof v === 'number' && !Number.isNaN(v) ? v : Infinity);

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
      const cause = d.cause && d.cause !== d.id ? String(d.cause) : '';
      return { id: d.id, name: d.name || d.id, state: d.state || 'down', cause,
               downstream, line, takes: downstream.length ? t('ov_down_takes') : '' };
    }),
  };
}

export function agoPhrase(iso, now = Date.now()) {
  const at = Date.parse(iso);
  if (!iso || Number.isNaN(at)) return '';
  const s = Math.max(0, Math.round((now - at) / 1000));
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

export function utcPhrase(iso) {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? String(iso ?? '') : `${d.toISOString().slice(0, 16).replace('T', ' ')} UTC`;
}

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
      url: webUrl(x.url), openIn: x.open_in || 'auto',
    })).sort((a, b) => (Number(a.ok) - Number(b.ok)) || a.name.localeCompare(b.name)),
  };
}

export function webUrl(url) {
  return typeof url === 'string' && /^https?:\/\//i.test(url.trim()) ? url.trim() : '';
}

export function favTile(list_, admin = false, t = plainT) {
  const items = list(list_).filter((x) => x && webUrl(x.url)).map((x) => {
    let host = '';
    try { host = new URL(webUrl(x.url)).host; } catch {   }
    return { label: x.label || host || x.url, url: webUrl(x.url), host,
             openIn: x.open_in || 'auto', place: x.place && x.place.id ? x.place : null };
  });
  return {
    empty: items.length ? '' : t('ov_fav_none'),
    how: items.length || !admin ? '' : t('ov_fav_how'),
    items,
  };
}


const RANK = { down: 0, warn: 1, '': 2 };

export function watchList(b, t = plainT, now = Date.now()) {
  if (!b || typeof b !== 'object') return [];
  const out = [];
  const d = downTile(b.down, t);
  for (const x of d.items) {
    const deps = x.downstream.map((p) => p.name || p.id).join(', ');
    out.push({
      key: `place:${x.id}`, tone: x.state === 'down' ? 'down' : 'warn', state: x.state,
      name: x.name, place: { id: x.id, name: x.name },
      word: t(`ov_state_${x.state}`),
      detail: deps ? `${x.takes} ${deps}` : (x.line || d.note || ''),
    });
  }
  for (const c of certRows(b.certs, t)) {
    out.push({
      key: `cert:${c.name}`, tone: c.tone, state: c.tone === 'down' ? 'down' : 'degraded',
      name: c.name, mono: true, place: c.place || null, word: c.phrase,
      detail: c.place ? (c.place.name || c.place.id) : '',
    });
  }
  const s = sourcesTile(b.sources, Boolean(b.admin), t, now);
  if (s.tone) {
    const silent = s.items.filter((x) => !x.ok);
    for (const x of silent) {
      out.push({ key: `source:${x.name}`, tone: 'warn', state: 'down', name: x.name, mono: true,
                 place: null, word: x.state, detail: x.when, url: x.url, openIn: x.openIn });
    }
    if (!silent.length) {
      out.push({ key: 'sources', tone: 'warn', state: 'down', name: t('ov_t_sources'),
                 place: null, word: '', detail: s.line });
    }
  }
  const u = unackedTile(b.unacked, t, now);
  if (!u.empty) {
    const first = u.items[0];
    out.push({
      key: 'unacked', tone: 'warn', state: 'degraded', name: t('ov_t_unacked'), place: null,
      word: String(u.count), go: 'annals',
      detail: first ? `${u.line} ${[first.name, first.move, first.when].filter(Boolean).join(' ')}` : u.line,
    });
  }
  for (const w of maintenanceTile(b.maintenance, t).items) {
    out.push({
      key: `maint:${w.window || w.reason}`, tone: w.now ? 'warn' : '', state: 'maintenance',
      name: w.reason, plain: true, place: w.places[0] || null, word: w.when,
      detail: w.places.map((p) => p.name || p.id).join(', '),
    });
  }
  const r = reviewTile(b.review, t, now);
  if (!r.empty) {
    out.push({
      key: 'review', tone: '', state: 'unknown', name: t('ov_t_review'), place: null,
      word: String(r.count), go: 'nodes',
      detail: [r.lines.join(' '), r.items.map((x) => x.name).join(', ')].filter(Boolean).join(' '),
    });
  }
  const c = changesTile(b.changes, t, now);
  const changed = c.admin ? c.items.length : num(b.changes?.count_7d);
  if (changed) {
    const first = c.items[0];
    out.push({
      key: 'changes', tone: '', state: 'unknown', name: t('ov_t_changes'), place: null,
      word: String(changed),
      detail: c.admin ? [first.summary, first.by, first.when].filter(Boolean).join(' · ') : c.line,
    });
  }
  return out.map((x, i) => ({ x, i }))
    .sort((a, z) => (RANK[a.x.tone] - RANK[z.x.tone]) || (a.i - z.i))
    .map(({ x }) => x);
}


export const CRITICAL_WINDOWS = [7, 30];

export function windowOr(stored) {
  const n = Number(stored);
  return CRITICAL_WINDOWS.includes(n) ? n : CRITICAL_WINDOWS[CRITICAL_WINDOWS.length - 1];
}

export function spanPhrase(from, to) {
  const a = Date.parse(from), z = Date.parse(to);
  if (Number.isNaN(a) || Number.isNaN(z) || z < a) return '';
  const s = Math.round((z - a) / 1000);
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.round(s / 60)}m`;
  if (s < 86400) return `${Math.round(s / 3600)}h`;
  return `${Math.round(s / 86400)}d`;
}

function standing(e, t) {
  switch (e.status) {
    case 'down': return { state: 'down', tone: 'down', word: t('ov_crit_down') };
    case 'open': return { state: 'down', tone: 'down', word: t('ov_crit_open_trip') };
    case 'acknowledged': return { state: 'healthy', tone: '', word: t('ov_crit_acked') };
    case 'cleared':
      return e.after && e.after !== 'healthy' && e.after !== 'down'
        ? { state: e.after, tone: e.after === 'degraded' ? 'warn' : '',
            word: t('ov_crit_eased', { state: t(`ov_state_${e.after}`).toLowerCase() }) }
        : { state: 'healthy', tone: '', word: t('ov_crit_cleared') };
    default: return { state: 'unknown', tone: '', word: t('ov_crit_unknown') };
  }
}

export function criticalTile(c, days = 30, t = plainT, now = Date.now()) {
  const none = { rows: [], lines: [], empty: '', note: '', count: 0 };
  if (!c || typeof c !== 'object') return none;
  const edge = now - days * 86400000;
  const since = Date.parse(c.since);
  const cut = !Number.isNaN(since) && since > edge;
  const note = cut ? t('ov_crit_since', { date: utcPhrase(c.since).slice(0, 10) }) : '';
  const items = list(c.items)
    .filter((e) => e && e.kind && Date.parse(e.at) >= edge)
    .sort((a, z) => Date.parse(z.at) - Date.parse(a.at));
  const rows = [];
  const byKey = new Map();
  for (const e of items) {
    const key = `crit:${e.kind}:${e.target}`;
    const seen = byKey.get(key);
    if (seen) { seen.n += 1; continue; }
    const how = standing(e, t);
    const went = t(e.kind === 'tripwire' ? 'ov_crit_tripped' : 'ov_crit_went', { when: agoPhrase(e.at, now) });
    const dur = spanPhrase(e.at, e.cleared_at);
    let after = '';
    if (e.status === 'cleared' && dur) {
      after = how.state === 'healthy' ? t('ov_crit_after', { dur })
        : t('ov_crit_after_to', { state: t(`ov_state_${e.after}`).toLowerCase(), dur });
    } else if (e.status === 'unknown') after = t('ov_crit_unwatched');
    const row = {
      key, ...how, status: e.status, name: e.name || e.target, kind: e.kind,
      kindWord: t(`ov_crit_kind_${e.kind}`) || e.kind,
      place: e.place && e.place.id ? e.place : null,
      at: e.at, when: utcPhrase(e.at), went, after, n: 1,
    };
    byKey.set(key, row);
    rows.push(row);
  }
  for (const r of rows) {
    r.detail = [r.kind === 'service' && r.place ? (r.place.name || r.place.id) : r.kindWord,
      r.went, r.after, r.n > 1 ? t('ov_crit_times', { n: r.n }) : ''].filter(Boolean).join(' · ');
  }
  if (!rows.length) {
    return { ...none, note: '', empty: cut ? t('ov_crit_none_since', { date: utcPhrase(c.since).slice(0, 10) })
      : t('ov_crit_none', { n: days }) };
  }
  const still = rows.filter((r) => r.status === 'down').length;
  const trips = rows.filter((r) => r.status === 'open').length;
  const count = items.length;
  const lines = [
    count === 1 ? t('ov_crit_count_one')
      : rows.length === 1 ? t('ov_crit_count_one_thing', { n: count })
        : t('ov_crit_count', { n: count, m: rows.length }),
  ];
  if (still) lines.push(t(still === 1 ? 'ov_crit_open_one' : 'ov_crit_open', { n: still }));
  if (trips) lines.push(t(trips === 1 ? 'ov_crit_trips_one' : 'ov_crit_trips', { n: trips }));
  if (!still && !trips) lines.push(t('ov_crit_open_none'));
  return { rows, lines, empty: '', note, count };
}

export function criticalCount(c, days = 30, now = Date.now()) {
  return criticalTile(c, days, plainT, now).rows.length;
}

export function notesLink(home, root, obsidianHref) {
  const path = typeof home === 'string' ? home.trim() : '';
  if (!path || typeof obsidianHref !== 'function') return null;
  const href = obsidianHref(path, String(root || ''));
  const m = /[?&]vault=([^&]+)/.exec(href);
  const folder = path.replace(/[\\/][^\\/]*$/, '').split(/[\\/]/).filter(Boolean).pop() || '';
  return { href, vault: m ? decodeURIComponent(m[1]) : folder };
}

export function quietLine(b, t = plainT, now = Date.now(), days = 30) {
  if (!b || typeof b !== 'object') return [];
  const out = [];
  const push = (text) => { if (text) out.push(String(text).replace(/[.]$/, '')); };
  push(downTile(b.down, t).empty);
  push(criticalTile(b.critical, days, t, now).empty);
  push(unackedTile(b.unacked, t, now).empty);
  push(maintenanceTile(b.maintenance, t).empty);
  if (!certRows(b.certs, t).length) push(t('ov_certs_none'));
  push(reviewTile(b.review, t, now).empty);
  const c = changesTile(b.changes, t, now);
  if (c.admin) push(c.empty);
  else if (num(b.changes?.count_7d) === 0) push(c.line);
  const s = sourcesTile(b.sources, Boolean(b.admin), t, now);
  if (!s.tone) push(s.line);
  return out;
}

export function worstTone(rows) {
  const all = list(rows);
  if (all.some((x) => x.tone === 'down')) return 'down';
  return all.some((x) => x.tone === 'warn') ? 'warn' : '';
}

export function chartLamps(places, states = {}, rows = []) {
  const named = new Set(list(rows).map((r) => r.place?.id).filter(Boolean));
  const lamps = [];
  let off = 0;
  for (const p of list(places)) {
    if (!p || !p.id) continue;
    const x = Number(p.x), y = Number(p.y);
    if (p.off || !Number.isFinite(x) || !Number.isFinite(y)) { off++; continue; }
    lamps.push({ id: p.id, name: p.name || p.id, x: Math.min(100, Math.max(0, x)),
                 y: Math.min(100, Math.max(0, y)), state: (states || {})[p.id] || 'unknown',
                 named: named.has(p.id) });
  }
  lamps.sort((a, z) => Number(a.named) - Number(z.named));
  return { lamps, off };
}

export function capped(items, cap = 6) {
  const all = list(items);
  return { shown: all.slice(0, cap), more: Math.max(0, all.length - cap) };
}
