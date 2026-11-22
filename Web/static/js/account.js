
import { A, CFG, $, esc, themeText, WRITE_HEADERS, postJSON, readJSON } from './config.js';
import { renderConnections } from './connections.js';

function renderAccount() {
  const el = $('sp-account');
  if (!el) return;
  const a = CFG.AUTH || {};
  if (!a.mode || a.mode === 'standalone') { el.hidden = true; return; }
  el.hidden = false;
  const who = esc(a.user || 'unknown');
  const via = a.session === 'hub' ? 'VIA THE HUB'
            : a.source === 'ldap' ? 'VIA AD'
            : a.source === 'local' ? 'LOCAL ACCOUNT'
            : '';
  const badges = [
    a.admin ? '<span class="acct-badge">ADMIN</span>' : '',
    via ? `<span class="acct-badge acct-badge-quiet">${via}</span>` : '',
    a.mode === 'accounts' && a.mfa ? '<span class="acct-badge acct-badge-quiet">MFA</span>' : '',
  ].join('');
  const note = a.canSignOut
    ? (a.mfa ? 'Two-factor sign-in is on for this account.' : 'Two-factor sign-in is off for this account.')
    : `Signed in through ${themeText('hub_name', 'the Hub')}. Sign out there.`;
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
  const pwForm = a.canSignOut && a.source === 'local'
    ? `<details class="acct-pw"><summary class="sp-hint">Change password</summary>
         <input class="dir-input" id="pw-current" type="password" placeholder="current password" autocomplete="current-password">
         <input class="dir-input" id="pw-new" type="password" placeholder="new password" autocomplete="new-password">
         <input class="dir-input" id="pw-again" type="password" placeholder="new password, again" autocomplete="new-password">
         <div class="sp-actions"><button class="sp-btn" id="pw-save" type="button">Change password</button></div>
       </details>`
    : '';
  el.innerHTML =
    `<button class="sp-sub" type="button">ACCOUNT <span class="sp-sub-plain">· your sign-in</span></button>
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
  A.applySettingsFolds?.();
}

async function changePassword() {
  const btn = $('pw-save');
  const current = $('pw-current').value, next = $('pw-new').value, again = $('pw-again').value;
  if (!current || !next) { A.showToast?.('Both the current and the new password are needed.'); return; }
  if (next !== again) { A.showToast?.('The new passwords do not match.'); return; }
  btn.disabled = true;
  try {
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


const EMBLEMS = ['🗡','🛡','🏹','🪄','🧭','🗺','⚗','🔥','🌙','⭐','🍄','👁'];

const hubNamedAdminHint =
  `<div class="sp-hint">You are signed in through ${esc(themeText('hub_name', 'the Hub'))}. Managing accounts needs ` +
  `an Atlas sign-in: <a href="auth/login">sign in to the Atlas directly</a>.</div>`;

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
  headers: WRITE_HEADERS,
  body: JSON.stringify(payload || {}),
});

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
  catch { body.innerHTML = `<div class="sp-hint">The user list could not be loaded.</div>`; return; }
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
    `<div class="sp-hint">Local accounts only. Directory users sign in with their directory ` +
    `password and appear here after their first sign-in. A blocked user cannot sign in either way.</div>`;
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
  try { events = (await authApi('api/v2/auth/audit?limit=60')).events || []; }
  catch { body.innerHTML = `<div class="sp-hint">Sign-in history could not be loaded.</div>`; return; }
  const rows = events.map((e) =>
    `<div class="aud-row${/fail|locked|denied/.test(e.event) ? ' aud-bad' : ''}">` +
    `<span class="aud-ts" title="${esc(e.ts || '')}">${esc(stampLocal(e.ts))}</span>` +
    `<span class="aud-ev">${esc(e.event)}</span>` +
    `<span class="aud-who">${esc(e.username || '')}</span>` +
    `<span class="aud-ip">${esc(e.ip || '')}</span></div>`).join('');
  body.innerHTML = `<div class="aud-list">` +
    (rows || `<div class="sp-hint">Nothing recorded yet.</div>`) + `</div>`;
}

function refreshSigninsIfOpen() {
  const el = $('sp-signins');
  if (el && !el.hidden && !el.classList.contains('closed') && !el._load) loadSignins();
}

function renderUsers() { adminSection('sp-users', 'USERS', 'who can sign in', loadUsers); }
function renderSignins() { adminSection('sp-signins', 'SIGN-IN HISTORY', 'recent attempts', loadSignins); }

function renderSettingsSections() {
  renderAccount();
  renderDirectory();
  renderConnections();
  const integrations = readIntegrations();
  renderSources(integrations);
  renderRealm(integrations);
  renderDeployment();
  renderUsers();
  renderSignins();
}

const REALM_FIELDS = [
  ['HUB_URL', 'Hub URL', 'https://hub.example.com'],
  ['ATLAS_SCROLL_ROOT', 'Docs folder (removed from document paths)', '/srv/docs/'],
  ['ATLAS_BEAT_TOKEN', 'Heartbeat token (scheduled jobs send it)', ''],
  ['ATLAS_EMBED_HOSTS', 'Embedding: extra sites the map may show', 'https://host:port https://other'],
  ['ATLAS_EMBED_SERVICES', 'Embedding: show the map\u2019s own services (1 on, 0 off)', '1'],
  ['ATLAS_EMBED_PROBE', 'Embedding: check a service allows it first (1 on, 0 off)', '1'],
  ['ATLAS_WHOIS', 'Whois: let viewers ask public registries (1 on, 0 off)', '1'],
];

async function readIntegrations() {
  if (!CFG.AUTH.admin) return null;
  try {
    const r = await fetch('api/v2/admin/integrations', { headers: { 'Accept': 'application/json' } });
    if (!r.ok) throw new Error(String(r.status));
    return await r.json();
  } catch { return null; }
}

async function renderRealm(pending = readIntegrations()) {
  const el = $('sp-realm');
  if (!el) return;
  el.hidden = !CFG.AUTH.admin;
  if (el.hidden) return;
  const cfg = await pending;
  if (!cfg) { el.hidden = true; return; }
  const rows = settingsRows(REALM_FIELDS, cfg, 'token');
  el.innerHTML =
    `<button class="sp-sub" type="button">LAB SETTINGS <span class="sp-sub-plain">· Hub, docs, heartbeats</span></button>
     <div class="sp-sec-body">
     <div class="acct-note">The Hub link, the folder removed from document paths, the token scheduled jobs
       send with their heartbeats, and which sites the map may show inside itself.
       Leave a field blank to use the deployment value.</div>
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
    const r = await postJSON('api/v2/admin/integrations', { settings: values });
    const j = await r.json();
    if (!r.ok) { box.className = 'dir-result dir-bad'; box.textContent = j.error || 'Those settings were refused.'; return; }
    await renderRealm();
    const fresh = $('realm-result');
    if (fresh) { fresh.className = 'dir-result dir-ok'; fresh.textContent = 'Saved. A reload picks up the Hub door and the vault root.'; }
  } catch {
    box.className = 'dir-result dir-bad';
    box.textContent = 'The save did not reach the server.';
  }
}

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
    `<button class="sp-sub" type="button">DEPLOYMENT <span class="sp-sub-plain">· every setting, read-only</span></button>
     <div class="sp-sec-body">
     <div class="acct-note">v${esc(d.version)} · ${esc(d.mode)} mode · self-report ${d.metrics ? 'on' : 'off'}.
       Every setting the Atlas knows and where its value came from. To change one, use
       Data sources or Lab settings; the rest are set in the deployment.</div>
     <div class="dep-list">${rows}</div>
     </div>`;
  A.applySettingsFolds?.();
}

