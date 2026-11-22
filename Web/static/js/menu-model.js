
import { serviceKey } from './alerts-model.js';

export const KINDS = ['place', 'service', 'collection'];

export const STATES = ['healthy', 'degraded', 'down', 'maintenance', 'slumbering', 'unknown', 'unmanaged'];

const SAME = (key) => ({ place: key, service: key });

export const ACTIONS = [
  { act: 'watched', line: true, words: SAME('nodes_menu_watched') },
  { act: 'last', line: true, words: SAME('nodes_menu_last') },
  { act: 'schedule', words: { ...SAME('nodes_menu_schedule'), collection: 'nodes_rail_schedule' } },
  {
    act: 'mode', way: true,
    on: { ...SAME('nodes_menu_mode_on'), collection: 'nodes_rail_mode_on' },
    off: { ...SAME('nodes_menu_mode_off'), collection: 'nodes_rail_mode_off' },
    notes: [['via', SAME('nodes_menu_mode_via')], ['place', { service: 'nodes_svc_mode_place' }]],
  },
  {
    act: 'unmanaged', way: true,
    on: { ...SAME('nodes_menu_unmanaged_on'), collection: 'nodes_rail_unmanaged_on' },
    off: { ...SAME('nodes_menu_unmanaged_off'), collection: 'nodes_rail_unmanaged_off' },
    notes: [['place', { service: 'nodes_svc_unmanaged_place' }], ['via', SAME('nodes_menu_unmanaged_via')]],
  },
  { act: 'collections', words: { service: 'nodes_menu_collections' } },
  { act: 'check', needs: 'check', words: SAME('nodes_menu_check') },
  {
    act: 'check-now', needs: 'ask', words: SAME('nodes_menu_check_now'),
    held: {
      kuma: SAME('nodes_menu_check_now_kuma'),
      unmanaged: SAME('nodes_menu_check_now_unmanaged'),
      off: SAME('nodes_menu_check_now_off'),
    },
  },
  {
    act: 'diagnose', needs: 'diagnose', words: { place: 'nodes_menu_diagnose' },
    held: {
      off: { place: 'nodes_menu_diagnose_off' },
      unmanaged: { place: 'nodes_menu_diagnose_unmanaged' },
      planned: { place: 'nodes_menu_diagnose_planned' },
    },
  },
  { act: 'topology', needs: 'topology', words: SAME('nodes_menu_topology') },
  {
    act: 'alerts', needs: 'alerts', words: SAME('nodes_menu_alerts'),
    silent: { off: SAME('nodes_menu_alerts_off'), nowhere: SAME('nodes_menu_alerts_nowhere') },
  },
  { act: 'location', needs: 'locate', words: { place: 'nodes_menu_location' } },
  { act: 'edit', needs: 'edit', words: { place: 'nodes_menu_edit' } },
  { act: 'rename', needs: 'edit', words: { collection: 'nodes_rail_rename' } },
  { act: 'remove', needs: 'remove', words: { place: 'nodes_menu_remove', collection: 'nodes_rail_remove' } },
];

const names = (list) => (Array.isArray(list) ? list.filter((n) => typeof n === 'string' && n) : []);

function watchedLine(f, key) {
  if (typeof f.watched !== 'string') return null;
  const by = f.watched.trim();
  return by ? { act: '', key, vars: { by }, words: { watched: 'nodes_col_confirmed' } }
    : { act: '', key: 'nodes_menu_unwatched' };
}

export function agoWords(secs) {
  const s = Math.max(0, Math.floor(Number(secs)));
  if (!Number.isFinite(s) || s < 60) return { key: 'nodes_ago_now', n: 0 };
  if (s < 3600) { const n = Math.floor(s / 60); return { key: n === 1 ? 'nodes_ago_min' : 'nodes_ago_mins', n }; }
  if (s < 86400) { const n = Math.floor(s / 3600); return { key: n === 1 ? 'nodes_ago_hour' : 'nodes_ago_hours', n }; }
  const n = Math.floor(s / 86400);
  return { key: n === 1 ? 'nodes_ago_day' : 'nodes_ago_days', n };
}

