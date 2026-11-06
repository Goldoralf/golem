// SPDX-License-Identifier: GPL-3.0-or-later
// LE PÉDALIER, EN DONNÉES (extrait du Designer le 2026-09-16 — maquette « Designer allégé »).
//
// L'éditeur de pédalier a quitté le Designer pour la page Live : la grille de /live EST le pédalier,
// pavé par pavé, et on assigne là où on voit la pédale. Les fonctions qui le nourrissaient vivaient
// dans `page-designer.js` ; elles sont ici pour qu'il n'y en ait qu'UNE version, quel que soit l'appelant.
//
// Tout travaille sur un DOCUMENT de preset et n'écrit qu'une chose : `block.foot`. Les potards, les
// scènes et les lanes ne bougent jamais — assigner une pédale n'est pas régler un son.
import { laneBlocks, bid, ROLE_ICON } from './designer-model.js';
import { loopRows } from './designer-sheets.js';

//: ce qu'un tap peut AJOUTER puis poser (Rec et Click sont permanents, le looper ne se pose pas)
export const PB_SVC = ['backing-track', 'drums', 'sample', 'standard', 'tuner'];

// tous les blocs d'un document (lanes + services), les MÊMES objets : on écrit `foot` en place
export const allBlocksOf = doc => [...((doc || {}).lanes || []).flatMap(L => laneBlocks(L)),
  ...['gen', 'rec', 'arr'].flatMap(k => ((((doc || {}).config || {})[k] || {}).blocks) || [])]
  .filter(b => b && typeof b === 'object');

export const laneRoleOf = (doc, id) => {
  const L = ((doc || {}).lanes || []).find(x => x.id === id);
  return (L && L.role) || id;
};

// ce que le pied peut porter : les blocs des lanes (étiquetés par leur lane) et les services de ⚙
export const pbItemsOf = (doc, laneTitle) => [
  ...((doc || {}).lanes || []).flatMap(L => laneBlocks(L).filter(b => b && b.id)
    .map(b => ({ b, role: L.role || L.id, laneId: L.id, laneName: (laneTitle ? laneTitle(L) : (L.name || L.id)) }))),
  ...['gen', 'rec', 'arr'].flatMap(k => ((((doc || {}).config || {})[k] || {}).blocks) || [])
    .filter(b => b && b.id).map(b => ({ b, role: 'service', laneId: 'cfg', laneName: 'Services' })),
];

// les services ABSENTS du preset qu'on peut encore poser — les conflits du catalogue jouent dans les
// deux sens (on ne propose pas un second batteur), et l'accordeur suppose une lane audio
export const pbServicesOf = (doc, fx) => {
  const def = t => (fx || []).find(e => e.type === t) || {};
  const have = new Set(allBlocksOf(doc).filter(b => b.foot).map(b => b.type));
  const all = new Set(allBlocksOf(doc).map(b => b.type));
  return PB_SVC.filter(t => {
    const d = def(t);
    if (!d.type || all.has(t)) return false;
    if ((d.conflicts || []).some(c => all.has(c))) return false;
    if ((fx || []).some(e => (e.conflicts || []).includes(t) && all.has(e.type))) return false;
    return t !== 'tuner' || ((doc || {}).lanes || []).some(L => !L.midi);
  }).map(t => ({ type: t, name: def(t).short || def(t).name || t, have: have.has(t) }));
};

// ── les quatre gestes, sur un document (mutations en place) ──────────────────────────────────────
export const pbPut = (doc, id, sw) => { const b = allBlocksOf(doc).find(k => k.id === id); if (b) b.foot = sw; };
export const pbRemove = (doc, id) => { const b = allBlocksOf(doc).find(k => k.id === id); if (b) delete b.foot; };
export const pbFree = (doc, sw) => allBlocksOf(doc).forEach(b => { if (b.foot === sw) delete b.foot; });
// la case ENTIÈRE change de switch ; si la case d'arrivée est occupée, les deux ÉCHANGENT — fusionner
// mélangerait deux cases qu'on ne saurait plus séparer
export const pbMoveSwitch = (doc, from, to) => {
  const bs = allBlocksOf(doc);
  const a = bs.filter(k => k.foot === from), z = bs.filter(k => k.foot === to);
  a.forEach(k => { k.foot = to; }); z.forEach(k => { k.foot = from; });
};
// un service absent : posé là où le tiroir le mettrait (⚙ Players, ou tête de la 1re lane audio pour
// l'accordeur — un bloc-marqueur qui désigne la source écoutée)
export const pbAddService = (doc, type, sw) => {
  const nb = { type, id: bid(type), params: {}, foot: sw };
  if (type === 'tuner') {
    const L = (doc.lanes || []).find(k => !k.midi);
    if (!L) return null;
    L.chain = L.chain || { pre: [], split: null, post: [] };
    (L.chain.pre = L.chain.pre || []).unshift(nb);
    return nb;
  }
  doc.config = doc.config || {};
  doc.config.gen = doc.config.gen || { blocks: [], out: '1-2' };
  (doc.config.gen.blocks = doc.config.gen.blocks || []).push(nb);
  return nb;
};

// ce que le looper POSSÈDE : ses boucles, 10 (clear all) et 5 (play/stop all) — verrouillé à l'écran
export const looperBlockOf = doc => {
  let found = null;
  const walk = o => {
    if (found) return;
    if (Array.isArray(o)) { o.forEach(walk); return; }
    if (o && typeof o === 'object') {
      if (o.type === 'looper') { found = o; return; }
      Object.values(o).forEach(walk);
    }
  };
  ['lanes', 'guitar', 'voice', 'keys', 'paths', 'config'].forEach(k => walk((doc || {})[k]));
  return found;
};
export const pbOwnedOf = doc => {
  const lp = looperBlockOf(doc);
  if (!lp && !((doc || {}).looper || {}).enabled) return [];
  return [...new Set([...loopRows(((lp || {}).params || {}).loops).map(r => r.sw), 5, 10])];
};

export const roleIcon = role => ROLE_ICON[role] || '•';
