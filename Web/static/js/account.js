/* Atlas — the account workstation: who you are on this instance (the
   seal and its emblem), the admin's ledgers (USERS, SIGN-INS), and THE
   DIRECTORY (which directory may sign people in). Lifted out of ui.js whole
   (ALIVE.md THE LIST #7). One inbound arrow — ui.js's settings tab calls
   `A.renderSettingsSections` — and every other tie is through `A`
   (`A.showToast`, `A.applySettingsFolds`); the block referenced no other ui.js
   local. Registered in atlas.js after ui.js. */

import { A, CFG, $, esc, themeText } from './config.js';

/* ── Who you are on this instance ─────────────────────────────────────────
   Drawn from CFG.AUTH (settings.auth_config), and deliberately different per
   mode rather than one surface pretending the modes are the same:

     accounts   — a real Atlas session: name, admin, whether MFA is on, and the
                  only sign-out that exists anywhere in this app.
     hub        — the Hub signed you in and owns the session. Naming
                  the viewer is useful; offering a sign-out would be a lie
                  (`/api/auth/*` is not even registered in this mode), so the
                  block says where the session lives instead.
     standalone — no gate, no identity. The block stays hidden; the startup
                  warning already says this plainly and the map is the point.

   This is the first front-end surface the accounts backend has ever had — it
   shipped with a login page and seventeen endpoints, and once you were on the
   map there was no way to see who you were or leave. */
function renderAccount() {
  const el = $('sp-account');
  if (!el) return;
  const a = CFG.AUTH || {};
  if (!a.mode || a.mode === 'standalone') { el.hidden = true; return; }
  el.hidden = false;
  const who = esc(a.user || 'unknown');
  /* who vouched for this viewer, at a glance (2026-08-16) — the note
     below says it in prose, but a chip is what a glance reads. `session` says
     WHERE the session lives (hub header vs atlas cookie); `source` says which
     backend proved the password for an atlas session. */
  const via = a.session === 'hub' ? 'VIA THE HUB'
            : a.source === 'ldap' ? 'VIA AD'
            : a.source === 'local' ? 'LOCAL ACCOUNT'
            : '';
  const badges = [
    a.admin ? '<span class="acct-badge">SURVEYOR</span>' : '',
    via ? `<span class="acct-badge acct-badge-quiet">${via}</span>` : '',
    a.mode === 'accounts' && a.mfa ? '<span class="acct-badge acct-badge-quiet">MFA</span>' : '',
  ].join('');
  // `canSignOut` is the server's answer to "is this a session we can end",
  // not a guess from the mode: in hybrid the same instance names some viewers
  // from its own session and others from the Hub's signed header, and only the
  // first can be signed out here.
  const note = a.canSignOut
    ? (a.mfa ? 'A second factor guards this account.' : 'No second factor on this account.')
    : `Named by ${themeText('hub_name', 'the Hub')}, which holds your session — sign out there.`;
  // The one door you did not come through has to be visible or it may as well
  // not be there: named by the Hub you can sign out THERE (the only place that
  // session ends) and — in hybrid — take an Atlas account instead; signed in
  // here you get this instance's own sign-out.
  /* every posture gets a way OUT and a way to become someone else (Link,
     2026-08-16). An atlas session signs out here (and lands on the login
     page — which IS the switch-user door); a Hub-named viewer signs out AT
     THE HUB, the only place that session can end, and can take an Atlas
     account instead. */
  const hubOut = CFG.HUB_URL
    ? `<a class="sp-btn" href="${esc(CFG.HUB_URL)}/logout">Sign out at the Hub</a>` : '';
  const doors = !a.canSignOut
    ? hubOut + (a.mode === 'hybrid'
        ? `<a class="sp-btn" href="auth/login">Sign in to the Atlas</a>` : '')
    : '';
  const otherDoor = doors ? `<div class="sp-actions">${doors}</div>` : '';
  const picker = a.canSignOut
    ? `<div class="acct-emblems" id="acct-emblems">` +
      EMBLEMS.map(e => `<button class="acct-emb${a.emblem === e ? ' on' : ''}" data-emblem="${e}">${e}</button>`).join('') +
      `<button class="acct-emb acct-emb-clear${a.emblem ? '' : ' on'}" data-emblem="" title="No emblem">·</button>` +
      `</div>`
    : '';
  /* change password — a LOCAL account signed in here (2026-09-27: the API
     shipped with accounts mode, but nothing called it, so a bootstrap admin
     had no way to replace the password it was born with). A directory
     account's password lives in the directory; a Hub-named viewer has no row. */
  const pwForm = a.canSignOut && a.source === 'local'
    ? `<details class="acct-pw"><summary class="sp-hint">Change password</summary>
         <input class="dir-input" id="pw-current" type="password" placeholder="current password" autocomplete="current-password">
         <input class="dir-input" id="pw-new" type="password" placeholder="new password" autocomplete="new-password">
         <input class="dir-input" id="pw-again" type="password" placeholder="new password, again" autocomplete="new-password">
         <div class="sp-actions"><button class="sp-btn" id="pw-save" type="button">Change password</button></div>
       </details>`
    : '';
  el.innerHTML =
    // ACCOUNT leads and the lore follows (2026-08-16 — the second ask
    // for this section in two days; a suffix translation was not enough, so
    // the plain word IS the name now and the seal is the flavor).
    `<button class="sp-sub" type="button">ACCOUNT <span class="sp-sub-plain">· the seal you carry</span></button>
     <div class="sp-sec-body">
     <div class="acct-row">${a.emblem ? `<span class="acct-worn">${esc(a.emblem)}</span>` : ''}<span class="acct-name">${who}</span>${badges}</div>
     <div class="acct-note">${note}</div>` + picker + pwForm +
    (a.canSignOut
      ? `<div class="sp-actions"><button class="sp-btn sp-btn-warn" id="acct-signout">Sign out</button></div>`
      : otherDoor) +
    `</div>`;
  if (a.canSignOut) $('acct-signout')?.addEventListener('click', signOut);
  $('pw-save')?.addEventListener('click', changePassword);
  $('acct-emblems')?.addEventListener('click', async (e) => {
    const btn = e.target.closest('.acct-emb');
    if (!btn) return;
    try {
      const j = await authPost('api/v2/auth/me/emblem', { emblem: btn.dataset.emblem });
      CFG.AUTH.emblem = j.emblem;
      /* patch IN PLACE — a full renderAccount used to cascade into three
         admin fetches and four section rebuilds, to move one glyph */
      const row = el.querySelector('.acct-row');
      let worn = row.querySelector('.acct-worn');
      if (j.emblem && !worn) {
        worn = document.createElement('span');
        worn.className = 'acct-worn';
        row.prepend(worn);
      }
      if (worn) { worn.textContent = j.emblem; worn.hidden = !j.emblem; }
      for (const b of el.querySelectorAll('.acct-emb')) {
        b.classList.toggle('on', b.dataset.emblem === j.emblem);
      }
    } catch (err) { A.showToast?.(err.message || 'the mark did not take'); }
  });
  A.applySettingsFolds?.();   // a re-render forgets its fold; put it back
}