function lastLine(f, key) {
  const last = f.last && typeof f.last === 'object' ? f.last : null;
  if (!last || !STATES.includes(last.state) || typeof last.secs !== 'number' || !Number.isFinite(last.secs)) return null;
  const ago = agoWords(last.secs);
  return { act: '', key, vars: { n: ago.n }, words: { state: `nodes_state_${last.state}`, ago: ago.key } };
}

const LINES = { watched: watchedLine, last: lastLine };

function wayItem(action, kind, fact) {
  const f = fact && typeof fact === 'object' ? fact : {};
  if (f.own) return { act: `${action.act}-off`, key: action.off[kind] };
  for (const [why, words] of action.notes) {
    const key = words[kind];
    if (!key) continue;
    if (why === 'via') {
      const through = names(f.via);
      if (through.length) return { act: '', key, vars: { name: through.join(', ') } };
    } else if (f.place) {
      return { act: '', key };
    }
  }
  return { act: `${action.act}-on`, key: action.on[kind] };
}

export function menuItems(kind, facts = {}) {
  if (!KINDS.includes(kind)) return [];
  const f = facts && typeof facts === 'object' ? facts : {};
  if (f.readonly === true) return kind === 'place' ? readOnlyItems(f) : [];
  const items = [];
  for (const action of ACTIONS) {
    if (action.way) {
      if (action.on[kind]) items.push(wayItem(action, kind, f[action.act]));
      continue;
    }
    const key = action.words[kind];
    if (!key) continue;
    if (action.line) {
      const item = LINES[action.act](f, key);
      if (item) items.push(item);
      continue;
    }
    if (action.held) {
      const why = f[action.needs];
      if (why === true) items.push({ act: action.act, key });
      else if (typeof why === 'string' && Object.hasOwn(action.held, why)) {
        items.push({ act: action.act, key: action.held[why][kind], held: true });
      }
      continue;
    }
    if (action.needs && !f[action.needs]) continue;
    const quiet = action.silent && typeof f.silent === 'string' && Object.hasOwn(action.silent, f.silent);
    items.push({ act: action.act, key: quiet ? action.silent[f.silent][kind] : key });
  }
  return items;
}

function readOnlyItems(f) {
  const state = STATES.includes(f.state) ? f.state : 'unknown';
  const watched = typeof f.watched === 'string' ? f.watched.trim() : null;
  const items = [watched
    ? { act: '', key: 'nodes_menu_seen', vars: { by: watched }, words: { state: `nodes_state_${state}`, watched: 'nodes_col_confirmed' } }
    : watched === ''
      ? { act: '', key: 'nodes_menu_seen_none', words: { state: `nodes_state_${state}`, watched: 'nodes_menu_unwatched' } }
      : { act: '', key: `nodes_state_${state}` }];
  const last = lastLine(f, 'nodes_menu_last');
  if (last) items.push(last);
  for (const action of ACTIONS) {
    if (!action.way || !action.on.place) continue;
    const fact = f[action.act] && typeof f[action.act] === 'object' ? f[action.act] : {};
    const item = wayItem(action, 'place', { ...fact, own: false });
    if (!item.act) items.push(item);
  }
  items.push({ act: 'open', key: 'nodes_open' });
  if (f.topology) items.push({ act: 'topology', key: 'nodes_menu_topology' });
  return items;
}

export function menuKeys() {
  const keys = new Set();
  for (const action of ACTIONS) {
    const groups = action.way ? [action.on, action.off, ...action.notes.map(([, words]) => words)]
      : [action.words, ...Object.values(action.held || {}), ...Object.values(action.silent || {})];
    for (const words of groups) for (const key of Object.values(words)) keys.add(key);
  }
  for (const key of ['nodes_menu_seen', 'nodes_menu_seen_none', 'nodes_menu_unwatched', 'nodes_col_confirmed',
    'nodes_open', ...AGO_KEYS, ...STATES.map((s) => `nodes_state_${s}`)]) keys.add(key);
  return [...keys];
}

const AGO_KEYS = ['nodes_ago_now', 'nodes_ago_min', 'nodes_ago_mins', 'nodes_ago_hour', 'nodes_ago_hours',
  'nodes_ago_day', 'nodes_ago_days'];


