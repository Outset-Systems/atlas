
import { inRack, rackList } from './rack-model.js';

export const LEVELS = ['site', 'building', 'floor', 'room', 'desk'];
const RANK = new Map(LEVELS.map((l, i) => [l, i]));
const fold = (name) => String(name ?? '').trim().replace(/\s+/g, ' ').toLowerCase();
const byName = (a, b) => String(a.name || a.id).localeCompare(String(b.name || b.id), undefined,
  { numeric: true, sensitivity: 'base' });

export function premiseIndex(data) {
  const rows = (Array.isArray(data?.premises) ? data.premises : [])
    .filter((p) => p && typeof p.id === 'string' && p.id);
  const byId = new Map(rows.map((p) => [p.id, p]));
  const children = new Map(rows.map((p) => [p.id, []]));
  const tops = [];
  for (const p of rows) {
    const parent = typeof p.parent === 'string' && byId.has(p.parent) && p.parent !== p.id ? p.parent : null;
    (parent ? children.get(parent) : tops).push(p);
  }
  const sortKids = (list) => list.sort((a, b) => {
    const oa = Number.isFinite(a.order) ? a.order : null;
    const ob = Number.isFinite(b.order) ? b.order : null;
    if (oa !== null && ob !== null && oa !== ob) return oa - ob;
    if ((oa === null) !== (ob === null)) return oa === null ? 1 : -1;
    return byName(a, b);
  });
  for (const list of children.values()) sortKids(list);
  sortKids(tops);
  const parentOf = (id) => {
    const p = byId.get(id);
    return p && typeof p.parent === 'string' && byId.has(p.parent) && p.parent !== id ? p.parent : null;
  };
  return {
    byId, children, tops, parentOf,
    rank: (id) => RANK.get(byId.get(id)?.level) ?? LEVELS.length,
    get size() { return byId.size; },
  };
}

export function lineage(index, id) {
  const out = [];
  for (let at = id, hops = 0; at && index.byId.has(at) && hops < 16; hops++) {
    if (out.includes(at)) break;
    out.unshift(at);
    at = index.parentOf(at);
  }
  return out;
}

export function under(index, id, scope) {
  if (!scope) return true;
  return !!id && lineage(index, id).includes(scope);
}

function nameMap(index) {
  const seen = new Map();
  for (const p of index.byId.values()) {
    const k = fold(p.name);
    if (!k) continue;
    seen.set(k, seen.has(k) ? null : p.id);
  }
  return seen;
}

export function premiseNamed(data, name) {
  const text = String(name ?? '');
  const ix = premiseIndex(data);
  if (/[›/]/.test(text)) {
    const want = text.split(/[›/]/).map(fold).filter(Boolean);
    if (!want.length) return null;
    const hits = [...ix.byId.keys()].filter((id) => {
      const line = lineage(ix, id).map((pid) => fold(ix.byId.get(pid)?.name));
      return line.length >= want.length && want.every((w, i) => line[line.length - want.length + i] === w);
    });
    return hits.length === 1 ? hits[0] : null;
  }
  const k = fold(text);
  return (k && nameMap(ix).get(k)) || null;
}

export function premisePaths(data, within = '') {
  const ix = premiseIndex(data);
  const out = [];
  const walk = (list, names) => {
    for (const p of list) {
      const here = [...names, p.name || p.id];
      if (p.level !== 'desk' || (within && under(ix, p.id, within))) out.push(here.join(' › '));
      if (names.length < 8) walk(ix.children.get(p.id) || [], here);
    }
  };
  walk(ix.tops, []);
  return out;
}

function sayer(index) {
  const named = nameMap(index);
  return (ref, text) => {
    if (typeof ref === 'string' && index.byId.has(ref)) return ref;
    const k = fold(text);
    return (k && named.get(k)) || null;
  };
}

export function rackPremises(data, index = premiseIndex(data)) {
  const out = new Map();
  if (!index.size) return out;
  const said = sayer(index);
  for (const r of Array.isArray(data?.racks) ? data.racks : []) {
    if (!r || typeof r.id !== 'string') continue;
    const at = said(r.premise, r.location);
    if (at) out.set(r.id, at);
  }
  return out;
}

