/* CONNECTIONS — one Settings section for everything that talks to this Atlas.

   Two directions, kept apart because they are different promises. TOOLS READ THE
   MAP: an API token, then the exact setup for each harness. THE ATLAS READS
   SYSTEMS: a card per system with a real test, on the shape of SolarWinds' one
   credential library and Zabbix's one list of integrations.

   A token appears once, here, right after it is issued; the server keeps only a
   hash. So the setup snippets show a placeholder until then, and the real token
   afterwards, which is the one moment copying it is possible.

   REVIEW is the Network Sonar shape: read what a system knows, list it, and let an
   admin tick what to add or mark things ignored. Nothing is ticked to begin with,
   a tick only ever adds, and the import is one change-log entry with an Undo. It
   runs when someone presses the button, never in the background.

   All writes go through the existing admin routes, with the same header. */

import { A, CFG, $, esc, WRITE_HEADERS, postJSON } from './config.js';
import { say } from './words.js';

const SOURCE = { file: 'saved', env: 'deployment', default: 'default' };
const LIFETIME = (d) => (d ? `${d} days` : 'never expires');

let issued = '';       // the plaintext, for as long as this panel stays open
let tab = 'local';     // a local model first: its answers never leave the network

const endpoint = () => new URL('api/v2/mcp', document.baseURI).href;
const readUrl = () => new URL('api/v2/signals', document.baseURI).href;

/* Formats change, so each was read from the harness's own docs on 2026-10-31.
   Gemini takes the header's value literally in settings.json, so it gets the
   token itself or the placeholder, never a variable. */
function setups(token) {
  const shown = token || 'PASTE_YOUR_TOKEN';
  const url = endpoint();
  /* Local first, then the plain read, then the cloud harnesses, each saying where
     its answers go. The order is the advice. */
  const cloud = (vendor) => `Cloud model: everything it reads from this map is sent to ${vendor}. `;
  return {
    local: { name: 'Local model', lang: 'any MCP client',
      note: 'For Ollama, LM Studio or your own harness: point any client that speaks MCP over HTTP at this address. Answers stay on your network.',
      text: `URL:    ${url}\nHeader: Authorization: Bearer ${shown}` },
    rest: { name: 'REST', lang: 'shell',
      note: 'The same token reads lab-data, maps, signals, rites and events under api/v2. The reference is api/v2/openapi.json.',
      text: `curl -H "Authorization: Bearer ${shown}" ${readUrl()}` },
    claude: { name: 'Claude Code (cloud)', lang: 'shell',
      note: cloud('Anthropic') + 'Then run claude mcp list to check it.',
      text: `export ATLAS_TOKEN="${shown}"\nclaude mcp add --transport http --scope user atlas ${url} --header "Authorization: Bearer $ATLAS_TOKEN"` },
    codex: { name: 'Codex (cloud)', lang: '~/.codex/config.toml',
      note: cloud('OpenAI') + 'The file names the variable, so the token stays out of it. Set ATLAS_TOKEN before starting Codex.',
      text: `[mcp_servers.atlas]\nurl = "${url}"\nbearer_token_env_var = "ATLAS_TOKEN"` },
    gemini: { name: 'Gemini CLI (cloud)', lang: '~/.gemini/settings.json',
      note: cloud('Google') + 'This file holds the token in plain text, so never commit it. Check with /mcp.',
      text: JSON.stringify({ mcpServers: { atlas: { httpUrl: url, headers: { Authorization: `Bearer ${shown}` } } } }, null, 2) },
  };
}

function tokenRow(t) {
  const when = t.last_used ? `last used ${esc(t.last_used)}` : 'not used yet';
  const ends = t.expired ? 'expired' : t.expires ? `expires ${esc(t.expires)}` : 'never expires';
  return `<div class="con-token${t.expired ? ' con-dead' : ''}">
      <span class="con-name">${esc(t.name)}</span>
      <span class="con-meta">${when} · ${ends}</span>
      <button class="sp-btn sp-btn-warn" type="button" data-revoke="${esc(t.id)}" data-name="${esc(t.name)}">Revoke</button>
    </div>`;
}

/* The switch for agent access as a whole. It starts off, and off refuses every
   token at once without revoking any. A deployment that sets ATLAS_AGENT_API=0
   holds it shut, and then there is no button here to press. */
