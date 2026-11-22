
import { serviceKey } from './alerts-model.js';

const DAY = 86400000;

export function checkWhere(link, node) {
  if (!link || (link.check !== 'tcp' && link.check !== 'dns')) return '';
  const raw = typeof link.check_host === 'string' ? link.check_host.trim() : '';
  const host = raw || (link.check === 'tcp' && node && typeof node.ip === 'string' && node.ip !== '—' ? node.ip : '');
  if (!host) return '';
  return link.check === 'tcp' && Number.isInteger(link.check_port) ? `${host}:${link.check_port}` : host;
}

const dayOf = (iso) => {
  const t = Date.parse(`${String(iso || '').slice(0, 10)}T00:00:00Z`);
  return Number.isNaN(t) ? null : t;
};

function hostOf(url) {
  if (typeof url !== 'string' || !/^https?:\/\//i.test(url)) return '';
  try { return new URL(url).hostname.toLowerCase(); } catch { return ''; }
}

function covers(name, tls, asked) {
  const want = String(name || '').trim().toLowerCase();
  if (!want) return false;
  const names = (Array.isArray(tls?.names) ? tls.names : []).map((n) => String(n).toLowerCase());
  if (names.includes(want)) return true;
  if (!asked) return false;
  if (asked === want) return true;
  if (want.startsWith('*.')) {
    const rest = want.slice(2);
    return asked.endsWith(`.${rest}`) && !asked.slice(0, -rest.length - 1).includes('.');
  }
  return false;
}

export function seenFor(cert, data, services) {
  if (!cert || cert.kind !== 'tls' || !services || typeof services !== 'object') return null;
  let best = null;
  for (const node of Array.isArray(data?.nodes) ? data.nodes : []) {
    if (!node || typeof node.id !== 'string') continue;
    for (const link of Array.isArray(node.links) ? node.links : []) {
      if (!link || typeof link !== 'object') continue;
      const tls = services[serviceKey(node.id, link)]?.tls;
      if (!tls || typeof tls.expires !== 'string') continue;
      const asked = hostOf(link.check_host) || hostOf(link.url);
      if (!covers(cert.name, tls, asked)) continue;
      const at = dayOf(tls.expires);
      if (at === null) continue;
      if (!best || at < best.at) {
        best = { at, expires: tls.expires, issuer: typeof tls.issuer === 'string' ? tls.issuer : '',
          via: `${link.label || ''} on ${node.name || node.id}` };
      }
    }
  }
  if (!best) return null;
  const charted = dayOf(cert.expires);
  const differs = charted === null || Math.abs(charted - best.at) >= DAY;
  return { expires: best.expires, issuer: best.issuer, via: best.via, differs };
}
