/* CONNECTIONS, the rules with no DOM.

   What connections.js shows and what connection-review.js lets an admin tick
   are decided here: the setup lines for each harness, the sentence that says
   what a kind of token reads, which review rows can be ticked, what a tick
   brings with it, and what ignoring a host does to what stands on it. Pure
   functions over plain rows, so tests/test_connections_model.mjs can pin them
   under node. */

/* Formats change, so each was read from the harness's own docs on 2026-10-31.
   Gemini takes the header's value literally in settings.json, so it gets the
   token itself or the placeholder, never a variable. `url` is the MCP address
   and `readUrl` the REST one, both absolute. */
export function setups(token, forKind, url, readUrl) {
  const shown = token || 'PASTE_YOUR_TOKEN';
  /* A token is made for one or the other, and gets the lines for that. A full
     token is never shown beside a cloud tool's command: the way to connect one
     is to make it a cloud token. */
  const cloud = (vendor) => `Cloud model: what this token reads is sent to ${vendor}. `;
  if (forKind !== 'cloud') {
    return {
      local: { name: 'Local model', lang: 'any MCP client',
        note: 'For Ollama, LM Studio or your own harness: point any client that speaks MCP over HTTP at this address. Answers stay on your network.',
        text: `URL:    ${url}\nHeader: Authorization: Bearer ${shown}` },
      rest: { name: 'REST', lang: 'shell',
        note: 'The same token reads lab-data, maps, signals, rites and events under api/v2. The reference is api/v2/openapi.json.',
        text: `curl -H "Authorization: Bearer ${shown}" ${readUrl}` },
    };
  }
  return {
    claude: { name: 'Claude Code (cloud)', lang: 'shell',
      note: cloud('Anthropic') + 'Then run claude mcp list to check it.',
      text: `export ATLAS_TOKEN="${shown}"\nclaude mcp add --transport http --scope user atlas ${url} --header "Authorization: Bearer $ATLAS_TOKEN"` },
    codex: { name: 'Codex (cloud)', lang: '~/.codex/config.toml',
      note: cloud('OpenAI') + 'The file names the variable, so the token stays out of it. Set ATLAS_TOKEN before starting Codex.',
      text: `[mcp_servers.atlas]\nurl = "${url}"\nbearer_token_env_var = "ATLAS_TOKEN"` },
    gemini: { name: 'Gemini CLI (cloud)', lang: '~/.gemini/settings.json',
      note: cloud('Google') + 'This file holds the token in plain text, so never commit it. Check with /mcp.',
      text: JSON.stringify({ mcpServers: { atlas: { httpUrl: url, headers: { Authorization: `Bearer ${shown}` } } } }, null, 2) },
    other: { name: 'Another cloud tool', lang: 'any MCP client',
      note: 'Any client that speaks MCP over HTTP. What this token reads is sent to that tool\u2019s vendor.',
      text: `URL:    ${url}\nHeader: Authorization: Bearer ${shown}` },
  };
}

/* What each kind reads, said where the choice is made. The cloud line carries
   this map's own numbers: a cloud token reads only what a person has checked. */
export function kindNote(tok, kind) {
  if (kind !== 'cloud') {
    return 'Reads everything on the map a viewer with no groups could, addresses included, on every '
      + 'route. For a model or a script that runs on your own network.';
  }
  const v = tok.cloud_view;
  const count = v && (v.readable + v.withheld) ? ` That is ${v.readable} of ${v.readable + v.withheld} places on this map.` : '';
  const empty = v && !v.readable && v.withheld ? ' Check places in the Desk first, or the tool reads an empty map.' : '';
  return 'Reads only places a person has checked and nothing has changed since.' + count + empty
    + ' No addresses, MAC addresses, URLs, hardware or notes, and through the MCP address only.'
    + ' The names of those places, what they are for and how they connect still go to the tool\u2019s vendor.';
}

/* ── the review ───────────────────────────────────────────────────────── */

export const tickable = (r) => (r.status === 'new' || r.status === 'clash') && !r.blocked;

export function groupsOf(rows) {
  const groups = new Map();
  for (const r of rows) groups.set(r.group, [...(groups.get(r.group) || []), r]);
  return groups;
}