function accessHTML(access, count) {
  const kept = count
    ? ` The ${count === 1 ? 'token below is' : `${count} tokens below are`} kept, and refused until it is on again.`
    : '';
  if (access.on) {
    return `<div class="con-access con-access-on">
        <span><strong>Agent access is on.</strong> A tool that holds a token can read this map.</span>
        <button class="sp-btn sp-btn-warn" type="button" id="con-access" data-on="0">Turn off</button>
      </div>`;
  }
  if (access.locked) {
    return `<div class="con-access">
        <span><strong>Agent access is off, and locked.</strong> This deployment sets
          <code>ATLAS_AGENT_API=0</code>, so it can only be turned on there.${kept}</span>
      </div>`;
  }
  return `<div class="con-access">
      <span><strong>Agent access is off.</strong> No tool can read this map: every token is refused
        and the MCP address answers "not found".${kept}</span>
      <button class="sp-btn sp-btn-go" type="button" id="con-access" data-on="1">Turn on</button>
    </div>`;
}

function setupHTML() {
  const all = setups(issued);
  const s = all[tab];
  const tabs = Object.entries(all).map(([k, v]) =>
    `<button class="con-tab${k === tab ? ' on' : ''}" type="button" role="tab" aria-selected="${k === tab}" data-tab="${k}">${esc(v.name)}</button>`).join('');
  return `<div class="con-tabs" role="tablist" aria-label="Set up a tool">${tabs}</div>
    <div class="con-lang">${esc(s.lang)}</div>
    <pre class="con-code" id="con-code">${esc(s.text)}</pre>
    <div class="sp-actions"><button class="sp-btn" type="button" id="con-copy">Copy</button></div>
    <div class="acct-note">${esc(s.note)}</div>`;
}

function systemCard(sys) {
  const rows = sys.fields.map((f) => {
    if (f.kind === 'insecure') {
      return `<label class="con-check"><input type="checkbox" data-key="${esc(f.key)}"${f.value === '1' ? ' checked' : ''}>
        ${esc(f.label)} <span class="con-meta">(skip the certificate check)</span></label>`;
    }
    const secret = f.kind === 'secret';
    const hint = secret ? (f.set ? 'leave blank to keep the stored one' : 'not set') : f.hint;
    const chip = secret ? (f.set ? 'kept' : 'unset') : (SOURCE[f.source] || '');
    return `<label class="dir-row">
        <span class="dir-label">${esc(f.label)}<span class="dir-src">${esc(chip)}</span></span>
        <input class="dir-input" data-key="${esc(f.key)}"${secret ? ' type="password" data-secret="1" autocomplete="new-password"' : ' autocomplete="off"'}
               value="${secret ? '' : esc(f.value)}" placeholder="${esc(hint)}" spellcheck="false">
      </label>`;
  }).join('');
  return `<details class="con-system" data-system="${esc(sys.key)}"${sys.configured ? ' open' : ''}>
      <summary><span class="con-name">${esc(sys.name)}</span>
        <span class="con-meta">${sys.configured ? 'set up' : 'not set up'} · ${esc(sys.about)}</span></summary>
      <div class="acct-note">${esc(sys.credential)}</div>
      ${rows}
      <div class="sp-actions">
        <button class="sp-btn" type="button" data-sys-test="${esc(sys.key)}">Test</button>
        <button class="sp-btn" type="button" data-sys-review="${esc(sys.key)}"${sys.configured ? '' : ' disabled title="Save a URL and credential first"'}>Review</button>
        <button class="sp-btn sp-btn-go" type="button" data-sys-save="${esc(sys.key)}">Save</button>
      </div>
      <div class="dir-result" data-sys-result="${esc(sys.key)}"></div>
      <div class="con-review" data-review="${esc(sys.key)}" hidden></div>
    </details>`;
}

function systemValues(card) {
  const out = {};
  for (const input of card.querySelectorAll('[data-key]')) {
    out[input.dataset.key] = input.type === 'checkbox' ? (input.checked ? '1' : '0') : input.value.trim();
  }
  return out;
}

async function post(url, body) {
  const r = await postJSON(url, body);
  return { r, j: await r.json().catch(() => ({})) };
}

async function testSystem(key, card, box, btn) {
  box.className = 'dir-result';
  box.textContent = 'Asking…';
  btn.disabled = true;
  try {
    const { j } = await post('api/v2/admin/connections/test', { key, settings: systemValues(card) });
    box.className = 'dir-result ' + (j.ok ? 'dir-ok' : 'dir-bad');
    box.textContent = j.ok ? j.detail : (j.error || 'It did not answer.');
  } catch {
    box.className = 'dir-result dir-bad';
    box.textContent = 'It did not answer.';
  } finally {
    btn.disabled = false;
  }
}

