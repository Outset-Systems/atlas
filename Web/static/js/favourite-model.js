/* A SERVICE AS A FAVOURITE: favourite-model.js (2026-11-21), with no DOM.

   Owner: "add a heart to each services' card that will let you add it to the
   favorites list in overview".

   OVERVIEW lists a service on one of two tiles when its link on the map says
   `favourite: internal` or `favourite: external` and has a URL
   (overview.py favourites; one address charted on two places is listed once).
   The heart on a service's card sets or clears that field. It does not ask
   which tile: an address only a machine inside the network could reach (a
   private address, a bare host name, a name under a private suffix) is
   `internal`, anything else `external`. The map editor's record of the
   service can still say otherwise.

   An address is one favourite however many places chart it, so "is it one"
   looks at every link with that URL, and clearing clears them all; marking
   writes only the link whose heart was pressed.

   Unit-tested by tests/test_favourite_model.mjs. */

const PRIVATE_SUFFIX = ['lan', 'local', 'internal', 'home', 'corp', 'test', 'localhost', 'arpa', 'intranet'];

/** The host of a URL, lower case, without port or brackets; '' when there is none. */
export function hostOf(url) {
  const m = String(url ?? '').trim().match(/^[a-z][a-z0-9+.-]*:\/\/(?:[^@/]*@)?(\[[^\]]+\]|[^/:?#]+)/i);
  return m ? m[1].replace(/^\[|\]$/g, '').toLowerCase() : '';
}

/** Which tile an address belongs on: 'internal' or 'external'. */
export function tileFor(url) {
  const h = hostOf(url);
  if (!h) return 'internal';
  const v4 = h.match(/^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/);
  if (v4) {
    const [a, b] = [Number(v4[1]), Number(v4[2])];
    const priv = a === 10 || a === 127 || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168)
      || (a === 169 && b === 254) || (a === 100 && b >= 64 && b <= 127);
    return priv ? 'internal' : 'external';
  }
  if (h.includes(':')) return /^(fc|fd|fe8|fe9|fea|feb)/.test(h) || h === '::1' ? 'internal' : 'external';
  const labels = h.split('.');
  if (labels.length === 1) return 'internal';               // a bare host name
  return PRIVATE_SUFFIX.includes(labels[labels.length - 1]) ? 'internal' : 'external';
}

const places = (data) => (Array.isArray(data?.nodes) ? data.nodes : []).filter((n) => n && typeof n.id === 'string');
const linksOf = (n) => (Array.isArray(n.links) ? n.links : []);
const same = (a, b) => String(a ?? '').trim() === String(b ?? '').trim();
const marked = (l) => l && (l.favourite === 'internal' || l.favourite === 'external');

/** The tile an address is listed on now ('internal' | 'external'), or '':
    any link with this URL that is marked makes it one. */
export function favouriteOf(data, url) {
  if (!String(url ?? '').trim()) return '';
  for (const n of places(data)) {
    const hit = linksOf(n).find((l) => marked(l) && same(l.url, url));
    if (hit) return hit.favourite;
  }
  return '';
}

/** What to send to make a service a favourite (`on` true) or not one.

    `data` is the map as it is on file; the service is the link of place
    `nodeId` with this label and URL. Marking writes that one link; clearing
    writes every place that marks the same address. Each op carries the
    place's whole `links` list, since a link has no id of its own. Returns []
    when there is nothing to change, or the service is not on the map as said. */
export function favouriteOps(data, nodeId, link, on, tile = '') {
  const url = String(link?.url ?? '').trim();
  if (!url) return [];
  const ops = [];
  if (on) {
    if (favouriteOf(data, url)) return [];
    const node = places(data).find((n) => n.id === nodeId);
    const links = node ? linksOf(node) : [];
    const at = links.findIndex((l) => l && same(l.url, url) && same(l.label, link.label));
    if (at < 0) return [];
    const kind = tile === 'internal' || tile === 'external' ? tile : tileFor(url);
    ops.push({ op: 'upsert', section: 'nodes', id: node.id,
      body: { links: links.map((l, i) => (i === at ? { ...l, favourite: kind } : l)) } });
    return ops;
  }
  for (const node of places(data)) {
    const links = linksOf(node);
    if (!links.some((l) => marked(l) && same(l.url, url))) continue;
    ops.push({ op: 'upsert', section: 'nodes', id: node.id,
      body: { links: links.map((l) => {
        if (!(marked(l) && same(l.url, url))) return l;
        const { favourite, ...rest } = l;
        return rest;
      }) } });
  }
  return ops;
}
