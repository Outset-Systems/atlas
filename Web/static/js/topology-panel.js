
import { esc } from './config.js';
import * as M from './topology-model.js';
import { T, t, tools, hooks } from './topology-state.js';

const HEX = /^#[0-9a-f]{3,8}$/i;
const KINDS = ['copper', 'fibre', 'dac', 'wireless', 'virtual'];
const STATES = [['tp-st-up', 'tp_lg_up'], ['tp-st-warn', 'tp_lg_warn'], ['tp-st-down', 'tp_lg_down'],
  ['tp-st-maint', 'tp_lg_maint'], ['tp-st-none', 'tp_lg_none']];

let root = null;

const zonesOf = () => (Array.isArray(T.data?.zones) ? T.data.zones : []);

const sample = (inner, box = '0 0 36 14') =>
  `<svg class="tp-canvas" viewBox="${box}" aria-hidden="true" focusable="false">${inner}</svg>`;
const LINE = 'M2 7H34';

function vlanSection() {
  const list = T.shown ? M.vlanList(T.shown, zonesOf()) : [];
  const rows = list.map((v) => {
    const on = T.vlan === v.vlan;
    const hue = HEX.test(String(v.hue || '')) ? v.hue : '';
    const count = v.cables === 1 ? t('tp_vlan_cables_one') : t('tp_vlan_cables', { n: v.cables });
    return `<li><button type="button" class="tp-vlan" data-key="vlan-${v.vlan}" data-vlan="${v.vlan}" aria-pressed="${on}"` +
      `${on ? ` title="${esc(t('tp_vlan_lit'))}"` : ''}>` +
      `<span class="tp-swatch"${hue ? ` style="--sw:${hue}"` : ''}></span>` +
      `<span class="tp-vlan-no">${v.vlan}</span><span class="tp-vlan-name">${esc(v.name || '')}</span>` +
      `<span class="tp-vlan-n">${esc(count)}</span></button></li>`;
  }).join('');
  return `<section class="tp-sec"><h3 class="tp-sec-h">${esc(t('tp_vlans'))}</h3>` +
    (rows ? `<ul class="tp-list">${rows}</ul>` : `<p class="tp-quiet">${esc(t('tp_vlans_none'))}</p>`) + '</section>';
}

function viewSection() {
  const seg = (mode, key) => `<button type="button" class="tp-btn" data-key="mode-${mode}" data-mode="${mode}" ` +
    `aria-pressed="${T.mode === mode}">${esc(t(key))}</button>`;
  return `<section class="tp-sec"><h3 class="tp-sec-h">${esc(t('tp_view'))}</h3>` +
    `<div class="tp-row" role="group" aria-label="${esc(t('tp_view'))}">${seg('all', 'tp_view_all')}${seg('infra', 'tp_view_infra')}</div></section>`;
}

function labelSection() {
  const box = (key, word) => `<label class="tp-check"><input type="checkbox" data-key="label-${key}" data-label="${key}"` +
    `${T.labels[key] ? ' checked' : ''}> ${esc(t(word))}</label>`;
  return `<section class="tp-sec"><h3 class="tp-sec-h">${esc(t('tp_labels'))}</h3>` +
    box('address', 'tp_label_address') + box('kind', 'tp_label_kind') + box('ports', 'tp_label_ports') + '</section>';
}

function arrangeSection() {
  const more = tools.map((tool) => `<button type="button" class="tp-btn" data-key="tool-${esc(tool.id)}" data-tool="${esc(tool.id)}"` +
    `${tool.title ? ` title="${esc(tool.title)}"` : ''}>${esc(tool.label)}</button>`).join('');
  return `<section class="tp-sec"><h3 class="tp-sec-h">${esc(t('tp_arrange'))}</h3><div class="tp-row">` +
    `<button type="button" class="tp-btn" data-key="act-fit" data-act="fit">${esc(t('tp_fit'))}</button>` +
    `<button type="button" class="tp-btn" data-key="act-rearrange" data-act="rearrange">${esc(t('tp_rearrange'))}</button>` +
    `${more}</div></section>`;
}

function legendSection() {
  const row = (art, word) => `<div class="tp-lg">${art}<span>${esc(word)}</span></div>`;
  const kinds = KINDS.map((k) => row(sample(`<g class="tp-link tp-cable tp-k-${k}"><path class="tp-wire tp-wire-plain" d="${LINE}"/>` +
    `${k === 'fibre' ? `<path class="tp-core" d="${LINE}"/>` : ''}</g>`), t(`tp_lg_${k}`))).join('');
  const hues = M.vlanList(T.shown || { things: [], links: [] }, zonesOf()).map((v) => v.hue).filter((h) => HEX.test(String(h || '')));
  const [h0, h1] = hues.length >= 2 ? hues : [null, null];
  const trunk = h0
    ? `<path class="tp-casing" d="${LINE}"/><path class="tp-wire" d="${LINE}" stroke="${h0}"/><path class="tp-stripe" d="${LINE}" stroke="${h1}" stroke-dasharray="10 10" stroke-dashoffset="-10"/>`
    : `<path class="tp-wire tp-wire-plain" d="${LINE}"/><path class="tp-stripe" d="${LINE}" style="stroke: var(--tp-gilt)" stroke-dasharray="10 10" stroke-dashoffset="-10"/>`;
  const dots = STATES.map(([cls, word]) => row(sample(`<g class="${cls}"><circle class="tp-state" cx="7" cy="7" r="4.5"/></g>`, '0 0 14 14'), t(word))).join('');
  return `<section class="tp-sec"><h3 class="tp-sec-h">${esc(t('tp_legend'))}</h3>${kinds}` +
    row(sample(`<g class="tp-link tp-cable tp-k-copper tp-assumed"><path class="tp-wire tp-wire-plain" d="${LINE}"/><path class="tp-gap" d="${LINE}"/></g>`), t('tp_lg_assumed')) +
    row(sample(`<g class="tp-link tp-cable tp-k-copper tp-trunk">${trunk}</g>`), t('tp_lg_trunk')) +
    row(sample(`<path class="tp-link tp-tie tp-route" d="${LINE}"/>`), t('tp_lg_route')) +
    dots + '</section>';
}

export function drawPanel() {
  if (!root) return;
  const had = document.activeElement && root.contains(document.activeElement) ? document.activeElement.dataset.key : '';
  root.innerHTML = vlanSection() + viewSection() + labelSection() + arrangeSection() + legendSection();
  if (had) root.querySelector(`[data-key="${CSS.escape(had)}"]`)?.focus();
}

function onClick(e) {
  const vlan = e.target.closest('[data-vlan]');
  if (vlan) { const v = Number(vlan.dataset.vlan); hooks.setVlan?.(T.vlan === v ? null : v); return; }
  const mode = e.target.closest('[data-mode]');
  if (mode) { hooks.setMode?.(mode.dataset.mode); return; }
  const act = e.target.closest('[data-act]');
  if (act) { (act.dataset.act === 'fit' ? hooks.fit : hooks.rearrange)?.(); return; }
  const tool = e.target.closest('[data-tool]');
  if (tool) tools.find((x) => x.id === tool.dataset.tool)?.onPress();
}

function onChange(e) {
  const box = e.target.closest('[data-label]');
  if (!box) return;
  T.labels[box.dataset.label] = box.checked;
  hooks.setLabels?.();
}

export function buildPanel(el) {
  root = el;
  root.addEventListener('click', onClick);
  root.addEventListener('change', onChange);
  drawPanel();
}
