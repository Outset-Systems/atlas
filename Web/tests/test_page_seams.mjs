// The page's one-line defects from the 11-12 audit, pinned in the source
// (2026-11-19, the refactor's stage 10). Each is a line in a DOM module that
// a node test cannot import; what these check is that the fix is still
// there, in the order that makes it a fix. Where a decision could live in a
// pure model it does, and is tested there instead.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const JS = join(dirname(fileURLToPath(import.meta.url)), '..', 'static', 'js');
const src = (file) => readFileSync(join(JS, file), 'utf8');
const before = (text, a, b, why) => {
  const i = text.indexOf(a), j = text.indexOf(b, i);
  assert.ok(i !== -1, `missing: ${a}`);
  assert.ok(j !== -1 && i < j, why);
};

test('Map 2: every card stamps the vitals box before asking for a pulse', () => {
  before(src('card.js'), 'vitals.dataset.node = n.id;', 'if (n.spark) {',
         'a card with no pulse must still move the stamp');
});

test('Map 5: no camera gesture zooms past a region\'s floor', () => {
  const camera = src('camera.js');
  const wheel = camera.slice(camera.indexOf("addEventListener('wheel'"));
  assert.ok(!/\bzoomAt\(e\.client/.test(wheel), 'the wheel and the pinch go through zoomVia');
  assert.ok(!/'dblclick', \(e\) => zoomAt\(/.test(camera), 'a double click goes through zoomVia');
  assert.match(camera, /const zoomVia = \(sx, sy, factor\) => \(A\.zoomAt \|\| zoomAt\)\(sx, sy, factor\);/);
});

test('Map 7: a rebuild puts away a lit service web', () => {
  const world = src('world.js');
  const build = world.slice(world.indexOf('A.buildWorld = function buildWorld()'));
  assert.match(build.slice(0, 600), /A\.clearHighlight\(\)/);
});

test('Map 10: the pan floor is set through panFloor, which refuses a map with no width', () => {
  assert.match(src('atlas.js'), /A\.cam\.min = panFloor\(innerWidth, w, A\.cam\.min\);/);
});

test('Map 12: a press clears a drag mark before anything can return early', () => {
  before(src('regions.js'), 'delete mk.dataset.dragged;', "if (!A.editMode || !level) return;",
         'the mark must go even when edit mode is off');
  before(src('reliquary.js'), 'delete el.dataset.dragged;', 'if (!editing) return;',
         'the rack clears it the same way');
});

test('Scenes 2: removing a sub-row keeps what was typed in the others', () => {
  const form = src('editor/form.js');
  const drop = form.slice(form.indexOf("drop.addEventListener('click'"));
  before(drop, 'rows = rows.map((r) => ({ entry: collectSub(field, r) }));', 'rows.splice(i, 1);',
         'snapshot what is typed, then remove');
});

test('Scenes 10: TRIPWIRES offers a write only where the server takes one', () => {
  const stones = src('stones.js');
  assert.match(stones, /const mayWrite = \(\) => canAdminWrite\(\) && document\.body\.dataset\.editable === '1';/);
  const uses = stones.replace(/const mayWrite = [^\n]+/, '');
  assert.ok(!/canAdminWrite\(\)/.test(uses), 'no write is gated on canAdminWrite alone');
});

test('Scenes 15: a frame is compared with its embed resolved, both places', () => {
  const chron = src('chronicle.js');
  assert.match(chron, /if \(f\.src !== resolved\(f\.dataset\.src\)\)/);
  assert.match(chron, /if \(f\.src === resolved\(src\)\) return;/);
});

test('Scenes 5: a token just issued is forgotten when Settings closes, or when it is revoked', () => {
  const con = src('connections.js');
  assert.match(con, /addEventListener\('atlas:settings', \(e\) => \{ if \(!e\.detail\?\.open\) forgetIssued\(\); \}\);/);
  assert.match(con, /if \(issuedId && b\.dataset\.revoke === issuedId\) forgetIssued\(\);/);
  const forget = con.slice(con.indexOf('function forgetIssued()'), con.indexOf('function forgetIssued()') + 260);
  assert.match(forget, /box\.innerHTML = ''/, 'the hidden box does not keep the plaintext');
});

test('Scenes 1: the read-only notice is put back after every section draws', () => {
  const panel = src('editor/panel.js');
  const show = panel.slice(panel.indexOf('async function show(key)'), panel.indexOf('function readOnlyNote()'));
  assert.match(show, /if \(still\(\)\) readOnlyNote\(\);/);
  const open = panel.slice(panel.indexOf('export async function openDesk'));
  assert.ok(!/bodyEl\.prepend\(notice\(/.test(open.slice(0, 1500)), 'not once, before a draw that clears it');
});

test('Scenes 11: a section that waited gives up when another was chosen', () => {
  const panel = src('editor/panel.js');
  assert.match(panel, /const mine = \+\+showing;/);
  assert.match(panel, /await drawChanges\(still\)/);
  assert.match(panel, /await drawSurvey\(still\)/);
  const survey = src('editor/survey.js');
  before(survey, 'await Editor.discovery();', 'if (!still()) return;', 'the survey checks after its first wait');
  const changes = src('editor/changes.js');
  before(changes, 'await Editor.revisions();', 'if (!still()) return;', 'the change log checks after its wait');
});

test('Map 13: a map art load has a load and an error listener, put away together', () => {
  const table = src('table.js');
  assert.match(table, /pending\?\.abort\(\);/);
  assert.match(table, /mapBase\.addEventListener\('error', \(\) => \{\n\s+done\.abort\(\);/);
  assert.ok(!/\{ once: true \}/.test(table.slice(table.indexOf('function pick(m)'))), 'no lone once-listener left waiting');
});

test('Map 11: a place asked for mid-transition waits it out, and is not focused unrevealed', () => {
  const regions = src('regions.js');
  const reveal = regions.slice(regions.indexOf('async function reveal(id)'), regions.indexOf('A.focusNode = async'));
  before(reveal, 'for (let t = 0; busy && t < 40; t++) await wait(120);', 'const drawn =',
         'wait the transition out before deciding');
  assert.match(regions, /if \(await reveal\(id\) === false\) return;\n\s+mainFocus\(id, \.\.\.rest\);/);
});
