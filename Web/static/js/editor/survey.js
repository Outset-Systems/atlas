/* THE SURVEYOR'S DESK — THE SURVEY: devices found on the wire, waiting to be
   charted, and the drafts they become.

   The Atlas never probes a network. A sweep, a lease file or a connected
   system's list is handed to it, filed, and shown here; the ones chosen become
   drafts that are corrected before anything is written, and land in one batch.
   The first-run wizard reaches the same draft review with a pasted list
   (`reviewCsv`). The panel itself is reached through `desk` (desk-kit.js). */

import { A, $, esc } from '../config.js';
import { say } from '../words.js';
import Editor from './store.js';
import { buildForm, makeEl as el } from './form.js';
import { VIRTUAL, desk, iconBtn, notice, problemList, run } from './desk-kit.js';

/* ── the discovery inbox ──────────────────────────────────────────────── */

/** Where a newcomer's router keeps its leases. Shared with the first survey. */
export const LEASE_HELP =
  'Or your router\'s DHCP leases — the devices that asked it for an address, with the ' +
  'names they gave themselves. Copy the file and paste it whole: ' +
  '<code>/var/dhcpd/var/db/dhcpd.leases</code> on pfSense or OPNsense, ' +
  '<code>kea-leases4.csv</code> where they run Kea, <code>/etc/pihole/dhcp.leases</code> ' +
  'on Pi-hole, <code>/tmp/dhcp.leases</code> on OpenWrt, or on Windows Server ' +
  '<code>Get-DhcpServerv4Lease -ScopeId 10.0.0.0 | ConvertTo-Csv</code>.';

export async function drawSurvey() {
  desk.setHead(VIRTUAL.survey.label, VIRTUAL.survey.lore);
  desk.body.innerHTML = '';

  const { observed, undocumented } = await Editor.discovery();
  const badge = $('dsk-n-survey');
  if (badge) badge.textContent = undocumented ? String(undocumented) : '';

  desk.body.append(el('div', 'dsk-bar',
    `<span class="dsk-bar-sub">The Atlas never probes the network itself. Run a sweep ` +
    `where you already have the rights, or copy your router's DHCP leases, and hand it ` +
    `the result.</span>`));

  // a connected system that can say what is on the network: one press, no paste
  let observers = [];
  try {
    observers = (await Editor.connections()).systems.filter((s) => s.observes && s.configured);
  } catch { /* not an admin of Connections, or it did not load: the paste box still works */ }
  for (const sys of observers) {
    const read = el('button', 'dsk-btn', `Read ${esc(sys.name)}`);
    read.title = 'Everything connected now, filed here beside a scan. Nothing is charted.';
    read.addEventListener('click', async () => {
      read.disabled = true;
      try {
        const res = await Editor.observe(sys.key);
        if (!res.ok) throw new Error(res.error || 'It did not answer.');
        A.showToast?.(`${res.seen} seen by ${res.source} · ${res.new} new to the survey.`);
        desk.show('survey');
      } catch (err) {
        desk.body.append(problemList(err));
      } finally { read.disabled = false; }
    });
    desk.body.append(read);
  }

  const paste = el('details', 'dsk-drop');
  paste.innerHTML = `<summary>Bring in a survey (nmap XML) or DHCP leases</summary>` +
    `<p class="dsk-help">A sweep, on a machine that can see the segment:<br>` +
    `<code>nmap -sn -oX - 192.0.2.0/24</code><br>A ping sweep is enough — a port scan is ` +
    `not required and not advised on someone else's network.</p>` +
    `<p class="dsk-help">${LEASE_HELP}</p>`;
  const area = el('textarea', 'dsk-input dsk-area dsk-mono');
  area.rows = 5;
  area.placeholder = '<?xml version="1.0"?><nmaprun …>   or a lease file';
  const go = el('button', 'dsk-btn dsk-btn-go', 'File this survey');
  go.addEventListener('click', async () => {
    if (!area.value.trim()) return;
    go.disabled = true;
    try {
      const res = await Editor.fileSurvey(area.value);
      A.showToast?.(res.format
        ? `${res.seen} ${res.format} leases · ${res.new} new to the survey.`
        : `${res.seen} answered · ${res.new} new to the survey.`);
      area.value = '';
      desk.show('survey');
    } catch (err) {
      paste.append(problemList(err));
    } finally { go.disabled = false; }
  });
  paste.append(area, go);
  desk.body.append(paste);

  if (!observed.length) {
    desk.body.append(notice('Nothing surveyed yet.'));
    return;
  }

  const chosen = new Set();
  const boxes = [];
  const table = el('table', 'dsk-table');
  table.innerHTML = '<thead><tr><th class="dsk-th-pick"></th><th>Address</th><th>Name</th>' +
    '<th>Vendor</th><th>Open ports</th><th>Looks like</th><th>' + say('Realm') + '</th><th>State</th>' +
    '<th class="dsk-th-act"></th></tr></thead>';
  // a first survey is often dozens of strangers: one box takes them all
  const all = el('input', 'dsk-check');
  all.type = 'checkbox';
  all.title = 'Choose every uncharted device';
  all.setAttribute('aria-label', 'Choose every uncharted device');
  table.querySelector('.dsk-th-pick').append(all);
  const sync = () => {
    chart.disabled = chosen.size === 0;
    chart.textContent = chosen.size ? `Chart ${chosen.size} of these ›` : 'Chart the chosen ›';
    const open = boxes.filter((b) => !b.box.disabled);
    all.checked = open.length > 0 && open.every((b) => b.box.checked);
    all.disabled = open.length === 0;
  };
  all.addEventListener('change', () => {
    for (const { box, key } of boxes) {
      if (box.disabled) continue;
      box.checked = all.checked;
      all.checked ? chosen.add(key) : chosen.delete(key);
    }
    sync();
  });
  const tbody = el('tbody');
  for (const row of observed) {
    const tr = el('tr', row.ignored ? 'dsk-dim-row' : '');
    const pick = el('td', 'dsk-td-pick');
    const box = el('input', 'dsk-check');
    box.type = 'checkbox';
    box.disabled = !row.undocumented || row.ignored;
    boxes.push({ box, key: row.key });
    box.addEventListener('change', () => {
      box.checked ? chosen.add(row.key) : chosen.delete(row.key);
      sync();
    });
    pick.append(box);
    tr.append(pick);
    tr.append(el('td', '', `<span class="dsk-mono">${esc(row.ip || row.mac || '—')}</span>`));
    tr.append(el('td', '', esc(row.hostname || '—')));
    tr.append(el('td', '', esc(row.vendor || '—')));
    tr.append(el('td', '', esc((row.ports || []).map((p) => p.port).slice(0, 8).join(' ') || '—')));
    // a suggestion, with its reason on hover; the draft says it again
    const guess = row.suggestion;
    const looks = el('td', '', guess
      ? `${esc(guess.role)} <span class="dsk-dim">${esc(guess.kind)}</span>` : '—');
    if (guess) looks.title = `A guess: ${guess.because}. Check it when you chart it.`;
    tr.append(looks);
    tr.append(el('td', '', esc(row.suggested_zone || '—')));
    const seenBy = row.source ? ` <span class="dsk-dim">· ${esc(row.source)}</span>` : '';
    tr.append(el('td', '', row.ignored
      ? '<span class="dsk-dim">silenced</span>'
      : row.undocumented
        ? `<span class="dsk-warn">uncharted</span>${seenBy}`
        : `<span class="dsk-ok">charted as ${esc(row.matched_node)}</span>`));
    const act = el('td', 'dsk-td-act');
    act.append(iconBtn(row.ignored ? '👁' : '🚫',
      row.ignored ? 'Bring it back into the survey' : "Silence it — I don't want this charted",
      async () => {
        await Editor.decide([row.key], row.ignored ? 'unignore' : 'ignore');
        desk.show('survey');
      }));
    tr.append(act);
    tbody.append(tr);
  }
  table.append(tbody);
  desk.body.append(table);

  const bar = el('div', 'dsk-formbar');
  const chart = el('button', 'dsk-btn dsk-btn-go', 'Chart the chosen ›');
  chart.addEventListener('click', () => draftReview([...chosen]));
  bar.append(chart);
  desk.body.append(bar);
  sync();
}

