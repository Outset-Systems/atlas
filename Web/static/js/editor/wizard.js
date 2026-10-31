/* THE FIRST SURVEY — charting a lab from nothing.

   The Atlas has always assumed a dataset already existed, because the only
   one that ever mattered was hand-written over a week. For anyone else the
   first screen is an empty map with no way in, and "edit this 1200-line JSON
   file" is not an onboarding.

   Three steps, each of which can be skipped: name the atlas, add a realm (a
   VLAN or segment, as the Desk calls it), then populate it — by hand, from a
   device list, or from a survey you run. Everything after that is the Desk. */

import { A, $, esc } from '../config.js';
import Editor from './store.js';
import { buildForm, makeEl as el } from './form.js';
import { openDesk, reviewCsv, LEASE_HELP } from './panel.js';

let root, bodyEl, stepEl;
let step = 0;

const STEPS = ['THE ATLAS', 'A FIRST REALM', 'ITS PLACES'];

function drawSteps() {
  stepEl.innerHTML = STEPS.map((label, i) =>
    `<span class="wiz-step${i === step ? ' on' : ''}${i < step ? ' done' : ''}">` +
    `<i>${i + 1}</i>${esc(label)}</span>`).join('');
}

function panel(title, blurb) {
  bodyEl.innerHTML = '';
  bodyEl.append(el('h2', 'wiz-h', esc(title)));
  if (blurb) bodyEl.append(el('p', 'wiz-blurb', blurb));
  return bodyEl;
}

function bar(...buttons) {
  const row = el('div', 'wiz-bar');
  row.append(...buttons);
  bodyEl.append(row);
  return row;
}

function button(label, kind, onClick) {
  const btn = el('button', `dsk-btn${kind ? ' dsk-btn-' + kind : ''}`, esc(label));
  btn.addEventListener('click', onClick);
  return btn;
}

function fail(err) {
  const box = el('div', 'dsk-notice dsk-notice-bad', esc(err.message || String(err)));
  for (const problem of err.problems || []) {
    if (problem !== err.message) box.append(el('div', 'dsk-dim', esc(problem)));
  }
  bodyEl.prepend(box);
}

/* Each step asks only what a newcomer needs; the rest of a section's fields
   (the backdrop, the host's memory and cores, label positions…) wait in the
   Desk, where they are one click away once there is a map to tune. */
function laterNote(what) {
  bodyEl.append(el('p', 'wiz-blurb', `${what} — all in the map editor (E), whenever you want them.`));
}

/* ── 1. the atlas ─────────────────────────────────────────────────────── */
function stepRealm() {
  step = 0;
  drawSteps();
  panel('Name your atlas',
    'This is the title on the map and in the Hub. It can change later, like everything ' +
    'else here.');
  const form = buildForm('meta', Editor.data?.meta || {}, { only: ['title'] });
  bodyEl.append(form.el);
  laterNote('The backdrop, the survey date and the host\'s memory and cores');
  bar(
    button('Skip', '', stepZone),
    button('Next ›', 'go', async () => {
      try {
        await Editor.upsert('meta', null, form.read());
        stepZone();
      } catch (err) { fail(err); }
    }));
}

/* ── 2. a realm ───────────────────────────────────────────────────────── */
function stepZone() {
  step = 1;
  drawSteps();
  const existing = Editor.entries('zones');
  panel('Add a realm',
    existing.length
      ? `You have ${existing.length} already. Add another, or move on.`
      : 'A realm is a VLAN or a network segment — every place belongs to one. ' +
        'Give it a subnet and ADDRESSES can chart it; give it a colour ' +
        'and everything on it is recognisable at a glance.');

  const seed = {
    id: existing.length ? '' : 'main',
    name: existing.length ? '' : 'Main',
    vlan: existing.length ? '' : 1,
    subnet: '', hue: '#C9A554',
  };
  // required by the catalogue but nothing a newcomer has an opinion on yet;
  // an insert is written whole, so they go in with the form's answers
  const unasked = { lore: 'Newly surveyed ground.', label_x: 50, label_y: 50 };
  const form = buildForm('zones', seed, { only: ['name', 'id', 'vlan', 'subnet', 'hue'] });
  bodyEl.append(form.el);
  laterNote('Its card line, route colour and label position');
  bar(
    button('‹ Back', '', stepRealm),
    button(existing.length ? 'Skip' : 'Skip for now', '', stepPlaces),
    button('Add it ›', 'go', async () => {
      try {
        await Editor.insert('zones', { ...unasked, ...form.read() });
        stepPlaces();
      } catch (err) { fail(err); }
    }));
}

