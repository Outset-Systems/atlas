
import { hiddenByPremise } from './premises.js';
import { A, DRAG_END, postJSON } from './config.js';
import { unproject } from './project.js';

const POS_KEY = 'atlas-pos-overrides';
function posOverrides() {
  try { return JSON.parse(localStorage.getItem(POS_KEY) || '{}'); } catch { return {}; }
}
const STYLE_POS_KEY = 'atlas-style-pos';
let styleDrafts = (() => {
  try { return JSON.parse(localStorage.getItem(STYLE_POS_KEY) || '{}') || {}; } catch { return {}; }
})();
export const onStyleArt = () => Boolean(A.styleArt) && (A.onOtherStyle?.() ?? true);
A.styleDraft = () => {
  const d = (onStyleArt() && styleDrafts[A.styleArt]) || {};
  return { places: d.places || {}, zones: d.zones || {}, regions: d.regions || {} };
};
A.draftStyleSpot = function draftStyleSpot(kind, id, at, regionId) {
  const d = (styleDrafts[A.styleArt] = A.styleDraft());
  const spot = { x: Math.round(at.x * 10) / 10, y: Math.round(at.y * 10) / 10 };
  if (regionId) (d.regions[regionId] ??= {})[id] = spot;
  else d[kind][id] = spot;
  try { localStorage.setItem(STYLE_POS_KEY, JSON.stringify(styleDrafts)); } catch {   }
};
const draftCount = (d) => Object.keys(d.places).length + Object.keys(d.zones).length +
  Object.values(d.regions).reduce((sum, pins) => sum + Object.keys(pins).length, 0);
function dropStyleDraft() {
  delete styleDrafts[A.styleArt];
  try { localStorage.setItem(STYLE_POS_KEY, JSON.stringify(styleDrafts)); } catch {   }
}
export function applyOverrides() {
  const o = posOverrides();
  const level = A.levelPlaces;
  const drafted = A.styleDraft().places;
  for (const n of A.DATA.nodes) {
    const home = o[n.id] || n._home || n;
    n._home = { x: home.x, y: home.y };
    n._realOff ??= Boolean(n.off_map);
    const at = level ? level[n.id] : drafted[n.id] || A.stylePlaces?.[n.id];
    n.off_map = n._realOff || Boolean(level && !at) || hiddenByPremise(n);
    n._folded = false;
    const to = at || n._home;
    n.x = to.x; n.y = to.y;
  }
  if (level) return;
  const drawn = {};
  for (const n of A.DATA.nodes) if (!n.off_map) drawn[n.id] = { x: n.x, y: n.y };
  const hidden = A.foldedHere?.(drawn);
  if (!hidden?.size) return;
  for (const n of A.DATA.nodes) {
    if (hidden.has(n.id)) { n.off_map = true; n._folded = true; }
  }
}
A.mainPlace = (n) => A.styleDraft().places[n.id] || A.stylePlaces?.[n.id] || posOverrides()[n.id] || n._home || n;
A.editMode = false;
A.setEditMode = function setEditMode(on) {
  A.editMode = !!on;
  document.body.classList.toggle('editing-map', A.editMode);
  if (A.editMode) { A.closeCard?.(); }
};
A.copyPositions = function copyPositions() {
  if (onStyleArt()) {
    const d = A.styleDraft();
    navigator.clipboard?.writeText(JSON.stringify(d, null, 2)).catch(() => {});
    return draftCount(d);
  }
  const o = posOverrides();
  const rounded = Object.fromEntries(Object.entries(o).map(
    ([id, p]) => [id, { x: +p.x.toFixed(1), y: +p.y.toFixed(1) }]));
  const txt = JSON.stringify(rounded, null, 1);
  navigator.clipboard?.writeText(txt).catch(() => {});
  return Object.keys(rounded).length;
};
A.resetPositions = function resetPositions() {
  if (onStyleArt()) dropStyleDraft();
  else localStorage.removeItem(POS_KEY);
  location.reload();
};
A.savePositions = async function savePositions() {
  if (onStyleArt()) {
    const d = A.styleDraft();
    if (!draftCount(d)) return { saved: 0 };
    const r = await postJSON(`api/v2/admin/map-art/${encodeURIComponent(A.styleArt)}/layout`, d);
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.status);
    const res = await r.json();
    dropStyleDraft();
    A.useMaps?.(res.maps || []);
    return { ...res, style: A.styleLabel || 'this map style' };
  }
  const o = posOverrides();
  if (!Object.keys(o).length) return { saved: 0 };
  const r = await postJSON('api/v2/positions', o);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.status);
  const res = await r.json();
  localStorage.removeItem(POS_KEY);
  return res;
};

function screenToPct(clientX, clientY) {
  const p = unproject(clientX, clientY);
  return {
    x: ((p.x - A.cam.x) / A.cam.k) / A.MAPW * 100,
    y: ((p.y - A.cam.y) / A.cam.k) / A.MAPH * 100,
  };
}

A.screenToPct = screenToPct;

export function dragOnMap(e, el, place, done) {
  e.stopPropagation(); e.preventDefault();
  delete el.dataset.dragged;
  el.setPointerCapture(e.pointerId);
  el.classList.add('dragging');
  const move = (ev) => {
    const at = place(screenToPct(ev.clientX, ev.clientY));
    el.style.left = at.x + '%';
    el.style.top = at.y + '%';
    el.dataset.dragged = '1';
  };
  const up = () => {
    el.classList.remove('dragging');
    el.removeEventListener('pointermove', move);
    for (const t of DRAG_END) el.removeEventListener(t, up);
    if (el.dataset.dragged) done();
  };
  el.addEventListener('pointermove', move);
  for (const t of DRAG_END) el.addEventListener(t, up);
}

export function keepSpot(id, at) {
  const o = posOverrides();
  o[id] = { x: at.x, y: at.y };
  try { localStorage.setItem(POS_KEY, JSON.stringify(o)); } catch {   }
}
