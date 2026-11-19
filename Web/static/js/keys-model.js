/* Atlas — keys-model.js: what a key on the map means, with no DOM.

   The map has two window-wide key handlers: the camera's (camera.js) and,
   while a region is open, the region's (regions.js, capture phase, first).
   Each decided for itself which keys it owned and what was in the way, and
   the 11-12 audit found five ways they disagreed with the rest of the page:

     Map 1  Escape in a region with a scene open left the region and kept the
            scene (the region never asked whether a scene was open).
     Map 4  In a region, Ctrl+S, Ctrl+D and Ctrl+H were swallowed as s, d, h.
     Map 5  The `-` key zoomed past a region's floor (it called the camera's
            own zoom, not the one the region wraps).
     Map 8  Map keys steered the camera behind an open scene.
     Map 9  `/` opened the palette from a dropdown, and with Ctrl or Alt held.

   So the decision lives here, once, as two pure functions the handlers call,
   and every case above has a node test (tests/test_keys_model.mjs). The
   browser pane cannot open a region at all (it runs no animation frames), so
   a walk could never have proved these.

   `ev` is {key, tag, editable, ctrl, meta, alt}; `state` is {region,
   scene, glass, card, away}. Both return an action name or null (not ours:
   let the key through). */

/** A key typed into a field, or one with a modifier held, is never the map's. */
function typing(ev) {
  return /^(INPUT|TEXTAREA|SELECT)$/.test(ev.tag || '') || !!ev.editable;
}

function chord(ev) {
  return !!(ev.ctrl || ev.meta || ev.alt);
}

/** The region's handler, which runs first while a region is open. */
export function regionKey(ev, state) {
  if (!state.region) return null;
  if (typing(ev) || chord(ev)) return null;               // Map 4
  // a scene over the region owns every key: its Escape goes through the
  // camera's handler (Map 1), and the region swallowing d or s in the
  // capture phase would take them from the scene too
  if (state.scene) return null;
  switch (ev.key) {
    case 'Escape':
      // the glass closes first, through the camera's Escape, then the card,
      // then the region
      if (state.glass) return null;
      return state.card ? 'close-card' : 'leave-region';
    case 'Home': case 'h':
      return 'leave-to-map';
    case 'd': case 's':
      return 'swallow';                                   // the sky and the depths are the main map's
    default:
      return null;
  }
}

/** The camera's handler. */
export function mapKey(ev, state) {
  if (typing(ev)) return null;
  if (ev.key === 'Escape') return 'escape';               // reachable from everywhere
  if (chord(ev)) return null;                             // Map 9: no palette on Ctrl+/ or Alt+/
  if (ev.key === '/') return 'palette';
  // a scene or a view over the map: nothing steers the camera behind it (Map 8);
  // the Index (m) still opens over either, as it always did
  if (state.scene || state.away) return ev.key === 'm' ? 'drawer' : null;
  switch (ev.key) {
    case 'ArrowLeft': return 'pan-left';
    case 'ArrowRight': return 'pan-right';
    case 'ArrowUp': return 'pan-up';
    case 'ArrowDown': return 'pan-down';
    case '+': case '=': return 'zoom-in';
    case '-': return 'zoom-out';                          // through A.zoomAt, so a region's floor holds (Map 5)
    case 'Home': case 'h': return 'home';
    case 'm': return 'drawer';
    case 'd': return 'descend';
    case 's': return 'ascend';
    case 'n': return 'net';
    case 'g': return 'decoys';
    default: return null;
  }
}

/** The fields of a KeyboardEvent the two functions read. */
export function describe(e) {
  return {
    key: e.key,
    tag: e.target?.tagName || '',
    editable: !!e.target?.isContentEditable,
    ctrl: e.ctrlKey, meta: e.metaKey, alt: e.altKey,
  };
}
