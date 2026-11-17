/* THE MENU's rules (NODES, 2026-11-16), with no DOM: what the ⋯ of a place,
   a service or a collection lists.

   NODES had the same actions written three times: a place's ⋯, a service's
   ⋯ and a row of buttons under a collection in the rail. They are one table
   here (ACTIONS, in the order a menu lists them) and one function
   (menuItems), which takes the kind of thing and a few plain facts about it
   and gives back the lines to draw. A container is a service link, so it
   asks as a service.

   The two ways out of the watch, maintenance mode and unmanaged, are each
   one line that reads one of three ways: the switch to turn it on, the
   switch to turn it off, or a quiet note that it is already so through
   something else (a collection that holds the thing, or the place a service
   runs on), where the thing's own switch would change nothing.

   A phone (2026-11-16) asks for the read-only way (`facts.readonly`): a
   place's card opens a sheet that lists only what changes nothing, its
   state and who watches it, the same quiet notes, and Open its card. A
   service and a collection have no line on a phone, so nothing.

   THE ENGINES IN THE MENU (2026-11-17). A place's and a service's menu
   opens with who watches it ("Watched by Kuma", or "Not watched") and,
   when a check has answered, a line with that answer and how long ago.
   An admin gets Check… (the check's own fields, in the scope bar) and
   Check now (ask it once, now), which is shown held, with the reason in
   words, where the server would refuse it (`checkAsk`: a named monitor
   speaks for it, it is unmanaged, or the checks source is off). The
   Alerts line says so when nothing can send, so a bell never looks armed.
   What Check now answers, or why it was refused, is `answerLine` and
   `refusalLine`; what Check… saves is `checkPatch`.

   WHERE DOES IT BREAK, AND THE CANVAS (2026-11-17). An admin's place menu
   adds "Where does it break?" after Check now (held, as Check now is,
   where the route would refuse it: `diagnoseAsk`), and a place's or a
   service's adds "Show in topology", which a phone's sheet lists too.
   What the chain answered is `diagnoseLines` and `diagnoseSummary`, what
   the canvas lights `diagnoseLight`, a refusal `diagnoseRefusal`; any
   line's words are `wordsOf`.

   This file knows the theme keys (`nodes_*`, nodes-text.js), never the
   words: nodes-menu.js gathers the facts, fills the words in and draws.
   Unit-tested by tests/test_menu_model.mjs under plain node. */

import { serviceKey } from './alerts-model.js';

export const KINDS = ['place', 'service', 'collection'];

/** The states a place reads as (nodes-state.js STATES), each with its
    words under `nodes_state_<state>`. Anything else reads as unknown. */
export const STATES = ['healthy', 'degraded', 'down', 'maintenance', 'slumbering', 'unknown', 'unmanaged'];

const SAME = (key) => ({ place: key, service: key });

/** Every action, in the order a menu lists them. `words` is the theme key of
    its label for each kind that has it (a kind not named does not list it);
    `needs` names the fact that must be true for it to be offered. A `way` is
    a switch: `on` and `off` are its two labels, and `notes` are the lines
    that stand in for it, first that applies wins, when the thing is already
    so through a collection (`via`, which names them) or with its place.
    A `line` is never a press: words built from a fact (`LINES`), or none.
    `held` gives a press's words for each reason it is shown held (a
    disabled item that says why), and `silent` the Alerts line's words for
    each reason nothing can send. */
export const ACTIONS = [
  // 2026-11-17: who watches it, then what its check last answered
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
  // 2026-11-17: the check's own fields, and the check asked now
  { act: 'check', needs: 'check', words: SAME('nodes_menu_check') },
  {
    act: 'check-now', needs: 'ask', words: SAME('nodes_menu_check_now'),
    held: {
      kuma: SAME('nodes_menu_check_now_kuma'),
      unmanaged: SAME('nodes_menu_check_now_unmanaged'),
      off: SAME('nodes_menu_check_now_off'),
    },
  },
  // 2026-11-17: the place's chain asked from the head down, held where the
  // route would refuse it (`diagnoseAsk`); and the place on the TOPOLOGY
  // canvas (a service's: its place)
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
  { act: 'edit', needs: 'edit', words: { place: 'nodes_menu_edit' } },
  { act: 'rename', needs: 'edit', words: { collection: 'nodes_rail_rename' } },
  { act: 'remove', needs: 'remove', words: { place: 'nodes_menu_remove', collection: 'nodes_rail_remove' } },
];

