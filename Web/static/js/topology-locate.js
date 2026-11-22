
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