/* What stands on a host: a service or a port on it, a link with it at either end.
   A guest and a monitor do not: a guest can land without its host, and a monitor
   is tied to a place already on the map. */
const STANDS = new Set(['service', 'port', 'route']);
export const standsOn = (r, key) => STANDS.has(r.type) && (r.parent === key || r.peer === key);

/** Ticking a service, a port or a link ticks what it stands on, and unticking a
    host unticks what stood on it. Returns the keys to tick and to untick; the
    caller skips a box that is not drawn or cannot be ticked. */
export function follow(rows, key, checked) {
  const row = rows.find((r) => r.key === key);
  const tick = [];
  const untick = [];
  if (checked && STANDS.has(row.type)) {
    for (const end of [row.parent, row.peer]) {
      if (end) tick.push(end);
    }
  }
  if (!checked) {
    for (const r of rows) {
      if (standsOn(r, key)) untick.push(r.key);
    }
  }
  return { tick, untick };
}

export function ignoreLocally(view, key, ignoring) {
  const row = view.rows.find((r) => r.key === key);
  if (ignoring) { row.was = row.status; row.status = 'ignored'; } else { row.status = row.was || 'new'; }
  for (const r of view.rows) {
    if (standsOn(r, key) && r.status !== 'charted') {
      r.blocked = ignoring;
      r.note = ignoring ? `${row.name} is ignored.` : '';
    }
  }
}

/* ── where a token may come from, and what it read ──────────────────────────
   Plain text out; the page escapes it. A tool's arguments are a client's words. */

/* A token's binding, as the list says it. */
export function fromWords(networks) {
  if (!networks || !networks.length) return 'from any address';
  if (networks.length === 1 && networks[0] === 'lan') return 'local network only';
  return `only from ${networks.map((n) => (n === 'lan' ? 'the local network' : n)).join(', ')}`;
}

/* Said beside the tick, with the address this Atlas sees the admin at. If that
   address is not a local one the admin is reaching Atlas through something it
   has not been told about, or from outside, and the binding needs a second look. */
export function bindNote(you) {
  const base = 'Bound to the local network, a token is refused from anywhere else, so a copy that '
    + 'leaks is no use from outside. It does not limit what a tool on your network does with what it reads.';
  if (!you || !you.ip) return base;
  return you.local
    ? `${base} This Atlas sees you at ${you.ip}. If that is a proxy's address and not your own, `
      + 'name the proxy in ATLAS_TRUSTED_PROXIES, or every caller will look local.'
    : `${base} This Atlas sees you at ${you.ip}, which is not a local address: a tool where you are `
      + 'would be refused.';
}

const size = (n) => (n >= 1024 * 1024 ? `${(n / 1048576).toFixed(1)} MB`
  : n >= 1024 ? `${Math.round(n / 1024)} KB` : `${n} B`);

/* A client's words on one line: a line break in an argument must not be able to
   draw what looks like a second entry in the list. */
const oneLine = (text) => String(text).replace(/[\r\n\u2028\u2029\u0085]+/g, ' ');

/* One line of the read log. */
export function readLine(row) {
  const args = row.args && Object.keys(row.args).length
    ? ` ${Object.entries(row.args).map(([k, v]) => `${k}=${oneLine(typeof v === 'string' ? v : JSON.stringify(v))}`).join(' ')}`
    : '';
  const what = row.tool ? `${row.tool}${args}` : row.method ? row.method : row.path;
  const bits = [row.at, `from ${row.ip || 'an unknown address'}`, what];
  if (row.refused) bits.push(`refused: ${row.refused}`);
  else {
    if (typeof row.places === 'number') bits.push(`${row.places} place${row.places === 1 ? '' : 's'}`);
    if (typeof row.bytes === 'number') bits.push(size(row.bytes));
    if (row.status >= 400) bits.push(`answered ${row.status}`);
  }
  return bits.join(' · ');
}

/* The sentence above the lines. */
export function readsHead(rows, days, name) {
  if (!rows.length) return `Nothing has been read with "${name}" in the last ${days} days.`;
  return `The last ${rows.length} request${rows.length === 1 ? '' : 's'} made with "${name}", newest first. `
    + `Kept for ${days} days. The answers are not stored: each line has the size and, in the file, a hash.`;
}
