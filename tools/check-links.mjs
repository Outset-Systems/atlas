/* Every name a module imports must be exported by the file it names.

   The front end is plain ES modules with no build step, so nothing checks an
   import until the browser loads the page: a function moved to another file, or
   an `export` dropped from one that is still imported somewhere, is a
   SyntaxError that takes the whole module graph down with it. This reads every
   non-vendor .js under the folder given and checks, for each
   `import {x, y} from './z.js'`:

     - that ./z.js exists, and
     - that it exports x and y (a default import needs `export default`).

   `import './z.js'` and `import('./z.js')` are checked for the file only.
   Only relative specifiers are followed. Comments are blanked first and an
   import must start its line, so a string or a URL that merely contains the
   word is not read as one.

   Run:  node tools/check-links.mjs Web/static/js      (exit 1 on a miss) */
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { dirname, join, normalize, relative } from 'node:path';

const DIR = process.argv[2];
if (!DIR) {
  console.error('usage: node tools/check-links.mjs <folder>');
  process.exit(2);
}

function walk(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    if (e.isDirectory()) return e.name === 'vendor' ? [] : walk(join(dir, e.name));
    return e.name.endsWith('.js') ? [join(dir, e.name)] : [];
  });
}

const uncommented = (text) => text
  .replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, ' '))
  .replace(/(^|[^:'"`\\])\/\/.*$/gm, '$1');

const sources = new Map();
const read = (path) => {
  const key = normalize(path);
  if (!sources.has(key)) sources.set(key, existsSync(key) ? uncommented(readFileSync(key, 'utf8')) : null);
  return sources.get(key);
};

/** The names inside one pair of braces: `a, b as c` → [['a', 'c'], ...]. */
const braceNames = (inner) => inner.split(',').map((part) => part.trim()).filter(Boolean)
  .map((part) => {
    const [name, alias] = part.split(/\s+as\s+/);
    return [name.trim(), (alias || name).trim()];
  });

const relativeTo = (file, spec) => join(dirname(file), spec.split('?')[0]);

/** Every name a file exports. `null` in the set's place means "cannot tell"
    (an `export *` from somewhere this does not follow). */
const exportsOf = (path, seen = new Set()) => {
  const text = read(path);
  if (text === null) return null;
  if (seen.has(normalize(path))) return new Set();
  seen.add(normalize(path));
  const out = new Set();
  for (const m of text.matchAll(/^[ \t]*export\s+(?:async\s+)?function\s*\*?\s*([\w$]+)/gm)) out.add(m[1]);
  for (const m of text.matchAll(/^[ \t]*export\s+class\s+([\w$]+)/gm)) out.add(m[1]);
  for (const m of text.matchAll(/^[ \t]*export\s+(?:const|let|var)\s+([\w$]+)/gm)) out.add(m[1]);
  for (const m of text.matchAll(/^[ \t]*export\s+(?:const|let|var)\s*\{([^}]*)\}/gm)) {
    for (const [, alias] of braceNames(m[1].replace(/:\s*/g, ' as '))) out.add(alias);
  }
  for (const m of text.matchAll(/^[ \t]*export\s*\{([^}]*)\}/gm)) {
    for (const [, alias] of braceNames(m[1])) out.add(alias);
  }
  if (/^[ \t]*export\s+default\b/m.test(text)) out.add('default');
  for (const m of text.matchAll(/^[ \t]*export\s*\*\s*from\s*['"]([^'"]+)['"]/gm)) {
    if (!m[1].startsWith('.')) return null;
    const more = exportsOf(relativeTo(path, m[1]), seen);
    if (more === null) return null;
    for (const name of more) if (name !== 'default') out.add(name);
  }
  return out;
};

const misses = [];
let checked = 0;

for (const file of walk(DIR)) {
  const text = read(file);
  const here = relative(DIR, file).replace(/\\/g, '/');
  const target = (spec) => {
    const path = relativeTo(file, spec);
    if (read(path) === null) {
      misses.push(`${here}: imports '${spec}', which does not exist`);
      return null;
    }
    return path;
  };

  // import <clause> from '<spec>'  ·  export { … } from '<spec>'
  const named = /^[ \t]*(import|export)\s+([\w$*\s,{}]+?)\s*from\s*['"]([^'"]+)['"]/gm;
  for (const m of text.matchAll(named)) {
    const [, word, clause, spec] = m;
    if (!spec.startsWith('.')) continue;
    if (word === 'export' && !clause.includes('{')) continue;      // `export * from`: file only, below
    const path = target(spec);
    if (!path) continue;
    const have = exportsOf(path);
    if (have === null) continue;
    const wanted = [];
    const braces = clause.match(/\{([^}]*)\}/);
    if (braces) for (const [name] of braceNames(braces[1])) wanted.push(name);
    const outside = clause.replace(/\{[^}]*\}/, '').split(',').map((s) => s.trim()).filter(Boolean);
    for (const part of outside) {
      if (word === 'import' && !part.startsWith('*')) wanted.push('default');
    }
    for (const name of wanted) {
      checked++;
      if (!have.has(name)) misses.push(`${here}: imports { ${name} } from '${spec}', which does not export it`);
    }
  }

  // import '<spec>'  ·  export * from '<spec>'  ·  import('<spec>')
  const bare = [
    /^[ \t]*import\s*['"]([^'"]+)['"]/gm,
    /^[ \t]*export\s*\*\s*from\s*['"]([^'"]+)['"]/gm,
    /\bimport\(\s*['"]([^'"]+)['"]\s*\)/g,
  ];
  for (const pattern of bare) {
    for (const m of text.matchAll(pattern)) {
      if (!m[1].startsWith('.')) continue;
      checked++;
      target(m[1]);
    }
  }
}

if (misses.length) {
  console.log('✗ IMPORTS THAT DO NOT RESOLVE:');
  for (const line of [...new Set(misses)]) console.log(`    ${line}`);
  process.exitCode = 1;
} else {
  console.log(`✓ every import resolves to an export (${checked} checked)`);
}
