/* The sign-in flow: password → (MFA verify | forced MFA enrollment) → the map.
 *
 * ⚠ THIS FILE EXISTS BECAUSE OF THE CSP. It was an inline <script> in
 * login.html until 2026-08-12, and the app-wide policy set in app.py is
 * `default-src 'self'` with no `script-src` — so `default-src` was the
 * fallback for scripts and the browser **blocked the whole block**. The page
 * still rendered, so it looked fine; what actually happened was that no
 * handler ever attached, `f-login` fell back to a NATIVE form submit, and the
 * password went into the URL as a GET query — into browser history, the
 * gunicorn access log (journald) and any proxy log in front of it. Every later
 * step (MFA verify, forced enrollment, "continue to the map") was dead for the
 * same reason, which made accounts mode unusable in a real browser.
 *
 * The test suite could not see it: the Flask test client does not enforce CSP,
 * so the flow passes there and fails in every browser. Served from `static/`
 * it is same-origin, which `default-src 'self'` already allows — the policy is
 * untouched, and nothing here needs 'unsafe-inline'.
 *
 * Server values arrive through a `type="application/json"` data block, the
 * same contract index.html uses for its own config: a data block is not
 * executable, so the CSP has no opinion about it.
 */

var _cfg = {};
try {
  _cfg = JSON.parse(document.getElementById('login-config').textContent || '{}');
} catch (e) {
  /* a malformed block must not leave the gate unusable — NEXT falls back to
     the map and the form still signs you in */
}

var NEXT = _cfg.next || '/';
var err = document.getElementById('err');

function show(stage) {
  document.querySelectorAll('.stage').forEach(function (s) { s.classList.remove('lit'); });
  document.getElementById('stage-' + stage).classList.add('lit');
  err.style.display = 'none';
  var first = document.querySelector('#stage-' + stage + ' input');
  if (first) first.focus();
}
function fail(msg) { err.textContent = msg; err.style.display = 'block'; }

/* ⚠ THE SECOND WAY THIS GATE WENT DECORATIVE — same shape as the CSP bug above,
 * a different mechanism. Every call here used an ABSOLUTE path
 * (`fetch('/api/v2/auth/login')`), which resolves against the ORIGIN, not the page.
 * Served directly that is right; served behind the Hub at `/atlas/auth/login`
 * it escapes the prefix and posts to the HUB's root, which 404s. The Atlas
 * never saw a single sign-in attempt — its access log had no POST at all while
 * the Hub's logged the 404s — so a correct password read as a failure.
 *
 * The server cannot help: the Hub strips its prefix before proxying, so Flask
 * sees `/auth/login` with an empty SCRIPT_ROOT and has no idea it is mounted
 * anywhere. The only thing that knows is this page's own URL, so derive the
 * root from it and hang every call off that.
 *
 * Latent until 2026-08-17: until the Hub began proxying self-gated apps
 * anonymously, it bounced anonymous callers to its OWN login and the Atlas's
 * sign-in was simply never reachable under `/atlas/`.
 */
var ROOT = window.location.pathname.replace(/\/auth\/login\/?$/, '');
/* Same trap for the landing: `next` is Atlas-relative ('/'), so under the Hub
 * `window.location = '/'` would leave the app entirely and land on the Hub's
 * own root instead of the map you just signed in to see. */
NEXT = ROOT + NEXT;

function post(path, body) {
  return fetch(ROOT + path, {
    method: 'POST',
    /* X-Atlas-Write is the app's one proof that a request came from its own
       page — a cross-origin page cannot set a custom header without a CORS
       preflight this app never answers. Same header the editor sends. */
    headers: { 'Content-Type': 'application/json', 'X-Atlas-Write': '1' },
    body: JSON.stringify(body || {})
  }).then(function (r) { return r.json().then(function (j) {
    return { status: r.status, body: j };
  }); });
}

document.getElementById('f-login').addEventListener('submit', function (e) {
  e.preventDefault();
  var btn = document.getElementById('b-login');
  btn.disabled = true;
  post('/api/v2/auth/login', {
    username: document.getElementById('u').value,
    password: document.getElementById('p').value
  }).then(function (r) {
    // Re-enable ONLY when the surveyor stays on this page. Re-enabling first
    // meant the button flicked back to full opacity — and to its gold hover
    // fill, since the cursor is still on it — for the whole of the redirect
    // or the stage swap. On the paths that leave, it stays disabled and simply
    // goes with the page.
    if (!r.body.ok) { btn.disabled = false; return fail(r.body.error || 'Sign-in failed.'); }
    if (r.body.mfa_required) return show('mfa');
    if (r.body.mfa_setup_required) return startEnroll();
    window.location = NEXT;
  }).catch(function () { btn.disabled = false; fail('The gate did not answer.'); });
});

document.getElementById('f-mfa').addEventListener('submit', function (e) {
  e.preventDefault();
  post('/api/v2/auth/login/mfa', { code: document.getElementById('c').value })
    .then(function (r) {
      if (!r.body.ok) return fail(r.body.error || 'Verification failed.');
      window.location = NEXT;
    });
});

function startEnroll() {
  post('/api/v2/auth/mfa/setup').then(function (r) {
    if (!r.body.ok) return fail(r.body.error || 'Could not begin enrollment.');
    /* markup on purpose: the SVG is drawn by this app's own server (auth/mfa) */
    document.getElementById('qr').innerHTML = r.body.qr_svg;
    document.getElementById('secret').textContent = r.body.secret;
    show('enroll');
  });
}

document.getElementById('f-enroll').addEventListener('submit', function (e) {
  e.preventDefault();
  post('/api/v2/auth/mfa/confirm', { code: document.getElementById('ec').value })
    .then(function (r) {
      if (!r.body.ok) return fail(r.body.error || 'Incorrect code.');
      var box = document.getElementById('codes');
      box.innerHTML = '';
      (r.body.backup_codes || []).forEach(function (c) {
        var d = document.createElement('div'); d.textContent = c; box.appendChild(d);
      });
      show('codes');
    });
});

document.getElementById('b-done').addEventListener('click', function () {
  window.location = NEXT;
});
