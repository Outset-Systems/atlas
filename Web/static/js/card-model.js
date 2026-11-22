
export function sparkPoints(series, w = 160, h = 40) {
  const pts = (series || []).filter((p) => Number.isFinite(p?.[1]));
  if (!(pts.length > 1)) return '';
  const t0 = pts[0][0], t1 = pts[pts.length - 1][0];
  const xs = (t) => ((t - t0) / Math.max(1, t1 - t0)) * w;
  const ys = (v) => h - (Math.min(100, Math.max(0, v)) / 100) * h;
  return pts.map((p) => `${xs(p[0]).toFixed(1)},${ys(p[1]).toFixed(1)}`).join(' ');
}

export function scrollTail(scroll, root) {
  return root && scroll.toLowerCase().startsWith(root.toLowerCase()) ? scroll.slice(root.length) : null;
}

export function obsidianHref(scroll, root) {
  const tail = scrollTail(scroll, root);
  if (tail !== null) {
    const vault = root.replace(/[\\/]+$/, '').split(/[\\/]/).pop();
    const file = tail.replace(/^[\\/]+/, '').replace(/\\/g, '/').replace(/\.md$/i, '');
    if (vault && file) return `obsidian://open?vault=${encodeURIComponent(vault)}&file=${encodeURIComponent(file)}`;
  }
  return `obsidian://open?path=${encodeURIComponent(scroll)}`;
}

export function serviceMeta(url, node) {
  const h = url.replace(/\/.*$/, '');
  const [name, port] = h.split(':');
  const own = name === node.ip || name.split('.')[0].toLowerCase() === String(node.id).toLowerCase();
  return own ? (port ? `:${port}` : '') : h;
}