async function changePassword() {
  const btn = $('pw-save');
  const current = $('pw-current').value, next = $('pw-new').value, again = $('pw-again').value;
  if (!current || !next) { A.showToast?.('Both the current and the new password are needed.'); return; }
  if (next !== again) { A.showToast?.('The new passwords do not match.'); return; }
  btn.disabled = true;
  try {
    // the server re-checks the current password and the length rule, re-seals
    // the session (so this tab stays signed in) and audits the change
    await authPost('api/v2/auth/password', { current, new: next });
    for (const id of ['pw-current', 'pw-new', 'pw-again']) $(id).value = '';
    btn.closest('details').open = false;
    A.showToast?.('Password changed.');
  } catch (err) {
    A.showToast?.(err.message || 'the password did not change');
  } finally {
    btn.disabled = false;
  }
}

/* ── USERS + SIGN-INS — the admin's ledger of who may pass ────────────────
   Admin-only, and only where the accounts store exists (accounts/hybrid). The
   management routes need an ATLAS session — a Hub-named admin has no account
   row and no CSRF here — so that posture gets the pointer, not broken
   buttons. Every action is one of the seventeen endpoints that shipped with
   accounts mode; this is their first UI. */

/* the emblem presets: a small mark the account wears beside its name. Stored
   ON the account (not this browser), so it follows you; only an Atlas session
   has a row to hang it on, so only one gets the picker. */
const EMBLEMS = ['🗡','🛡','🏹','🪄','🧭','🗺','⚗','🔥','🌙','⭐','🍄','👁'];