export function premiseOf(data, index = premiseIndex(data)) {
  const out = new Map();
  if (!index.size) return out;
  const said = sayer(index);
  const nodes = (Array.isArray(data?.nodes) ? data.nodes : []).filter((n) => n && typeof n.id === 'string');

  const racks = rackList(Array.isArray(data?.racks) ? data.racks : [], '');
  const rackPremise = rackPremises(data, index);
  const racked = new Set();
  for (const section of [data?.rack, data?.rack_rear]) {
    for (const r of racks) {
      for (const slot of inRack(Array.isArray(section) ? section : [], racks, r.id)) {
        if (!slot || typeof slot.node !== 'string' || !slot.node || racked.has(slot.node)) continue;
        racked.add(slot.node);
        const at = rackPremise.get(r.id);
        if (at) out.set(slot.node, at);
      }
    }
  }
  const vms = Array.isArray(data?.vms) ? data.vms.filter((v) => v && typeof v.id === 'string') : [];
  const guests = new Set(vms.map((v) => v.id));
  for (const n of nodes) if (n.kind === 'vm') guests.add(n.id);
  for (const n of nodes) {
    if (racked.has(n.id) || guests.has(n.id)) continue;
    const at = said(n.premise, n.location);
    if (at) out.set(n.id, at);
  }
  const hostOf = new Map(vms.map((v) => [v.id, v.host]));
  for (const n of nodes) if (guests.has(n.id) && !hostOf.get(n.id) && n.parent) hostOf.set(n.id, n.parent);
  for (const id of guests) {
    let host = hostOf.get(id);
    for (let hops = 0; host && guests.has(host) && hops < 8; hops++) host = hostOf.get(host);
    if (host && out.has(host)) out.set(id, out.get(host));
  }
  return out;
}

export function placesIn(index, where, nodes, scope) {
  const list = (Array.isArray(nodes) ? nodes : []).filter((n) => n && typeof n.id === 'string');
  if (!scope) return list;
  return list.filter((n) => under(index, where.get(n.id), scope));
}

export function ownHolders(where) {
  return new Set(where.values());
}

export const holdsOwn = (own, id) => own.has(id);

export function descend(index, own, id) {
  let at = id;
  for (let hops = 0; at && hops < 16; hops++) {
    const kids = index.children.get(at) || [];
    if (kids.length !== 1 || own.has(at)) break;
    at = kids[0].id;
  }
  return at;
}

export const wouldDescend = (index, own, id) => !!id && descend(index, own, id) !== id;

export function leaveTo(index, own, id) {
  let at = index.parentOf(id);
  for (let hops = 0; at && hops < 16 && wouldDescend(index, own, at); hops++) at = index.parentOf(at);
  return at || null;
}

export function crumbs(index, own, id) {
  const line = lineage(index, id);
  const out = [];
  let held = [];
  line.forEach((pid, i) => {
    const p = index.byId.get(pid);
    const item = { id: pid, name: p.name || pid, level: p.level };
    const last = i === line.length - 1;
    const kids = index.children.get(pid) || [];
    if (!last && wouldDescend(index, own, pid) && kids[0]?.id === line[i + 1]) {
      held.push(item);
      return;
    }
    out.push({ ...item, skipped: held });
    held = [];
  });
  return out;
}

export const crumbLabel = (c) => [...c.skipped.map((s) => s.name), c.name].join(' · ');

