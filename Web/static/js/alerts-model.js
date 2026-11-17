/* ALERTS' rules, with no DOM (2026-11-13, the views' stage 4).

   ALERTS is rules and destinations, not an engine. A rule says, in one
   sentence: when this place, collection or network goes to this state and stays
   there this long, send to this destination. It reads the state changes the
   ANNALS already records, at the annals' own poll, and measures nothing. The
   server keeps the rules and destinations (`api/v2/admin/alerts`, admin only),
   sends, and logs every send; it is off until the operator sets ATLAS_ALERTS
   and lists the hosts it may send to in ATLAS_ALERT_HOSTS.

   This file words all of it: the rule's sentence, the daily digest's
   sentence, what the page checks before it posts (and so says first, in
   plain words), how to turn alerts on, the outcome of a send, and a line of
   the delivery log, and which rules reach a place. Since 2026-11-14 two
   files draw: alert-rules.js the rules on one thing inside NODES, and
   alert-setup.js where word goes in Settings › Alerts (the ALERTS view,
   alerts.js, is gone); this file only decides and words. Every visible
   phrase is a theme key with its plain fallback in ALERTS_TEXT, filled by a
   `t` the caller passes (alert-forms.js passes one that reads the theme
   first). A secret's VALUE never passes through here: a destination
   only names its secret, and the server reads it from the environment.
   Unit-tested by tests/test_alerts_model.mjs under plain node. */