const hubNamedAdminHint =
  `<div class="sp-hint">You are named by ${esc(themeText('hub_name', 'the Hub'))}. Managing accounts needs ` +
  `an Atlas session — <a href="auth/login">sign in at the Atlas door</a>.</div>`;

function authAdminPosture() {
  const a = CFG.AUTH;
  if (!a.admin || (a.mode !== 'accounts' && a.mode !== 'hybrid')) return 'hide';
  return a.canSignOut ? 'full' : 'hub-named';
}

async function authApi(path, opts) {
  const r = await fetch(path, opts);
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || 'refused');
  return j;
}

const authPost = (path, payload) => authApi(path, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json', 'X-Atlas-Write': '1' },
  body: JSON.stringify(payload || {}),
});

/* ── The admin-section shell ──────────────────────────────────────────────
   One scaffold for the admin ledgers (users, sign-ins): the posture gate,
   the head, the hub-named pointer and the fold call live HERE, once — they
   were drifting copies per section.

   The body is LAZY: it loads when the section is first unfolded (the fold
   click handler runs `_load`), because the sections default closed
   (v1.19.4) and fetching a roster nobody opened was most of a
   settings-open's cost. A section whose stored fold is OPEN loads at once. */
function adminSection(id, title, plain, load) {
  const el = $(id);
  if (!el) return;
  const posture = authAdminPosture();
  el.hidden = posture === 'hide';
  if (el.hidden) return;
  el.innerHTML =
    `<button class="sp-sub" type="button">${title} <span class="sp-sub-plain">\u00b7 ${plain}</span></button>` +
    `<div class="sp-sec-body">` +
    (posture === 'hub-named' ? hubNamedAdminHint : `<div class="sp-hint">\u2026</div>`) +
    `</div>`;
  el._load = posture === 'full' ? load : null;
  A.applySettingsFolds?.();
  if (el._load && !el.classList.contains('closed')) { const f = el._load; el._load = null; f(); }
}

const sectionBody = (id) => $(id)?.querySelector('.sp-sec-body');

async function loadUsers() {
  const body = sectionBody('sp-users');
  if (!body) return;
  let users = [];
  try { users = (await authApi('api/v2/auth/users')).users || []; }
  catch { body.innerHTML = `<div class="sp-hint">The roster would not answer.</div>`; return; }
  const me = CFG.AUTH.user;
  const rows = users.map((u) => {
    const chips =
      (u.is_admin ? `<span class="acct-badge">ADMIN</span>` : '') +
      `<span class="acct-badge acct-badge-quiet">${u.source === 'ldap' ? 'AD' : 'LOCAL'}</span>` +
      (u.mfa_enabled ? `<span class="acct-badge acct-badge-quiet">MFA</span>` : '');
    const self = u.username === me;
    const acts = self ? `<span class="usr-self">you</span>` :
      `<button class="sp-btn usr-act" data-u="${esc(u.username)}" data-act="active" data-on="${u.active ? 0 : 1}">${u.active ? 'Block' : 'Unblock'}</button>` +
      (u.source === 'ldap' ? '' :
        `<button class="sp-btn usr-act" data-u="${esc(u.username)}" data-act="admin" data-on="${u.is_admin ? 0 : 1}">${u.is_admin ? 'Demote' : 'Make admin'}</button>`) +
      (u.mfa_enabled ? `<button class="sp-btn usr-act" data-u="${esc(u.username)}" data-act="reset-mfa">Reset MFA</button>` : '');
    return `<div class="usr-row${u.active ? '' : ' usr-blocked'}">` +
      `<div class="usr-id">${u.emblem ? `<span class="acct-worn">${esc(u.emblem)}</span>` : ''}` +
      `<span class="usr-name">${esc(u.username)}</span>${chips}</div>` +
      `<div class="usr-acts">${acts}</div></div>`;
  }).join('');
  body.innerHTML = rows +
    `<div class="usr-new">` +
      `<input class="dir-input" id="usr-new-name" placeholder="username" autocomplete="off" spellcheck="false">` +
      `<input class="dir-input" id="usr-new-pass" type="password" placeholder="password" autocomplete="new-password">` +
      `<label class="usr-new-admin"><input type="checkbox" id="usr-new-admin"> admin</label>` +
      `<button class="sp-btn sp-btn-go" id="usr-create">Create</button>` +
    `</div>` +
    `<div class="sp-hint">Local accounts only \u2014 directory people sign in with their AD ` +
    `password and appear here on first bind. Blocking wins over both doors.</div>`;
  body.querySelectorAll('.usr-act').forEach((b) => b.addEventListener('click', async () => {
    const u = b.dataset.u, act = b.dataset.act;
    try {
      if (act === 'reset-mfa') await authPost(`api/v2/auth/users/${encodeURIComponent(u)}/reset-mfa`);
      else await authPost(`api/v2/auth/users/${encodeURIComponent(u)}/${act}`, { on: b.dataset.on === '1' });
      loadUsers(); refreshSigninsIfOpen();
    } catch (e) { A.showToast?.(e.message); }
  }));
  $('usr-create')?.addEventListener('click', async () => {
    try {
      await authPost('api/v2/auth/users', {
        username: $('usr-new-name').value.trim(),
        password: $('usr-new-pass').value,
        is_admin: $('usr-new-admin').checked,
      });
      A.showToast?.('The account is written.');
      loadUsers(); refreshSigninsIfOpen();
    } catch (e) { A.showToast?.(e.message); }
  });
}

