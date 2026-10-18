/* THE FIRST SURVEY — charting a realm from nothing.

   The Atlas has always assumed a dataset already existed, because the only
   one that ever mattered was hand-written over a week. For anyone else the
   first screen is an empty map with no way in, and "edit this 1200-line JSON
   file" is not an onboarding.

   Four steps, each of which can be skipped: name the realm, add a segment,
   then populate it — by hand, from a device list, or from a survey you
   already ran. Everything after that is the Desk. */

import { A, $, esc } from '../config.js';
import Editor from './store.js';
import { buildForm, makeEl as el } from './form.js';
import { openDesk, reviewCsv } from './panel.js';

let root, bodyEl, stepEl;
let step = 0;

const STEPS = ['THE REALM', 'A FIRST SEGMENT', 'ITS PLACES'];

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

/* ── 1. the realm ─────────────────────────────────────────────────────── */
function stepRealm() {
  step = 0;
  drawSteps();
  panel('Name your realm',
    'This is the title on the map and in the Hub. Everything else can change later — ' +
    'so can this.');
  const form = buildForm('meta', Editor.data?.meta || {});
  bodyEl.append(form.el);
  bar(
    button('Skip', '', stepZone),
    button('Next ›', 'go', async () => {
      try {
        await Editor.upsert('meta', null, form.read());
        stepZone();
      } catch (err) { fail(err); }
    }));
}

/* ── 2. a segment ─────────────────────────────────────────────────────── */
function stepZone() {
  step = 1;
  drawSteps();
  const existing = Editor.entries('zones');
  panel('Add a segment',
    existing.length
      ? `You have ${existing.length} already. Add another, or move on.`
      : 'A realm is a VLAN or a network segment — every place belongs to one. ' +
        'Give it a subnet and the Ledger can chart its addresses; give it a colour ' +
        'and everything on it is recognisable at a glance.');

  const seed = {
    id: existing.length ? '' : 'main',
    name: existing.length ? '' : 'Main',
    vlan: existing.length ? '' : 1,
    subnet: '', hue: '#C9A554',
    lore: 'Newly surveyed ground.',
    label_x: 50, label_y: 50,
  };
  const form = buildForm('zones', seed);
  bodyEl.append(form.el);
  bar(
    button('‹ Back', '', stepRealm),
    button(existing.length ? 'Skip' : 'Skip for now', '', stepPlaces),
    button('Add it ›', 'go', async () => {
      try {
        await Editor.insert('zones', form.read());
        stepPlaces();
      } catch (err) { fail(err); }
    }));
}

/* ── 3. its places ────────────────────────────────────────────────────── */
function stepPlaces() {
  step = 2;
  drawSteps();
  panel('Chart its places',
    'Three ways in. None of them is permanent — anything charted can be renamed, ' +
    'moved or removed from the Desk afterwards.');

  const zones = Editor.entries('zones');
  if (!zones.length) {
    bodyEl.append(el('div', 'dsk-notice dsk-notice-warn',
      'There are no segments yet, so places have nowhere to live. Go back and add one.'));
    bar(button('‹ Back', '', stepZone));
    return;
  }

  const choices = el('div', 'wiz-choices');

  choices.append(choice('✎', 'One at a time',
    'Open the Desk and add places by hand. Best when you have a handful and know them well.',
    () => { close(); openDesk('nodes'); }));

  choices.append(choice('☰', 'From a device list',
    'Paste a CSV — <code>name,ip,kind,zone,role,url</code>. Validated whole before ' +
    'anything is written, with the line number of every problem.',
    () => paste('csv')));

  choices.append(choice('◈', 'From a survey',
    'Paste the output of <code>nmap -sn -oX -</code> run where you already have the ' +
    'rights. The Atlas never probes the network itself — it reads what you hand it.',
    () => paste('nmap')));

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

function paste(kind) {
  const csv = kind === 'csv';
  panel(csv ? 'Paste your device list' : 'Paste your survey',
    csv
      ? 'The first line is the header. Only <code>name</code> is required.'
      : 'The XML from <code>nmap -sn -oX - 10.0.0.0/24</code>. A ping sweep is enough.');
  const area = el('textarea', 'dsk-input dsk-area dsk-mono');
  area.rows = 12;
  area.placeholder = csv
    ? 'name,ip,kind,zone,role,url\nGATEWAY,10.0.0.1,network,main,the way in,http://10.0.0.1\n'
    : '<?xml version="1.0"?><nmaprun …>';
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
          const res = await Editor.scan(area.value);
          close();
          A.showToast?.(`${res.seen} answered — review them in THE SURVEY.`);
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