/** Every visible string, by theme key, with its plain fallback. */
export const ALERTS_TEXT = {
  alerts_loading: 'Reading the alerts…',
  alerts_failed: 'The alerts could not be read: {why}',

  // the status strip
  alerts_on: 'On',
  alerts_off: 'Off',
  alerts_hosts: 'may send to {hosts}',
  alerts_no_hosts: 'no host is allowed',
  alerts_poll: 'looks every {n} s',
  alerts_poll_off: 'the poll is off',
  alerts_poll_stopped: 'the poll is not running',
  alerts_tick: 'last looked {when}',
  alerts_tick_never: 'has not looked yet',

  // turning it on
  alerts_off_title: 'Alerts are off.',
  alerts_off_both: 'Atlas sends nothing until two settings are in its environment: ATLAS_ALERTS=1, and ATLAS_ALERT_HOSTS listing the hosts it may send to, for example ntfy.example:443. No host is listed yet.',
  alerts_off_flag: 'The hosts it may send to are listed in ATLAS_ALERT_HOSTS. Set ATLAS_ALERTS=1 as well to turn alerts on.',
  alerts_off_hosts: 'ATLAS_ALERTS is set, but ATLAS_ALERT_HOSTS lists no host, so there is nowhere Atlas may send. List them as host:port, for example ntfy.example:443.',
  alerts_off_restart: 'Restart Atlas after changing its environment. Destinations and rules can be made once it is on.',
  alerts_poll_needed: 'Alerts need the annals\' poll; it is off. Set ATLAS_ANNALS_POLL above 0 and run Atlas under gunicorn, or nothing will be sent.',
  alerts_poll_dead: 'Alerts need the annals\' poll, and it is not running: it runs under gunicorn, never under flask run. Nothing is sent until it does.',
  alerts_no_link: 'ATLAS_PUBLIC_URL is not set, so messages will carry no link to the place.',

  // the sections
  alerts_t_destinations: 'Destinations',
  alerts_t_digest: 'The daily digest',
  alerts_t_deliveries: 'Deliveries',
  alerts_add_destination: 'Add a destination',
  alerts_add_rule: 'Add a rule',
  alerts_edit: 'Edit',
  alerts_remove: 'Remove',
  alerts_remove_sure: 'Yes, remove it',
  alerts_save: 'Save',
  alerts_cancel: 'Cancel',
  alerts_saving: 'Saving…',
  alerts_saved: 'Saved.',
  alerts_stale: 'Someone changed the alerts while you were editing. They have been read again: make your change once more.',
  alerts_refused: 'That was not saved: {why}',
  alerts_fix: 'That was not saved. Put these right first:',
  alerts_fix_form: 'That was not saved. The form says what to put right.',

  // destinations
  alerts_dest_none: 'There is nowhere to send yet. Add a destination first; a rule sends to one.',
  alerts_kind_ntfy: 'ntfy',
  alerts_kind_gotify: 'Gotify',
  alerts_kind_webhook: 'A JSON webhook',
  alerts_kind_discord: 'Discord',
  alerts_discord_url_hint: 'The webhook\'s address up to its id. The operator lists discord.com:443 in ATLAS_ALERT_HOSTS first.',
  alerts_discord_secret_hint: 'The token, the part of the webhook\'s address after the id: the server reads it from ATLAS_ALERT_SECRET_<NAME> or its _FILE; Atlas never stores it.',
  alerts_f_name: 'Name',
  alerts_f_kind: 'Kind',
  alerts_f_url: 'Address',
  alerts_f_secret: 'Secret\'s name',
  alerts_secret_hint: 'The server reads ATLAS_ALERT_SECRET_<NAME> or its _FILE; Atlas never stores the secret.',
  alerts_hosts_hint: 'Only these hosts are allowed: {hosts}.',
  alerts_secret_none: 'no secret',
  alerts_secret_bound: 'secret from ATLAS_ALERT_SECRET_{name}',
  alerts_secret_unbound: 'the address changed, so ATLAS_ALERT_SECRET_{name} is not sent to it: edit it to name the secret again',
  alerts_f_bind: 'Send ATLAS_ALERT_SECRET_{name} to this address',
  alerts_test: 'Send a test',
  alerts_testing: 'Sending…',
  alerts_in_use: 'Rules send here: {names}. Change them first.',

  // rules
  alerts_f_rule_name: 'Name',
  alerts_f_note: 'Note (for you; never sent)',
  alerts_f_states: 'When it goes',
  alerts_f_minutes: 'And stays for (minutes; 0 sends at once)',
  alerts_f_dest: 'Send to',
  alerts_f_enabled: 'On',
  alerts_pick: 'Pick one…',
  alerts_resolution: 'Atlas looks every {n} seconds, so a wait is measured to the nearest {n} seconds.',
  alerts_resolution_off: 'Atlas measures a wait at the annals\' poll, which is off.',
  alerts_rule_on: 'Send by this rule',
  alerts_rule_paused: 'paused',
  alerts_suspended: 'Suspended: what it watches is hidden from a viewer with no groups, so nothing about it is sent.',
  alerts_rule_now: 'When {target} goes {states}, send to {dest} at once.',
  alerts_rule_wait: 'When {target} goes {states} and stays for {wait}, send to {dest}.',
  alerts_t_place: '{name}',
  alerts_t_collection: 'any place in the collection {name}',
  alerts_t_network: 'any place on the network {name}',
  alerts_t_gone_place: 'a place no longer on the map ({id})',
  alerts_t_gone_collection: 'a collection that no longer exists ({id})',
  alerts_t_gone_network: 'a network no longer on the map ({id})',
  alerts_t_service: 'the service {name}',
  alerts_t_gone_service: 'a service no longer on the map ({id})',
  alerts_t_nothing: 'nothing yet',
  alerts_nowhere: 'nowhere yet',
  alerts_or: 'or',
  alerts_go_down: 'down',
  alerts_go_degraded: 'degraded',
  alerts_go_healthy: 'up',
  alerts_go_maintenance: 'into maintenance',
  alerts_go_slumbering: 'to sleep',
  alerts_go_none: 'anywhere yet',
  alerts_state_down: 'Down',
  alerts_state_degraded: 'Degraded',
  alerts_state_healthy: 'Up',
  alerts_state_maintenance: 'In maintenance',
  alerts_state_slumbering: 'Asleep',
  alerts_min_one: '1 minute',
  alerts_min_many: '{n} minutes',
  alerts_hour_one: 'an hour',
  alerts_hour_many: '{n} hours',

  // what the page checks before it posts
  alerts_need_name: 'Name it.',
  alerts_need_target: 'Pick what the rule watches.',
  alerts_need_state: 'Pick at least one state.',
  alerts_need_dest: 'Pick where to send it.',
  alerts_need_dest_first: 'Add a destination first.',
  alerts_need_minutes: 'The wait is a whole number of minutes, from 0 to 1440.',
  alerts_need_url: 'Give the address to send to.',
  alerts_need_kind: 'Pick {kinds}.',
  alerts_need_secret: 'Name the secret this kind sends; it cannot send without one.',
  alerts_bad_url: 'The address must start with https:// or http://.',
  alerts_bad_userinfo: 'The address may not carry a user name or password. Name a secret instead.',
  alerts_bad_query: 'The address may not carry a query (?…). Name a secret instead.',
  alerts_bad_host: '{host} is not in ATLAS_ALERT_HOSTS, so Atlas will not send there.',
  alerts_bad_fragment: 'The address may not carry a fragment (#…).',
  alerts_bad_ntfy: 'An ntfy address names its topic, as https://ntfy.example/atlas.',
  alerts_bad_gotify: 'A Gotify address is the server itself, or ends in /message.',
  alerts_bad_secret: 'A secret\'s name is capitals, digits and _ only, at most 40 of them, as NTFY_LAB.',
  alerts_need_hour: 'The hour is a whole number from 0 to 23.',
  alerts_need_cert_days: 'Certificate days are a whole number from 1 to 365.',
  alerts_need_review_days: 'Review days are a whole number from 1 to 3650.',

  // the daily digest
  alerts_f_digest_on: 'Send the digest',
  alerts_f_hour: 'Hour of the day (server time)',
  alerts_f_cert_days: 'Certificates lapsing within (days)',
  alerts_f_review_days: 'Places not checked in (days)',
  alerts_f_drift: 'Monitors the map has not charted',
  alerts_f_uncharted: 'Devices a source sees that the map has not charted',
  alerts_unsupported: 'not supported yet',
  alerts_digest_off: 'The daily digest is not sent.',
  alerts_digest_line: 'Every day at {hour}, send to {dest}: {what}.',
  alerts_d_certs: 'certificates lapsing within {n} days',
  alerts_d_review: 'places not checked in {n} days',
  alerts_d_drift: 'monitors the map has not charted',
  alerts_d_uncharted: 'devices the map has not charted',
  alerts_and: 'and',

  // the outcome of a send, and the log
  alerts_o_delivered: 'delivered',
  alerts_o_refused: 'refused',
  alerts_o_refused_status: 'refused (HTTP {status})',
  alerts_o_unreachable: 'unreachable',
  alerts_o_blocked: 'blocked',
  alerts_deliveries_none: 'Nothing has been sent yet.',
  alerts_deliveries_failed: 'The deliveries could not be read: {why}',
  alerts_l_rule: 'Rule “{rule}”',
  alerts_l_test: 'A test',
  alerts_l_digest: 'The daily digest',
  alerts_l_fold: 'The changes held back by the rate limit',
  alerts_l_one: '1 change',
  alerts_l_many: '{n} changes',
  alerts_l_line: '{what} to {dest}: {outcome}.',
  alerts_l_line_n: '{what}, {count}, to {dest}: {outcome}.',

  // Settings › Alerts (2026-11-14): where word goes, the digest, the log
  alerts_setup_title: 'ALERTS',
  alerts_setup_sub: 'where word goes, the daily digest, the log',
  alerts_setup_note: 'Where alerts are sent, the daily digest, and what was sent. The rules are made in NODES: a place’s bell, or the ⋯ beside a collection or a network.',

  // the alerts on one thing, inside NODES (2026-11-14)
  alerts_panel_title: 'Alerts on {target}',
  alerts_panel_shut: 'Close',
  alerts_panel_none: 'No rule of its own yet.',
  alerts_panel_also: 'Also reached through:',
  alerts_panel_one: '1 rule',
  alerts_panel_many: '{n} rules',
  alerts_panel_no_dest: 'A rule sends to a destination, and there is none yet.',
  alerts_panel_to_setup: 'Open Settings › Alerts',
  alerts_panel_setup: 'Destinations, the daily digest and the log are in Settings › Alerts.',
  alerts_t_orphans: 'Rules on something gone',
  alerts_panel_unmanaged: 'No rule sends for this place: it is unmanaged, not ours to watch, so it has no state to send about. Its own rules are listed here to be removed.',
  alerts_panel_held: 'No rule sends for this place: it is behind an access group, and the alerts read the map as someone with no group does. Its own rules are listed here to be removed; a new one could not be saved.',
  alerts_orphans_note: 'These rules watch a place, a collection or a network that is no longer on the map, so NODES has no bell for them, and they send nothing. Remove them here, or bring their target back.',

  // the ANNALS' note beside an event that caused a send
  annals_sent: 'sent to {to}',
};