/* The ledger's stamps are UTC-Z (`2026-08-25T11:40:00Z`) — the store's clock
   became honest on 2026-08-25 (THE LIST #2; it wrote naive local time before,
   which no reader could place). Now that the value says which zone it means,
   show it in the zone the reader is actually in, and keep the UTC original in
   the title. A stamp we cannot parse is shown as it came: never invent a time. */
function stampLocal(iso) {
  const raw = (iso || '').trim();
  if (!raw) return '';
  const d = new Date(raw);
  if (isNaN(d)) return raw.replace('T', ' ');
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ` +
         `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

async function loadSignins() {
  const body = sectionBody('sp-signins');
  if (!body) return;
  let events = [];
  // the panel shows 60 — ask for 60, not the server's 200-row default
  try { events = (await authApi('api/v2/auth/audit?limit=60')).events || []; }
  catch { body.innerHTML = `<div class="sp-hint">The ledger would not answer.</div>`; return; }
  const rows = events.map((e) =>
    `<div class="aud-row${/fail|locked|denied/.test(e.event) ? ' aud-bad' : ''}">` +
    `<span class="aud-ts" title="${esc(e.ts || '')}">${esc(stampLocal(e.ts))}</span>` +
    `<span class="aud-ev">${esc(e.event)}</span>` +
    `<span class="aud-who">${esc(e.username || '')}</span>` +
    `<span class="aud-ip">${esc(e.ip || '')}</span></div>`).join('');
  body.innerHTML = `<div class="aud-list">` +
    (rows || `<div class="sp-hint">Nothing recorded yet.</div>`) + `</div>`;
}

/* an admin act refreshes the ledger only if someone can SEE it — folded
   shut, it reloads on its next unfold anyway */
function refreshSigninsIfOpen() {
  const el = $('sp-signins');
  if (el && !el.hidden && !el.classList.contains('closed') && !el._load) loadSignins();
}

function renderUsers() { adminSection('sp-users', 'USERS', 'who may pass', loadUsers); }
function renderSignins() { adminSection('sp-signins', 'SIGN-INS', 'the gate\u2019s ledger', loadSignins); }

/* every settings section, in panel order — the ONE list a new section joins.
   renderAccount used to grow these as tail-calls, which made a function
   named for one section the panel's accidental orchestrator. */
function renderSettingsSections() {
  renderAccount();
  renderDirectory();
  renderSources();
  renderRealm();
  renderDeployment();
  renderUsers();
  renderSignins();
}

/* ── THE REALM — where the Hub is, the vault prefix, the heartbeat token
   (v1.38.0). The same layer as THE SOURCES (integrations.json), its own
   section because these are not things the Atlas asks — they are where it
   sends you and what the rites post with. */
const REALM_FIELDS = [
  ['HUB_URL', 'Hub URL', 'https://hub.example.com'],
  ['ATLAS_SCROLL_ROOT', 'Vault root (trimmed off scroll paths)', '/srv/docs/'],
  ['ATLAS_BEAT_TOKEN', 'Heartbeat token (the rites post with it)', ''],
  // THE VIEWING GLASS (v1.38.2) — the last three env-only knobs, now live
  ['ATLAS_EMBED_HOSTS', 'Glass: extra origins the map may frame', 'https://host:port https://other'],
  ['ATLAS_EMBED_SERVICES', 'Glass: frame the dataset\u2019s own services (1/0)', '1'],
  ['ATLAS_EMBED_PROBE', 'Glass: ask a service if it allows framing (1/0)', '1'],
];

async function renderRealm() {
  const el = $('sp-realm');
  if (!el) return;
  el.hidden = !CFG.AUTH.admin;
  if (el.hidden) return;
  let cfg;
  try {
    const r = await fetch('api/v2/admin/integrations', { headers: { 'Accept': 'application/json' } });
    if (!r.ok) throw new Error(String(r.status));
    cfg = await r.json();
  } catch { el.hidden = true; return; }
  const rows = REALM_FIELDS.map(([key, label, hint]) => {
    const f = cfg.settings[key] || {};
    const src = SOURCE_LABEL[f.source] || '';
    if (f.secret) {
      return `<label class="dir-row">
          <span class="dir-label">${esc(label)}<span class="dir-src">${esc(f.set ? src + ' · kept' : 'unset')}</span></span>
          <input class="dir-input" type="password" data-key="${key}" data-secret="1" value=""
                 placeholder="${f.set ? 'leave blank to keep the stored token' : 'not set'}"
                 autocomplete="new-password" spellcheck="false">
        </label>`;
    }
    return `<label class="dir-row">
        <span class="dir-label">${esc(label)}<span class="dir-src">${esc(src)}</span></span>
        <input class="dir-input" data-key="${key}" value="${esc(f.value || '')}" placeholder="${esc(hint)}"
               autocomplete="off" spellcheck="false">
      </label>`;
  }).join('');
  el.innerHTML =
    `<button class="sp-sub" type="button">THE REALM</button>
     <div class="sp-sec-body">
     <div class="acct-note">Where the seal sends you home, what is trimmed off a scroll's path,
       and the token the rites post their heartbeats with. Blank means “use the deployment value”.</div>
     ${rows}
     <div class="sp-actions"><button class="sp-btn sp-btn-go" id="realm-save">Save</button></div>
     <div class="dir-result" id="realm-result"></div>
     </div>`;
  $('realm-save')?.addEventListener('click', saveRealm);
  A.applySettingsFolds?.();
}

async function saveRealm() {
  const box = $('realm-result');
  const values = {};
  for (const input of document.querySelectorAll('#sp-realm .dir-input[data-key]')) values[input.dataset.key] = input.value.trim();
  try {
    const r = await fetch('api/v2/admin/integrations', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Atlas-Write': '1' },
      body: JSON.stringify({ settings: values }),
    });
    const j = await r.json();
    if (!r.ok) { box.className = 'dir-result dir-bad'; box.textContent = j.error || 'Those settings were refused.'; return; }
    await renderRealm();
    const fresh = $('realm-result');
    if (fresh) { fresh.className = 'dir-result dir-ok'; fresh.textContent = 'The realm is set. A reload picks up the Hub door and the vault root.'; }
  } catch {
    box.className = 'dir-result dir-bad';
    box.textContent = 'The save did not reach the realm.';
  }
}

