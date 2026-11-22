
export function setups(token, forKind, url, readUrl) {
  const shown = token || 'PASTE_YOUR_TOKEN';
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


export const tickable = (r) => (r.status === 'new' || r.status === 'clash') && !r.blocked;

export function groupsOf(rows) {
  const groups = new Map();
  for (const r of rows) groups.set(r.group, [...(groups.get(r.group) || []), r]);
  return groups;
}

const STANDS = new Set(['service', 'port', 'route']);
export const standsOn = (r, key) => STANDS.has(r.type) && (r.parent === key || r.peer === key);

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

export const differs = (r) => r.type === 'cable' && r.blocked === true
  && Array.isArray(r.differs) && r.differs.length > 0 && r.status !== 'ignored';

export function cableState(r) {
  if (r.updates) return 'updates the cable it gave before';
  return 'a new cable, port to port';
}

export function reviewCounts(rows) {
  return {
    fresh: rows.filter(tickable).length,
    charted: rows.filter((r) => r.status === 'charted').length,
    differ: rows.filter(differs).length,
    ignored: rows.filter((r) => r.status === 'ignored').length,
  };
}

export function countsLine({ fresh, charted, differ, ignored }) {
  return [`${fresh} new`, `${charted} already on the map`,
    differ ? `${differ} cable${differ === 1 ? '' : 's'} the map has otherwise` : '',
    ignored ? `${ignored} ignored` : ''].filter(Boolean).join(' · ');
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


export function fromWords(networks) {
  if (!networks || !networks.length) return 'from any address';
  if (networks.length === 1 && networks[0] === 'lan') return 'local network only';
  return `only from ${networks.map((n) => (n === 'lan' ? 'the local network' : n)).join(', ')}`;
}

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

const oneLine = (text) => String(text).replace(/[\r\n\u2028\u2029\u0085]+/g, ' ');

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

export function readsHead(rows, days, name) {
  if (!rows.length) return `Nothing has been read with "${name}" in the last ${days} days.`;
  return `The last ${rows.length} request${rows.length === 1 ? '' : 's'} made with "${name}", newest first. `
    + `Kept for ${days} days. The answers are not stored: each line has the size and, in the file, a hash.`;
}