/** Fill `{name}` in a phrase; an unknown name is left as it is. */
export function fill(text, vars = {}) {
  return String(text ?? '').replace(/\{(\w+)\}/g, (m, k) => (k in vars ? String(vars[k]) : m));
}

/** The plain words, for a caller (and the tests) with no theme. */
export const plainT = (key, vars) => fill(ALERTS_TEXT[key] ?? key, vars);

/** The states a rule can wait for, when the server does not list them. */
export const STATES = ['down', 'degraded', 'maintenance', 'slumbering', 'healthy'];
/** The three shapes a destination can take (the server fixes method and body).
    Since 2026-11-16 the server lists its kinds itself (`kindList`); these are
    what the page knows when it is not told. */
export const KINDS = ['ntfy', 'gotify', 'webhook'];
const PLACEHOLDERS = { ntfy: 'https://ntfy.example/lab-alerts', gotify: 'https://gotify.example', webhook: 'https://hooks.example/atlas' };
const FIELD_TYPES = ['url', 'secret-name', 'text', 'select'];

/** The kinds a destination can be, as the server declares them (2026-11-16):
    `kinds` in the alerts read, from Web/senders/, only those that can send,
    in the order offered. Each is {kind, label, fields}; a field is {name,
    type: url|secret-name|text|select, required, label (a theme key), text
    (its plain words), hint, hint_text, placeholder, options}. A declaration
    with no address is left out. Told nothing, the three this page has always
    known, with the same fields, so the form is drawn the same either way. */
export function kindList(given) {
  const field = (f) => f && typeof f === 'object' && typeof f.name === 'string' && f.name
    && FIELD_TYPES.includes(f.type);
  const told = list(given)
    .filter((k) => k && typeof k.kind === 'string' && k.kind && list(k.fields).some((f) => field(f) && f.name === 'url'))
    .map((k) => ({ kind: k.kind, label: String(k.label || k.kind), fields: list(k.fields).filter(field) }));
  if (told.length) return told;
  return KINDS.map((kind) => ({
    kind,
    label: ALERTS_TEXT[`alerts_kind_${kind}`],
    fields: [
      { name: 'url', type: 'url', required: true, label: 'alerts_f_url', placeholder: PLACEHOLDERS[kind] },
      { name: 'secret', type: 'secret-name', required: false, label: 'alerts_f_secret', hint: 'alerts_secret_hint', placeholder: 'NTFY_LAB' },
    ],
  }));
}

/** What a destination of `kind` posts, read from the form's values by field:
    {url, secret, ...}. An address is trimmed, a secret is its name; a kind
    that asks for no secret posts none, so an old one is not kept. */
export function destinationValues(fields, read) {
  const out = {};
  for (const f of list(fields)) {
    const v = read(f.name);
    out[f.name] = f.type === 'secret-name' ? secretName(v) : f.type === 'select' ? String(v ?? '') : String(v ?? '').trim();
  }
  if (!('secret' in out)) out.secret = null;
  return out;
}
/** Whether a rule is on, as the server reads it (alerts.py `rule_on`): no
    `enabled` is on, `true` is on, anything else a hand edit left is off. */
export const ruleOn = (rule) => ((rule && rule.enabled) ?? true) === true;

/** What a rule can watch. */
export const TARGETS = ['place', 'collection', 'network', 'service'];
/** The digest's four conditions. */
export const CONDITIONS = ['cert_days', 'review_days', 'drift', 'uncharted'];

const list = (v) => (Array.isArray(v) ? v : []);
const blank = (v) => v === null || v === undefined || String(v).trim() === '';
const wholeIn = (v, lo, hi) => {
  if (blank(v)) return false;
  const n = Number(v);
  return Number.isInteger(n) && n >= lo && n <= hi;
};

