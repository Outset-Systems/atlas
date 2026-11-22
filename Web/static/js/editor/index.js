
import { A } from '../config.js';
import Editor from './store.js';
import { buildDesk, closeDesk, deskOpen, editPlace, newPlace, openDesk, removePlace } from './panel.js';
import { buildWizard, close as closeWizard, openWizard } from './wizard.js';

const SCENE_EDITORS = [
  { at: '#reliquary .rel-tools', section: 'rack', title: 'Show or hide the editing tools', tools: 'reliquary', records: 'rel-records' },
  { at: '#tribute .trb-head', section: 'vms', title: 'Add or remove guests' },
  { at: '#ledger .ldg-head', section: 'prefixes', title: 'Edit networks, prefixes and addressing' },
  { at: '#path .ldg-head', section: 'routes', title: 'Open WIRING, where the cables are drawn', view: 'topology' },
  { at: '#calendar .ldg-head', section: 'rites', title: 'Add or remove scheduled jobs' },
  { at: '#stones .ldg-head', section: 'stones', title: 'Add a honeypot or a canary token' },
  { at: '#chronicle .chron-head', section: 'chronicle', title: 'Add or remove charts' },
  { at: '#abyss .abyss-head', section: 'abyss', title: 'Add or remove reports' },
];

const editable = () => document.body.dataset.editable === '1';

function addHeaderButtons() {
  for (const { at, section, title, tools, records, view } of SCENE_EDITORS) {
    const host = document.querySelector(at);
    if (!host) continue;
    const btn = document.createElement('button');
    btn.className = 'scene-edit';
    btn.textContent = '✎';
    btn.title = title;
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      if (view) { A.closeAllScenes?.(); A.setView?.(view, { remember: true }); return; }
      if (!tools) { openDesk(section); return; }
      const scene = document.getElementById(tools);
      const on = !scene.classList.contains('tools-on');
      scene.classList.toggle('tools-on', on);
      btn.setAttribute('aria-pressed', String(on));
      btn.classList.toggle('on', on);
      dispatchEvent(new CustomEvent('atlas:scene-tools', { detail: { scene: tools, on } }));
    });
    if (tools) btn.setAttribute('aria-pressed', 'false');
    const door = records && document.getElementById(records);
    if (door) {
      door.hidden = false;
      door.addEventListener('click', (e) => { e.stopPropagation(); openDesk(section); });
    }
    host.insertBefore(btn, host.querySelector('.ldg-close, .rel-close, .trb-close'));
  }
}

function addSettingsEntry() {
  const panel = document.querySelector('#map-editor-body [data-group="map"]');
  if (!panel) return;
  const block = document.createElement('div');
  block.className = 'sp-editor sp-sec';
  block.dataset.sec = 'desk';
  block.innerHTML = '<button class="sp-sub" type="button">EVERY RECORD <span class="sp-sub-plain">· everything on the map</span></button>';
  const body = document.createElement('div');
  body.className = 'sp-sec-body';
  body.innerHTML =
    '<div class="sp-hint">Add, change or remove anything on the map: places, networks, ' +
    'prefixes, routes, racks, VMs and schedules: RECORDS, in the ATLAS menu ' +
    '(or press E). Every change is recorded and can be undone.</div>';
  const first = document.createElement('button');
  first.className = 'sp-btn';
  first.textContent = 'Guided setup';
  first.title = 'Name your atlas, add a network, and add its places';
  first.addEventListener('click', (e) => { e.stopPropagation(); openWizard(); });
  const row = document.createElement('div');
  row.className = 'sp-actions';
  row.append(first);
  body.append(row);
  block.append(body);
  panel.append(block);
  A.applySettingsFolds?.();
}

function addMenuEntry() {
  const item = document.getElementById('view-records');
  if (!item) return;
  item.hidden = false;
  addEventListener('atlas:records', () => openDesk());
}

function offerFirstSurvey() {
  if (document.body.dataset.seeded === '1') return;
  const demo = document.body.dataset.demo === '1';
  const invite = document.createElement(demo ? 'div' : 'button');
  invite.id = 'first-survey';
  if (demo) invite.classList.add('fs-demo');
  invite.innerHTML = demo
    ? '<span class="fs-head">YOU ARE LOOKING AT THE DEMO LAB</span>' +
      '<span class="fs-sub">to chart your own, set ATLAS_FALLBACK=empty in .env and run up -d</span>'
    : '<span class="fs-head">THIS ATLAS IS UNCHARTED</span>' +
      '<span class="fs-sub">start guided setup ›</span>';
  if (!demo) invite.addEventListener('click', () => openWizard());
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
  }, true);
}

function init() {
  buildDesk();
  buildWizard();
  if (!editable()) return;
  addHeaderButtons();
  addSettingsEntry();
  addMenuEntry();
  offerFirstSurvey();
  wireKeys();
}

if (document.readyState === 'loading') {
  addEventListener('DOMContentLoaded', init, { once: true });
} else {
  init();
}

A.editorReady = () => editable();
A.editPlace = (id) => (editable() ? editPlace(id) : undefined);
A.newPlace = () => (editable() ? newPlace() : undefined);
A.removePlace = (id) => (editable() ? removePlace(id) : undefined);
export { Editor };