export const CHECK_TYPES = ['http', 'tcp', 'dns', 'keyword', 'json'];

export const CHECK_FIELDS = ['check', 'check_host', 'check_port', 'check_expect', 'check_every'];

const isObj = (v) => Boolean(v) && typeof v === 'object' && !Array.isArray(v);
const httpURL = (v) => typeof v === 'string' && /^https?:\/\//i.test(v.trim());

export function monitorMap(data) {
  const out = {};
  for (const node of Array.isArray(data?.nodes) ? data.nodes : []) {
    if (!isObj(node) || !node.id) continue;
    for (const name of Array.isArray(node.monitors) ? node.monitors : []) {
      if (typeof name === 'string' && name && !(name in out)) out[name] = node.id;
    }
  }
  const kuma = isObj(data?.signals) && isObj(data.signals.kuma) ? data.signals.kuma : {};
  for (const [k, v] of Object.entries(kuma)) if (typeof v === 'string') out[k] = v;
  return out;
}

export function checkAsk(kind, data, id, opts = {}) {
  const o = isObj(opts) ? opts : {};
  if (kind !== 'place' && kind !== 'service') return '';
  if (o.unmanaged === true) return 'unmanaged';
  const nodes = (Array.isArray(data?.nodes) ? data.nodes : []).filter((n) => isObj(n) && typeof n.id === 'string');
  const shadow = isObj(data?.meta) && data.meta.shadow_kuma === true;
  const monitors = monitorMap(data);
  let ask;
  if (kind === 'place') {
    const node = nodes.find((n) => n.id === id);
    if (!node || node.planned) return '';
    const own = CHECK_TYPES.includes(node.check);
    if (Object.values(monitors).includes(id)) ask = shadow && own ? true : 'kuma';
    else ask = own ? true : '';
  } else {
    let link = null;
    for (const node of nodes) {
      if (node.planned) continue;
      link = (Array.isArray(node.links) ? node.links : []).find((l) => isObj(l) && serviceKey(node.id, l) === id) || null;
      if (link) break;
    }
    if (!link || link.planned) return '';
    const type = link.check === 'off' ? '' : CHECK_TYPES.includes(link.check) ? link.check : httpURL(link.url) ? 'http' : '';
    const named = typeof link.kuma === 'string' && link.kuma;
    if (named) ask = shadow && !(link.kuma in monitors) && type ? true : 'kuma';
    else ask = type ? true : '';
  }
  return ask === true && o.on === false ? 'off' : ask;
}

const DAY = 86400000;

export function answerLine(answer, now = Date.now()) {
  const a = isObj(answer) ? answer : {};
  const asked = Date.parse(a.asked_at);
  const heard = Date.parse(a.heard_at);
  const unanswered = !Number.isNaN(asked) && (Number.isNaN(heard) || heard < asked);
  const said = !unanswered && STATES.includes(a.said) ? a.said : 'unknown';
  const parts = [{ key: `nodes_state_${said}` }];
  if (Number.isInteger(a.ms) && a.ms >= 0 && said !== 'unknown') parts.push({ key: 'nodes_asked_ms', vars: { ms: a.ms } });
  if (typeof a.error === 'string' && a.error) parts.push({ key: 'nodes_asked_error', vars: { why: a.error } });
  if (Number.isInteger(a.status) && a.error) parts.push({ key: 'nodes_asked_status', vars: { status: a.status } });
  const expires = isObj(a.tls) && typeof a.tls.expires === 'string' ? Date.parse(`${a.tls.expires.slice(0, 10)}T00:00:00Z`) : NaN;
  if (!Number.isNaN(expires)) {
    const today = Date.parse(`${new Date(now).toISOString().slice(0, 10)}T00:00:00Z`);
    const n = Math.round((expires - today) / DAY);
    parts.push(n < 0 ? { key: 'nodes_asked_cert_lapsed' }
      : n === 1 ? { key: 'nodes_asked_cert_1day' } : { key: 'nodes_asked_cert_days', vars: { n } });
  }
  if (a.asked === false && a.stored === true) parts.push({ key: 'nodes_asked_held' });
  const tone = said === 'healthy' ? 'up' : said === 'degraded' ? 'warn' : said === 'down' ? 'down' : '';
  return { tone, parts };
}

