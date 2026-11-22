
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

const postFile = (path, formData) =>
  call(path, { method: 'POST', headers: { 'X-Atlas-Write': '1' }, body: formData });

export const Editor = {
  ctx: null,
  data: null,
  stamp: null,
  overridden: {},
  loaded: false,

  repairs: null,

  section(key) { return this.ctx?.schema?.sections?.[key] || null; },
  sectionKeys() { return this.ctx?.schema?.order || []; },

  storeOf(key) { return this.section(key)?.store || 'dataset'; },

  entries(key) {
    if (this.storeOf(key) === 'maintenance' || (key === 'maintenance' && !this.ctx)) return this.repairs?.windows || [];
    const value = this.data?.[key];
    return Array.isArray(value) ? value : [];
  },

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

  async apply(ops, note = '', origin = '', { refresh = true } = {}) {
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

  async loadRepairs() {
    this.repairs = await call('maintenance');
    return this.repairs;
  },
  async saveRepairs(windows) {
    const clean = windows.map(({ state, occurrence_start, occurrence_end, ...w }) => w);
    const result = await post('maintenance', { windows: clean, expect: this.repairs?.stamp });
    return this.settle({ ...result, changed: [`saved ${clean.length} repair window(s)`] },
                       () => this.loadRepairs(), () => A.refreshSignals?.());
  },

  ackEvent(id, note) { return post(`events/${id}/ack`, { note }); },

  mapArt() { return call('map-art'); },
  uploadMapArt(file, name) {
    const form = new FormData();
    form.append('image', file);
    if (name) form.append('name', name);
    return postFile('map-art', form);
  },
  surveyMapArt(query) {
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
  fileSurvey(text) { return text.trimStart().startsWith('<') ? this.scan(text) : this.leases(text); },
  connections() { return call('connections'); },
  observe(key) { return post('discovery/connection', { key }); },
  review(key) { return post('connections/review', { key }); },
  async importPicks(key, picks, expect) {
    return this.settle(await post('connections/import', { key, picks, expect }));
  },
  decide(keys, action) { return post('discovery/decide', { keys, action }); },
  draftsFrom(keys) { return post('discovery/as-nodes', { keys }); },
  importCsv(csv) { return post('import/csv', { csv }); },
};

export default Editor;