async function saveSystem(card, box) {
  const { r, j } = await post('api/v2/admin/integrations', { settings: systemValues(card) });
  if (!r.ok) {
    box.className = 'dir-result dir-bad';
    box.textContent = j.error || 'Could not save.';
    return;
  }
  await renderConnections();
  const fresh = document.querySelector(`[data-sys-result="${card.dataset.system}"]`);
  if (fresh) { fresh.className = 'dir-result dir-ok'; fresh.textContent = 'Saved.'; }
}

/* ── the review ───────────────────────────────────────────────────────── */

const FILTER_FROM = 12;   // below this a list is short enough to read

const tickable = (r) => (r.status === 'new' || r.status === 'clash') && !r.blocked;

function rowState(r, zones) {
  // a charted row can still disagree with the map about a name, and says so
  if (r.status === 'charted') return `on the map as ${esc(r.matched)}${r.note ? `. ${esc(r.note)}` : ''}`;
  if (r.note) return esc(r.note);
  if (r.type === 'zone') return say('a new realm');
  if (r.type === 'service') return 'a service on its host';
  if (r.type === 'port') return 'a port on its device';
  if (r.type === 'route') return 'a link between them';
  if (r.type === 'fact') return 'adds to what the map has';
  const zone = zones.find((z) => z.id === r.zone);
  return zone ? `lands in ${esc(zone.name)}` : say('no realm yet');
}

function reviewRow(r, zones) {
  const off = !tickable(r);
  const worry = r.status === 'clash' || r.blocked;
  const act = r.status === 'ignored'
    ? `<button class="sp-btn" type="button" data-unignore="${esc(r.key)}">Bring back</button>`
    : r.status === 'charted' ? ''
      : `<button class="sp-btn" type="button" data-ignore="${esc(r.key)}">Ignore</button>`;
  return `<div class="con-row${off ? ' con-off' : ''}" data-row="${esc(r.key)}">
      <input type="checkbox" class="con-pick" data-pick="${esc(r.key)}" aria-label="Add ${esc(r.name)}"${off ? ' disabled' : ''}>
      <span class="con-row-text">
        <span class="con-name">${esc(r.name)}</span>
        ${r.ip && r.ip !== '—' ? `<span class="con-ip">${esc(r.ip)}</span>` : ''}
        <span class="con-meta con-row-line">${[r.detail && esc(r.detail), `<span class="${worry ? 'con-worry' : ''}">${rowState(r, zones)}</span>`].filter(Boolean).join(' · ')}</span>
      </span>
      ${act}
    </div>`;
}

function groupsOf(rows) {
  const groups = new Map();
  for (const r of rows) groups.set(r.group, [...(groups.get(r.group) || []), r]);
  return groups;
}

function reviewHTML(view) {
  const { rows, zones, notes } = view;
  const open = rows.filter((r) => r.status !== 'ignored');
  const ignored = rows.filter((r) => r.status === 'ignored');
  const fresh = rows.filter(tickable).length;
  const charted = rows.filter((r) => r.status === 'charted').length;
  if (!rows.length) return '<div class="acct-note">It answered, but it has nothing to list.</div>';
  const lists = [...groupsOf(open)].map(([group, members]) => {
    const all = members.some(tickable)
      ? `<label class="con-all"><input type="checkbox" data-all="${esc(group)}"> all</label>` : '';
    return `<div class="con-group"><div class="dir-label">${esc(group)} ${all}</div>
      ${members.map((r) => reviewRow(r, zones)).join('')}</div>`;
  }).join('');
  // Uncharted is the blank choice, made if the map has not got it
  const choices = zones.filter((z) => z.id !== 'uncharted').map((z) => `<option value="${esc(z.id)}">${esc(z.name)}</option>`).join('');
  return `<div class="acct-note">${fresh} new · ${charted} already on the map${ignored.length ? ` · ${ignored.length} ignored` : ''}.
      Nothing is added until you tick it.</div>
    ${notes.map((n) => `<div class="acct-note">${esc(n)}</div>`).join('')}
    ${rows.length > FILTER_FROM ? '<input class="dir-input con-filter" data-filter placeholder="filter by name or address" aria-label="Filter" autocomplete="off" spellcheck="false">' : ''}
    ${lists}
    ${ignored.length ? `<details class="con-ignored"><summary class="con-meta">Ignored (${ignored.length})</summary>
      ${ignored.map((r) => reviewRow(r, zones)).join('')}</details>` : ''}
    ${fresh ? `<label class="dir-row"><span class="dir-label">${say('Realm for a place whose address names none')}</span>
      <select class="dir-input" data-fallback><option value="">Uncharted</option>${choices}</select></label>
    <div class="sp-actions"><button class="sp-btn sp-btn-go" type="button" data-import disabled>Add to the map</button></div>` : ''}`;
}

