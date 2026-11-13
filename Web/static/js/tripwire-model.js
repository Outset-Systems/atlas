/* TRIPWIRES' reading rules, with no DOM (v1.52.0).

   The scene (stones.js) and the map layer (decoys.js) both answer "which
   tripwire has been touched, and is anybody listening?". With the admin read
   `GET /api/v2/tripwires` in hand they read its states and its per-source
   contact; without it (a viewer who is not an admin, an older server) they
   fall back to the decoy feed alone, as before. Unit-tested by
   tests/test_tripwire_model.mjs under plain node. */

/* The overview's three states, mapped onto the scene's voices. The voice
   names stay the scene's CSS classes; the WORDS are theme text. */
const VOICE_OF_STATE = { lit: 'speaking', stirred: 'stirred', quiet: 'silent' };
const RANK = { speaking: 0, stirred: 1, unheard: 1.5, silent: 2 };

const voiceOf = (v) => (v in RANK ? v : 'unheard');

/** The family a tripwire belongs to when the row does not say. Mirrors
    schema.stone_family: `honeypot-*` kinds are honeypots, the rest tokens. */
export function familyOf(t) {
  const f = String(t?.family || '').trim();
  if (f === 'honeypot' || f === 'token') return f;
  return String(t?.kind || '').startsWith('honeypot') ? 'honeypot' : 'token';
}

/** Per-source contact → the head's verdict.
    'unset'  nothing is configured to listen at all;
    'lost'   a configured source is not answering (named in `lost`);
    'ok'     every configured source is answering;
    'waiting' the only source is a webhook nothing has reached yet.
    `waiting` also says so beside a source that does answer. */
export function listening(sources) {
  const d = sources?.decoys || {};
  const w = sources?.webhook || {};
  const on = [];
  const lost = [];
  if (d.contact && d.contact !== 'off') (d.contact === 'ok' ? on : lost).push('decoys');
  if (w.contact === 'ok') on.push('webhook');
  const waiting = w.contact === 'waiting';
  if (!on.length && !lost.length) return { verdict: waiting ? 'waiting' : 'unset', on, lost, waiting };
  return { verdict: lost.length ? 'lost' : 'ok', on, lost, waiting };
}

/** The legacy (feed-only) sources object as the same shape: lets the head
    speak one language whichever read it had. */
export function legacySources(signalsSources) {
  if (!signalsSources || !('deception' in signalsSources)) {
    return { decoys: { contact: 'off' }, webhook: { contact: 'off' } };
  }
  return { decoys: { contact: signalsSources.deception === 'ok' ? 'ok' : 'lost' },
           webhook: { contact: 'off' } };
}

/** One roster, loudest first. With an overview its rows are the truth (it
    already merged chart, feed and webhook trips); without one, the chart
    merged with the feed, feed winning — the scene's original rule. */
export function roster({ overview = null, charted = [], live = {} } = {}) {
  let rows;
  if (overview && Array.isArray(overview.tripwires)) {
    rows = overview.tripwires.map((t) => ({ ...t, voice: VOICE_OF_STATE[t.state] || 'unheard' }));
    /* A stone the decoy feed reports but the map has not charted is still
       listed: the engine is the authority on what is planted, and hiding one
       would be the map deciding a real tripwire does not exist. (A deployment
       whose stones live only in the engine showed an empty scene in v1.52.0
       until this was restored, 2026-10-20.) */
    const have = new Set(rows.map((t) => String(t.id)));
    for (const [id, info] of Object.entries(live || {})) {
      if (have.has(String(id))) continue;
      rows.push({ id, ...info, voice: voiceOf(info?.state), uncharted: true });
    }
  } else {
    const byId = new Map();
    for (const s of charted) if (s && s.id) byId.set(s.id, { ...s });
    for (const [id, info] of Object.entries(live || {})) {
      byId.set(id, { ...(byId.get(id) || { id }), ...info, id });
    }
    rows = [...byId.values()].map((s) => ({ ...s, voice: voiceOf(s.state) }));
  }
  return rows.sort((a, z) => (RANK[a.voice] - RANK[z.voice])
    || String(a.name || a.id).localeCompare(String(z.name || z.id)));
}

/** Rows grouped for the scene: honeypots first (they answer), then tokens. */
export function byFamily(rows) {
  const out = { honeypot: [], token: [] };
  for (const r of rows) out[familyOf(r)].push(r);
  return out;
}

/** "3m ago" — the one question asked of a stamp here is how fresh it is. */
export function ago(iso, now = Date.now()) {
  if (!iso) return null;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return null;
  const s = Math.max(0, Math.round((now - t) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

const SOURCE_WORD = { opencanary: 'OpenCanary', canarytokens: 'Canarytokens',
                      generic: 'webhook', decoys: 'the decoy feed' };

/** A trip as one plain line of TEXT (the caller escapes it): what, from
    where, through which sender, how often. Every part is optional because
    every part of a trip is optional. */
export function tripLine(trip, now = Date.now()) {
  if (!trip) return '';
  const parts = [];
  const when = ago(trip.last_at || trip.at, now);
  parts.push(trip.signal ? String(trip.signal) : 'tripped');
  if (trip.src) parts.push(`from ${trip.src}${trip.port ? `:${trip.port}` : ''}`);
  else if (trip.port) parts.push(`on port ${trip.port}`);
  parts.push(`via ${SOURCE_WORD[trip.source] || trip.source || 'unknown'}`);
  if ((trip.count | 0) > 1) parts.push(`×${trip.count | 0}`);
  if (when) parts.push(when);
  return parts.join(' · ');
}

/** The expiry note for a canary token, or null. */
export function expiryNote(t) {
  const d = t?.expires_in_days;
  if (typeof d !== 'number') return null;
  if (d < 0) return { level: 'expired', text: `expired ${-d}d ago` };
  if (d <= 14) return { level: 'soon', text: `expires in ${d}d` };
  return { level: 'later', text: `expires ${t.expires}` };
}

/** Node id → loudest voice + count, for the map layer. Retired tripwires
    leave the map; a lost watch draws every eye as unheard. */
export function watchByNode(rows, lost) {
  const nodes = new Map();
  let unplaced = 0, speaking = 0, total = 0;
  for (const r of rows) {
    if (r.retired) continue;
    total++;
    const voice = lost ? 'unheard' : r.voice;
    if (voice === 'speaking') speaking++;
    if (!r.host) { unplaced++; continue; }
    const cur = nodes.get(r.host);
    if (!cur) nodes.set(r.host, { voice, count: 1 });
    else {
      cur.count++;
      if (RANK[voice] < RANK[cur.voice]) cur.voice = voice;
    }
  }
  return { nodes, unplaced, speaking, total };
}