export function fromLocations(data, siteName = 'Home', fallback = '') {
  if (premiseIndex(data).size) return [];
  const names = new Map();
  const note = (text) => {
    const shown = String(text ?? '').trim().replace(/\s+/g, ' ');
    const k = fold(shown);
    if (k && !names.has(k)) names.set(k, shown);
    return k;
  };
  const racks = (Array.isArray(data?.racks) ? data.racks : []).filter((r) => r && typeof r.id === 'string');
  const nodes = (Array.isArray(data?.nodes) ? data.nodes : []).filter((n) => n && typeof n.id === 'string');
  for (const r of racks) note(r.location || fallback);
  for (const n of nodes) if (n.location) note(n.location);
  if (!names.size) return [];
  const slug = (s) => String(s).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'room';
  const site = slug(siteName) || 'site';
  const used = new Set([site, ...racks.map((r) => r.id), ...nodes.map((n) => n.id)]);
  const idOf = new Map();
  for (const [k, shown] of names) {
    let id = `${site}-${slug(shown)}`;
    for (let i = 2; used.has(id); i++) id = `${site}-${slug(shown)}-${i}`;
    used.add(id);
    idOf.set(k, id);
  }
  const ops = [{ op: 'upsert', section: 'premises', id: site,
    body: { id: site, name: String(siteName).trim() || 'Home', level: 'site' } }];
  for (const [k, shown] of names) {
    ops.push({ op: 'upsert', section: 'premises', id: idOf.get(k),
      body: { id: idOf.get(k), name: shown, level: 'room', parent: site } });
  }
  for (const r of racks) {
    const room = idOf.get(fold(r.location || fallback));
    if (room && !r.premise) ops.push({ op: 'upsert', section: 'racks', id: r.id, body: { premise: room } });
  }
  for (const n of nodes) {
    if (!n.location || n.premise) continue;
    ops.push({ op: 'upsert', section: 'nodes', id: n.id, body: { premise: idOf.get(fold(n.location)) } });
  }
  return ops;
}


