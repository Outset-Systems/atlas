
export const INTENT_WORD = {
  public: 'public', internal: 'internal', vpn: 'vpn', unset: 'not decided', outside: 'not ours',
};

export const INTENT_SAYS = {
  public: 'meant to answer from the internet',
  internal: 'meant to answer only inside',
  vpn: 'meant to answer over a VPN',
  unset: 'its domain is yours; what this name is meant to be is not decided',
  outside: "no entry covers it: somebody else's name",
};

export const serviceKey = (place, service) => `${place}\n${service}`;

export function serviceIntents(body) {
  const out = new Map();
  for (const row of body?.names || []) {
    for (const u of row?.uses || []) {
      if (!u || u.service == null) continue;
      const key = serviceKey(u.place, u.service);
      const byUrl = (u.via || []).includes('url');
      const had = out.get(key);
      if (had && (had.byUrl || !byUrl)) continue;
      out.set(key, { intent: row.intent, name: row.name, rule: row.rule || null, byUrl });
    }
  }
  return out;
}

export function intentMark(entry) {
  if (!entry) return null;
  const how = INTENT_SAYS[entry.intent] || '';
  return {
    word: INTENT_WORD[entry.intent] || entry.intent,
    title: `${how} · ${entry.name}${entry.rule && entry.rule !== entry.name ? `, by ${entry.rule}` : ''}`,
  };
}

export const SOON_DAYS = 14;

function plural(n, one, many = `${one}s`) { return `${n} ${n === 1 ? one : many}`; }

export function usesLabel(row) {
  if (!row?.uses?.length) return row?.wildcard ? 'a wildcard certificate' : 'certificate only';
  const places = [...new Set(row.uses.map((u) => u.place_name))];
  const services = row.uses.filter((u) => u.service).length;
  const what = services ? plural(services, 'service') : 'its check';
  const where = places.length > 2
    ? `${places.slice(0, 2).join(', ')} +${places.length - 2}` : places.join(', ');
  return `${what} on ${where}`;
}

export function usersTitle(row) {
  return (row?.uses || []).map((u) =>
    (u.service ? `${u.service} · ${u.place_name}` : `${u.place_name}'s check`)).join('\n');
}

export function certLabel(cert) {
  if (!cert || typeof cert.days !== 'number') return '';
  return cert.days < 0 ? `cert lapsed ${-cert.days}d ago` : `cert ${cert.days}d`;
}

export function certTone(cert) {
  if (!cert || typeof cert.days !== 'number') return '';
  return cert.days < 0 ? 'lapsed' : cert.days <= SOON_DAYS ? 'soon' : '';
}

export function namesCount(counts) {
  if (!counts?.total) return 'none';
  return [plural(counts.total, 'name'),
    ...['public', 'internal', 'vpn', 'unset', 'outside']
      .filter((k) => counts[k]).map((k) => `${counts[k]} ${INTENT_WORD[k]}`)].join(' · ');
}

export function namesNote(body) {
  const rows = body?.names || [];
  const counts = body?.counts || {};
  if (!rows.length) return 'empty';
  return counts.outside === counts.total ? 'undecided' : '';
}
