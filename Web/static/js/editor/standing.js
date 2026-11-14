/* What a place's stamp says, in words. Pure: no DOM, so node can test it.

   The rules moved to ../roster-model.js on 2026-11-13, so the Desk and NODES
   read one copy of them. This file stays as the Desk's name for them
   (tests/test_standing.mjs imports it). */

export { standing, sentence, waiting } from '../roster-model.js';
