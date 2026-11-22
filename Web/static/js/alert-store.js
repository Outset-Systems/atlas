
import { WRITE_HEADERS, getJSON, readJSON } from './config.js';
import * as M from './alerts-model.js';

export const API = 'api/v2/admin/alerts';

const list = (v) => (Array.isArray(v) ? v : []);
export const clone = (v) => JSON.parse(JSON.stringify(v ?? null));

export function normalise(body) {
  const b = body && typeof body === 'object' ? body : {};
  const doc = b.doc && typeof b.doc === 'object' ? b.doc : {};
  return {
    ...b,
    doc: {
      ...doc,
      rules: list(doc.rules).filter((r) => r && typeof r === 'object'),
      destinations: list(doc.destinations).filter((d) => d && typeof d === 'object'),
      digest: doc.digest && typeof doc.digest === 'object' ? doc.digest : {},
    },
    stamp: b.stamp ?? null,
    status: b.status && typeof b.status === 'object' ? b.status : {},
    states: M.stateList(b.states),
  };
}

export { getJSON };

export async function postJSON(url, payload) {
  const res = await fetch(url, { method: 'POST', headers: WRITE_HEADERS, body: JSON.stringify(payload ?? {}) });
  const body = await readJSON(res);
  return { ok: res.ok, status: res.status, body, why: body?.error || `${res.status} ${res.statusText}` };
}

export const ALERTS = { body: null, error: '' };

const listeners = new Set();
export function listen(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}
function tellAll(changed) {
  for (const fn of [...listeners]) {
    try { fn(changed); } catch (err) { console.error(err); }
  }
}

const shownStatus = (b) => JSON.stringify([b.status.enabled, b.status.on, b.status.held ?? null, b.status.suspended ?? null]);

let inflight = null;
export function read({ fresh = false } = {}) {
  if (inflight) return fresh ? inflight.then(() => read({ fresh: true })) : inflight;
  inflight = (async () => {
    let body = null;
    try { body = normalise(await getJSON(API)); ALERTS.error = ''; } catch (err) { ALERTS.error = err.message || String(err); }
    const was = ALERTS.body;
    const changed = Boolean(body) && (!was || body.stamp !== was.stamp || shownStatus(body) !== shownStatus(was));
    if (body) ALERTS.body = body;
    inflight = null;
    tellAll(changed);
    return changed;
  })();
  return inflight;
}

export const CONFLICT = Symbol('conflict');

export async function save(change) {
  if (!ALERTS.body) await read();
  if (!ALERTS.body) return { ok: false, status: 0, body: null, why: ALERTS.error };
  const doc = clone(ALERTS.body.doc);
  const said = change(doc);
  if (said === CONFLICT) {
    await read({ fresh: true });
    return { ok: false, status: 409, body: null, why: 'changed elsewhere since it was opened' };
  }
  if (said === false) return { ok: true, status: 0, body: null, why: '', unchanged: true };
  doc.destinations = list(doc.destinations).map(({ secret_bound: _bound, ...d }) => d);
  const r = await postJSON(API, { doc, expect: ALERTS.body.stamp });
  if (r.ok || r.status === 409 || r.status === 403) await read({ fresh: true });
  return r;
}

export async function deliveries(limit = 50) {
  const body = await getJSON(`${API}/deliveries?limit=${limit}`);
  return M.newestFirst(Array.isArray(body) ? body : body?.deliveries);
}