function refusal(prefix, whys, status, body) {
  const b = isObj(body) ? body : {};
  if (status === 403) return { key: `${prefix}403` };
  if (status === 404) return { key: `${prefix}404` };
  if (status === 409 && whys.includes(b.why)) return { key: `${prefix}${b.why}` };
  if (status === 429) {
    const n = Math.max(1, Math.ceil(Number(b.retry_after) || 1));
    const why = b.why === 'spent' ? 'spent' : 'soon';
    return { key: n === 1 ? `${prefix}${why}_one` : `${prefix}${why}`, vars: { n } };
  }
  const why = typeof b.error === 'string' && b.error ? b.error : status ? `${status}` : 'no answer';
  return { key: `${prefix}failed`, vars: { why } };
}

export function refusalLine(status, body) {
  return refusal('nodes_asked_', ['kuma', 'unmanaged', 'off'], status, body);
}

export function wordsOf(item, t) {
  const it = isObj(item) ? item : {};
  const vars = { ...(isObj(it.vars) ? it.vars : {}) };
  for (const [k, key] of Object.entries(isObj(it.words) ? it.words : {})) vars[k] = t(key, isObj(it.vars) ? it.vars : {});
  return t(it.key, vars);
}

export function checkPatch(original, values) {
  const was = isObj(original) ? original : {};
  const now = isObj(values) ? values : {};
  const out = {};
  for (const name of CHECK_FIELDS) {
    if (!Object.hasOwn(now, name)) continue;
    const v = typeof now[name] === 'string' ? now[name].trim() : now[name];
    const had = Object.hasOwn(was, name) && was[name] !== '' && was[name] !== null && was[name] !== undefined;
    if (v === '' || v === null || v === undefined) {
      if (had) out[name] = null;
      continue;
    }
    if (!had || was[name] !== v) out[name] = v;
  }
  return out;
}

export function patched(entry, patch) {
  const out = { ...(isObj(entry) ? entry : {}) };
  for (const [k, v] of Object.entries(isObj(patch) ? patch : {})) {
    if (v === null) delete out[k]; else out[k] = v;
  }
  return out;
}


export const DIAGNOSE_STEPS = ['hop', 'dns', 'place', 'internet'];

export const DIAGNOSE_WHYS = ['stub', 'no-address', 'no-port', 'off', 'hidden', 'planned', 'unmanaged', 'kuma',
  'not-asked', 'busy', 'stopped', 'late'];

const whyKey = (code) => (DIAGNOSE_WHYS.includes(code) ? `nodes_dx_why_${code.replace(/-/g, '_')}` : 'nodes_dx_why_other');

export function diagnoseAsk(data, id, opts = {}) {
  const o = isObj(opts) ? opts : {};
  if (typeof id !== 'string' || !id) return '';
  const node = (Array.isArray(data?.nodes) ? data.nodes : []).find((n) => isObj(n) && n.id === id);
  if (!node) return '';
  if (o.on === false) return 'off';
  if (o.unmanaged === true || node.unmanaged === true) return 'unmanaged';
  if (node.planned) return 'planned';
  return true;
}

const stepsOf = (answer) => (isObj(answer) && Array.isArray(answer.steps) ? answer.steps.map((s) => (isObj(s) ? s : {})) : []);
const brokeAt = (answer, steps) => (isObj(answer) && Number.isInteger(answer.broke_at) && answer.broke_at >= 0
  && answer.broke_at < steps.length ? answer.broke_at : null);
const word = (v) => (typeof v === 'string' && v ? v : '');

function whoPart(s) {
  if (s.step === 'internet') return { key: 'nodes_dx_internet' };
  const name = word(s.name) || word(s.thing);
  if (!name) return { key: 'nodes_dx_hidden' };
  return { key: s.step === 'dns' ? 'nodes_dx_dns' : 'nodes_dx_thing', vars: { name } };
}