/** "a", "a or b", "a, b or c" (`or` may be `and`). */
export function listWords(items, t = plainT, join = 'alerts_or') {
  const xs = list(items).filter((x) => !blank(x)).map(String);
  if (xs.length <= 1) return xs[0] || '';
  return `${xs.slice(0, -1).join(', ')} ${t(join)} ${xs[xs.length - 1]}`;
}

/** The states, in the server's list when it gives one, else ours. */
export function stateList(given) {
  const xs = list(given).filter((s) => typeof s === 'string' && s);
  return xs.length ? xs : STATES.slice();
}

/** A state as a checkbox's label ("Down"). */
export const stateLabel = (s, t = plainT) => (ALERTS_TEXT[`alerts_state_${s}`] ? t(`alerts_state_${s}`) : String(s));

/** A state after "goes" ("down", "into maintenance"). */
const goes = (s, t) => (ALERTS_TEXT[`alerts_go_${s}`] ? t(`alerts_go_${s}`) : String(s));

/** What a rule watches, from the map the browser holds: places are `nodes`,
    collections are `collections`, networks are `zones`. */
export function lookup(data, kind, id) {
  const d = data || {};
  if (kind === 'service') return services(d).find((s) => s.id === id) || null;
  const where = kind === 'place' ? d.nodes : kind === 'collection' ? d.collections : kind === 'network' ? d.zones : null;
  return list(where).find((x) => x && x.id === id) || null;
}

/** A service's key, as the server files it (signals.service_key): its Kuma
    monitor, else `<place id>/<label>` (stage 3b, 2026-11-15). */
export function serviceKey(placeId, link) {
  const monitor = link?.kuma;
  if (typeof monitor === 'string' && monitor) return monitor;
  return `${placeId}/${typeof link?.label === 'string' ? link.label : ''}`;
}

/** Every service on the map: {id: its key, name: "UI on Alpha", place, label}.
    Two links naming one monitor share a key; the first keeps it. */
export function services(data) {
  const out = [];
  const seen = new Set();
  for (const node of list(data?.nodes)) {
    if (!node || typeof node.id !== 'string') continue;
    for (const link of list(node.links)) {
      if (!link || typeof link !== 'object') continue;
      const id = serviceKey(node.id, link);
      if (seen.has(id)) continue;
      seen.add(id);
      const label = typeof link.label === 'string' && link.label ? link.label : id;
      out.push({ id, name: `${label} on ${node.name || node.id}`, place: node.id, label });
    }
  }
  return out;
}

/** The choices for the rule form's second pick, by name. */
export function targetOptions(data, kind) {
  const d = data || {};
  const where = kind === 'service' ? services(d)
    : kind === 'place' ? d.nodes : kind === 'collection' ? d.collections : kind === 'network' ? d.zones : null;
  return list(where)
    .filter((x) => x && typeof x.id === 'string')
    .map((x) => [x.id, String(x.name || x.id)])
    .sort((a, b) => a[1].localeCompare(b[1]));
}

/** "Core", "any place in the collection Web", "a place no longer on the map (core)". */
export function targetPhrase(target, data, t = plainT) {
  const kind = target?.kind;
  const id = target?.id;
  if (!TARGETS.includes(kind) || blank(id)) return t('alerts_t_nothing');
  // the map is not read yet: its id, rather than calling it gone
  if (!data) return t(`alerts_t_${kind}`, { name: id });
  const found = lookup(data, kind, id);
  if (!found) return t(`alerts_t_gone_${kind}`, { id });
  return t(`alerts_t_${kind}`, { name: found.name || id });
}

/** "1 minute", "5 minutes", "an hour", "2 hours". */
export function waitPhrase(minutes, t = plainT) {
  const n = Number(minutes) || 0;
  if (n >= 60 && n % 60 === 0) return n === 60 ? t('alerts_hour_one') : t('alerts_hour_many', { n: n / 60 });
  return n === 1 ? t('alerts_min_one') : t('alerts_min_many', { n });
}

const destName = (id, destinations) => {
  if (blank(id)) return '';
  const d = list(destinations).find((x) => x && x.id === id);
  return d ? String(d.name || d.id) : String(id);
};

/** The rule, in one sentence:
    "When Core goes down or degraded and stays for 5 minutes, send to Lab ntfy."
    "When any place in the collection Web goes down, send to Lab ntfy at once." */
export function ruleSentence(rule, { data, destinations } = {}, t = plainT) {
  const r = rule || {};
  const states = list(r.to).filter((s) => !blank(s));
  const vars = {
    target: targetPhrase(r.target, data, t),
    states: states.length ? listWords(states.map((s) => goes(s, t)), t) : t('alerts_go_none'),
    dest: destName(r.destination, destinations) || t('alerts_nowhere'),
  };
  const n = Number(r.for_minutes) || 0;
  if (n <= 0) return t('alerts_rule_now', vars);
  return t('alerts_rule_wait', { ...vars, wait: waitPhrase(n, t) });
}

/* ── what the page checks before it posts ───────────────────────────────── */

/** The default port a URL's scheme implies. */
const portOf = (u) => u.port || (u.protocol === 'https:' ? '443' : u.protocol === 'http:' ? '80' : '');

/** True when `url`'s host and port are in the allowed list. An entry is
    always `host:port`; a host listed without its port allows nothing (the
    server's rule), so the default port is never assumed. */
export function hostAllowed(url, hosts) {
  let u;
  try { u = new URL(url); } catch { return false; }
  const want = `${u.hostname.toLowerCase()}:${portOf(u)}`;
  return list(hosts).some((h) => String(h || '').trim().toLowerCase() === want);
}