const names = (list) => (Array.isArray(list) ? list.filter((n) => typeof n === 'string' && n) : []);

/** Who watches it, as the column says it: `watched` is the words ('' for
    nothing); left out, or not words, there is no line. */
function watchedLine(f, key) {
  if (typeof f.watched !== 'string') return null;
  const by = f.watched.trim();
  return by ? { act: '', key, vars: { by }, words: { watched: 'nodes_col_confirmed' } }
    : { act: '', key: 'nodes_menu_unwatched' };
}

/** How long ago, as a theme key and its `n`. */
export function agoWords(secs) {
  const s = Math.max(0, Math.floor(Number(secs)));
  if (!Number.isFinite(s) || s < 60) return { key: 'nodes_ago_now', n: 0 };
  if (s < 3600) { const n = Math.floor(s / 60); return { key: n === 1 ? 'nodes_ago_min' : 'nodes_ago_mins', n }; }
  if (s < 86400) { const n = Math.floor(s / 3600); return { key: n === 1 ? 'nodes_ago_hour' : 'nodes_ago_hours', n }; }
  const n = Math.floor(s / 86400);
  return { key: n === 1 ? 'nodes_ago_day' : 'nodes_ago_days', n };
}

/** What its check last answered and how long ago: `last` is {state, secs}
    (the answer's `said`, and the seconds since it was heard). */
function lastLine(f, key) {
  const last = f.last && typeof f.last === 'object' ? f.last : null;
  if (!last || !STATES.includes(last.state) || typeof last.secs !== 'number' || !Number.isFinite(last.secs)) return null;
  const ago = agoWords(last.secs);
  return { act: '', key, vars: { n: ago.n }, words: { state: `nodes_state_${last.state}`, ago: ago.key } };
}

const LINES = { watched: watchedLine, last: lastLine };

/** One switch's line: off when the thing itself is so, else the first note
    that applies, else on. */
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

/** The lines of one thing's menu, in order: `{act, key, vars?, words?,
    held?}`. `act` is what a press does (`schedule`, `mode-on`, `mode-off`,
    `unmanaged-on`, `unmanaged-off`, `collections`, `check`, `check-now`,
    `diagnose`, `topology`, `alerts`, `edit`, `rename`, `remove`, `open`),
    or '' for a note, which is
    words and not a button. `key` is the theme key of its words and `vars`
    what fills them in; `words` are vars whose values are theme keys, to be
    filled in as words (with the same `vars`). `held: true` is a press shown
    but not pressable: its words say why.

    `kind` is `place`, `service` or `collection`. `facts`:
      mode       {own, via, place}: in maintenance mode itself; the names of
                 the collections it is in maintenance mode through; (a
                 service) its place is in maintenance now
      unmanaged  {own, via, place}: marked unmanaged itself; the names of the
                 unmanaged collections that hold it; (a service) its place
                 is unmanaged
      alerts     this viewer may set alerts
      silent     (with alerts) why nothing can send: `off` (alerts are off)
                 or `nowhere` (no destination yet); the Alerts line says so
      edit       it can be edited (a place's form, a collection's name)
      remove     it can be removed
      watched    (a place, a service) who watches it, in words; '' for
                 nothing ("Not watched"); left out, no line
      last       (a place, a service) {state, secs}: what its check last
                 said and how many seconds ago; left out, no line
      check      (a place, a service) its check's fields may be written
      ask        (a place, a service) what `checkAsk` says: true, Check now
                 may be pressed; `kuma`, `unmanaged` or `off`, it is shown
                 held with that reason; anything else, no Check now
      diagnose   (a place) what `diagnoseAsk` says: true, "Where does it
                 break?" may be pressed; `off`, `unmanaged` or `planned`, it
                 is shown held with that reason; anything else, not listed
      topology   (a place, a service) the TOPOLOGY view is there to open:
                 "Show in topology" (a service's opens its place). The
                 read-only way lists it too, after Open its card
      readonly   true: the read-only way (a phone), below
    Anything left out reads as no. An unknown kind has no menu.

    The read-only way lists nothing that writes, whoever asks. A place gets
    a first note naming its state (`state`, one of STATES) and, when
    `watched` names who watches it (its words), the column's "Watched by"
    after it, or "Not watched" when `watched` is ''; then its `last`
    answer; then the notes its `mode` and `unmanaged` would give through
    a collection (its own mode or unmanaged is its state, said already);
    then `open`, what a press on its card does. */
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

