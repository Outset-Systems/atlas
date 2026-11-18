/* A VISIT TO THE DEMO STARTS CLEAN (owner, 2026-11-17). The rule is
   visit-model.js's; this runs it. atlas.js imports this file FIRST and it
   imports nothing that reads the browser's storage, so every module after it
   (the colour scheme, the views, the map's style) finds what a first visit
   finds. Only the look-only demo (`data-demo="1"`, views.py: the bundled map,
   never seeded): an Atlas with a map of its own keeps what its people chose. */

import { beginVisit } from './visit-model.js';

function storage(name) {
  try { return window[name]; } catch { return null; }   // a browser may refuse even the read
}

if (document.body.dataset.demo === '1') beginVisit(storage('localStorage'), storage('sessionStorage'));
