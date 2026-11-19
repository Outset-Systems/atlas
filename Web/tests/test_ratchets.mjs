// Two ratchets on the front end (2026-11-19, the refactor's stage 6). Each
// counts something the page should have less of and fails if the count
// GROWS; a change that lowers one lowers its number here in the same commit.
//
//   A        the properties modules hang on the shared `A` object, counted as
//            distinct `A.name =` assignments. New work imports what it needs
//            instead; the data on `A` (the map, the view, the live feed)
//            stays there for now.
//   fetch    raw `fetch(` calls outside config.js, whose getJSON and sendJSON
//            check the answer and say a refusal (the 11-12 audit's Scenes 4,
//            6, 9 and 12 were raw calls that did not).
//
// Counted from the source, not at run time: config.js needs a document.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const JS = join(dirname(fileURLToPath(import.meta.url)), '..', 'static', 'js');

const A_PROPERTIES = 159;
const RAW_FETCH = 32;

function sources(dir) {
  const out = [];
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) { if (name !== 'vendor') out.push(...sources(full)); }
    else if (name.endsWith('.js')) out.push(full);
  }
  return out;
}

/** a file's lines with whole-line comments dropped (a comment may name a call) */
function code(file) {
  return readFileSync(file, 'utf8').split('\n')
    .filter((line) => !/^\s*(\/\/|\/\*|\*)/.test(line)).join('\n');
}

test('no new properties on A', () => {
  const names = new Set();
  for (const file of sources(JS)) {
    for (const m of code(file).matchAll(/\bA\.([A-Za-z_$][\w$]*)\s*=(?!=)/g)) names.add(m[1]);
  }
  assert.ok(names.size <= A_PROPERTIES,
    `A has ${names.size} properties, more than ${A_PROPERTIES}: import the new one instead`);
  if (names.size < A_PROPERTIES) console.log(`A is down to ${names.size}: lower A_PROPERTIES to it`);
});

test('no new raw fetch calls outside config.js', () => {
  const where = [];
  for (const file of sources(JS)) {
    if (relative(JS, file) === 'config.js') continue;
    const n = (code(file).match(/\bfetch\(/g) || []).length;
    if (n) where.push([relative(JS, file), n]);
  }
  const total = where.reduce((s, [, n]) => s + n, 0);
  assert.ok(total <= RAW_FETCH,
    `${total} raw fetch calls, more than ${RAW_FETCH}: use getJSON or sendJSON (config.js). ` +
    where.map(([f, n]) => `${f} ${n}`).join(', '));
  if (total < RAW_FETCH) console.log(`raw fetch is down to ${total}: lower RAW_FETCH to it`);
});