function syncTicks(box, view) {
  const picks = [...box.querySelectorAll('[data-pick]:checked')];
  const go = box.querySelector('[data-import]');
  if (go) {
    go.disabled = !picks.length;
    go.textContent = picks.length ? `Add ${picks.length} to the map` : 'Add to the map';
  }
  for (const all of box.querySelectorAll('[data-all]')) {
    const boxes = view.rows.filter((r) => r.group === all.dataset.all && tickable(r)).map((r) => pickBox(box, r.key));
    all.checked = boxes.length > 0 && boxes.every((b) => b?.checked);
  }
}

const pickBox = (box, key) => box.querySelector(`[data-pick="${CSS.escape(key)}"]`);

/* What stands on a host: a service or a port on it, a link with it at either end.
   A guest and a monitor do not: a guest can land without its host, and a monitor
   is tied to a place already on the map. */
const STANDS = new Set(['service', 'port', 'route']);
const standsOn = (r, key) => STANDS.has(r.type) && (r.parent === key || r.peer === key);

/** Ticking a service, a port or a link ticks what it stands on, and unticking a
    host unticks what stood on it. */
function followTick(box, view, key, checked) {
  const row = view.rows.find((r) => r.key === key);
  if (checked && STANDS.has(row.type)) {
    for (const end of [row.parent, row.peer]) {
      const host = end && pickBox(box, end);
      if (host && !host.disabled) host.checked = true;
    }
  }
  if (!checked) {
    for (const r of view.rows) {
      if (standsOn(r, key)) {
        const child = pickBox(box, r.key);
        if (child) child.checked = false;
      }
    }
  }
}

function ignoreLocally(view, key, ignoring) {
  const row = view.rows.find((r) => r.key === key);
  if (ignoring) { row.was = row.status; row.status = 'ignored'; } else { row.status = row.was || 'new'; }
  for (const r of view.rows) {
    if (standsOn(r, key) && r.status !== 'charted') {
      r.blocked = ignoring;
      r.note = ignoring ? `${row.name} is ignored.` : '';
    }
  }
}

function resultLine(box, cls, text) {
  const line = box.querySelector('[data-review-result]');
  line.className = `dir-result ${cls}`;
  line.textContent = text;
  return line;
}

async function runImport(key, box, view) {
  const picks = [...box.querySelectorAll('[data-pick]:checked')].map((b) => b.dataset.pick);
  const go = box.querySelector('[data-import]');
  go.disabled = true;
  resultLine(box, '', 'Reading it again and adding…');
  let answer;
  try {
    answer = await post('api/v2/admin/connections/import',
      { key, picks, expect: view.stamp, zone: box.querySelector('[data-fallback]')?.value || '' });
  } catch {
    resultLine(box, 'dir-bad', 'It did not answer. Nothing was added.');
    go.disabled = false;
    return;
  }
  const { r, j } = answer;
  if (!r.ok) {
    resultLine(box, 'dir-bad', (j.problems || [j.error || 'Could not add those.']).join(' '));
    go.disabled = false;
    return;
  }
  await A.refreshData?.();
  // the list redraws from a fresh read, and if that fails the import still happened
  const next = await drawReview(key, box).catch(() => box);
  const line = resultLine(next, 'dir-ok', `Added ${j.added} to the map. It is in the change log. `);
  const undo = document.createElement('button');
  undo.className = 'sp-btn';
  undo.type = 'button';
  undo.textContent = 'Undo';
  undo.addEventListener('click', async () => {
    undo.disabled = true;
    const back = await post(`api/v2/admin/revisions/${j.revision}/revert`, { expect: j.stamp });
    if (!back.r.ok) {
      undo.disabled = false;
      resultLine(next, 'dir-bad', `${back.j.error || 'Could not undo that.'} `).append(undo);
      return;
    }
    await A.refreshData?.();
    const after = await drawReview(key, next).catch(() => next);
    resultLine(after, 'dir-ok', 'Undone. The map is as it was.');
  });
  line.append(undo);
}

