
import { beginPage } from './visit-model.js';

function storage(name) {
  try { return window[name]; } catch { return null; }
}

if (document.body.dataset.demo === '1') beginPage(storage('localStorage'), storage('sessionStorage'));
