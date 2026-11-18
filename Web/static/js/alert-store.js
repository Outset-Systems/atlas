/* THE ALERTS DOCUMENT, read once and shared (2026-11-14).

   Alerts are set up in two places since 2026-11-14 (owner: "i wanted it built
   into the node view"; "put destinations in settings › alerts"): the rules
   are made where their target is, in NODES (alert-rules.js), and where word
   goes, the daily digest and the log are Settings › Alerts (alert-setup.js).
   Both read and write the one document `GET/POST api/v2/admin/alerts`, so
   they hold it here, once: two copies would each post under a stamp the
   other had already moved, and every save would come back 409.

   A save is a CHANGE, not a copy: the caller gets the latest document read,
   makes its one change to a clone, and posts it under that document's stamp.
   A save from another browser in between still comes back 409 (the stamp
   moved), and is read again; a save from the other surface in this page
   does not, because it was read back before this one began.

   Admins only: the routes refuse anyone else, and nothing here is drawn
   without `A.MAY_ALERTS` (views.js). */

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

export { getJSON };   // config.js holds it

export async function postJSON(url, payload) {
  const res = await fetch(url, { method: 'POST', headers: WRITE_HEADERS, body: JSON.stringify(payload ?? {}) });
  const body = await readJSON(res);
  return { ok: res.ok, status: res.status, body, why: body?.error || `${res.status} ${res.statusText}` };
}

/** What is known: the document as last read (`body`), or why it could not be. */
export const ALERTS = { body: null, error: '' };

const listeners = new Set();
/** Call `fn(changed)` after every read; returns the way to stop. */
export function listen(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}
function tellAll(changed) {
  for (const fn of [...listeners]) {
    try { fn(changed); } catch (err) { console.error(err); }
  }
}

/** What changes the drawing besides the document: on or off, and which
    places and rules the alerts cannot reach (the map moves these). */
const shownStatus = (b) => JSON.stringify([b.status.enabled, b.status.on, b.status.held ?? null, b.status.suspended ?? null]);

let inflight = null;
/** Read the document. Calls that land while one is reading share it; a
    `fresh` read (after a save) never joins one that began before it, or the
    save would be read back as it was before. True when the document, or what
    is drawn from its status, changed since the last read. */
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

/** What a change returns when the entry it edits is no longer as the form
    was opened on it (another admin saved it, or removed it): nothing is
    posted, the document is read again, and the answer is a 409, as the
    server gives for a stale stamp. */
export const CONFLICT = Symbol('conflict');

/** Make one change and post it: `change(doc)` edits a clone of the latest
    document read, and returns false for "nothing to do" or CONFLICT.
    Answers {ok, status, body, why} as the server gave it; after a save or a
    409 the document has been read again. */
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
  // what the server computes is not posted back: a destination's binding
  doc.destinations = list(doc.destinations).map(({ secret_bound: _bound, ...d }) => d);
  const r = await postJSON(API, { doc, expect: ALERTS.body.stamp });
  if (r.ok || r.status === 409 || r.status === 403) await read({ fresh: true });
  return r;
}

/** The deliveries log, newest first. */
export async function deliveries(limit = 50) {
  const body = await getJSON(`${API}/deliveries?limit=${limit}`);
  return M.newestFirst(Array.isArray(body) ? body : body?.deliveries);
}
