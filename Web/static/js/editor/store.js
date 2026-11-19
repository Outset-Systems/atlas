/* THE SURVEYOR'S DESK — the client half of the editing API.

   Deliberately not a state machine. Every form submit is one atomic write to
   the server, and the table redraws from what came back. The alternative —
   queueing operations in the browser and posting a batch — needs the client
   to reason about how its own pending inserts shift the positions of its own
   pending deletes, and that is a bug factory for a saving of one HTTP round
   trip on a LAN app.

   Undo is the change log, not a Discard button: the server journals every
   write and can put any of them back. That is strictly better than local
   pending state, because it survives a closed tab. */

import { A, WRITE_HEADERS, readJSON } from '../config.js';

const API = 'api/v2/admin';

export class EditorError extends Error {
  constructor(message, problems, status) {
    super(message);
    this.problems = problems || [message];
    this.status = status;
  }
}

async function call(path, options) {
  const res = await fetch(`${API}/${path}`, options);
  const body = await readJSON(res);
  if (!res.ok) {
    throw new EditorError(body?.error || `${res.status} ${res.statusText}`,
                          body?.problems, res.status);
  }
  return body;
}

const post = (path, payload) =>
  call(path, { method: 'POST', headers: WRITE_HEADERS, body: JSON.stringify(payload ?? {}) });

/** Multipart, so a 20 MB render doesn't grow a third on the wire as base64.
    Content-Type is deliberately unset — the browser writes the boundary. */
const postFile = (path, formData) =>
  call(path, { method: 'POST', headers: { 'X-Atlas-Write': '1' }, body: formData });

