/* What a place's stamp says, in words. Pure: no DOM, so node can test it.

   The server writes the stamp (provenance.py) and is the only one who may.
   This file only reads it back to the person at the Desk. */

/** 'checked' | 'changed' | 'unchecked' | 'unknown' (charted before the map kept the record).
    'changed' is a place a person checked that has changed since: the review
    stands for what was there, and what changed is waiting for a look. The rule
    is the server's (`provenance.settled`), so the Desk lists exactly the places
    a cloud token is not being shown: the mark an import leaves, a stamp whose
    change is later than its review, or one that cannot say when it was reviewed. */
export function standing(entry) {
  const mark = entry && entry.provenance;
  if (!mark || typeof mark !== 'object' || typeof mark.reviewed !== 'boolean') return 'unknown';
  if (!mark.reviewed) return 'unchecked';
  const reviewed = String(mark.reviewed_at || '');
  if (mark.changed_since_review === true || !reviewed || String(mark.changed_at || '') > reviewed) return 'changed';
  return 'checked';
}

const day = (stamp) => String(stamp || '').slice(0, 10);

function by(who, when) {
  if (who && when) return `by ${who} on ${day(when)}`;
  if (when) return `on ${day(when)}`;
  return who ? `by ${who}` : '';
}

/** One or two sentences for the form's head and a row's tooltip. */
export function sentence(entry) {
  const mark = (entry && entry.provenance) || {};
  const state = standing(entry);
  const parts = [];
  if (mark.charted_at || mark.charted_by) {
    const from = mark.source && mark.source !== 'hand' ? `, from ${mark.source}` : '';
    parts.push(`Charted ${by(mark.charted_by, mark.charted_at)}${from}.`);
  } else {
    parts.push('Charted before the map kept a record of who and when.');
  }
  if (state === 'checked' || state === 'changed') {
    parts.push(`Checked ${by(mark.reviewed_by, mark.reviewed_at)}`.trim() + '.');
    if (state === 'changed') parts.push('It has changed since, and nobody has looked at what changed.');
  } else {
    parts.push('Not yet checked by a person.');
  }
  return parts.join(' ');
}

/** The line above the table: how many are waiting, and why. */
export function waiting(entries, plural = 'places') {
  const pending = entries.filter((e) => standing(e) !== 'checked');
  if (!pending.length) return '';
  const unknown = pending.filter((e) => standing(e) === 'unknown').length;
  const changed = pending.filter((e) => standing(e) === 'changed').length;
  const imported = pending.length - unknown - changed;
  const n = pending.length;
  let head = `${n} of ${entries.length} ${plural} ${n === 1 ? 'has' : 'have'} not been checked by a person.`;
  if (n === entries.length) {
    head = n === 1 ? 'The one entry here has not been checked by a person.'
      : `None of the ${n} ${plural} here has been checked by a person.`;
  }
  // a changed place WAS checked, so "has not been checked" would be untrue of it
  if (changed) head = `${n} of ${entries.length} ${plural} ${n === 1 ? 'is' : 'are'} waiting for a person to look.`;
  const why = [];
  if (imported) why.push(`${imported} came from an import`);
  if (changed) why.push(`${changed} changed after being checked`);
  if (unknown) why.push(`${unknown} ${unknown === 1 ? 'was' : 'were'} charted before the map kept this record`);
  return `${head} ${why.join(', ')}.`;
}