/** The review step: drafts are shown and corrected before anything is written. */
async function draftReview(keys) {
  const { nodes } = await Editor.draftsFrom(keys);
  drawDrafts(nodes, `${nodes.length} place${nodes.length === 1 ? '' : 's'} from the survey`,
    'A survey can say a thing answered, not what it is: each lands as <code>unknown</code> ' +
    'unless its maker or its own name suggests a type, and then its role line says why. ' +
    say('Check those, give them names and realms now, or later.'));
}

function drawDrafts(nodes, headline, caveat) {
  desk.setHead('CHART THESE PLACES', 'nothing is written until you say so');
  desk.body.innerHTML = '';
  if (!nodes.length) { desk.body.append(notice('Nothing to chart.')); return; }
  desk.body.append(el('div', 'dsk-bar', `<span class="dsk-bar-sub">${esc(headline)}. ` +
    (caveat || 'Correct anything that came through wrong, then chart them.') + `</span>`));

  const forms = nodes.map((node) => {
    const wrap = el('details', 'dsk-draft');
    wrap.open = nodes.length <= 3;
    wrap.append(el('summary', '', `${esc(node.name)} <span class="dsk-mono">${esc(node.ip)}</span>`));
    const form = buildForm('nodes', node);
    wrap.append(form.el);
    desk.body.append(wrap);
    return form;
  });

  const errors = el('div', 'dsk-form-errors');
  const bar = el('div', 'dsk-formbar');
  const cancel = el('button', 'dsk-btn', 'Not yet');
  cancel.addEventListener('click', () => desk.show('survey'));
  const go = el('button', 'dsk-btn dsk-btn-go', `Chart ${forms.length}`);
  go.addEventListener('click', async () => {
    errors.innerHTML = '';
    let ops;
    try {
      ops = forms.map((f) => ({ op: 'insert', section: 'nodes', body: f.read() }));
    } catch (err) { errors.append(notice(err.message, 'bad')); return; }
    go.disabled = true;
    try {
      // One batch: either every discovered place lands or none does, so a
      // typo in the fourth doesn't leave three half-charted strangers.
      await run(() => Editor.apply(ops, 'charted from a survey', 'survey'));
      desk.show('nodes');
    } catch (err) {
      errors.append(problemList(err));
      go.disabled = false;
    }
  });
  bar.append(cancel, go);
  desk.body.append(errors, bar);
}

/** Offer the drafts from a pasted CSV — used by the first-run wizard. */
export async function reviewCsv(text) {
  const { nodes } = await Editor.importCsv(text);
  await desk.open();
  drawDrafts(nodes, `${nodes.length} place${nodes.length === 1 ? '' : 's'} from your list`,
    'Positions default to the middle of the map — drag them where they belong afterwards, ' +
    'or set them here.');
}
