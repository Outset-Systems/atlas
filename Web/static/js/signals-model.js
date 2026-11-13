/* Atlas — signals-model.js: what a live feed adds up to, with no DOM and no
   imports, so tests/test_signals_model.mjs can ask it questions in plain
   node. signals.js reads the feed and the markers, asks this module, and
   writes the classes, the colours and the colophon. */

/** Count the faults among the places drawn. `ids` are the drawn places in the
    order they are drawn; `feedNodes` is the feed's word on each
    (`{ id: {state, cause} }`). `dark` counts the places that are down and are
    their own cause, `caused` the ones down behind something else, and
    `darkIds` names the first kind, in order. Only `down` is counted. */
export function tally(ids, feedNodes) {
  const nodes = feedNodes || {};
  let dark = 0;            // faults that are their own cause
  let caused = 0;          // faults explained by one of those
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

/** The colophon's warning, or '' when there is nothing to warn of. It counts
    CAUSES, not craters: one dark place is named (`firstName`), several are
    counted, and the places behind them follow as a clause. */
export function colophonText(dark, caused, firstName) {
  if (dark > 0) {
    // "it" or "them" follows the number of CAUSES, not of consequences:
    // one dead hypervisor with six vassals behind *it*, not behind *them*.
    const behind = caused
      ? ` — ${caused} place${caused === 1 ? '' : 's'} behind ${dark === 1 ? 'it' : 'them'}`
      : '';
    return dark === 1
      ? `⚠ ${firstName} has gone dark${behind}`
      : `⚠ ${dark} places are dark${behind}`;
  }
  if (caused > 0) {
    // every fault is explained by something that is no longer faulted —
    // rare, but saying nothing at all would be wrong
    return `⚠ ${caused} place${caused === 1 ? '' : 's'} still unreachable`;
  }
  return '';
}