/* ── THE DEPLOYMENT — every knob this instance runs with, read-only (v1.38.0).
   Secrets show only set/unset. There is no Save here and there must never be
   one: the two allow-listed forms above are the only writable knobs. */
async function renderDeployment() {
  const el = $('sp-deployment');
  if (!el) return;
  el.hidden = !CFG.AUTH.admin;
  if (el.hidden) return;
  let d;
  try {
    const r = await fetch('api/v2/admin/deployment', { headers: { 'Accept': 'application/json' } });
    if (!r.ok) throw new Error(String(r.status));
    d = await r.json();
  } catch { el.hidden = true; return; }
  const SRC = { settings: 'set here', environment: 'from the deployment', default: 'default' };
  const rows = (d.knobs || []).map((k) =>
    `<div class="dep-row${k.source === 'default' ? ' dep-default' : ''}">` +
      `<span class="dep-name">${esc(k.name)}</span>` +
      `<span class="dep-val${k.secret ? ' dep-secret' : ''}">${esc(k.value || (k.source === 'default' ? '—' : ''))}</span>` +
      `<span class="dir-src">${esc(SRC[k.source] || k.source)}</span></div>`).join('');
  el.innerHTML =
    `<button class="sp-sub" type="button">THE DEPLOYMENT</button>
     <div class="sp-sec-body">
     <div class="acct-note">v${esc(d.version)} · ${esc(d.mode)} mode · self-report ${d.metrics ? 'on' : 'off'}.
       Every knob the Atlas knows and where its value came from — reading only; the two
       forms above are the only pens.</div>
     <div class="dep-list">${rows}</div>
     </div>`;
  A.applySettingsFolds?.();
}