/** A place's read-only lines: its state (and who watches it), its last
    answer, the notes that say it is so through something else, and Open
    its card. */
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
    // its own switch is no part of this way: only a note is kept
    const item = wayItem(action, 'place', { ...fact, own: false });
    if (!item.act) items.push(item);
  }
  items.push({ act: 'open', key: 'nodes_open' });
  // the canvas only reads too (2026-11-17)
  if (f.topology) items.push({ act: 'topology', key: 'nodes_menu_topology' });
  return items;
}

/** Every theme key the model can hand back, for the test that each has its
    plain words. */
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

/* ── a check: may Atlas ask it now, what it answered, what Check… saves ──
   (2026-11-17) */

/** The kinds of check Atlas asks (watch.py TYPES); `off` and blank are not. */
export const CHECK_TYPES = ['http', 'tcp', 'dns', 'keyword', 'json'];

/** The check's own fields Check… edits, in the Desk form's order (schema.py
    `_check_fields`): its type, address, port, expectation and interval.
    Their labels, options and limits are the schema's, read in the page. */
export const CHECK_FIELDS = ['check', 'check_host', 'check_port', 'check_expect', 'check_every'];

const isObj = (v) => Boolean(v) && typeof v === 'object' && !Array.isArray(v);
const httpURL = (v) => typeof v === 'string' && /^https?:\/\//i.test(v.trim());

/** {monitor name: place id} the map charts (engines/base.py `monitor_map`):
    each place's own `monitors`, then `signals.kuma`. */
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

/** Whether Atlas may ask a thing's check now, as the server's
    `POST checks/run` would answer it (watch.py `targets` and `not_asked`):
    true; `unmanaged` (the thing, or what holds it, is unmanaged:
    `opts.unmanaged`); `kuma` (a monitor the owner named speaks for it, and
    the map's "Check beside Kuma" is off, or the monitor is tied to a
    place); `off` (the checks source is off: `opts.on === false`); or ''
    when it has no check of its own to ask, and there is no Check now.
    Only what the map says for sure is held; an address the server cannot
    ask is its own 404, said in words when pressed. `id` is a place's id or
    a service's key. */
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

/** What Check now answered, as lines of words joined with " · ": what it
    said (or that it got no answer), how long it took, the error in words
    when it was not up, and the certificate's days left when it saw one;
    `tone` is `up`, `warn` or `down` for the line's ink. `answer` is the
    route's (watch.py `answer_for`, with `asked`/`stored`). */
