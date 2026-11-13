/* CONNECTIONS — one Settings section for everything that talks to this Atlas.

   Two directions, kept apart because they are different promises. TOOLS READ THE
   MAP: an API token, then the exact setup for each harness. THE ATLAS READS
   SYSTEMS: a card per system with a real test, on the shape of SolarWinds' one
   credential library and Zabbix's one list of integrations.

   A token appears once, here, right after it is issued; the server keeps only a
   hash. So the setup snippets show a placeholder until then, and the real token
   afterwards, which is the one moment copying it is possible.

   REVIEW, the list a system card opens for an admin to tick from, is
   connection-review.js; the setup lines and the sentence for each kind of token
   are connections-model.js.

   All writes go through the existing admin routes, with the same header. */

import { A, CFG, $, esc, WRITE_HEADERS } from './config.js';
import { bindNote, fromWords, kindNote, readLine, readsHead, setups } from './connections-model.js';
import { post, reviewSystem } from './connection-review.js';

const SOURCE = { file: 'saved', env: 'deployment', default: 'default' };
const LIFETIME = (d) => (d ? `${d} days` : 'never expires');

let issued = '';       // the plaintext, for as long as this panel stays open
let issuedKind = '';   // which kind that token is: its lines are shown for that kind only
let kind = 'full';     // a local model first: its answers never leave the network
let tab = 'local';
const FIRST_TAB = { full: 'local', cloud: 'claude' };

const endpoint = () => new URL('api/v2/mcp', document.baseURI).href;
const readUrl = () => new URL('api/v2/signals', document.baseURI).href;

function lifeOptions(tok) {
  const p = (tok.profiles && tok.profiles[kind]) || { lifetimes: tok.lifetimes, default_days: tok.default_days };
  return p.lifetimes.map((d) =>
    `<option value="${d ?? ''}"${d === p.default_days ? ' selected' : ''}>${LIFETIME(d)}</option>`).join('');
}

function tokenRow(t) {
  const when = t.last_used ? `last used ${esc(t.last_used)}` : 'not used yet';
  const ends = t.expired ? 'expired' : t.expires ? `expires ${esc(t.expires)}` : 'never expires';
  const view = t.profile === 'cloud' ? 'cloud view'
    : t.untyped ? 'full view, made before tokens had a kind' : 'full view';
  return `<div class="con-token${t.expired ? ' con-dead' : ''}">
      <span class="con-name">${esc(t.name)}</span>
      <span class="dir-src">${view}</span>
      <span class="con-meta">${when} · ${ends} · ${esc(fromWords(t.networks))}</span>
      <button class="sp-btn" type="button" data-reads="${esc(t.id)}" data-name="${esc(t.name)}" aria-expanded="false">What it read</button>
      <button class="sp-btn sp-btn-warn" type="button" data-revoke="${esc(t.id)}" data-name="${esc(t.name)}">Revoke</button>
    </div>
    <div class="acct-note" data-reads-for="${esc(t.id)}" hidden></div>`;
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
  // the token just made is shown in the lines for its own kind, and nowhere else
  const all = setups(issuedKind === kind ? issued : '', kind, endpoint(), readUrl());
  if (!all[tab]) tab = FIRST_TAB[kind];
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

  // an Atlas from before the switch answers without `access`: it has none, so it is on
  const access = tok.access || { on: true, locked: false };
  const pick = (value, label, hint) =>
    `<label class="con-check"><input type="radio" name="con-kind" value="${value}"${kind === value ? ' checked' : ''}>
       ${label} <span class="con-meta">${hint}</span></label>`;
  // creating a token and the setup lines are for an Atlas that will honour one
  const making = access.on
    ? `<div class="con-kinds" role="radiogroup" aria-label="What the token is for">
       ${pick('full', 'A local model or a script', 'full view, stays on your network')}
       ${pick('cloud', 'A cloud AI tool', 'reduced view, 30 days at most')}
     </div>
     <div class="acct-note" id="con-kind-note">${esc(kindNote(tok, kind))}</div>
     <label class="con-check"><input type="checkbox" id="con-lan" checked>
       Only from the local network <span class="con-meta">refused from anywhere else</span></label>
     <div class="acct-note">${esc(bindNote(tok.you))}</div>
     <div class="dir-test">
       <input class="dir-input" id="con-name" placeholder="what is it for?" maxlength="64" autocomplete="off">
       <select class="dir-input con-life" id="con-life" aria-label="Lifetime">${lifeOptions(tok)}</select>
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
       so say which kind of tool a token is for.</em> A local model keeps the map here.</div>
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
    if (!on) { issued = ''; issuedKind = ''; }      // a token shown a moment ago is no use to copy now
    await renderConnections();
  });
  for (const radio of el.querySelectorAll('input[name="con-kind"]')) {
    radio.addEventListener('change', () => {
      // in place, so a name already typed stays
      kind = radio.value;
      tab = FIRST_TAB[kind];
      $('con-kind-note').textContent = kindNote(tok, kind);
      $('con-life').innerHTML = lifeOptions(tok);
      $('con-setup').innerHTML = setupHTML();
      wireSetup(el);
    });
  }
  $('con-issue')?.addEventListener('click', async () => {
    const box = $('con-result');
    const days = $('con-life').value;
    const { r, j } = await post('api/v2/admin/tokens',
      { name: $('con-name').value, days: days ? Number(days) : null, profile: kind,
        networks: $('con-lan').checked ? 'lan' : null });
    if (!r.ok) {
      box.className = 'dir-result dir-bad';
      box.textContent = j.error || 'Could not create a token.';
      return;
    }
    issued = j.secret;
    issuedKind = kind;
    await renderConnections();
  });
  for (const b of el.querySelectorAll('[data-reads]')) {
    b.addEventListener('click', async () => {
      const box = el.querySelector(`[data-reads-for="${CSS.escape(b.dataset.reads)}"]`);
      if (!box.hidden) { box.hidden = true; b.setAttribute('aria-expanded', 'false'); return; }
      box.hidden = false;
      b.setAttribute('aria-expanded', 'true');
      box.textContent = 'Reading the log…';
      try {
        const r = await fetch(`api/v2/admin/tokens/reads?token=${encodeURIComponent(b.dataset.reads)}&limit=50`);
        if (!r.ok) throw new Error('refused');
        const j = await r.json();
        // a tool's arguments are its own words: text, never markup
        box.innerHTML = `${esc(readsHead(j.reads, j.keep_days, b.dataset.name))}
          ${j.reads.length ? `<pre class="con-code">${j.reads.map((row) => esc(readLine(row))).join('\n')}</pre>` : ''}`;
      } catch { box.textContent = 'The log could not be read.'; }
    });
  }
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
