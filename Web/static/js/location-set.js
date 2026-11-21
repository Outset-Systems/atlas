/* SAYING WHERE A THING STANDS, the one box (2026-11-20; owner: "add a way to
   add locations. maybe a button in the node view, or hardware view to set/add
   location for stuff", "maybe you can also add a location in the wiring
   section too").

   `setLocation({node: id} | {rack: id})` is asked by NODES' ⋯ menu, by
   HARDWARE's Location tool and by WIRING's. It reads the map as it is on
   file (the editor's store), finds the record that decides where the thing
   stands (location-set-model.js: a rack for what is in one, the host for a
   guest), and asks for one name: a location the map already has, picked from
   the list, or a new one typed in. Typing a new name is how a location is
   added; nothing else has to exist first. Blank puts it back at the map's
   default location.

   It is a <dialog>, so it stands over whatever scene or view asked for it,
   holds the keyboard, and closes on Escape; its keys never reach the map.
   Resolves true when something was saved. */

import { A, CFG, canAdminWrite, esc } from './config.js';
import { knownLocations, locationOps, locationTarget } from './location-set-model.js';

/** The Desk's gate: an admin, on an Atlas that takes changes. */
export const mayLocate = () => canAdminWrite() && document.body.dataset.editable === '1';
export const LOCATE_WHY = 'Off here: setting a location needs an admin, on an Atlas that takes changes.';

const fallback = () => CFG.THEME?.text?.rack_location || '';

let box = null;
let done = null;       // the open ask's resolve
let state = null;      // {store, target}

function build() {
  if (box) return box;
  box = document.createElement('dialog');
  box.className = 'loc-box';
  box.setAttribute('aria-labelledby', 'loc-title');
  box.innerHTML = `
    <form method="dialog" class="loc-form" id="loc-form">
      <div class="loc-title" id="loc-title">LOCATION</div>
      <div class="loc-what" id="loc-what"></div>
      <div class="loc-note" id="loc-note" hidden></div>
      <label class="rel-add-field"><span>Where it stands</span>
        <input id="loc-name" class="dir-input" type="text" maxlength="60" autocomplete="off"
               spellcheck="false" list="loc-known" placeholder="Home office"></label>
      <datalist id="loc-known"></datalist>
      <div class="sp-hint">Pick a location the map has, or type a new one to add it. Blank is the map's default location.</div>
      <div class="loc-msg" id="loc-msg" role="status"></div>
      <div class="loc-acts">
        <button class="sp-btn sp-btn-go" id="loc-save" type="submit" value="save">Save</button>
        <button class="sp-btn" id="loc-cancel" type="button">Cancel</button>
      </div>
    </form>`;
  document.body.append(box);
  const q = (id) => box.querySelector(`#${id}`);
  // the map's keys (arrows, letters, Escape closing a scene) stop here
  box.addEventListener('keydown', (e) => e.stopPropagation());
  box.addEventListener('close', () => finish(false));
  q('loc-cancel').addEventListener('click', () => box.close());
  q('loc-form').addEventListener('submit', (e) => { e.preventDefault(); save(); });
  return box;
}

function finish(saved) {
  const resolve = done;
  done = null;
  state = null;
  resolve?.(saved);
}

const q = (id) => box.querySelector(`#${id}`);

function whatWords(t) {
  const at = `<b>${esc(t.current || 'no location')}</b>`;
  if (t.kind === 'rack' && !t.via) return `${esc(t.name)} stands at ${at}.`;
  return `${esc(t.asked)} stands at ${at}.`;
}

function noteWords(t) {
  if (t.via === 'host' && t.kind === 'rack') {
    return `${t.asked} runs on ${t.host}, which is in ${t.name}. This moves the whole rack, and everything in it.`;
  }
  if (t.via === 'host') return `${t.asked} runs on ${t.host}. This says where ${t.host} stands.`;
  if (t.via === 'rack') return `${t.asked} is in ${t.name}. This moves the whole rack, and everything in it.`;
  if (t.kind === 'rack') return 'Everything in the rack goes with it.';
  return '';
}

async function save() {
  if (!state) return;
  const { store, target } = state;
  const name = q('loc-name').value;
  const ops = locationOps(store.data, target, name);
  if (!ops.length) { box.close(); return; }
  const go = q('loc-save');
  go.disabled = true;
  q('loc-msg').textContent = '';
  const said = name.trim().replace(/\s+/g, ' ');
  try {
    await store.apply(ops, said
      ? `${target.name} stands at ${said} (Location)`
      : `${target.name} back at the default location (Location)`);
    const resolve = done;
    done = null;
    state = null;
    box.close();
    A.showToast?.(said ? `${target.name} is at ${said}.` : `${target.name} is back at the default location.`);
    resolve?.(true);
  } catch (err) {
    q('loc-msg').textContent = `Not saved: ${err.message || err}`;
  } finally {
    go.disabled = false;
  }
}

/** Ask where a place (`{node}`) or a rack (`{rack}`) stands, and save the
    answer. Resolves true when the map was changed. */
export async function setLocation(ask) {
  if (!mayLocate()) { A.showToast?.(LOCATE_WHY); return false; }
  if (done) return false;   // one ask at a time
  let store;
  try {
    ({ Editor: store } = await import('./editor/index.js'));
    await store.load();
  } catch (err) {
    A.showToast?.(`The map could not be read: ${err.message || err}`);
    return false;
  }
  const target = locationTarget(store.data, fallback(), ask);
  if (target.kind === 'none') {
    A.showToast?.(target.why === 'guest'
      ? `${target.asked} is a guest with no host on the map. Give it a host, and it is where the host is.`
      : 'That is not on the map any more.');
    return false;
  }
  build();
  state = { store, target };
  q('loc-what').innerHTML = whatWords(target);
  const note = noteWords(target);
  q('loc-note').textContent = note;
  q('loc-note').hidden = !note;
  q('loc-name').value = target.written;
  q('loc-name').placeholder = fallback() || 'Home office';
  q('loc-known').innerHTML = knownLocations(store.data, fallback())
    .map((n) => `<option value="${esc(n)}"></option>`).join('');
  q('loc-msg').textContent = '';
  const asked = new Promise((resolve) => { done = resolve; });
  box.showModal();
  q('loc-name').select();
  return asked;
}