/* ── THE SOURCES — what the Atlas asks, and where (v1.37.0) ──────────────
   Prometheus (the pulse, the watchings), Loki (the edge's log-derived
   watchings), Uptime-Kuma (the signals) and the decoy feed (the stones). Admins in
   ANY mode: unlike THE DIRECTORY this form decides nothing about sign-in, so
   a Hub-named admin may set it. Every field is optional — blank falls through
   to the deployment — and the chip beside each says which layer the value in
   force came from. Keys are write-only: the form never learns a stored one,
   only that one is set; TEST with a blank key asks with the one in force. */
const SRC_FIELDS = [
  ['ATLAS_SIGNALS_SOURCES', 'Signals sources', 'kuma,prometheus,deception'],
  ['ATLAS_PROM_URL', 'Prometheus URL', 'http://prometheus:9090'],
  ['ATLAS_LOKI_URL', 'Loki URL', 'http://loki:3100'],
  ['ATLAS_KUMA_URL', 'Uptime-Kuma URL', 'http://kuma:3001'],
  ['ATLAS_KUMA_API_KEY', 'Kuma API key', ''],
  ['ATLAS_DECOYS_URL', `${themeText('decoy_source', 'Decoy feed')} URL`, 'http://decoys:5013'],
  ['ATLAS_DECOYS_KEY', `${themeText('decoy_source', 'Decoy feed')} read key`, ''],
];
const SRC_TESTS = [['prometheus', 'Prometheus'], ['loki', 'Loki'], ['kuma', 'Kuma'], ['decoys', themeText('decoy_source', 'Decoy feed')]];

async function renderSources() {
  const el = $('sp-integrations');
  if (!el) return;
  el.hidden = !CFG.AUTH.admin;
  if (el.hidden) return;
  let cfg;
  try {
    const r = await fetch('api/v2/admin/integrations', { headers: { 'Accept': 'application/json' } });
    if (!r.ok) throw new Error(String(r.status));
    cfg = await r.json();
  } catch { el.hidden = true; return; }   // not an admin after all, or no editing API
  const rows = SRC_FIELDS.map(([key, label, hint]) => {
    const f = cfg.settings[key] || {};
    const src = SOURCE_LABEL[f.source] || '';
    if (f.secret) {
      return `<label class="dir-row">
          <span class="dir-label">${esc(label)}<span class="dir-src">${esc(f.set ? src + ' · kept' : 'unset')}</span></span>
          <input class="dir-input" type="password" data-key="${key}" data-secret="1" value=""
                 placeholder="${f.set ? 'leave blank to keep the stored key' : 'not set'}"
                 autocomplete="new-password" spellcheck="false">
        </label>`;
    }
    return `<label class="dir-row">
        <span class="dir-label">${esc(label)}<span class="dir-src">${esc(src)}</span></span>
        <input class="dir-input" data-key="${key}" value="${esc(f.value || '')}" placeholder="${esc(hint)}"
               autocomplete="off" spellcheck="false">
      </label>`;
  }).join('');
  const hub = cfg.hub || {};
  const state = (hub.enabled || []).length
    ? (hub.enabled || []).map((s) => `${esc(s)} <em>${esc(hub.last?.[s] || 'not asked yet')}</em>`).join(' · ')
    : 'no live source is running — the map is static';
  el.innerHTML =
    `<button class="sp-sub" type="button">THE SOURCES</button>
     <div class="sp-sec-body">
     <div class="acct-note">What the realm asks for its numbers, its signals and its stones.
       Blank means “use the deployment value”. Live now: ${state}.</div>
     ${rows}
     <div class="sp-actions src-tests">
       ${SRC_TESTS.map(([k, name]) => `<button class="sp-btn" data-test="${k}">Test ${esc(name)}</button>`).join('')}
       <button class="sp-btn sp-btn-go" id="src-save">Save</button>
     </div>
     <div class="dir-result" id="src-result"></div>
     </div>`;
  for (const b of el.querySelectorAll('[data-test]')) b.addEventListener('click', () => testSource(b.dataset.test, b));
  $('src-save')?.addEventListener('click', saveSources);
  A.applySettingsFolds?.();
}