export function diagnoseLines(answer) {
  const steps = stepsOf(answer);
  const broke = brokeAt(answer, steps);
  return steps.map((s, i) => {
    const parts = [whoPart(s)];
    if (word(s.asks)) parts.push({ key: 'nodes_dx_asks', vars: { asks: s.asks } });
    const state = s.state === 'up' || s.state === 'down' ? s.state : 'skipped';
    if (state === 'skipped') {
      parts.push({ key: 'nodes_dx_skipped', words: { why: whyKey(s.why) } });
    } else {
      parts.push({ key: `nodes_dx_${state}` });
      if (Number.isInteger(s.ms) && s.ms >= 0) parts.push({ key: 'nodes_asked_ms', vars: { ms: s.ms } });
      if (state === 'down' && word(s.error)) parts.push({ key: 'nodes_asked_error', vars: { why: s.error } });
    }
    return { step: DIAGNOSE_STEPS.includes(s.step) ? s.step : '', tone: state === 'skipped' ? '' : state, broke: i === broke, parts };
  });
}

export function diagnoseSummary(answer) {
  const steps = stepsOf(answer);
  const broke = brokeAt(answer, steps);
  if (broke !== null) {
    const s = steps[broke];
    if (s.step === 'internet') return { key: 'nodes_dx_breaks_outside', tone: 'down' };
    const who = whoPart(s);
    if (!who.vars) return { key: 'nodes_dx_breaks_hidden', tone: 'down' };
    return { key: s.step === 'dns' ? 'nodes_dx_breaks_dns' : 'nodes_dx_breaks', vars: { name: who.vars.name }, tone: 'down' };
  }
  const up = steps.filter((s) => s.state === 'up').length;
  if (!up) return { key: 'nodes_dx_none', tone: '' };
  const n = steps.length - up;
  if (!n) return { key: 'nodes_dx_clear', tone: 'up' };
  return { key: n === 1 ? 'nodes_dx_clear_some_one' : 'nodes_dx_clear_some', vars: { n }, tone: 'up' };
}

export function diagnoseLight(answer) {
  const a = isObj(answer) ? answer : {};
  const path = isObj(a.path) ? a.path : {};
  let things = Array.isArray(path.things) ? path.things.map((x) => word(x) || null) : [];
  let links = Array.isArray(path.links) ? path.links.map((x) => word(x) || null) : [];
  if (!things.length && word(a.id)) { things = [a.id]; links = []; }
  const steps = stepsOf(a);
  const broke = brokeAt(a, steps);
  let failedAt = null;
  if (broke !== null && things.length) {
    const s = steps[broke];
    if (s.step === 'dns') failedAt = things.length - 1;
    else if (s.step === 'place') failedAt = things.length - 1;
    else if (s.step === 'hop') {
      const byId = word(s.thing) ? things.indexOf(s.thing) : -1;
      const turn = steps.slice(0, broke).filter((x) => x.step === 'hop').length;
      failedAt = byId >= 0 ? byId : turn < things.length ? turn : null;
    }
  }
  return { things, links, failedAt };
}

export function diagnoseRefusal(status, body) {
  return refusal('nodes_dx_', ['off', 'unmanaged', 'planned'], status, body);
}

export function diagnoseKeys() {
  return [
    'nodes_dx_internet', 'nodes_dx_hidden', 'nodes_dx_dns', 'nodes_dx_thing', 'nodes_dx_asks', 'nodes_dx_skipped',
    'nodes_dx_up', 'nodes_dx_down', 'nodes_asked_ms', 'nodes_asked_error',
    ...DIAGNOSE_WHYS.map(whyKey), 'nodes_dx_why_other',
    'nodes_dx_breaks', 'nodes_dx_breaks_dns', 'nodes_dx_breaks_outside', 'nodes_dx_breaks_hidden',
    'nodes_dx_clear', 'nodes_dx_clear_some', 'nodes_dx_clear_some_one', 'nodes_dx_none',
    ...['403', '404', 'off', 'unmanaged', 'planned', 'soon', 'soon_one', 'spent', 'spent_one', 'failed'].map((k) => `nodes_dx_${k}`),
  ];
}
