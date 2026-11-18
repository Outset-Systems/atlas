/* TOPOLOGY, taking it out (2026-11-17): the rules of topology-export-model.js
   in plain node (file names, the file's frame, the styles and fonts written
   in, nothing reaching out of the file, the picture's size guard, the site
   report's rows), and the view's words matching plain.json.

   Run:  node --test tests/test_topology_export_model.mjs        (from Web/) */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  HEAD, MARGIN, MIN_WIDTH, NEAR_DAYS, PAPER_GROUND, PNG_MAX_AREA, PNG_MAX_SIDE,
  boundsOf, cssVarNames, wideView, dateText, daysLeft, downRows, exportBox, externalRefs, fileName, firstFamily, fontFaceCss,
  nearCerts, paperValues, parseFaces, pickFaces, pngPlan, resolveCss, slug, stripComments, svgDocument, xml,
} from '../static/js/topology-export-model.js';

const here = (path) => new URL(path, import.meta.url);
const read = (path) => readFileSync(here(path), 'utf8');
const CANVAS_CSS = read('../static/topology-canvas.css');
const VIEW_CSS = read('../static/topology.css');
const FONTS_CSS = read('../static/fonts.css');
const STATE_JS = read('../static/js/topology-state.js');
const EXPORT_JS = read('../static/js/topology-export.js');
const PLAIN = JSON.parse(read('../themes/plain.json')).text;

/** The `--tp-*` values topology.css sets on the svg, with a stand-in value. */
function tpValues() {
  const out = {};
  for (const m of stripComments(VIEW_CSS).matchAll(/(--tp-[\w-]+)\s*:\s*([^;]+);/g)) {
    out[m[1]] = m[1].endsWith('sans') ? "'Alegreya Sans', sans-serif"
      : m[1].endsWith('mono') ? "'JetBrains Mono', monospace"
        : m[1] === '--tp-dim' ? '0.22' : '#123456';
  }
  return out;
}

/* ── names and dates ──────────────────────────────────────────────────────── */

test('a date is the reader\'s own day, zero-padded', () => {
  assert.equal(dateText(new Date(2026, 10, 7, 23, 59)), '2026-11-07');
  assert.equal(dateText(new Date(2027, 0, 1, 0, 0)), '2027-01-01');
  assert.match(dateText(new Date('not a date')), /^\d{4}-\d{2}-\d{2}$/);
});

test('a file is named for the map, the view and the day', () => {
  const day = new Date(2026, 10, 17, 9);
  assert.equal(fileName('Test Realm', 'svg', day), 'test-realm-wiring-2026-11-17.svg');
  assert.equal(fileName('Test Realm', 'PNG', day), 'test-realm-wiring-2026-11-17.png');
  assert.equal(fileName('', 'svg', day), 'atlas-wiring-2026-11-17.svg');
  assert.equal(fileName('../../etc/passwd', 'svg', day), 'etc-passwd-wiring-2026-11-17.svg');
});

test('a slug is plain ASCII, one hyphen a run, at most 40, never empty', () => {
  assert.equal(slug('The Demo Atlas'), 'the-demo-atlas');
  assert.equal(slug('  Café  Ünïcode!! '), 'cafe-unicode');
  assert.equal(slug('日本'), 'atlas');
  assert.equal(slug(null), 'atlas');
  const long = slug('a'.repeat(30) + ' ' + 'b'.repeat(30));
  assert.ok(long.length <= 40 && !long.endsWith('-'), long);
  assert.match(slug('x<y>"z\'&'), /^[a-z0-9-]+$/);
});

/* ── the frame ────────────────────────────────────────────────────────────── */

test('the file\'s box holds the drawing with a margin, a head for the title, in whole units', () => {
  const b = { x: 10.5, y: 20.25, w: 900, h: 400 };
  const box = exportBox(b);
  for (const k of ['x', 'y', 'w', 'h']) assert.ok(Number.isInteger(box[k]), k);
  assert.ok(box.x <= b.x - MARGIN && box.x + box.w >= b.x + b.w + MARGIN);
  assert.ok(box.y <= b.y - MARGIN - HEAD && box.y + box.h >= b.y + b.h + MARGIN);
  assert.ok(box.w - (b.w + 2 * MARGIN) < 2 && box.h - (b.h + 2 * MARGIN + HEAD) < 2);
});

