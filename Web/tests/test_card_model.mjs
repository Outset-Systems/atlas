/* The working out behind a place's card. `node tests/test_card_model.mjs` */

import assert from 'node:assert/strict';
import { sparkPoints, scrollTail, obsidianHref, serviceMeta } from '../static/js/card-model.js';

let passed = 0;
function test(name, fn) {
  try { fn(); passed++; console.log(`  ok  ${name}`); }
  catch (e) { console.log(`  FAIL ${name}\n       ${e.message}`); process.exitCode = 1; }
}

/* ── the sparkline ────────────────────────────────────────────────────── */

test('a week of samples spans the box, oldest at the left, 100% at the top', () => {
  assert.equal(sparkPoints([[0, 0], [50, 50], [100, 100]]), '0.0,40.0 80.0,20.0 160.0,0.0');
  assert.equal(sparkPoints([[1000, 25], [2000, 75]]), '0.0,30.0 160.0,10.0');
});

test('values clamp to 0–100 and do not rescale the week', () => {
  assert.equal(sparkPoints([[0, -5], [10, 150]]), '0.0,40.0 160.0,0.0');
});

test('a sample with no number is left out, and the span is of what is left', () => {
  const series = [[0, 10], [5, NaN], [10, null], undefined, [20, 'x'], [40, 50]];
  assert.equal(sparkPoints(series), '0.0,36.0 160.0,20.0');
});

test('fewer than two samples is no line at all', () => {
  assert.equal(sparkPoints([[0, 50]]), '');
  assert.equal(sparkPoints([[0, NaN], [1, 50]]), '');
  assert.equal(sparkPoints([]), '');
  assert.equal(sparkPoints(undefined), '');
});

test('samples that share one instant do not divide by nothing', () => {
  assert.equal(sparkPoints([[7, 20], [7, 80]]), '0.0,32.0 0.0,8.0');
});

test('the box can be another size', () => {
  assert.equal(sparkPoints([[0, 0], [1, 100]], 10, 20), '0.0,20.0 10.0,0.0');
});

/* ── the scroll ───────────────────────────────────────────────────────── */

const WIN = 'V:\\Vault\\Hosts\\Gate.md';

test('the tail is the path after the root, case ignored, nothing else trimmed', () => {
  assert.equal(scrollTail(WIN, 'V:\\Vault\\'), 'Hosts\\Gate.md');
  assert.equal(scrollTail(WIN, 'v:\\vault'), '\\Hosts\\Gate.md');        // no trailing separator on the root
  assert.equal(scrollTail('/srv/vault/hosts/gate.md', '/srv/vault'), '/hosts/gate.md');
  assert.equal(scrollTail(WIN, WIN), '');
});

test('no root, or a scroll outside it, has no tail', () => {
  assert.equal(scrollTail(WIN, ''), null);
  assert.equal(scrollTail(WIN, 'W:\\Other\\'), null);
  assert.equal(scrollTail('/srv/vault/a.md', '/srv/vault/a.md/deeper'), null);
});

test('a scroll under the root opens by vault and note', () => {
  assert.equal(obsidianHref(WIN, 'V:\\Vault\\'), 'obsidian://open?vault=Vault&file=Hosts%2FGate');
  assert.equal(obsidianHref(WIN, 'v:\\vault'), 'obsidian://open?vault=vault&file=Hosts%2FGate');
  assert.equal(obsidianHref('/srv/My Vault/hosts/gate.MD', '/srv/My Vault/'),
    'obsidian://open?vault=My%20Vault&file=hosts%2Fgate');
});

test('with no root, or outside it, the scroll opens by its whole path', () => {
  const byPath = `obsidian://open?path=${encodeURIComponent(WIN)}`;
  assert.equal(obsidianHref(WIN, ''), byPath);
  assert.equal(obsidianHref(WIN, 'W:\\Other\\'), byPath);
  assert.equal(byPath, 'obsidian://open?path=V%3A%5CVault%5CHosts%5CGate.md');
});

test('a root with no folder name, or a scroll that is the root itself, opens by path', () => {
  assert.equal(obsidianHref('/a.md', '/'), 'obsidian://open?path=%2Fa.md');
  assert.equal(obsidianHref('V:\\Vault\\', 'V:\\Vault\\'), 'obsidian://open?path=V%3A%5CVault%5C');
});

/* ── a service row's second word ──────────────────────────────────────── */

const GATE = { id: 'GATE', ip: '10.0.0.5' };

test('a service on the place itself shows only its port', () => {
  assert.equal(serviceMeta('10.0.0.5:8096/web/index.html', GATE), ':8096');
  assert.equal(serviceMeta('gate.home.example:3000', GATE), ':3000');     // its own name, any case
  assert.equal(serviceMeta('gate:9000/', GATE), ':9000');
});

test('on the place itself with no port, there is nothing to add', () => {
  assert.equal(serviceMeta('10.0.0.5/admin', GATE), '');
  assert.equal(serviceMeta('gate.home.example', GATE), '');
});

test('a service that answers somewhere else names where, without the path', () => {
  assert.equal(serviceMeta('media.example.org/library?x=1', GATE), 'media.example.org');
  assert.equal(serviceMeta('10.0.0.6:8096/web', GATE), '10.0.0.6:8096');
  assert.equal(serviceMeta('gateway:80', GATE), 'gateway:80');       // a longer name is another host
});

test('an empty address on a place with no address of its own', () => {
  assert.equal(serviceMeta('', { id: 'x', ip: '' }), '');
  assert.equal(serviceMeta('', { id: 'x' }), '');
});

console.log(`\n${passed} passed`);