const HASH_KEY = 'premise';
const hashParts = (hash) => String(hash || '').replace(/^#/, '').split('&').filter(Boolean);
const keyOf = (part) => part.split('=')[0];

export function premiseFromHash(hash) {
  for (const part of hashParts(hash)) {
    if (keyOf(part) !== HASH_KEY || !part.includes('=')) continue;
    let id;
    try { id = decodeURIComponent(part.slice(part.indexOf('=') + 1)); } catch { return null; }
    id = id.trim();
    return id && id.length <= 200 ? id : null;
  }
  return null;
}

export function hashWithPremise(hash, id) {
  const mine = id ? `${HASH_KEY}=${encodeURIComponent(id)}` : null;
  const out = [];
  let placed = false;
  for (const part of hashParts(hash)) {
    if (keyOf(part) !== HASH_KEY) { out.push(part); continue; }
    if (!placed && mine) out.push(mine);
    placed = true;
  }
  if (!placed && mine) out.push(mine);
  return out.join('&');
}


export const ROOM_DEVICES = Object.freeze(new Set(['laptop', 'desktop', 'kiosk', 'printer', 'scanner',
  'mfp', 'phone', 'display', 'room-system', 'camera', 'iot']));

export function hiddenAt(index, where, n, scope) {
  if (!n || !index.size) return false;
  const at = where.get(n.id);
  const roomy = ROOM_DEVICES.has(n.device);
  if (!scope) return roomy && Boolean(at);
  if (!under(index, at, scope)) return true;
  if (!roomy || at === scope) return false;
  const line = lineage(index, at);
  return line.slice(line.indexOf(scope) + 1).some((id) => index.byId.get(id)?.level === 'floor');
}

export function schematic(index, where, nodes, scope, stateOf = () => null) {
  const list = (Array.isArray(nodes) ? nodes : []).filter((n) => n && typeof n.id === 'string');
  const kids = (index.children.get(scope) || []).map((p) => {
    const inside = list.filter((n) => under(index, where.get(n.id), p.id));
    const states = inside.map((n) => stateOf(n.id));
    const worst = ['down', 'degraded'].find((s) => states.includes(s)) || '';
    return { id: p.id, name: p.name || p.id, level: p.level || '', kind: p.kind || '',
      count: inside.length, trouble: states.filter((s) => s === 'down' || s === 'degraded').length, worst };
  });
  const here = list.filter((n) => where.get(n.id) === scope);
  return { kids, here };
}


const BOX = ['x', 'y', 'w', 'h'];
export function boxOf(p) {
  if (!p || !BOX.every((k) => Number.isFinite(p[k]))) return null;
  return p.w > 0 && p.h > 0 ? { x: p.x, y: p.y, w: p.w, h: p.h } : null;
}

export function planSpots(index, where, nodes, pid, pins = {}, skip = () => false) {
  const out = {};
  const list = (Array.isArray(nodes) ? nodes : [])
    .filter((n) => n && typeof n.id === 'string' && !skip(n) && under(index, where.get(n.id), pid));
  const boxed = new Map();
  const loose = [];
  const boxes = new Map(boxesOn(index, pid).map((b) => [b.p.id, b.box]));
  for (const n of list) {
    const pin = pins && pins[n.id];
    if (pin && Number.isFinite(pin.x) && Number.isFinite(pin.y)) { out[n.id] = { x: pin.x, y: pin.y }; continue; }
    const line = lineage(index, where.get(n.id));
    const child = line[line.indexOf(pid) + 1];
    const box = child ? boxes.get(child) : null;
    if (box) {
      if (!boxed.has(child)) boxed.set(child, { box, ids: [] });
      boxed.get(child).ids.push(n.id);
    } else loose.push(n.id);
  }
  for (const { box, ids } of boxed.values()) {
    const cols = Math.max(1, Math.ceil(Math.sqrt(ids.length * (box.w / box.h))));
    const rows = Math.max(1, Math.ceil(ids.length / cols));
    ids.forEach((id, i) => {
      const c = i % cols;
      const r = Math.floor(i / cols);
      out[id] = { x: box.x + box.w * (0.12 + 0.76 * (cols === 1 ? 0.5 : c / (cols - 1))),
        y: box.y + box.h * (0.22 + 0.66 * (rows === 1 ? 0.5 : r / (rows - 1))) };
    });
  }
  loose.forEach((id, i) => {
    out[id] = { x: loose.length === 1 ? 50 : 4 + (92 * i) / (loose.length - 1), y: 95 };
  });
  return out;
}

export function premiseOfPlan(index, regionId) {
  if (!regionId) return '';
  for (const p of index.byId.values()) if (p.region === regionId) return p.id;
  return '';
}

export function boxesOn(index, pid) {
  const kids = index.children.get(pid) || [];
  const bare = kids.filter((p) => !boxOf(p));
  const cols = Math.max(1, Math.ceil(Math.sqrt(bare.length)));
  const rows = Math.max(1, Math.ceil(bare.length / cols));
  const W = 84 / cols;
  const H = 76 / rows;
  return kids.map((p) => {
    const own = boxOf(p);
    if (own) return { p, box: own, auto: false };
    const i = bare.indexOf(p);
    return { p, auto: true, box: { x: 8 + (i % cols) * W + W * 0.06, y: 8 + Math.floor(i / cols) * H + H * 0.06,
      w: W * 0.88, h: H * 0.88 } };
  });
}

export function roomOps(data, owner, name, level, rect, targets = []) {
  const ix = premiseIndex(data);
  const parent = ix.byId.get(owner);
  if (!parent || !String(name || '').trim()) return [];
  const want = LEVELS.includes(level) ? level : 'room';
  const rank = Math.max(LEVELS.indexOf(want), ix.rank(owner) + 1);
  if (rank >= LEVELS.length) return [];
  const slug = (s) => String(s).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'room';
  const used = new Set([...ix.byId.keys()]);
  let id = `${owner}-${slug(name)}`;
  for (let n = 2; used.has(id); n++) id = `${owner}-${slug(name)}-${n}`;
  const round = (v) => Math.round(v * 10) / 10;
  const ops = [{ op: 'insert', section: 'premises', body: {
    id, name: String(name).trim(), level: LEVELS[rank], parent: owner,
    x: round(rect.x), y: round(rect.y), w: round(rect.w), h: round(rect.h) } }];
  for (const t of targets) {
    if (t.kind === 'place') ops.push({ op: 'upsert', section: 'nodes', id: t.id, body: { premise: id } });
    else if (t.kind === 'rack' && !t.implied) ops.push({ op: 'upsert', section: 'racks', id: t.id, body: { premise: id } });
  }
  return ops;
}