test('the bounds are read from where the cards are now, a group\'s back card included', () => {
  const pos = { a: { x: 0, y: 0 }, b: { x: 400, y: 160 }, g: { x: -300, y: 80 }, bad: { x: NaN, y: 0 }, none: null };
  assert.deepEqual(boundsOf(pos, 176, 64, (id) => id === 'g'), { x: -300, y: 0, w: 876, h: 224 });
  assert.deepEqual(boundsOf({ g: { x: 0, y: 10 } }, 176, 64, () => true), { x: 0, y: 5, w: 181, h: 69 });
  assert.equal(boundsOf({}, 176, 64), null);
  assert.equal(boundsOf(null, 176, 64), null);
});

test('the wide view puts every card inside the window, however small that makes it', () => {
  for (const b of [{ x: -300, y: 0, w: 876, h: 224 }, { x: 5e5, y: -2e5, w: 4e6, h: 9e3 }, { x: 0, y: 0, w: 0, h: 0 }]) {
    for (const [w, h] of [[800, 600], [320, 900], [0, 0]]) {
      const v = wideView(b, w, h);
      const W = w || 800;
      const H = h || 600;
      const box = { x: -v.x / v.k, y: -v.y / v.k, w: W / v.k, h: H / v.k };
      const eps = 1e-6 * Math.max(1, Math.abs(b.x) + b.w, Math.abs(b.y) + b.h);
      assert.ok(box.x <= b.x + eps && box.y <= b.y + eps, JSON.stringify([b, w, h]));
      assert.ok(box.x + box.w >= b.x + Math.max(1, b.w) - eps && box.y + box.h >= b.y + Math.max(1, b.h) - eps, JSON.stringify([b, w, h]));
    }
  }
});

test('a small drawing is widened to fit its title, centred', () => {
  const box = exportBox({ x: 0, y: 0, w: 176, h: 64 });
  assert.equal(box.w, MIN_WIDTH);
  assert.equal(box.x, Math.floor(88 - MIN_WIDTH / 2));
  assert.deepEqual(exportBox(null), { x: -MIN_WIDTH / 2, y: -MARGIN - HEAD, w: MIN_WIDTH, h: 2 * MARGIN + HEAD });
});

/* ── the styles ───────────────────────────────────────────────────────────── */

