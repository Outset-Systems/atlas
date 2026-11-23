
import { canAdminWrite, HEALTH_DOT } from './config.js';
import * as R from './roster-model.js';

export const STATES = ['healthy', 'degraded', 'down', 'maintenance', 'slumbering', 'unknown', 'unmanaged'];
export const DOT = HEALTH_DOT;
export const REPEATS = ['none', 'daily', 'weekly', 'monthly'];

export const COLUMNS = [
  ['state', 'nodes_col_state'], ['name', 'nodes_col_name'], ['zone', 'nodes_col_zone'],
  ['kind', 'nodes_col_kind'], ['addresses', 'nodes_col_addresses'], ['services', 'nodes_col_services'],
  ['confirmed_by', 'nodes_col_confirmed'], ['reviewed', 'nodes_col_reviewed'],
  ['maintenance', 'nodes_col_maintenance'], ['cert', 'nodes_col_cert'],
  ['collections', 'nodes_col_collections'],
];

export let store = null;
try { store = localStorage; } catch {   }

export const S = {
  roster: null,
  intents: new Map(),
  error: '',
  filter: { ...R.NO_FILTER },
  sort: R.readSort(store),
  saved: R.readSaved(store),
  selected: new Set(),
  shown: [],
  form: '',
  naming: false,
  arm: R.twoPress(),
  busy: false,
  msg: null,
  railShut: R.readRail(store),
  railMode: '',
  railRename: '',
  railArm: '',
  railRules: [],
  railFocus: '',
  railArmAt: 0,
  menu: null,
  scope: null,
  asked: null,
  dx: null,
  expanded: new Set(),
  win: null,
  cards: 200,
  events: null,
  shadow: null,
  thingsShown: [],
  eventsError: false,
};

export const el = {};

export const shared = { formEl: null, formFor: '', pendingWhileBusy: false };

export const hooks = {};

export const phone = () => document.body.classList.contains('phone');
export const mayWrite = () => canAdminWrite() && document.body.dataset.editable === '1';
export const menuOn = (kind, id) => S.menu?.kind === kind && S.menu.id === id;
export const dim = '<span class="nv-dim">—</span>';
export const blank = (v) => v === null || v === undefined || v === '';
