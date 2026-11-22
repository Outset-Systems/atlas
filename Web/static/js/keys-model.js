
function typing(ev) {
  return /^(INPUT|TEXTAREA|SELECT)$/.test(ev.tag || '') || !!ev.editable;
}

function chord(ev) {
  return !!(ev.ctrl || ev.meta || ev.alt);
}

export function regionKey(ev, state) {
  if (!state.region) return null;
  if (typing(ev) || chord(ev)) return null;
  if (state.scene) return null;
  switch (ev.key) {
    case 'Escape':
      if (state.glass) return null;
      return state.card ? 'close-card' : 'leave-region';
    case 'Home': case 'h':
      return 'leave-to-map';
    case 'd': case 's':
      return 'swallow';
    default:
      return null;
  }
}

export function mapKey(ev, state) {
  if (typing(ev)) return null;
  if (ev.key === 'Escape') return 'escape';
  if (chord(ev)) return null;
  if (ev.key === '/') return 'palette';
  if (state.scene || state.away) return ev.key === 'm' ? 'drawer' : null;
  switch (ev.key) {
    case 'ArrowLeft': return 'pan-left';
    case 'ArrowRight': return 'pan-right';
    case 'ArrowUp': return 'pan-up';
    case 'ArrowDown': return 'pan-down';
    case '+': case '=': return 'zoom-in';
    case '-': return 'zoom-out';
    case 'Home': case 'h': return 'home';
    case 'm': return 'drawer';
    case 'd': return 'descend';
    case 's': return 'ascend';
    case 'n': return 'net';
    case 'g': return 'decoys';
    default: return null;
  }
}

export function describe(e) {
  return {
    key: e.key,
    tag: e.target?.tagName || '',
    editable: !!e.target?.isContentEditable,
    ctrl: e.ctrlKey, meta: e.metaKey, alt: e.altKey,
  };
}