export function answerLine(answer, now = Date.now()) {
  const a = isObj(answer) ? answer : {};
  // the last ask got no answer (watch.py `answer_for`: asked, and not heard
  // since): what an older answer said is not this one's, nor how long it took
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

/** A refusal in words, for keys under `prefix`: 403, 404, 409 by `why`
    (one of `whys`), 429 with how many seconds to wait, else `failed`. */
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

/** Why Check now was refused, in words: `{key, vars}` from the status and
    the body the route gave (403, 404, 409 by `why`, 429 with how many
    seconds to wait), or the words of anything else (`nodes_asked_failed`). */
export function refusalLine(status, body) {
  return refusal('nodes_asked_', ['kuma', 'unmanaged', 'off'], status, body);
}

/** One line's words: its key filled in with its `vars`, and each of its
    `words` (vars whose values are theme keys) filled in as words first,
    with the same vars. `t(key, vars)` is the caller's (nodes-text.js), so
    NODES and the TOPOLOGY canvas say a line the same way. */
export function wordsOf(item, t) {
  const it = isObj(item) ? item : {};
  const vars = { ...(isObj(it.vars) ? it.vars : {}) };
  for (const [k, key] of Object.entries(isObj(it.words) ? it.words : {})) vars[k] = t(key, isObj(it.vars) ? it.vars : {});
  return t(it.key, vars);
}

/** What Check… saves: the change from `original` (the place or the link
    as it is on disk) to `values` (what each field holds now, by name),
    with `null` for a field cleared that had a value; {} when nothing
    changed. Only CHECK_FIELDS are read. */
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

/** A link with a patch laid on it: a value set, `null` deleted. A link is
    written whole, inside its place's `links`, so it never carries a null. */
export function patched(entry, patch) {
  const out = { ...(isObj(entry) ? entry : {}) };
  for (const [k, v] of Object.entries(isObj(patch) ? patch : {})) {
    if (v === null) delete out[k]; else out[k] = v;
  }
  return out;
}

/* ── where does it break? (2026-11-17) ───────────────────────────────────────
   `POST api/v2/admin/diagnose` asks one place's chain from the head of the
   network down (diagnose.py) and answers {id, name, steps, broke_at, path}.
   What may be asked, the lines and the summary that say the answer, the
   chain the TOPOLOGY canvas lights, and a refusal in words. NODES (under
   the place's row) and the canvas (a note beside it) both say it through
   these, with nodes-text.js's words. */

/** The steps the route asks, in the order it asks them (diagnose.py STEPS). */
export const DIAGNOSE_STEPS = ['hop', 'dns', 'place', 'internet'];

/** Why a step was not asked (diagnose.py WHY): each has its words under
    `nodes_dx_why_<code>`, a dash read as an underscore; any other code
    reads as `nodes_dx_why_other`. */
export const DIAGNOSE_WHYS = ['stub', 'no-address', 'no-port', 'off', 'hidden', 'planned', 'unmanaged', 'kuma',
  'not-asked', 'busy', 'stopped', 'late'];

const whyKey = (code) => (DIAGNOSE_WHYS.includes(code) ? `nodes_dx_why_${code.replace(/-/g, '_')}` : 'nodes_dx_why_other');

/** May Atlas ask this place's chain now, as the route would answer it
    (checks.py `diagnose_place`, in its order): true; `off` (the checks
    source is off: `opts.on === false`); `unmanaged` (it, or a collection
    that holds it, is: the place's own field, or `opts.unmanaged`);
    `planned` (not built yet); '' when there is no such place. A Kuma
    monitor is no refusal here: the chain is asked, and the place's own
    step says Kuma watches it. Unknown is not off. */
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

/** Who a step is about: the thing's name (its id when it has none), its
    DNS name, the outside address, or a place this viewer may not see. */
function whoPart(s) {
  if (s.step === 'internet') return { key: 'nodes_dx_internet' };
  const name = word(s.name) || word(s.thing);
  if (!name) return { key: 'nodes_dx_hidden' };
  return { key: s.step === 'dns' ? 'nodes_dx_dns' : 'nodes_dx_thing', vars: { name } };
}

/** One line per step, in the order asked: `{step, tone, broke, parts}`,
    the parts joined with " · " as Check now's are. Who it is about; what
    was asked; Up, Down, or Not asked with the reason in words; how long
    it took; and, when it was down, the error in words. `tone` is `up`,
    `down` or '' (not asked) for the state's ink, and `broke` marks the
    step that failed (`broke_at`). */
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

/** The one line that sums it up, `{key, vars?, words?, tone}`: where it
    breaks (a thing, its DNS name, or past the whole path at the outside
    address); every step answered; every step asked answered but some
    could not be asked; or nothing could be asked. */
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

/** What the canvas lights (topology-state.js `lightPath`): the chain head
    first, `null` in place of a thing or a cable this viewer may not see,
    and `failedAt`, an index into `things`, for the step that failed.
    `broke_at` is an index into the steps, not the path: a hop or the place
    failing is that thing's place on the path; its DNS name failing is the
    place's (the last); the outside address failing is no thing on the
    path, so the whole path is lit as good. A place nothing reaches has an
    empty path: it is lit alone. */
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
      // the hops are the path's things but the last, in order, one step each:
      // a hop's place on the path is its place among the hops. By id first; a
      // hop the viewer may not see has no id and is found by its turn.
      const byId = word(s.thing) ? things.indexOf(s.thing) : -1;
      const turn = steps.slice(0, broke).filter((x) => x.step === 'hop').length;
      failedAt = byId >= 0 ? byId : turn < things.length ? turn : null;
    }
  }
  return { things, links, failedAt };
}

/** Why "Where does it break?" was refused, in words: 403, 404, 409 by
    `why` (`off`, `unmanaged`, `planned`), 429 with how many seconds to
    wait (`soon` or `spent`), else the words of anything else. */
export function diagnoseRefusal(status, body) {
  return refusal('nodes_dx_', ['off', 'unmanaged', 'planned'], status, body);
}

/** Every theme key the diagnose lines, summaries and refusals can give,
    for the test that each has its plain words. */
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
