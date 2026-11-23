
import { A, CFG, canAdminWrite, esc } from './config.js';
import { knownLocations, locationOps, locationTarget } from './location-set-model.js';
import { premiseScope } from './premises.js';

export const mayLocate = () => canAdminWrite() && document.body.dataset.editable === '1';
export const LOCATE_WHY = 'Off here: setting a location needs an admin, on an Atlas that takes changes.';

const fallback = () => CFG.THEME?.text?.rack_location || '';

let box = null;
let done = null;
let state = null;

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

export async function setLocation(ask) {
  if (!mayLocate()) { A.showToast?.(LOCATE_WHY); return false; }
  if (done) return false;
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
  q('loc-known').innerHTML = knownLocations(store.data, fallback(), premiseScope())
    .map((n) => `<option value="${esc(n)}"></option>`).join('');
  q('loc-msg').textContent = '';
  const asked = new Promise((resolve) => { done = resolve; });
  box.showModal();
  q('loc-name').select();
  return asked;
}