function wireReview(key, box, view) {
  box.addEventListener('change', (e) => {
    const t = e.target;
    if (t.dataset.pick) followTick(box, view, t.dataset.pick, t.checked);
    if (t.dataset.all) {
      for (const r of view.rows) {
        if (r.group !== t.dataset.all || !tickable(r)) continue;
        const pick = pickBox(box, r.key);
        if (pick.closest('.con-row').hidden) continue;
        pick.checked = t.checked;
        followTick(box, view, r.key, t.checked);
      }
    }
    syncTicks(box, view);
  });
  box.querySelector('[data-filter]')?.addEventListener('input', (e) => {
    const want = e.target.value.trim().toLowerCase();
    for (const r of view.rows) {
      const row = box.querySelector(`[data-row="${CSS.escape(r.key)}"]`);
      if (row) row.hidden = !`${r.name} ${r.ip}`.toLowerCase().includes(want);
    }
  });
  box.addEventListener('click', async (e) => {
    const t = e.target.closest('button');
    if (!t) return;
    if (t.dataset.import !== undefined) { await runImport(key, box, view); return; }
    const ignoring = t.dataset.ignore !== undefined;
    if (!ignoring && t.dataset.unignore === undefined) return;
    const target = ignoring ? t.dataset.ignore : t.dataset.unignore;
    t.disabled = true;
    const { r } = await post('api/v2/admin/discovery/decide',
      { keys: [target], action: ignoring ? 'ignore' : 'unignore' });
    if (!r.ok) { t.disabled = false; return; }
    ignoreLocally(view, target, ignoring);
    paintReview(key, box, view);
  });
}

function paintReview(key, box, view) {
  // a fresh node each time, so a repaint cannot stack a second set of listeners
  const ticked = [...box.querySelectorAll('[data-pick]:checked')].map((b) => b.dataset.pick);
  const next = box.cloneNode(false);
  next.innerHTML = `${reviewHTML(view)}<div class="dir-result" data-review-result></div>`;
  box.replaceWith(next);
  wireReview(key, next, view);
  for (const pick of ticked) {
    const again = pickBox(next, pick);
    if (again && !again.disabled) again.checked = true;
  }
  syncTicks(next, view);
  return next;
}

async function drawReview(key, box) {
  const { j } = await post('api/v2/admin/connections/review', { key });
  if (!j.ok) throw new Error(j.error || 'It did not answer.');
  box.hidden = false;
  box.querySelectorAll('[data-pick]:checked').forEach((b) => { b.checked = false; });
  return paintReview(key, box, { rows: j.rows, zones: j.zones, notes: j.notes, stamp: j.stamp });
}

async function reviewSystem(key, card, status, btn) {
  status.className = 'dir-result';
  status.textContent = 'Reading what it knows…';
  btn.disabled = true;
  try {
    await drawReview(key, card.querySelector('[data-review]'));
    status.textContent = '';
  } catch (e) {
    status.className = 'dir-result dir-bad';
    status.textContent = e.message || 'It did not answer.';
  } finally {
    btn.disabled = false;
  }
}

function wireSetup(el) {
  for (const b of el.querySelectorAll('[data-tab]')) {
    b.addEventListener('click', () => {
      tab = b.dataset.tab;
      $('con-setup').innerHTML = setupHTML();
      wireSetup(el);
    });
  }
  $('con-copy')?.addEventListener('click', async (e) => {
    const text = $('con-code')?.textContent || '';
    try {
      await navigator.clipboard.writeText(text);
      e.target.textContent = 'Copied';
    } catch {
      // plain http has no clipboard API: leave the text selected for Ctrl+C
      const range = document.createRange();
      range.selectNodeContents($('con-code'));
      getSelection().removeAllRanges();
      getSelection().addRange(range);
      e.target.textContent = 'Press Ctrl+C';
    }
  });
}

