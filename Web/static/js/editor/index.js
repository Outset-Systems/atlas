/* The editing layer, bolted onto the map without the map knowing.

   Loaded unconditionally, but inert unless the server rendered the page with
   `editable` — a viewer who can't write is never shown a pencil that 403s.
   Everything it adds is additive: a ✎ in each scene's header, an entry in the
   Settings panel, and the `e` key.

   Kept in its own folder so the read-only Atlas is still the read-only Atlas:
   deleting this directory and the four markup blocks it needs would leave the
   original app intact. */

import { A, $ } from '../config.js';
import Editor from './store.js';
import { buildDesk, closeDesk, deskOpen, openDesk } from './panel.js';
import { buildWizard, close as closeWizard, openWizard } from './wizard.js';

/** Every scene that can be edited: where its ✎ goes, and what it opens.
    Selectors are scoped to the panel because THE PATH and THE CALENDAR reuse
    the Ledger's `.ldg-head`, and THE ARMORY's toolbar is a class, not an id.
    ⚠ These are the only place a scene's markup is named from outside its own
    module: rename a panel and the pencil silently stops appearing, which is
    what `#rites` did the moment THE RITES became THE CALENDAR (v1.45.0).
    `test_calendar_scene.py` pins that every `at` here still resolves. */
const SCENE_EDITORS = [
  { at: '#reliquary .rel-tools', section: 'rack', title: 'Add, remove or re-describe the rack' },
  { at: '#tribute .trb-head', section: 'vms', title: 'Add or remove vassals' },
  { at: '#ledger .ldg-head', section: 'prefixes', title: 'Edit realms, prefixes and addressing' },
  { at: '#path .ldg-head', section: 'routes', title: 'Add or remove routes' },
  { at: '#calendar .ldg-head', section: 'rites', title: 'Add or remove rites' },
  { at: '#stones .ldg-head', section: 'stones', title: 'Add a honeypot or a canary token' },
  { at: '#chronicle .chron-head', section: 'chronicle', title: 'Add or remove watchings' },
  { at: '#abyss .abyss-head', section: 'abyss', title: 'Add or remove scryings' },
];

const editable = () => document.body.dataset.editable === '1';

function addHeaderButtons() {
  for (const { at, section, title } of SCENE_EDITORS) {
    const host = document.querySelector(at);
    if (!host) continue;
    const btn = document.createElement('button');
    btn.className = 'scene-edit';
    btn.textContent = '✎';
    btn.title = title;
    btn.addEventListener('click', (e) => { e.stopPropagation(); openDesk(section); });
    // before the × so the close button stays the rightmost thing in every header
    host.insertBefore(btn, host.querySelector('.ldg-close, .rel-close, .trb-close'));
  }
}

function addSettingsEntry() {
  const panel = document.querySelector('#settings-panel [data-group="map"]');
  if (!panel) return;
  // A real foldable section since 2026-08-16 (the owner: "ALL the sections should
  // be collapsable") — the same .sp-sec/.sp-sub/.sp-sec-body shape as every
  // sibling, so the panel's delegated fold click and applyFolds cover it for
  // free. It was the one plain <div> header in the panel.
  const block = document.createElement('div');
  block.className = 'sp-editor sp-sec';
  block.dataset.sec = 'desk';
  block.innerHTML = '<button class="sp-sub" type="button">EDIT THE MAP <span class="sp-sub-plain">· everything on it</span></button>';
  const body = document.createElement('div');
  body.className = 'sp-sec-body';
  body.innerHTML =
    '<div class="sp-hint">Add, change or remove anything on the map: places, networks, ' +
    'prefixes, routes, racks, VMs and schedules. Every change is recorded and ' +
    'can be undone.</div>';
  const open = document.createElement('button');
  open.className = 'sp-btn sp-btn-go';
  open.textContent = 'Open the map editor (E)';
  open.addEventListener('click', (e) => { e.stopPropagation(); openDesk(); });
  const first = document.createElement('button');
  first.className = 'sp-btn';
  first.textContent = 'Guided setup';
  first.title = 'Name your atlas, add a network, and add its places';
  first.addEventListener('click', (e) => { e.stopPropagation(); openWizard(); });
  const row = document.createElement('div');
  row.className = 'sp-actions';
  row.append(open, first);
  body.append(row);
  block.append(body);
  panel.querySelector('.sp-group-name').after(block);   // above MOVE PLACES
  A.applySettingsFolds?.();   // pick up this section's stored/default fold
}

/** An unseeded Atlas has nothing to show, so it offers the way in instead.
    On the bundled demo there IS a map, so the invite names it and steps off
    to a corner rather than covering the middle of it. */
function offerFirstSurvey() {
  if (document.body.dataset.seeded === '1') return;
  const demo = document.body.dataset.demo === '1';
  const invite = document.createElement('button');
  invite.id = 'first-survey';
  if (demo) invite.classList.add('fs-demo');
  invite.innerHTML = demo
    ? '<span class="fs-head">YOU ARE LOOKING AT THE DEMO LAB</span>' +
      '<span class="fs-sub">chart your own ›</span>'
    : '<span class="fs-head">THIS ATLAS IS UNCHARTED</span>' +
      '<span class="fs-sub">start guided setup ›</span>';
  invite.addEventListener('click', () => openWizard());
  document.body.append(invite);
}

function wireKeys() {
  addEventListener('keydown', (e) => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || '');
    if (e.key === 'Escape') {
      if (deskOpen()) { e.stopPropagation(); closeDesk(); }
      closeWizard();
      return;
    }
    if (typing) return;
    if (e.key === 'e' || e.key === 'E') {
      e.preventDefault();
      deskOpen() ? closeDesk() : openDesk();
    }
  }, true);   // capture: the Desk must claim Escape before the map closes a card
}

function init() {
  buildDesk();
  buildWizard();
  if (!editable()) return;
  addHeaderButtons();
  addSettingsEntry();
  offerFirstSurvey();
  wireKeys();
}

if (document.readyState === 'loading') {
  addEventListener('DOMContentLoaded', init, { once: true });
} else {
  init();
}

A.editorReady = () => editable();
export { Editor };