test('the canvas\'s sheet reads only values topology.css sets, and resolves to none', () => {
  const names = cssVarNames(CANVAS_CSS);
  const values = tpValues();
  assert.ok(names.length > 10);
  for (const n of names) assert.ok(n in values, `${n} is not set on svg.tp-canvas`);
  const out = resolveCss(CANVAS_CSS, values);
  assert.ok(!out.includes('var('), 'a var() is left in the file');
  assert.ok(!out.includes('/*'), 'comments are left out');
  assert.match(out, /svg\.tp-canvas \.tp-ground \{ fill: #123456; \}/);
});

test('a value it lacks takes the fallback, else initial; a nested fallback resolves', () => {
  assert.equal(resolveCss('a { b: var(--x, red); c: var(--y); d: var(--z, var(--x)); }', { '--x': 'blue' }),
    'a { b: blue; c: initial; d: blue; }');
  assert.equal(resolveCss('a { b: var(--q, var(--r, 3px)); }', {}), 'a { b: 3px; }');
});

/* ── the fonts ────────────────────────────────────────────────────────────── */

test('fonts.css is read face by face', () => {
  const faces = parseFaces(FONTS_CSS);
  assert.ok(faces.length >= 10);
  const alegreya = faces.filter((f) => f.family === 'Alegreya Sans').map((f) => [f.min, f.style, f.file]);
  assert.deepEqual(alegreya, [[400, 'normal', 'AlegreyaSans-400.woff2'], [500, 'normal', 'AlegreyaSans-500.woff2'],
    [700, 'normal', 'AlegreyaSans-700.woff2']]);
  const garamond = faces.find((f) => f.family === 'EB Garamond' && f.style === 'normal');
  assert.deepEqual([garamond.min, garamond.max], [400, 500]);
  assert.ok(faces.some((f) => f.family === 'IM Fell English' && f.style === 'italic'));
  // the page's CSSOM gives the address back absolute and double-quoted
  assert.deepEqual(parseFaces('@font-face { font-family: "Cinzel"; font-style: normal; font-weight: 700; ' +
    'src: url("http://192.0.2.1:5006/static/fonts/Cinzel-700.woff2") format("woff2"); }'),
  [{ family: 'Cinzel', style: 'normal', min: 700, max: 700, file: 'Cinzel-700.woff2' }]);
  assert.deepEqual(parseFaces('@font-face { font-family: X; src: url(x.ttf); }'), []);
});

test('only the faces the drawing uses go into the file, each once', () => {
  const faces = parseFaces(FONTS_CSS);
  const used = [
    { family: '"Alegreya Sans", sans-serif', weight: '700', style: 'normal' },
    { family: '"Alegreya Sans", sans-serif', weight: '400', style: 'normal' },
    { family: '"Alegreya Sans", sans-serif', weight: 400, style: 'normal' },
    { family: '"JetBrains Mono", monospace', weight: '400', style: 'normal' },
    { family: 'Cinzel, serif', weight: '700', style: 'normal' },
    { family: 'sans-serif', weight: '400', style: 'normal' },
  ];
  assert.deepEqual(pickFaces(used, faces).map((f) => f.file),
    ['AlegreyaSans-400.woff2', 'AlegreyaSans-700.woff2', 'Cinzel-700.woff2', 'JetBrainsMono-400.woff2']);
  // a weight between two faces takes the nearest; one inside a range takes the range's file
  assert.deepEqual(pickFaces([{ family: 'JetBrains Mono', weight: 500 }], faces).map((f) => f.file), ['JetBrainsMono-400.woff2']);
  assert.deepEqual(pickFaces([{ family: 'EB Garamond', weight: 450 }], faces).map((f) => f.file), ['EBGaramond-400-500.woff2']);
  // an italic with no italic face falls back to the normal one
  assert.deepEqual(pickFaces([{ family: 'Cinzel', weight: 600, style: 'italic' }], faces).map((f) => f.file), ['Cinzel-600.woff2']);
  assert.equal(firstFamily(" 'IM Fell English' , serif"), 'IM Fell English');
});

test('a face is written in as a data: address', () => {
  const css = fontFaceCss({ family: 'Alegreya Sans', style: 'normal', min: 400, max: 400 }, 'AAEC/+=\n');
  assert.equal(css, "@font-face { font-family: 'Alegreya Sans'; font-style: normal; font-weight: 400; " +
    "src: url(data:font/woff2;base64,AAEC/+=) format('woff2'); }");
  assert.match(fontFaceCss({ family: 'EB Garamond', style: 'normal', min: 400, max: 500 }, 'x'), /font-weight: 400 500;/);
});

/* ── the file ─────────────────────────────────────────────────────────────── */

const SYMBOL = '<symbol id="tp-e-network" viewBox="0 0 24 24"><rect class="tp-glyph" x="2.5" y="8" width="19" height="8" rx="1.5"/></symbol>';
const CARD = '<g class="tp-cards"><g class="tp-card tp-place tp-st-up" transform="translate(0 0)"><title>Alpha &amp; co</title>' +
  '<rect class="tp-box" width="176" height="64" rx="4"/>' +
  '<use href="#tp-e-network" xlink:href="#tp-e-network" x="14" y="22" width="20" height="20"/>' +
  '<text class="tp-name" x="46" y="23">ALPHA</text></g></g>';

function sampleFile(extra = {}) {
  const values = tpValues();
  return svgDocument({
    box: exportBox({ x: 0, y: 0, w: 176, h: 64 }), cls: 'tp-canvas tp-no-ports evil"class', values,
    css: resolveCss(CANVAS_CSS, values),
    fonts: fontFaceCss({ family: 'Alegreya Sans', style: 'normal', min: 400, max: 400 }, 'AAAA'),
    defs: SYMBOL, body: CARD, title: 'Test <Realm>: topology', date: 'Taken out 2026-11-17',
    ground: '#16120D', ink: '#C9BFA8', dim: '#8A8069', gilt: '#C9A554',
    display: "'Cinzel', serif", mono: "'JetBrains Mono', monospace", ...extra,
  });
}

test('the file is one svg with its namespace, viewBox, size, title, date, styles and ground', () => {
  const svg = sampleFile();
  assert.ok(svg.startsWith('<?xml version="1.0" encoding="UTF-8"?>\n<svg xmlns="http://www.w3.org/2000/svg"'));
  assert.equal(svg.match(/<svg\b/g).length, 1);
  const box = exportBox({ x: 0, y: 0, w: 176, h: 64 });
  assert.ok(svg.includes(`viewBox="${box.x} ${box.y} ${box.w} ${box.h}" width="${box.w}" height="${box.h}"`));
  assert.match(svg, /class="tp-canvas tp-no-ports"/, 'the labels turned off travel, nothing else does');
  assert.ok(svg.includes('<title>Test &lt;Realm&gt;: topology</title>'));
  assert.ok(svg.includes('>Taken out 2026-11-17</text>'));
  assert.ok(svg.includes(`<rect class="tp-ground" x="${box.x}" y="${box.y}" width="${box.w}" height="${box.h}" fill="#16120D"/>`));
  assert.match(svg, /style="--tp-ground: #123456; [^"]*--tp-sans: &#39;Alegreya Sans&#39;, sans-serif/);
  assert.match(svg, /<style><!\[CDATA\[\n@font-face/);
  assert.ok(svg.includes(SYMBOL) && svg.includes(CARD));
  assert.ok(!svg.includes('var('), 'every value is written in');
});

test('nothing in the file reaches outside it', () => {
  assert.deepEqual(externalRefs(sampleFile()), []);
});

test('a reference out of the file is caught, however it is written', () => {
  const bad = [
    '<use href="https://example.org/x.svg#a"/>', "<use xlink:href='other.svg#a'/>", '<image src="/static/icons/a.svg"/>',
    '<rect fill="url(#tp-dots)"/>', '<style>a { background: url(https://example.org/a.png) }</style>',
    "<style><![CDATA[a { src: url('fonts/a.woff2') }]]></style>", '<style>@import "x.css";</style>',
    '<a href="javascript:alert(1)">', '<rect style="fill: url(other.svg#p)"/>',
    '<g data-x="a > b"><use href="far.svg#a"/></g>',
  ];
  for (const b of bad) assert.equal(externalRefs(b).length, 1, b);
  assert.deepEqual(externalRefs('<use href="#a"/><style>a { src: url(data:font/woff2;base64,AA) } b { c: url( "data:image/png;base64,AA") }</style>'), []);
  // a name's or a note's own words are not markup: they point nowhere
  assert.deepEqual(externalRefs("<title>Printer (see url(http://wiki.example/printer))</title><text>NAS src='old' href=\"x\" @import y;</text>"), []);
});

test('xml escapes all five', () => {
  assert.equal(xml(`<a href="x">'&'</a>`), '&lt;a href=&quot;x&quot;&gt;&#39;&amp;&#39;&lt;/a&gt;');
});

/* ── the picture ──────────────────────────────────────────────────────────── */

test('a picture is twice the drawing\'s size when that fits', () => {
  assert.deepEqual(pngPlan(1200, 800), { scale: 2, width: 2400, height: 1600, reduced: false });
  assert.deepEqual(pngPlan(0, -5), { scale: 2, width: 2, height: 2, reduced: false });
});

test('a picture too large for a canvas is scaled to fit and says so', () => {
  for (const [w, h] of [[20000, 300], [4000, 4000], [60000, 60000], [3000, 9000]]) {
    const p = pngPlan(w, h);
    assert.equal(p.reduced, true, `${w}x${h}`);
    assert.ok(p.width <= PNG_MAX_SIDE && p.height <= PNG_MAX_SIDE, `${w}x${h} side`);
    assert.ok(p.width * p.height <= PNG_MAX_AREA, `${w}x${h} area`);
    assert.ok(p.scale < 2 && p.scale > 0);
  }
  const custom = pngPlan(1000, 1000, { maxSide: 1500, maxArea: 1e9 });
  assert.equal(custom.width, 1500);
  assert.equal(custom.reduced, true);
});

/* ── the site report ──────────────────────────────────────────────────────── */

const NOW = Date.parse('2026-11-17T15:00:00Z');

test('days left are counted as SEALS counts them', () => {
  assert.equal(daysLeft('2026-11-17', NOW), -1);   // midnight UTC that day, 15 hours gone: rounds to -1
  assert.equal(daysLeft('2026-11-18', NOW), 0);
  assert.equal(daysLeft('2026-12-01', NOW), 13);
  assert.equal(daysLeft('2026-11-10', NOW), -8);
  assert.equal(daysLeft('', NOW), null);
  assert.equal(daysLeft('soon', NOW), null);
  assert.equal(daysLeft(20261201, NOW), null);
});

test('near is lapsed or 14 days or fewer, soonest first; no date is not near', () => {
  const certs = [
    { name: 'later.example', expires: '2026-12-31' },
    { name: 'edge.example', kind: 'tls', host: 'Alpha', expires: '2026-12-02', renews: 'step' },   // 14 days
    { name: 'past.example', expires: '2026-12-03' },                                                // 15 days
    { name: 'gone.example', expires: '2026-11-01' },
    { name: 'undated.example' },
    'not a cert',
  ];
  assert.equal(daysLeft('2026-12-02', NOW), NEAR_DAYS);
  const near = nearCerts(certs, NOW);
  assert.deepEqual(near.map((c) => [c.name, c.days]), [['gone.example', -17], ['edge.example', 14]]);
  assert.deepEqual(near[1], { name: 'edge.example', host: 'Alpha', kind: 'tls', issuer: '', renews: 'step', expires: '2026-12-02', days: 14 });
});

test('down now: places by name with what they are behind, then services', () => {
  const data = {
    nodes: [
      { id: 'b', name: 'Beta', links: [{ label: 'UI', url: 'http://192.0.2.6' }, { label: 'Mon', kuma: 'k-1' }] },
      { id: 'a', name: 'alpha', links: [{ label: 'Files' }] },
      { id: 'c', name: 'Gamma' },
      'stray',
    ],
  };
  const feed = {
    nodes: { a: { state: 'down' }, b: { state: 'down', cause: 'a' }, c: { state: 'down', cause: 'hidden' },
      gone: { state: 'down' } },
    services: { 'b/UI': { state: 'down' }, 'k-1': { state: 'healthy' }, 'a/Files': { state: 'down' } },
    confirmed_by: { a: 'kuma' },
  };
  assert.deepEqual(downRows(data, feed), [
    { kind: 'place', id: 'a', name: 'alpha', cause: '', by: 'kuma' },
    { kind: 'place', id: 'b', name: 'Beta', cause: 'alpha', by: '' },
    { kind: 'place', id: 'c', name: 'Gamma', cause: '', by: '' },
    { kind: 'service', id: 'a/Files', name: 'Files', on: 'alpha' },
    { kind: 'service', id: 'b/UI', name: 'UI', on: 'Beta' },
  ]);
  assert.deepEqual(downRows(data, null), []);
  assert.deepEqual(downRows(null, feed), []);
});

test('paper takes the light scheme\'s tokens and a white ground', () => {
  const mapping = { '--tp-ground': 'var(--surface)', '--tp-ink': 'var(--text)', '--tp-emblem': 'var(--parchment)',
    '--tp-sans': "'Alegreya Sans', sans-serif" };
  const light = { '--surface': '#c5cad2', '--text': '#0f172a' };
  const live = { '--tp-ground': '#16120D', '--tp-ink': '#C9BFA8', '--tp-emblem': '#EFE7D3', '--tp-sans': '"Alegreya Sans", sans-serif' };
  assert.deepEqual(paperValues(mapping, light, live), {
    '--tp-ground': PAPER_GROUND, '--tp-ink': '#0f172a', '--tp-emblem': '#EFE7D3', '--tp-sans': '"Alegreya Sans", sans-serif',
  });
  assert.equal(live['--tp-ink'], '#C9BFA8', 'what it is given is not changed');
});

/* ── the words ────────────────────────────────────────────────────────────── */

/** TP_TEXT as topology-state.js writes it (read as text: that file imports the page). */
function tpText() {
  const block = STATE_JS.match(/export const TP_TEXT = \{([\s\S]*?)\n\};/);
  assert.ok(block, 'TP_TEXT is in topology-state.js');
  const out = {};
  for (const m of block[1].matchAll(/^\s*([a-z_]+):\s*'((?:[^'\\]|\\.)*)',?\s*$/gm)) out[m[1]] = m[2].replace(/\\(.)/g, '$1');
  return out;
}

test("TOPOLOGY's words: every one has its plain twin in plain.json", () => {
  const words = tpText();
  assert.ok(Object.keys(words).length > 40);
  for (const [k, v] of Object.entries(words)) assert.equal(PLAIN[k], v, `plain.json text.${k}`);
});

test('every word the export uses is a TP_TEXT word, in sentence case with no em dash', () => {
  const words = tpText();
  const used = [...new Set([...EXPORT_JS.matchAll(/\bt\('(tp_[a-z_]+)'/g)].map((m) => m[1]))];
  assert.ok(used.length > 20, 'the export says things');
  for (const k of used) assert.ok(k in words, `${k} is not in TP_TEXT`);
  for (const [k, v] of Object.entries(words)) {
    if (!k.startsWith('tp_x_')) continue;
    assert.ok(!v.includes(String.fromCharCode(0x2014)), `${k} has an em dash`);
    assert.ok(!/^[a-z]/.test(v) || v.startsWith('{'), `${k} starts in lower case`);
  }
});