/* ── 3. its places ────────────────────────────────────────────────────── */
function stepPlaces() {
  step = 2;
  drawSteps();
  panel('Chart its places',
    'Four ways in. None of them is permanent — anything charted can be renamed, ' +
    'moved or removed in the map editor afterwards.');

  const zones = Editor.entries('zones');
  if (!zones.length) {
    bodyEl.append(el('div', 'dsk-notice dsk-notice-warn',
      'There are no segments yet, so places have nowhere to live. Go back and add one.'));
    bar(button('‹ Back', '', stepZone));
    return;
  }

  const choices = el('div', 'wiz-choices');

  choices.append(choice('✎', 'One at a time',
    'Open the map editor and add places by hand. Best when you have a handful and know them well.',
    () => { close(); openDesk('nodes'); }));

  choices.append(choice('☰', 'From a device list',
    'Paste a CSV — <code>name,ip,kind,zone,role,url</code>. Validated whole before ' +
    'anything is written, with the line number of every problem.',
    () => paste('csv')));

  choices.append(choice('◈', 'From a survey',
    `Run <code>${esc(scanCommand())}</code> on a machine in that network, where you ` +
    'have the right to, and paste what it prints. The Atlas never probes the network ' +
    'itself — it reads what you hand it.',
    () => paste('nmap')));

  choices.append(choice('⇄', 'From your router',
    'Paste its DHCP lease file: every device that asked it for an address, with the name ' +
    'it gave itself. No scan at all, and usually the best names.',
    () => paste('leases')));

  bodyEl.append(choices);
  bar(button('‹ Back', '', stepZone), button('I will do this later', '', close));
}

function choice(glyph, title, blurb, onClick) {
  const card = el('button', 'wiz-choice',
    `<span class="wiz-choice-g">${glyph}</span>` +
    `<span class="wiz-choice-t">${esc(title)}</span>` +
    `<span class="wiz-choice-b">${blurb}</span>`);
  card.addEventListener('click', onClick);
  return card;
}

/** The survey command for the realms charted so far: a ping sweep of every
    subnet they name, printed as the XML the Atlas reads. A realm with no
    addressing (`—`) or a typo adds nothing; with none left, a placeholder. */
function scanCommand() {
  const nets = Editor.entries('zones')
    .map((z) => String(z.subnet || '').trim())
    .filter((s) => /^[0-9a-f.:]+\/\d{1,3}$/i.test(s));
  return `nmap -sn -oX - ${nets.length ? [...new Set(nets)].join(' ') : '<your subnet, e.g. 192.168.1.0/24>'}`;
}

/** A command the reader copies: shown whole, selectable, with a copy button
    (the clipboard API only exists on https and localhost, so it falls back
    to selecting the text for Ctrl+C). */
function commandRow(cmd) {
  const row = el('div', 'wiz-cmd');
  const box = el('input', 'dsk-input dsk-mono');
  box.type = 'text';
  box.readOnly = true;
  box.value = cmd;
  box.addEventListener('focus', () => box.select());
  const copy = button('Copy', '', async () => {
    try {
      await navigator.clipboard.writeText(cmd);
      copy.textContent = 'Copied';
    } catch {
      box.focus();
      box.select();
      copy.textContent = 'Press Ctrl+C';
    }
  });
  row.append(box, copy);
  return row;
}

function paste(kind) {
  const csv = kind === 'csv';
  const leases = kind === 'leases';
  panel(csv ? 'Paste your device list' : leases ? 'Paste your router\'s leases' : 'Paste your survey',
    csv
      ? 'The first line is the header. Only <code>name</code> is required.'
      : leases
        ? LEASE_HELP.replace(/^Or your/, 'Your')
        : 'Run this on a machine inside the network, then paste everything it prints. ' +
          'A ping sweep is enough; run it with <code>sudo</code> and nmap also names each ' +
          'device\'s maker, which helps tell them apart.');
  if (kind === 'nmap') bodyEl.append(commandRow(scanCommand()));
  const area = el('textarea', 'dsk-input dsk-area dsk-mono');
  area.rows = 12;
  area.placeholder = csv
    ? 'name,ip,kind,zone,role,url\nGATEWAY,10.0.0.1,network,main,the way in,http://10.0.0.1\n'
    : leases
      ? 'lease 10.0.0.20 { … }   or   1792400000 aa:bb:cc:dd:ee:ff 10.0.0.20 nas *'
      : '<?xml version="1.0"?><nmaprun …>  (paste the whole output here)';
  bodyEl.append(area);
  bar(
    button('‹ Back', '', stepPlaces),
    button('Read it ›', 'go', async () => {
      if (!area.value.trim()) return;
      try {
        if (csv) {
          close();
          await reviewCsv(area.value);
        } else {
          const res = leases ? await Editor.leases(area.value) : await Editor.scan(area.value);
          close();
          A.showToast?.(leases
            ? `${res.seen} devices from ${res.format} leases — review them in THE SURVEY.`
            : `${res.seen} answered — review them in THE SURVEY.`);
          await openDesk('survey');
        }
      } catch (err) { fail(err); }
    }));
}

/* ── shell ────────────────────────────────────────────────────────────── */

export async function openWizard() {
  if (!root) return;
  if (!Editor.loaded) {
    try { await Editor.load(); } catch { return; }
  }
  if (!Editor.writable()) {
    A.showToast?.('This Atlas is read-only — there is nothing to set up here.');
    return;
  }
  root.classList.add('open');
  root.setAttribute('aria-hidden', 'false');
  stepRealm();
}

export function close() {
  if (!root) return;
  root.classList.remove('open');
  root.setAttribute('aria-hidden', 'true');
}

export function buildWizard() {
  root = $('wizard');
  if (!root) return;
  bodyEl = $('wiz-body');
  stepEl = $('wiz-steps');
  $('wiz-close')?.addEventListener('click', close);
}
