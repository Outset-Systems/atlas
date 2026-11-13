/* Every A.buildXScene() the bootstrap calls must actually be defined somewhere,
   and every module it calls into must be imported. This is the check that would
   have caught buildRepairsScene surviving the removal of repairs.js: the call
   sat in an unguarded chain, so it threw and took buildAnnalsScene AND
   startSignals down with it. */
import { readFileSync, readdirSync } from 'node:fs';

const DIR = process.argv[2];
const files = readdirSync(DIR).filter((f) => f.endsWith('.js'));
const src = Object.fromEntries(files.map((f) => [f, readFileSync(`${DIR}/${f}`, 'utf8')]));
const all = Object.values(src).join('\n');

const boot = src['atlas.js'];
const imports = [...boot.matchAll(/import\s+'\.\/([\w/.-]+)'/g)].map((m) => m[1]);
const called = [...boot.matchAll(/A\.(build\w+|start\w+)\(\)/g)].map((m) => m[1]);

const missing = called.filter((name) => !new RegExp(`A\\.${name}\\s*=`).test(all));
const unguarded = called.filter((name) => !boot.includes(`A.${name}?.()`));

console.log('imports   :', imports.join(', '));
console.log('bootstrap :', called.join(', '));
console.log('');
if (missing.length) {
  console.log('✗ CALLED BUT NEVER DEFINED:', missing.join(', '));
  process.exitCode = 1;
} else {
  console.log('✓ every bootstrap call resolves to a definition');
}
// not a failure — the chain is deliberately unguarded so a real breakage is loud
console.log(`  (${unguarded.length}/${called.length} are unguarded calls — a missing one throws)`);

// every module defining a scene opener should be imported by the bootstrap
for (const [file, text] of Object.entries(src)) {
  if (file === 'atlas.js') continue;
  const defines = [...text.matchAll(/A\.(build\w+Scene)\s*=/g)].map((m) => m[1]);
  if (defines.length && !imports.includes(file)) {
    console.log(`✗ ${file} defines ${defines.join(', ')} but atlas.js never imports it`);
    process.exitCode = 1;
  }
}

/* The same question for the whole folder, not only the bootstrap: every plain
   `A.x(` call must have an `A.x =` somewhere. Modules reach each other through
   `A` and nothing checks the name, so a function that is moved or renamed and
   leaves a caller behind fails only when that caller runs. A guarded call
   (`A.x?.()`) says it can be absent and is not counted. Subfolders are read
   too, vendor code is not, and a name in a comment does not count as a call. */
function walk(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    if (e.isDirectory()) return e.name === 'vendor' ? [] : walk(`${dir}/${e.name}`);
    return e.name.endsWith('.js') ? [`${dir}/${e.name}`] : [];
  });
}
const uncommented = (text) => text
  .replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, ' '))
  .replace(/(^|[^:'"`\\])\/\/.*$/gm, '$1');
const tree = walk(DIR).map((path) => [path.slice(DIR.length + 1), uncommented(readFileSync(path, 'utf8'))]);
const defined = new Set();
for (const [, text] of tree) {
  for (const m of text.matchAll(/(?<![\w.$])A\.(\w+)\s*(?:\?\?|\|\|)?=(?!=)/g)) defined.add(m[1]);
}
const undefinedCalls = [];
for (const [file, text] of tree) {
  for (const m of text.matchAll(/(?<![\w.$])A\.(\w+)\(/g)) {
    if (!defined.has(m[1])) undefinedCalls.push(`${file}: A.${m[1]}()`);
  }
}
if (undefinedCalls.length) {
  console.log('✗ CALLED ON A BUT NEVER SET:');
  for (const line of [...new Set(undefinedCalls)]) console.log(`    ${line}`);
  process.exitCode = 1;
} else {
  console.log(`✓ every A.x( call in the folder has an A.x = (${defined.size} names set)`);
}