export async function renderConnections() {
  const el = $('sp-connections');
  if (!el) return;
  el.hidden = !CFG.AUTH.admin;
  if (el.hidden) return;
  let tok, con;
  try {
    const [a, b] = await Promise.all([fetch('api/v2/admin/tokens'), fetch('api/v2/admin/connections')]);
    if (!a.ok || !b.ok) throw new Error('refused');
    [tok, con] = [await a.json(), await b.json()];
  } catch { el.hidden = true; return; }

  const life = tok.lifetimes.map((d) =>
    `<option value="${d ?? ''}"${d === tok.default_days ? ' selected' : ''}>${LIFETIME(d)}</option>`).join('');
  // an Atlas from before the switch answers without `access`: it has none, so it is on
  const access = tok.access || { on: true, locked: false };
  // creating a token and the setup lines are for an Atlas that will honour one
  const making = access.on
    ? `<div class="dir-test">
       <input class="dir-input" id="con-name" placeholder="what is it for? e.g. local model on my GPU box" maxlength="64" autocomplete="off">
       <select class="dir-input con-life" id="con-life" aria-label="Lifetime">${life}</select>
       <button class="sp-btn sp-btn-go" type="button" id="con-issue">Create</button>
     </div>
     <div class="dir-result" id="con-result"></div>
     <div id="con-setup">${setupHTML()}</div>`
    : '<div class="dir-result" id="con-result"></div>';
  el.innerHTML =
    `<button class="sp-sub" type="button">CONNECTIONS <span class="sp-sub-plain">· AI tools, scripts and other systems</span></button>
     <div class="sp-sec-body">
     <div class="sp-sub-h">Let a tool read this map</div>
     <div class="acct-note">A token is read-only and sees no more than a viewer with no groups: no accounts,
       no tripwires, no restricted places. <em>A cloud tool sends what it reads to its model's vendor,
       so this map leaves your network with it.</em> A local model keeps it here.</div>
     ${accessHTML(access, tok.tokens.length)}
     <div id="con-fresh" class="con-fresh" ${issued ? '' : 'hidden'}>Copy this now. It will not be shown again.
       <pre class="con-code">${esc(issued)}</pre></div>
     <div class="con-tokens">${tok.tokens.map(tokenRow).join('') || '<div class="acct-note">No tokens yet.</div>'}</div>
     ${making}
     <div class="sp-sub-h">Let this Atlas read a system</div>
     <div class="acct-note">Test makes one or two read-only calls and reports what it found. Review lists
       what the system knows, using what is saved here, and you tick what to add to the map. It never runs
       on its own. Use each system's read-only credential.</div>
     ${con.systems.map(systemCard).join('')}
     </div>`;

  wireSetup(el);
  $('con-access')?.addEventListener('click', async (e) => {
    const on = e.target.dataset.on === '1';
    if (!on && !confirm('Turn agent access off? Every tool reading this map stops at once. Tokens are kept.')) return;
    const { r, j } = await post('api/v2/admin/tokens/access', { on });
    if (!r.ok) {
      const box = $('con-result');
      box.className = 'dir-result dir-bad';
      box.textContent = j.error || 'Could not change agent access.';
      return;
    }
    if (!on) issued = '';      // a token shown a moment ago is no use to copy now
    await renderConnections();
  });
  $('con-issue')?.addEventListener('click', async () => {
    const box = $('con-result');
    const days = $('con-life').value;
    const { r, j } = await post('api/v2/admin/tokens',
      { name: $('con-name').value, days: days ? Number(days) : null });
    if (!r.ok) {
      box.className = 'dir-result dir-bad';
      box.textContent = j.error || 'Could not create a token.';
      return;
    }
    issued = j.secret;
    await renderConnections();
  });
  for (const b of el.querySelectorAll('[data-revoke]')) {
    b.addEventListener('click', async () => {
      if (!confirm(`Revoke "${b.dataset.name}"? Anything using it stops at once.`)) return;
      await fetch(`api/v2/admin/tokens/${encodeURIComponent(b.dataset.revoke)}`, { method: 'DELETE', headers: WRITE_HEADERS });
      await renderConnections();
    });
  }
  for (const card of el.querySelectorAll('[data-system]')) {
    const key = card.dataset.system;
    const box = card.querySelector('[data-sys-result]');
    card.querySelector('[data-sys-test]').addEventListener('click', (e) => testSystem(key, card, box, e.target));
    card.querySelector('[data-sys-save]').addEventListener('click', () => saveSystem(card, box));
    card.querySelector('[data-sys-review]').addEventListener('click', (e) => reviewSystem(key, card, box, e.target));
  }
  A.applySettingsFolds?.();
}
