
try {
  if (localStorage.getItem('atlas-words') === 'standard') {
    document.getElementById('b-login').textContent = 'Sign in';
  }
} catch (e) {   }

var _cfg = {};
try {
  _cfg = JSON.parse(document.getElementById('login-config').textContent || '{}');
} catch (e) {
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

var ROOT = window.location.pathname.replace(/\/auth\/login\/?$/, '');
NEXT = ROOT + NEXT;
try {
  if (new URL(NEXT, location.origin).origin !== location.origin) NEXT = ROOT + '/';
} catch (e) { NEXT = ROOT + '/'; }

function post(path, body) {
  return fetch(ROOT + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Atlas-Write': '1' },
    body: JSON.stringify(body || {})
  }).then(function (r) {
    return r.json().catch(function () { return {}; }).then(function (j) {
      return { status: r.status, body: j || {} };
    });
  });
}

var NO_ANSWER = 'The gate did not answer.';

document.getElementById('f-login').addEventListener('submit', function (e) {
  e.preventDefault();
  var btn = document.getElementById('b-login');
  btn.disabled = true;
  post('/api/v2/auth/login', {
    username: document.getElementById('u').value,
    password: document.getElementById('p').value
  }).then(function (r) {
    if (!r.body.ok) { btn.disabled = false; return fail(r.body.error || 'Sign-in failed.'); }
    if (r.body.mfa_required) return show('mfa');
    if (r.body.mfa_setup_required) return startEnroll();
    window.location = NEXT;
  }).catch(function () { btn.disabled = false; fail(NO_ANSWER); });
});

document.getElementById('f-mfa').addEventListener('submit', function (e) {
  e.preventDefault();
  post('/api/v2/auth/login/mfa', { code: document.getElementById('c').value })
    .then(function (r) {
      if (!r.body.ok) return fail(r.body.error || 'Verification failed.');
      window.location = NEXT;
    }).catch(function () { fail(NO_ANSWER); });
});

function startEnroll() {
  var again = function (msg) { document.getElementById('b-login').disabled = false; fail(msg); };
  post('/api/v2/auth/mfa/setup').then(function (r) {
    if (!r.body.ok) return again(r.body.error || 'Could not begin enrollment.');
    document.getElementById('qr').innerHTML = r.body.qr_svg;
    document.getElementById('secret').textContent = r.body.secret;
    show('enroll');
  }).catch(function () { again(NO_ANSWER); });
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
    }).catch(function () { fail(NO_ANSWER); });
});

document.getElementById('b-done').addEventListener('click', function () {
  window.location = NEXT;
});