function sourceValues() {
  const out = {};
  for (const input of document.querySelectorAll('#sp-integrations .dir-input[data-key]')) {
    // a blank secret means "keep what is stored" — the API reads it that way
    out[input.dataset.key] = input.value.trim();
  }
  return out;
}

async function testSource(kind, btn) {
  const box = $('src-result');
  box.className = 'dir-result';
  box.textContent = `Asking ${kind}…`;
  btn.disabled = true;
  try {
    const r = await fetch('api/v2/admin/integrations/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Atlas-Write': '1' },
      body: JSON.stringify({ kind, settings: sourceValues() }),
    });
    const j = await r.json();
    box.className = 'dir-result ' + (j.ok ? 'dir-ok' : 'dir-bad');
    box.textContent = j.ok ? j.detail : (j.error || `${kind} did not answer.`);
  } catch {
    box.className = 'dir-result dir-bad';
    box.textContent = `${kind} did not answer.`;
  } finally {
    btn.disabled = false;
  }
}

async function saveSources() {
  const box = $('src-result');
  try {
    const r = await fetch('api/v2/admin/integrations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Atlas-Write': '1' },
      body: JSON.stringify({ settings: sourceValues() }),
    });
    const j = await r.json();
    if (!r.ok) {
      box.className = 'dir-result dir-bad';
      box.textContent = j.error || 'Those settings were refused.';
      return;
    }
    await renderSources();   // fresh chips first — the re-render would swallow the message
    const fresh = $('src-result');
    if (fresh) {
      fresh.className = 'dir-result dir-ok';
      fresh.textContent = 'The sources are set. The next poll asks the new ones; the watchings redraw as they refresh.';
    }
    A.repaintSignals?.();
  } catch {
    box.className = 'dir-result dir-bad';
    box.textContent = 'The save did not reach the realm.';
  }
}

/* ── THE DIRECTORY — which directory may sign people in ──────────────────
   Admin-only, and only where an Atlas session can exist at all (accounts /
   hybrid); in hub mode the Hub owns sign-in and these fields would decide
   nothing. Every field is optional: left blank it falls through to the
   deployment config, and the source chip beside each says which layer the
   value in force actually came from.

   The Save button stays disabled until a Test has bound a real account,
   because this form decides who may sign in AND who is an admin — the API
   refuses a directory-only save without that proof, and a UI that let you
   press Save first would only be teaching you to ignore the refusal. */
const DIR_FIELDS = [
  ['ATLAS_AUTH_BACKENDS', 'Sign-in order', 'local,ldap'],
  ['ATLAS_LDAP_URL', 'Directory URL', 'ldaps://dc.example.com:636'],
  ['ATLAS_LDAP_BASE_DN', 'Base DN', 'DC=example,DC=com'],
  ['ATLAS_LDAP_UPN_DOMAIN', 'UPN domain', 'derived from the base DN'],
  ['ATLAS_LDAP_CA_FILE', 'CA bundle', '/run/secrets/directory-ca.pem'],
  ['ATLAS_LDAP_ACCESS_GROUPS', 'May sign in (groups)', 'Atlas-Viewers'],
  ['ATLAS_LDAP_ADMIN_GROUPS', 'Are surveyors (groups)', 'Atlas-Admins'],
  ['ATLAS_LDAP_TIMEOUT', 'Timeout (s)', '5'],
];
const SOURCE_LABEL = { settings: 'set here', deployment: 'from the deployment', unset: 'unset' };

