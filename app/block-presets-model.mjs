// SPDX-License-Identifier: GPL-3.0-or-later
// LES PRESETS DE BLOC EN LISTE (mockups/block-presets-list.html, validée le 2026-10-11) : la grammaire de la
// liste des VST — recherche, filtres, Recent, accordéon par instrument. Pur, testé (block-presets-model.test.mjs).
// Un preset de bloc = {id, name, inst, params, factory, default} (API /api/block-presets/<type>).

export const INSTS = ['guitar', 'bass', 'voice', 'drums', 'keys', 'any'];
export const INST_LB = { guitar: 'Guitar', bass: 'Bass', voice: 'Voice', drums: 'Drums', keys: 'Keys', any: 'Any instrument' };

// ce qui reste après la recherche, le périmètre (l'instrument de la lane | tous) et les cases Factory / Mine
export const filterPresets = (list, { inst = 'guitar', scope = 'inst', q = '', factory = true, mine = true, sig } = {}) => {
  const needle = String(q || '').trim().toLowerCase();
  return (list || []).filter(p => {
    if (!p) return false;
    if (scope === 'inst' && !(p.inst === inst || p.inst === 'any')) return false;
    if (p.factory ? !factory : !mine) return false;
    if (!needle) return true;
    const hay = (p.name + ' ' + (p.inst || '') + ' ' + (sig ? sig(p.params) : '')).toLowerCase();
    return hay.includes(needle);
  });
};

// l'accordéon : l'instrument de la lane d'abord, puis « any », puis les autres dans l'ordre des INSTS ;
// chaque groupe compte ses presets d'usine et les tiens
export const groupByInst = (shown, inst) => {
  const order = [inst, 'any', ...INSTS.filter(i => i !== inst && i !== 'any')];
  return order.map(i => {
    const items = shown.filter(p => (p.inst || 'any') === i);
    if (!items.length) return null;
    const mineN = items.filter(p => !p.factory).length;
    return { inst: i, label: INST_LB[i] || i, items, factory: items.length - mineN, mine: mineN };
  }).filter(Boolean);
};

// le défaut EFFECTIF pour cette lane : (type, inst) sinon (type, any)
export const effectiveDefault = (list, inst) =>
  ((list || []).find(p => p.default && p.inst === inst) || (list || []).find(p => p.default && p.inst === 'any') || {}).id || null;

// « Recent » : les derniers presets chargés sur CE rack, par type de bloc (localStorage, comme la liste des VST)
const KEY = btype => 'golem.bpRecent.' + btype;
export const loadRecent = (btype, store) => {
  try { const s = store || globalThis.localStorage; const v = JSON.parse((s && s.getItem(KEY(btype))) || '[]'); return Array.isArray(v) ? v : []; }
  catch (e) { return []; }
};
export const pushRecent = (btype, id, store, max = 6) => {
  const cur = loadRecent(btype, store).filter(x => x !== id);
  const next = [id, ...cur].slice(0, max);
  try { const s = store || globalThis.localStorage; s && s.setItem(KEY(btype), JSON.stringify(next)); } catch (e) { /* privé */ }
  return next;
};
export const pickRecent = (shown, ids) => (ids || []).map(id => shown.find(p => p.id === id)).filter(Boolean);
