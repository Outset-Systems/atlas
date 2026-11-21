/* WIRING, where the selected place stands (2026-11-20; owner: "maybe you can
   also add a location in the wiring section too"): one more button in the
   panel's ARRANGE AND EXPORT, for whoever may write. It asks the one box
   every view opens (location-set.js) about the card selected; a card in a
   rack is answered by its rack, and a guest by its host, as the box says.
   The canvas is drawn again by the map's own refresh after a save.

   Offered and taken away exactly as "Where does it break?" is
   (topology-diagnose.js): on the view opening and on every fresh map. */

import { A, canAdminWrite } from './config.js';
import { T, t, addTool } from './topology-state.js';
import { setLocation } from './location-set.js';

const mayAsk = () => canAdminWrite() && document.body.dataset.editable === '1';

let removeTool = null;

function press() {
  const id = T.selected;
  const th = id ? T.shown?.byId.get(id) : null;
  if (!th) { A.showToast?.(t('tp_loc_pick')); return; }
  if (th.type !== 'place') { A.showToast?.(t('tp_loc_not_place')); return; }
  setLocation({ node: id });
}

function syncTool() {
  if (mayAsk()) {
    if (!removeTool) removeTool = addTool({ id: 'location', label: t('tp_loc'), title: t('tp_loc_title'), onPress: press });
    return;
  }
  if (removeTool) { removeTool(); removeTool = null; }
}

addEventListener('atlas:view', (e) => {
  if (e.detail?.view === 'topology') requestAnimationFrame(syncTool);
});
addEventListener('atlas:data', () => { if (T.up) requestAnimationFrame(syncTool); });
if (A.VIEW === 'topology' || document.body.dataset.view === 'topology') requestAnimationFrame(syncTool);
