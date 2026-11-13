// Every front-end module must at least parse. The model tests import only the
// pure modules, so a syntax error in a module that touches the DOM would
// otherwise reach a browser before anything noticed (one did, 2026-11-12).
// Run: node --test Web/tests/*.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', 'static', 'js');

function modules(dir) {
  const out = [];
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) { if (name !== 'vendor') out.push(...modules(full)); }
    else if (name.endsWith('.js') && name !== 'login.js') out.push(full);   // login.js is a classic script
  }
  return out;
}

test('every module parses', () => {
  const bad = [];
  for (const file of modules(ROOT)) {
    const r = spawnSync(process.execPath, ['--input-type=module', '--check'],
      { input: readFileSync(file), encoding: 'utf8' });
    if (r.status !== 0) bad.push(`${file}: ${(r.stderr || '').split('\n').slice(0, 4).join(' ')}`);
  }
  assert.deepEqual(bad, []);
});
