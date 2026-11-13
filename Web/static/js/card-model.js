/* Atlas — card-model.js: the working out behind the card a place opens, with
   no DOM and no imports, so tests/test_card_model.mjs can ask it questions in
   plain node. card.js reads the page, the config and the feed, asks this
   module, and writes the answer to the page. */

/** A week of one vital as the points of a polyline in a `w`×`h` box:
    `x,y x,y …`, one decimal each. `series` is `[[time, value], …]`; a sample
    whose value is not a number is left out, and values clamp to 0–100 (they
    are percentages, and one bad sample must not rescale the week). '' when
    fewer than two samples are left: one point is not a line. */
export function sparkPoints(series, w = 160, h = 40) {
  const pts = (series || []).filter((p) => Number.isFinite(p?.[1]));
  if (!(pts.length > 1)) return '';
  const t0 = pts[0][0], t1 = pts[pts.length - 1][0];
  const xs = (t) => ((t - t0) / Math.max(1, t1 - t0)) * w;
  const ys = (v) => h - (Math.min(100, Math.max(0, v)) / 100) * h;
  return pts.map((p) => `${xs(p[0]).toFixed(1)},${ys(p[1]).toFixed(1)}`).join(' ');
}

/** What is left of a scroll's path after the vault root, or null when the
    path is not under the root or there is no root. Case is ignored in the
    comparison; nothing else is trimmed, so the tail keeps its leading
    separator and its `.md`. */
export function scrollTail(scroll, root) {
  return root && scroll.toLowerCase().startsWith(root.toLowerCase()) ? scroll.slice(root.length) : null;
}

/** An Obsidian link for a scroll. The vault is the folder `root` names
    (Obsidian calls a vault by its folder's name) and the note is the rest of
    the path, without `.md`. With no root, or a scroll outside it, ask Obsidian
    to find the note by its absolute path instead. */
export function obsidianHref(scroll, root) {
  const tail = scrollTail(scroll, root);
  if (tail !== null) {
    const vault = root.replace(/[\\/]+$/, '').split(/[\\/]/).pop();
    const file = tail.replace(/^[\\/]+/, '').replace(/\\/g, '/').replace(/\.md$/i, '');
    if (vault && file) return `obsidian://open?vault=${encodeURIComponent(vault)}&file=${encodeURIComponent(file)}`;
  }
  return `obsidian://open?path=${encodeURIComponent(scroll)}`;
}

/** A service row's quiet second word: just the port when the service answers
    on its own place (by that place's address or its own name), else the host
    it answers at. `url` is the service's address with the scheme already
    taken off; `node` is the place the row is listed under ({id, ip}). Plain
    text: the caller escapes it. */
export function serviceMeta(url, node) {
  const h = url.replace(/\/.*$/, '');
  const [name, port] = h.split(':');
  const own = name === node.ip || name.split('.')[0].toLowerCase() === String(node.id).toLowerCase();
  return own ? (port ? `:${port}` : '') : h;
}
