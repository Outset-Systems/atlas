
export function tally(ids, feedNodes) {
  const nodes = feedNodes || {};
  let dark = 0;
  let caused = 0;
  const darkIds = [];
  for (const id of ids || []) {
    const info = nodes[id];
    if (!info || !info.state || info.state === 'healthy') continue;
    if (info.state === 'down') {
      if (info.cause) caused++;
      else { dark++; darkIds.push(id); }
    }
  }
  return { dark, caused, darkIds };
}

export function colophonText(dark, caused, firstName) {
  if (dark > 0) {
    const behind = caused
      ? ` — ${caused} place${caused === 1 ? '' : 's'} behind ${dark === 1 ? 'it' : 'them'}`
      : '';
    return dark === 1
      ? `⚠ ${firstName} has gone dark${behind}`
      : `⚠ ${dark} places are dark${behind}`;
  }
  if (caused > 0) {
    return `⚠ ${caused} place${caused === 1 ? '' : 's'} still unreachable`;
  }
  return '';
}

export function colophonLook({ warning = '', silentNote = '', fallback = '' } = {}) {
  if (silentNote) return { text: silentNote, alarm: false, silent: true };
  if (warning) return { text: warning, alarm: true, silent: false };
  return { text: fallback, alarm: false, silent: false };
}