/** A secret's name as the server reads it: upper case, letters, digits and _.
    Blank is null (no secret). */
export function secretName(raw) {
  const s = String(raw ?? '').trim().toUpperCase();
  return s || null;
}
const SECRET_RE = /^[A-Z0-9_]{1,40}$/;

/** The kinds as a sentence names them, from what each declares (2026-11-16):
    its theme word, else its label, so a kind added on the server needs no
    edit here. A label that opens with "A" or "An" ("A JSON webhook") reads
    in lower case inside the sentence. `kinds` are declarations or names. */
export function kindWords(kinds, t = plainT) {
  const word = (k) => {
    const key = `alerts_kind_${k.kind}`;
    const said = t(key);
    const w = said && said !== key ? said : String(k.label || k.kind);
    return w.replace(/^(A|An) /, (m) => m.toLowerCase());
  };
  return listWords(list(kinds).map((k) => (typeof k === 'string' ? { kind: k, label: k } : k))
    .filter((k) => k && typeof k.kind === 'string' && k.kind).map(word), t);
}

/** Problems with a destination, by field: [{field, text}]. Empty means it may
    be posted. `hosts` is the allowed list from the status (an empty list
    skips that check: the server decides). `kinds` are the kinds the server
    can send to, as declared (`kindList`) or by name; none given, the three.
    A declared field that is required (Discord's secret) is asked for. The
    path rules here are ntfy's and Gotify's; another kind's own rule is the
    server's, and its answer is put beside the address. */