async function renderDirectory() {
  const el = $('sp-directory');
  if (!el) return;
  const posture = authAdminPosture();
  el.hidden = posture === 'hide';
  if (el.hidden) return;
  if (posture === 'hub-named') {
    el.innerHTML = `<button class="sp-sub" type="button">THE DIRECTORY</button>` +
      `<div class="sp-sec-body">${hubNamedAdminHint}</div>`;
    A.applySettingsFolds?.();
    return;
  }
  let cfg;
  try {
    const r = await fetch('api/v2/admin/auth', { headers: { 'Accept': 'application/json' } });
    if (!r.ok) throw new Error(String(r.status));
    cfg = await r.json();
  } catch { el.hidden = true; return; }   // not an admin after all, or no editing API
  el.hidden = false;
  const rows = DIR_FIELDS.map(([key, label, hint]) => {
    const val = esc(cfg.settings[key] || '');
    const src = SOURCE_LABEL[cfg.sources[key]] || '';
    return `<label class="dir-row">
        <span class="dir-label">${esc(label)}<span class="dir-src">${esc(src)}</span></span>
        <input class="dir-input" data-key="${key}" value="${val}" placeholder="${esc(hint)}"
               autocomplete="off" spellcheck="false">
      </label>`;
  }).join('');
  el.innerHTML =
    `<button class="sp-sub" type="button">THE DIRECTORY</button>
     <div class="sp-sec-body">
     <div class="acct-note">Who the realm asks about a name it does not keep itself.
       Blank means “use the deployment value”.</div>
     ${rows}
     <div class="dir-test">
       <input class="dir-input" id="dir-user" placeholder="a directory name to test with" autocomplete="off">
       <input class="dir-input" id="dir-pass" type="password" placeholder="their password" autocomplete="off">
     </div>
     <div class="sp-actions">
       <button class="sp-btn" id="dir-test">Test the binding</button>
       <button class="sp-btn sp-btn-go" id="dir-save" disabled title="Test a real account first">Save</button>
     </div>
     <div class="dir-result" id="dir-result"></div>
     </div>`;
  $('dir-test')?.addEventListener('click', testDirectory);
  $('dir-save')?.addEventListener('click', saveDirectory);
  A.applySettingsFolds?.();   // a re-render forgets its fold; put it back
}

function directoryValues() {
  const out = {};
  for (const input of document.querySelectorAll('#sp-directory .dir-input[data-key]')) {
    out[input.dataset.key] = input.value.trim();
  }
  return out;
}

async function testDirectory() {
  const box = $('dir-result');
  const btn = $('dir-test');
  box.className = 'dir-result';
  box.textContent = 'Asking the directory…';
  btn.disabled = true;
  try {
    const r = await fetch('api/v2/admin/auth/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Atlas-Write': '1' },
      body: JSON.stringify({ settings: directoryValues(),
                             username: $('dir-user').value, password: $('dir-pass').value }),
    });
    const j = await r.json();
    if (j.ok) {
      box.className = 'dir-result dir-ok';
      box.textContent = `${$('dir-user').value} was admitted` +
        (j.is_admin ? ' as a SURVEYOR — this config can be saved.'
                    : ' — but not as a surveyor. A directory-only sign-in still needs a proven admin.');
      // the password was only ever needed for the bind; don't leave it sitting in the DOM
      $('dir-pass').value = '';
      $('dir-save').disabled = false;
      $('dir-save').title = '';
    } else {
      box.className = 'dir-result dir-bad';
      box.textContent = j.error || 'The directory refused that account.';
    }
  } catch {
    box.className = 'dir-result dir-bad';
    box.textContent = 'The directory did not answer.';
  } finally {
    btn.disabled = false;
  }
}

async function saveDirectory() {
  const box = $('dir-result');
  try {
    const r = await fetch('api/v2/admin/auth', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Atlas-Write': '1' },
      body: JSON.stringify({ settings: directoryValues() }),
    });
    const j = await r.json();
    if (!r.ok) {
      box.className = 'dir-result dir-bad';
      box.textContent = j.error || 'That configuration was refused.';
      return;
    }
    box.className = 'dir-result dir-ok';
    box.textContent = 'The directory is set. New sign-ins use it from now on.';
    renderDirectory();
  } catch {
    box.className = 'dir-result dir-bad';
    box.textContent = 'The save did not reach the realm.';
  }
}

/** Ends the Atlas session (accounts/hybrid). The route requires the same-origin
    write proof — the `X-Atlas-Write` header a cross-origin page cannot set — so
    a bare cross-site POST is refused, which is the point of it. (No CSRF token
    any more; the header is the whole proof.) */
async function signOut() {
  const btn = $('acct-signout');
  if (btn) { btn.disabled = true; btn.textContent = 'Signing out…'; }
  try {
    const r = await fetch('api/v2/auth/logout', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Atlas-Write': '1' },
    });
    if (!r.ok) throw new Error('refused');
    location.href = 'auth/login';
  } catch {
    if (btn) { btn.disabled = false; btn.textContent = 'Sign out'; }
    A.showToast?.('The realm would not let go of you — reload and try again.');
  }
}


// The one inbound arrow (ui.js's settings-tab handler → here). Everything else
// this surface exposes is wired to its own buttons at load.
A.renderSettingsSections = renderSettingsSections;