const SRC_FIELDS = [
  ['ATLAS_SIGNALS_SOURCES', 'Live sources (comma-separated)', 'kuma,prometheus,unifi,checks,deception'],
  ['ATLAS_PROM_URL', 'Prometheus URL', 'http://prometheus:9090'],
  ['ATLAS_LOKI_URL', 'Loki URL', 'http://loki:3100'],
  ['ATLAS_KUMA_URL', 'Uptime-Kuma URL', 'http://kuma:3001'],
  ['ATLAS_KUMA_API_KEY', 'Kuma API key', ''],
  ['ATLAS_DECOYS_URL', `${themeText('decoy_source', 'Decoy feed')} URL`, 'http://decoys:8080'],
  ['ATLAS_DECOYS_KEY', `${themeText('decoy_source', 'Decoy feed')} read key`, ''],
];
const SRC_TESTS = [['prometheus', 'Prometheus'], ['loki', 'Loki'], ['kuma', 'Kuma'], ['decoys', themeText('decoy_source', 'Decoy feed')]];

async function renderSources(pending = readIntegrations()) {
  const el = $('sp-integrations');
  if (!el) return;
  el.hidden = !CFG.AUTH.admin;
  if (el.hidden) return;
  const cfg = await pending;
  if (!cfg) { el.hidden = true; return; }
  const rows = settingsRows(SRC_FIELDS, cfg, 'key');
  const hub = cfg.hub || {};
  const state = (hub.enabled || []).length
    ? (hub.enabled || []).map((s) => `${esc(s)} <em>${esc(hub.last?.[s] || 'not asked yet')}</em>`).join(' · ')
    : 'no live source is running — the map is static';
  el.innerHTML =
    `<button class="sp-sub" type="button">DATA SOURCES <span class="sp-sub-plain">· health, metrics and logs</span></button>
     <div class="sp-sec-body">
     <div class="acct-note">Where the map gets its health, metrics, logs and tripwires. Test a source before
       you save. Leave a field blank to use the deployment value. Built-in checks (add
       checks to the live sources): asks the service URLs on your map; nothing else.
       Live now: ${state}.</div>
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
    const r = await postJSON('api/v2/admin/integrations/test', { kind, settings: sourceValues() });
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
    const r = await postJSON('api/v2/admin/integrations', { settings: sourceValues() });
    const j = await r.json();
    if (!r.ok) {
      box.className = 'dir-result dir-bad';
      box.textContent = j.error || 'Those settings were refused.';
      return;
    }
    await renderSources();
    const fresh = $('src-result');
    if (fresh) {
      fresh.className = 'dir-result dir-ok';
      fresh.textContent = 'Saved. The next poll uses the new sources, and charts update as they refresh.';
    }
    A.repaintSignals?.();
  } catch {
    box.className = 'dir-result dir-bad';
    box.textContent = 'The save did not reach the server.';
  }
}

const DIR_FIELDS = [
  ['ATLAS_AUTH_BACKENDS', 'Sign-in order', 'local,ldap'],
  ['ATLAS_LDAP_URL', 'Directory URL', 'ldaps://dc.example.com:636'],
  ['ATLAS_LDAP_BASE_DN', 'Base DN', 'DC=example,DC=com'],
  ['ATLAS_LDAP_UPN_DOMAIN', 'UPN domain', 'derived from the base DN'],
  ['ATLAS_LDAP_CA_FILE', 'CA bundle', '/run/secrets/directory-ca.pem'],
  ['ATLAS_LDAP_ACCESS_GROUPS', 'Groups allowed to sign in', 'Atlas-Viewers'],
  ['ATLAS_LDAP_ADMIN_GROUPS', 'Admin groups', 'Atlas-Admins'],
  ['ATLAS_LDAP_TIMEOUT', 'Timeout (s)', '5'],
];
const SOURCE_LABEL = { settings: 'set here', deployment: 'from the deployment', unset: 'unset' };

const textRow = (key, label, hint, value, src) =>
  `<label class="dir-row">
        <span class="dir-label">${esc(label)}<span class="dir-src">${esc(src)}</span></span>
        <input class="dir-input" data-key="${key}" value="${esc(value)}" placeholder="${esc(hint)}"
               autocomplete="off" spellcheck="false">
      </label>`;
const secretRow = (key, label, src, set, noun) =>
  `<label class="dir-row">
          <span class="dir-label">${esc(label)}<span class="dir-src">${esc(set ? src + ' · kept' : 'unset')}</span></span>
          <input class="dir-input" type="password" data-key="${key}" data-secret="1" value=""
                 placeholder="${set ? `leave blank to keep the stored ${noun}` : 'not set'}"
                 autocomplete="new-password" spellcheck="false">
        </label>`;
function settingsRows(fields, cfg, noun) {
  return fields.map(([key, label, hint]) => {
    const f = cfg.settings[key] || {};
    const src = SOURCE_LABEL[f.source] || '';
    return f.secret ? secretRow(key, label, src, f.set, noun) : textRow(key, label, hint, f.value || '', src);
  }).join('');
}

async function renderDirectory() {
  const el = $('sp-directory');
  if (!el) return;
  const posture = authAdminPosture();
  el.hidden = posture === 'hide';
  if (el.hidden) return;
  if (posture === 'hub-named') {
    el.innerHTML = `<button class="sp-sub" type="button">DIRECTORY SIGN-IN <span class="sp-sub-plain">· Active Directory or LDAP</span></button>` +
      `<div class="sp-sec-body">${hubNamedAdminHint}</div>`;
    A.applySettingsFolds?.();
    return;
  }
  let cfg;
  try {
    const r = await fetch('api/v2/admin/auth', { headers: { 'Accept': 'application/json' } });
    if (!r.ok) throw new Error(String(r.status));
    cfg = await r.json();
  } catch { el.hidden = true; return; }
  el.hidden = false;
  const rows = DIR_FIELDS.map(([key, label, hint]) =>
    textRow(key, label, hint, cfg.settings[key] || '', SOURCE_LABEL[cfg.sources[key]] || '')).join('');
  el.innerHTML =
    `<button class="sp-sub" type="button">DIRECTORY SIGN-IN <span class="sp-sub-plain">· Active Directory or LDAP</span></button>
     <div class="sp-sec-body">
     <div class="acct-note">Lets people sign in with their directory account. Test a real account, then Save.
       Leave a field blank to use the deployment value.</div>
     ${rows}
     <div class="dir-test">
       <input class="dir-input" id="dir-user" placeholder="a directory username to test" autocomplete="off">
       <input class="dir-input" id="dir-pass" type="password" placeholder="their password" autocomplete="off">
     </div>
     <div class="sp-actions">
       <button class="sp-btn" id="dir-test">Test sign-in</button>
       <button class="sp-btn sp-btn-go" id="dir-save" disabled title="Test a real account first">Save</button>
     </div>
     <div class="dir-result" id="dir-result"></div>
     </div>`;
  $('dir-test')?.addEventListener('click', testDirectory);
  $('dir-save')?.addEventListener('click', saveDirectory);
  A.applySettingsFolds?.();
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
  box.textContent = 'Testing the sign-in…';
  btn.disabled = true;
  try {
    const r = await postJSON('api/v2/admin/auth/test', {
      settings: directoryValues(), username: $('dir-user').value, password: $('dir-pass').value,
    });
    const j = await r.json();
    if (j.ok) {
      box.className = 'dir-result dir-ok';
      box.textContent = `${$('dir-user').value} was admitted` +
        (j.is_admin ? ' as an admin. You can save this now.'
                    : ' — but not as a surveyor. A directory-only sign-in still needs a proven admin.');
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
    const r = await postJSON('api/v2/admin/auth', { settings: directoryValues() });
    const j = await readJSON(r);
    if (!r.ok) {
      box.className = 'dir-result dir-bad';
      box.textContent = j?.error || 'That configuration was refused.';
      return;
    }
  } catch {
    box.className = 'dir-result dir-bad';
    box.textContent = 'The save did not reach the server.';
    return;
  }
  try { await renderDirectory(); } catch {   }
  const fresh = $('dir-result') || box;
  fresh.className = 'dir-result dir-ok';
  fresh.textContent = 'Saved. New sign-ins use this directory from now on.';
}

async function signOut() {
  const btn = $('acct-signout');
  if (btn) { btn.disabled = true; btn.textContent = 'Signing out…'; }
  try {
    const r = await postJSON('api/v2/auth/logout');
    if (!r.ok) throw new Error('refused');
    location.href = 'auth/login';
  } catch {
    if (btn) { btn.disabled = false; btn.textContent = 'Sign out'; }
    A.showToast?.('Sign-out did not finish — reload and try again.');
  }
}


A.renderSettingsSections = renderSettingsSections;