export function checkDestination(dest, { hosts, kinds } = {}, t = plainT) {
  const d = dest || {};
  const out = [];
  const offered = list(kinds).length ? list(kinds) : kindList();
  const known = offered.map((k) => (typeof k === 'string' ? k : k?.kind));
  if (blank(d.name)) out.push({ field: 'name', text: t('alerts_need_name') });
  if (!known.includes(d.kind)) out.push({ field: 'kind', text: t('alerts_need_kind', { kinds: kindWords(offered, t) }) });
  if (blank(d.url)) out.push({ field: 'url', text: t('alerts_need_url') });
  else {
    let u = null;
    try { u = new URL(String(d.url).trim()); } catch { /* below */ }
    if (!u || !['https:', 'http:'].includes(u.protocol)) out.push({ field: 'url', text: t('alerts_bad_url') });
    else if (u.username || u.password) out.push({ field: 'url', text: t('alerts_bad_userinfo') });
    else if (u.search || String(d.url).includes('?')) out.push({ field: 'url', text: t('alerts_bad_query') });
    else if (u.hash || String(d.url).includes('#')) out.push({ field: 'url', text: t('alerts_bad_fragment') });
    else if (d.kind === 'ntfy' && !u.pathname.replace(/\//g, '')) out.push({ field: 'url', text: t('alerts_bad_ntfy') });
    else if (d.kind === 'gotify' && u.pathname.replace(/\/+$/, '') && !u.pathname.replace(/\/+$/, '').endsWith('/message')) {
      out.push({ field: 'url', text: t('alerts_bad_gotify') });
    } else if (list(hosts).length && !hostAllowed(u.href, hosts)) {
      out.push({ field: 'url', text: t('alerts_bad_host', { host: `${u.hostname}:${portOf(u)}` }) });
    }
  }
  const secret = secretName(d.secret);
  if (secret && !SECRET_RE.test(secret)) out.push({ field: 'secret', text: t('alerts_bad_secret') });
  const declared = offered.find((k) => k && typeof k === 'object' && k.kind === d.kind);
  if (!secret && list(declared?.fields).some((f) => f && f.name === 'secret' && f.required === true)) {
    out.push({ field: 'secret', text: t('alerts_need_secret') });
  }
  return out;
}

/** Problems with a rule, by field: [{field, text}]. */
export function checkRule(rule, { destinations } = {}, t = plainT) {
  const r = rule || {};
  const out = [];
  if (blank(r.name)) out.push({ field: 'name', text: t('alerts_need_name') });
  if (!TARGETS.includes(r.target?.kind) || blank(r.target?.id)) out.push({ field: 'target', text: t('alerts_need_target') });
  if (!list(r.to).filter((s) => !blank(s)).length) out.push({ field: 'to', text: t('alerts_need_state') });
  if (!wholeIn(r.for_minutes ?? 0, 0, 1440)) out.push({ field: 'for_minutes', text: t('alerts_need_minutes') });
  if (!list(destinations).length) out.push({ field: 'destination', text: t('alerts_need_dest_first') });
  else if (blank(r.destination)) out.push({ field: 'destination', text: t('alerts_need_dest') });
  return out;
}

/** Problems with the daily digest, by field. Its hour and days are checked
    whether it is sent or not (the server keeps them either way); a
    destination is asked for only when it is sent. */
export function checkDigest(digest, { destinations } = {}, t = plainT) {
  const g = digest || {};
  const out = [];
  if (!wholeIn(g.hour, 0, 23)) out.push({ field: 'hour', text: t('alerts_need_hour') });
  if (!wholeIn(g.cert_days, 1, 365)) out.push({ field: 'cert_days', text: t('alerts_need_cert_days') });
  if (!wholeIn(g.review_days, 1, 3650)) out.push({ field: 'review_days', text: t('alerts_need_review_days') });
  if (g.enabled) {
    if (!list(destinations).length) out.push({ field: 'destination', text: t('alerts_need_dest_first') });
    else if (blank(g.destination)) out.push({ field: 'destination', text: t('alerts_need_dest') });
  }
  return out;
}

/** The ids already taken make a new one from a name: `lab-ntfy`, `lab-ntfy-2`. */
export function slugFor(name, taken = [], fallback = 'alert') {
  const base = String(name ?? '').toLowerCase().normalize('NFKD').replace(/[^\w\s-]/g, '')
    .trim().replace(/[\s_]+/g, '-').replace(/-+/g, '-').replace(/^-|-$/g, '').slice(0, 60) || fallback;
  const have = new Set(list(taken));
  if (!have.has(base)) return base;
  for (let i = 2; ; i++) if (!have.has(`${base}-${i}`)) return `${base}-${i}`;
}

/** Which field a server sentence is about, from its words. Order matters:
    "a destination that does not exist" is the rule's destination, and "The
    address carries a user name or password… Name a secret instead" is the
    address, not the name or the secret. */
const FIELD_WORDS = [
  [/sends to a destination|destination that does not exist/i, 'destination'],
  [/address|url\b|ATLAS_ALERT_HOSTS|\bport\b|\bhost\b|topic|loopback/i, 'url'],
  [/secret/i, 'secret'],
  [/\bnote\b/i, 'note'],
  [/\bname\b/i, 'name'],
  [/target|cannot be alerted/i, 'target'],
  [/\bstates?\b/i, 'to'],
  [/how long|minutes/i, 'for_minutes'],
  [/\bkind\b/i, 'kind'],
  [/\bhour\b/i, 'hour'],
  [/certificate days/i, 'cert_days'],
  [/review days/i, 'review_days'],
  [/\bdrift\b/i, 'drift'],
  [/uncharted/i, 'uncharted'],
  [/\benabled\b/i, 'enabled'],
];
export const fieldOfSentence = (text) => FIELD_WORDS.find(([re]) => re.test(text))?.[1] || '';

/** The server's 422 problems, sorted to the thing being edited.

    A problem is a sentence that names what it is about ("rule core-down: it
    needs one or more states…", "destination lab: …", "digest: …"), or an
    object naming where it is (`field`, `path` or `where`) and what
    (`message`, `problem` or `error`). `label` is how the server names the
    edited item (`rule core-down`, `destination lab`, `digest`) and `prefix`
    its place in the document (`rules[2]`, `destinations.0`); a problem about
    it is filed by its field (`byField`), or in `mine` when no field can be
    told. Anything about another item is `general`, said as the server said
    it. */
export function sortProblems(problems, prefix = '', label = '') {
  const byField = {};
  const general = [];
  const mine = [];
  const want = String(prefix || '');
  const forms = want ? [want, want.replace(/\[(\d+)\]/, '.$1'), want.replace(/\.(\d+)$/, '[$1]')] : [];
  for (const p of list(problems)) {
    if (p && typeof p === 'object') {
      const where = String(p.field ?? p.path ?? p.where ?? '');
      const text = String(p.message ?? p.problem ?? p.error ?? JSON.stringify(p));
      const hit = forms.find((f) => where === f || where.startsWith(`${f}.`) || where.startsWith(`${f}[`));
      if (hit && where !== hit) {
        const field = where.slice(hit.length).replace(/^[.[]/, '').split(/[.[\]]/)[0];
        (byField[field] = byField[field] || []).push(text);
      } else general.push(where && !hit ? `${where}: ${text}` : text);
    } else if (!blank(p)) {
      const text = String(p);
      if (label && text.startsWith(`${label}: `)) {
        const rest = text.slice(label.length + 2);
        const field = fieldOfSentence(rest);
        const said = rest.charAt(0).toUpperCase() + rest.slice(1);
        if (field) (byField[field] = byField[field] || []).push(said);
        else mine.push(said);
      } else general.push(text);
    }
  }
  return { byField, general, mine };
}

/* ── on and off ──────────────────────────────────────────────────────────── */

/** The ids of the rules the server has suspended (their target is hidden
    from a viewer with no groups): `status.suspended`, or a rule's own flag. */
export function suspendedIds(body) {
  const ids = new Set(list(body?.status?.suspended ?? body?.suspended).map(String));
  for (const r of list(body?.doc?.rules)) if (r && r.suspended === true) ids.add(String(r.id));
  return ids;
}

/** True when the poll that alerts ride on is running. */
export const pollRunning = (status) => Number(status?.poll_seconds) > 0 && status?.poll_running !== false;

/** What the page says about being on or off, from the server's status.
    `off` hides every form: then `lines` say how to turn it on. `notes` are
    true either way and stand on the status strip: the poll is off (nothing
    fires) or no public URL is set (messages carry no link). With no host
    listed the page cannot tell whether ATLAS_ALERTS is set, so it names both. */
export function onOff(status, t = plainT) {
  const s = status || {};
  const hosts = list(s.hosts);
  // `on` is the server's whole answer (the flag and a host); `enabled` is the flag
  const off = typeof s.on === 'boolean' ? !s.on : !(s.enabled === true && hosts.length > 0);
  const lines = [];
  if (off) {
    if (s.enabled === true) lines.push(t('alerts_off_hosts'));
    else lines.push(hosts.length ? t('alerts_off_flag') : t('alerts_off_both'));
    lines.push(t('alerts_off_restart'));
  }
  const notes = [];
  if (!(Number(s.poll_seconds) > 0)) notes.push(t('alerts_poll_needed'));
  else if (s.poll_running === false) notes.push(t('alerts_poll_dead'));
  if (s.public_url_set !== true) notes.push(t('alerts_no_link'));
  return { off, title: off ? t('alerts_off_title') : '', lines, notes };
}

/** A time from the server (ISO text, or seconds or ms since 1970) as ms. */
export function toMs(when) {
  if (when === null || when === undefined || when === '') return null;
  if (typeof when === 'number') return when > 1e12 ? when : when * 1000;
  const ms = Date.parse(when);
  return Number.isNaN(ms) ? null : ms;
}

/** The status strip's pieces after On/Off: hosts, the poll, the last look. */
export function statusBits(status, clock, t = plainT) {
  const s = status || {};
  const hosts = list(s.hosts);
  const bits = [hosts.length ? t('alerts_hosts', { hosts: hosts.join(', ') }) : t('alerts_no_hosts')];
  bits.push(pollRunning(s) ? t('alerts_poll', { n: Number(s.poll_seconds) })
    : Number(s.poll_seconds) > 0 ? t('alerts_poll_stopped') : t('alerts_poll_off'));
  const at = toMs(s.last_tick);
  bits.push(at === null ? t('alerts_tick_never') : t('alerts_tick', { when: clock(at) }));
  return bits;
}

/* ── the digest ─────────────────────────────────────────────────────────── */

/** Whether the server can include devices a source sees and the map has not
    charted. It says so (`supports.uncharted`, or `status.uncharted`), or it
    gives a reason (`unsupported.uncharted`, or a problem naming `uncharted`);
    a page that cannot tell shows it off, "not supported yet". */
export function unchartedSupport(body, t = plainT) {
  const b = body || {};
  if (b.supports?.uncharted === true || b.status?.uncharted === true) return { ok: true, why: '' };
  const said = b.unsupported?.uncharted ?? b.status?.uncharted_why;
  if (typeof said === 'string' && said.trim()) return { ok: false, why: said.trim() };
  for (const p of list(b.problems)) {
    const text = typeof p === 'string' ? p : String(p?.message ?? p?.problem ?? '');
    const where = typeof p === 'object' && p ? String(p.field ?? p.path ?? '') : '';
    if (/uncharted/i.test(where) || /uncharted/i.test(text)) return { ok: false, why: text };
  }
  return { ok: false, why: t('alerts_unsupported') };
}

const hh = (h) => `${String(Number(h) || 0).padStart(2, '0')}:00`;

/** The digest in one sentence:
    "Every day at 08:00, send to Lab ntfy: certificates lapsing within 30 days
    and places not checked in 90 days." The certificates and the places are
    always in it; drift (and uncharted devices, once the server can) are picks. */
export function digestSentence(digest, { destinations } = {}, t = plainT) {
  const g = digest || {};
  if (!g.enabled) return t('alerts_digest_off');
  const what = [
    t('alerts_d_certs', { n: Number(g.cert_days) || 0 }),
    t('alerts_d_review', { n: Number(g.review_days) || 0 }),
  ];
  if (g.drift) what.push(t('alerts_d_drift'));
  if (g.uncharted) what.push(t('alerts_d_uncharted'));
  const vars = { hour: hh(g.hour), dest: destName(g.destination, destinations) || t('alerts_nowhere') };
  return t('alerts_digest_line', { ...vars, what: listWords(what, t, 'alerts_and') });
}

/* ── a send's outcome, and the log ───────────────────────────────────────── */

/** "delivered", "refused (HTTP 403)", "unreachable", "blocked". Nothing of
    the response itself is ever shown: the server sends none. */
export function outcomeWord(outcome, status, t = plainT) {
  if (outcome === 'refused') {
    return Number(status) > 0 ? t('alerts_o_refused_status', { status: Number(status) }) : t('alerts_o_refused');
  }
  if (['delivered', 'unreachable', 'blocked'].includes(outcome)) return t(`alerts_o_${outcome}`);
  return String(outcome || '');
}

/** The tone a row or a test's answer wears: up, warn (refused) or down. */
export const outcomeTone = (outcome) => (outcome === 'delivered' ? 'up' : outcome === 'refused' ? 'warn' : 'down');

/** A test's answer: the outcome word, and the server's short why. */
export function testLine(answer, t = plainT) {
  const a = answer || {};
  const word = outcomeWord(a.outcome, a.status, t);
  const why = blank(a.why) ? '' : String(a.why).trim();
  return why && a.outcome !== 'delivered' ? `${word}: ${why}` : word;
}

/** The log as the page shows it: newest first. */
export function newestFirst(rows) {
  return list(rows).filter((r) => r && typeof r === 'object')
    .slice().sort((a, b) => (toMs(b.at) ?? 0) - (toMs(a.at) ?? 0));
}

/** One line of the delivery log, in a sentence:
    "Rule “Core down”, 2 changes, to Lab ntfy: delivered."
    "A test to Lab ntfy: refused (HTTP 403)." */
export function deliveryLine(row, { rules, destinations } = {}, t = plainT) {
  const r = row || {};
  let what;
  if (blank(r.rule) || r.rule === 'test') what = t('alerts_l_test');
  else if (r.rule === 'digest') what = t('alerts_l_digest');
  else if (r.rule === 'fold') what = t('alerts_l_fold');
  else {
    const rule = list(rules).find((x) => x && x.id === r.rule);
    what = t('alerts_l_rule', { rule: rule?.name || r.rule });
  }
  const n = Array.isArray(r.events) ? r.events.length : Number(r.events) || 0;
  const dest = destName(r.destination, destinations) || t('alerts_nowhere');
  let outcome = outcomeWord(r.outcome, r.status, t);
  if (!blank(r.why) && r.outcome !== 'delivered') outcome += `: ${String(r.why).trim()}`;
  return n > 0
    ? t('alerts_l_line_n', { what, count: n === 1 ? t('alerts_l_one') : t('alerts_l_many', { n }), dest, outcome })
    : t('alerts_l_line', { what, dest, outcome });
}

/** The ANNALS' note beside an event that caused a send: "sent to Lab ntfy",
    "sent to Lab ntfy and Phone". '' when it caused none. */
export function sentNote(sent, t = plainT) {
  const names = [...new Set(list(sent).map((s) => (s && typeof s === 'object' ? s.to : s))
    .filter((x) => !blank(x)).map(String))];
  return names.length ? t('annals_sent', { to: listWords(names, t, 'alerts_and') }) : '';
}

/** A destination's address as the list shows it: the scheme, host and port,
    and only the last four characters of the path. A path can carry a token (an
    open ntfy topic IS its secret, a webhook's `/id/token`), and the list may be
    on a shared screen; the edit form still shows the whole address. */
export function shownAddress(raw) {
  let u;
  try { u = new URL(String(raw ?? '')); } catch { return ''; }
  const path = u.pathname.replace(/\/+$/, '');
  if (!path) return `${u.protocol}//${u.host}`;
  return `${u.protocol}//${u.host}/…${path.slice(-4)}`;
}

/* ── which rules reach a place (2026-11-14, alerts inside NODES) ────────── */

/** A rule's target as today's kind and a text id, or null when it names
    nothing (a hand edit's list or number). A rule saved when collections were
    sets says `set`; the server reads it back as a collection already, and so
    does this. */
export function targetOf(rule) {
  const tg = rule && typeof rule === 'object' ? rule.target : null;
  if (!tg || typeof tg !== 'object' || typeof tg.id !== 'string' || !tg.id) return null;
  const kind = tg.kind === 'set' ? 'collection' : tg.kind;
  return TARGETS.includes(kind) ? { kind, id: tg.id } : null;
}

/** The rules on exactly this target, in the document's order. */
export function rulesOn(rules, kind, id) {
  return list(rules).filter((r) => {
    const tg = targetOf(r);
    return tg !== null && tg.kind === kind && tg.id === id;
  });
}

/** The rules that reach one place, as the server matches them (alerts.py
    `_matches`): its own, each of its collections', its network's. `row` is a
    roster row: {id, zone, collections: [ids]}. `count` is all of them, `on`
    the ones switched on. */
export function rulesCovering(rules, row) {
  const own = [];
  const network = [];
  const byCollection = new Map();
  const id = row && typeof row.id === 'string' ? row.id : '';
  const zone = row && typeof row.zone === 'string' ? row.zone : '';
  const mine = new Set(list(row?.collections).filter((c) => typeof c === 'string'));
  for (const r of list(rules)) {
    const tg = targetOf(r);
    if (!tg) continue;
    if (tg.kind === 'place' && tg.id === id) own.push(r);
    else if (tg.kind === 'collection' && mine.has(tg.id)) {
      if (!byCollection.has(tg.id)) byCollection.set(tg.id, []);
      byCollection.get(tg.id).push(r);
    } else if (tg.kind === 'network' && zone && tg.id === zone) network.push(r);
  }
  const all = [...own, ...[...byCollection.values()].flat(), ...network];
  return {
    own,
    collections: [...byCollection].map(([cid, rs]) => ({ id: cid, rules: rs })),
    network,
    count: all.length,
    on: all.filter(ruleOn).length,
  };
}

/** The targets of a kind that some rule watches, for the rail's bell. */
export function watchedIds(rules, kind) {
  const out = new Set();
  for (const r of list(rules)) {
    const tg = targetOf(r);
    if (tg && tg.kind === kind) out.add(tg.id);
  }
  return out;
}

/** The rules NODES has no bell for, so they can be reached only from
    Settings › Alerts: they name nothing, or a place, collection or network
    that is not on the map (a network is in THE RAIL only while a place is in
    it). A paused rule counts too. Null while the map is not read yet. */
export function unreachableRules(rules, data) {
  if (!data || typeof data !== 'object') return null;
  const nodes = list(data.nodes).filter((n) => n && typeof n.id === 'string');
  const places = new Set(nodes.map((n) => n.id));
  const collections = new Set(list(data.collections).filter((c) => c && typeof c.id === 'string').map((c) => c.id));
  const zones = new Set(list(data.zones).filter((z) => z && typeof z.id === 'string').map((z) => z.id));
  const peopled = new Set(nodes.map((n) => n.zone).filter((z) => typeof z === 'string' && zones.has(z)));
  const keys = new Set(services(data).map((s) => s.id));
  return list(rules).filter((r) => r && typeof r === 'object').filter((r) => {
    const tg = targetOf(r);
    if (!tg) return true;
    if (tg.kind === 'place') return !places.has(tg.id);
    if (tg.kind === 'collection') return !collections.has(tg.id);
    if (tg.kind === 'service') return !keys.has(tg.id);
    return !peopled.has(tg.id);
  });
}

/** The rules that reach one service (stage 3b): its own, and each rule on a
    collection whose `services` hold it, as the server matches them. */
export function rulesReachingService(rules, key, collections) {
  const holding = new Set(list(collections)
    .filter((c) => c && typeof c.id === 'string' && list(c.services).includes(key)).map((c) => c.id));
  return list(rules).filter((r) => {
    const tg = targetOf(r);
    return tg !== null && ((tg.kind === 'service' && tg.id === key) || (tg.kind === 'collection' && holding.has(tg.id)));
  });
}