export const Editor = {
  /** the field catalogue and this deployment's posture */
  ctx: null,
  /** the dataset as it is on disk — NOT the overlaid copy the map renders */
  data: null,
  /** the version token every write is checked against */
  stamp: null,
  /** {section: [keys]} the layout overlays are currently overriding */
  overridden: {},
  loaded: false,

  /** windows + stamp for the maintenance store (see `storeOf`) */
  repairs: null,

  section(key) { return this.ctx?.schema?.sections?.[key] || null; },
  sectionKeys() { return this.ctx?.schema?.order || []; },

  /** Which backing store owns a section — "dataset" or its own endpoint. */
  storeOf(key) { return this.section(key)?.store || 'dataset'; },

  entries(key) {
    // the repairs are their own store whether or not the catalogue has loaded:
    // NODES reads them (its menus' "maintenance mode" lines) on a page where
    // the Desk was never opened, and the dataset holds no windows (2026-11-15)
    if (this.storeOf(key) === 'maintenance' || (key === 'maintenance' && !this.ctx)) return this.repairs?.windows || [];
    const value = this.data?.[key];
    return Array.isArray(value) ? value : [];
  },

  /** True when this instance can actually be written to at all. */
  writable() { return Boolean(this.ctx?.writable); },

  async load() {
    this.ctx = await call('context');
    await this.reload();
    this.loaded = true;
    return this.ctx;
  },

  async reload() {
    const body = await call('dataset');
    this.data = body.data;
    this.stamp = body.stamp;
    this.overridden = body.overridden || {};
    return this.data;
  },

  /** After a write that landed: re-read the editor's copy and the map's.
      A re-read that fails must not fail the write (2026-11-19, the 11-12
      audit's Scenes 12: it ran inside the same promise, so a saved change
      reported as a failed save). The result says `unread: true` instead,
      and the stamp stays the one from before the write, so the next write
      is refused as stale (the Desk re-reads on that refusal) rather than
      applied over a copy that no longer matches the file. Said here, once,
      for every caller (the Desk, NODES, WIRING, the wizard). */
  async settle(result, reread = () => this.reload(), refresh = () => A.refreshData?.()) {
    try {
      await reread();
      await refresh();
      return result;
    } catch {
      A.showToast?.('Saved, but the map could not be read again. Reload to see the change.');
      return { ...result, unread: true };
    }
  },

  /** Apply operations, then refresh both the editor's copy and the map's.
      `refresh: false` (a long run saved in parts, 2026-11-15) only takes the
      new stamp: the caller refreshes once after its last part, and must,
      since `data` is the copy from before. */
  async apply(ops, note = '', origin = '', { refresh = true } = {}) {
    // `origin` names an import ('survey'): what it writes starts unreviewed
    const result = await post('ops', { ops, expect: this.stamp, note, origin });
    if (!refresh) { this.stamp = result.stamp; return result; }
    return this.settle(result);
  },

  upsert(section, id, body) {
    const op = { op: 'upsert', section, body };
    if (id !== null && id !== undefined) op.id = id;
    return this.apply([op]);
  },
  upsertAt(section, index, body) {
    return this.apply([{ op: 'upsert', section, index, body }]);
  },
  insert(section, body) { return this.apply([{ op: 'insert', section, body }]); },
  remove(section, ref, cascade) {
    return this.apply([{ op: 'delete', section, ...ref, cascade: Boolean(cascade) }]);
  },

  /* ── store-agnostic mutations ──────────────────────────────────────────
     The Desk renders every section from one catalogue and must not know
     which of them is the dataset. These three dispatch on `storeOf`, so a
     section that lives in its own file gets the same table and form for
     free — which is the entire reason the catalogue exists. */

  async saveEntry(section, ref, body) {
    if (this.storeOf(section) !== 'maintenance') {
      return ref
        ? (ref.id !== undefined ? this.upsert(section, ref.id, body)
                                : this.upsertAt(section, ref.index, body))
        : this.insert(section, body);
    }
    const windows = [...this.entries(section)];
    if (!ref) windows.push(body);
    else {
      const i = ref.id !== undefined
        ? windows.findIndex((w) => w.id === ref.id) : ref.index;
      windows[i] = { ...windows[i], ...body };
    }
    return this.saveRepairs(windows);
  },

  async removeEntry(section, ref, cascade) {
    if (this.storeOf(section) !== 'maintenance') return this.remove(section, ref, cascade);
    const windows = this.entries(section).filter((w, i) =>
      (ref.id !== undefined ? w.id !== ref.id : i !== ref.index));
    return this.saveRepairs(windows);
  },

  /* ── THE REPAIRS ───────────────────────────────────────────────────── */
  async loadRepairs() {
    this.repairs = await call('maintenance');
    return this.repairs;
  },
  async saveRepairs(windows) {
    // strip the annotations the server added on read; they are derived
    const clean = windows.map(({ state, occurrence_start, occurrence_end, ...w }) => w);
    const result = await post('maintenance', { windows: clean, expect: this.repairs?.stamp });
    // the same rule as a dataset write: a failed re-read leaves the old stamp
    return this.settle({ ...result, changed: [`saved ${clean.length} repair window(s)`] },
                       () => this.loadRepairs(), () => A.refreshSignals?.());
  },

  /* ── THE ANNALS ────────────────────────────────────────────────────── */
  ackEvent(id, note) { return post(`events/${id}/ack`, { note }); },

  /* ── The base render ───────────────────────────────────────────────── */
  mapArt() { return call('map-art'); },
  uploadMapArt(file, name) {
    const form = new FormData();
    form.append('image', file);
    if (name) form.append('name', name);
    return postFile('map-art', form);
  },
  surveyMapArt(query) {
    // THE REAL-WORLD SURVEY (2026-08-16) — lives here with its map-art
    // siblings so every api/admin/map-art* call shares one client and one
    // refusal shape
    return post('map-art/survey', { query });
  },
  deleteMapArt(name) {
    return call(`map-art/${encodeURIComponent(name)}`,
                { method: 'DELETE', headers: { 'X-Atlas-Write': '1' } });
  },

  dependents(section, id) {
    return call(`dependents?section=${encodeURIComponent(section)}&id=${encodeURIComponent(id)}`);
  },

  revisions(limit = 40) { return call(`revisions?limit=${limit}`); },
  async revert(id) {
    return this.settle(await post(`revisions/${id}/revert`));
  },

  discovery() { return call('discovery'); },
  scan(nmapXml) { return post('discovery/scan', { nmap_xml: nmapXml }); },
  leases(text) { return post('discovery/leases', { leases: text }); },
  /** nmap XML or a DHCP lease file, told apart by the first character: XML
      opens with `<`, no lease format does. */
  fileSurvey(text) { return text.trimStart().startsWith('<') ? this.scan(text) : this.leases(text); },
  /** the systems Settings → Connections knows, and which are set up */
  connections() { return call('connections'); },
  /** what a connected system sees on the network now, filed into the survey */
  observe(key) { return post('discovery/connection', { key }); },
  /** a connection's review: every row it offers, annotated against the map */
  review(key) { return post('connections/review', { key }); },
  /** land the picked rows of a review, then re-read the map */
  async importPicks(key, picks, expect) {
    return this.settle(await post('connections/import', { key, picks, expect }));
  },
  decide(keys, action) { return post('discovery/decide', { keys, action }); },
  draftsFrom(keys) { return post('discovery/as-nodes', { keys }); },
  importCsv(csv) { return post('import/csv', { csv }); },
};

export default Editor;
