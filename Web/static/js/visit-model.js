/* A VISIT TO THE DEMO STARTS CLEAN (owner, 2026-11-17: "guest access should
   reset on every visit"). No DOM here, so node can test it
   (tests/test_visit_model.mjs); visit.js runs it, first of all.

   An Atlas remembers a person's choices in their browser: the view they were
   on, the colours, the map's style, markers and rack slots dragged but not
   saved, pins, NODES' filters and sort, what is folded, the topology's panel.
   On a map that is someone's own that is the point. On the look-only demo it
   is not: a stranger who comes back a week later, or the next person at the
   same screen, met whatever the last visit left, and a demo that opens
   differently each time explains itself badly.

   So on the demo, the first page of a visit forgets every one of those. A
   VISIT is one tab's session (sessionStorage's own lifetime): a reload, or a
   link followed inside the demo, is the same visit and keeps what was chosen
   in it; a new tab, or the browser opened again, is a new one. What the
   address says (`?view=`, a place, a region) is not remembered state and
   still opens what it names.

   Every key an Atlas stores begins `atlas-` or `atlas.`; nothing else in the
   origin's storage is touched. */

/** The mark a visit leaves in its own tab's session. */
export const VISIT_KEY = 'atlas.visit';

/** A key an Atlas stored. */
export const OURS = /^atlas[.-]/;

/** Forget what earlier visits left, once per visit. `local` and `session`
    are the two Storages (either may be missing or may throw, as in a private
    window). Returns the keys forgotten, [] when this visit has already
    begun. When the session cannot hold the mark the visit cannot be told
    from a new one, and every page forgets: the safe way round for a demo. */
export function beginVisit(local, session) {
  let begun = false;
  try { begun = !!session && session.getItem(VISIT_KEY) !== null; } catch { begun = false; }
  if (begun) return [];
  const gone = [];
  try {
    for (let i = 0; i < local.length; i++) {
      const key = local.key(i);
      if (typeof key === 'string' && OURS.test(key)) gone.push(key);
    }
    for (const key of gone) local.removeItem(key);
  } catch { /* storage closed to us: there is nothing kept to forget */ }
  try { session.setItem(VISIT_KEY, '1'); } catch { /* no mark: the next page forgets again */ }
  return gone;
}
