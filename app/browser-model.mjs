// SPDX-License-Identifier: GPL-3.0-or-later
// Le sélecteur du top menu, filtré par SETLIST (2026-10-14 : « pour se repérer, un filtre pour les banks » ;
// maquette mockups/browser-setlists.html, proposition de l'agent UX). Une bank = une setlist : les presets se rangent
// dans les setlists de CHANSONS (kind songs), les patches dans celles de SONS (kind sounds, ids `patch:<id>`).
// Tout est pur ici (testé par browser-model.test.mjs) ; les deux modals ne font que l'afficher.

export const PER_PAGE = 16;            // 2 colonnes × 8 rangées de 48 px tiennent en 1024×600
export const PER_PAGE_PAGED = 14;      // dès qu'il y a des pages : 7 rangées, la 8e laisse la place au pager

const idsOf = s => (s.presets || []).map(x => String(x).replace(/^patch:/, ''));

// les setlists d'un catalogue : celle du pied en tête, puis A→Z
export function railLists(setlists, kind, active) {
  const want = kind === 'presets' ? 'songs' : 'sounds';
  return (setlists || []).filter(s => (s.kind || 'songs') === want)
    .slice().sort((a, b) => (b.id === active) - (a.id === active) || String(a.name || a.id).localeCompare(String(b.name || b.id)));
}

// les éléments d'une sélection du rail : 'all' (A→Z) · 'none' (dans aucune setlist, A→Z) · <id> (ordre de la setlist)
export function itemsFor(sel, pool, lists) {
  const byName = (a, b) => String(a.name || a.id).localeCompare(String(b.name || b.id));
  if (sel === 'all') return pool.slice().sort(byName);
  if (sel === 'none') {
    const inAny = new Set(lists.flatMap(idsOf));
    return pool.filter(x => !inAny.has(x.id)).sort(byName);
  }
  const s = lists.find(l => l.id === sel);
  if (!s) return [];
  const map = new Map(pool.map(x => [x.id, x]));
  return idsOf(s).map(id => map.get(id)).filter(Boolean);
}

export const railCount = (sel, pool, lists) => itemsFor(sel, pool, lists).length;

// la position à afficher : dans la setlist choisie ; sur « All », dans celle du PIED (si elle est de ce catalogue)
export function posOf(id, sel, lists, active) {
  const ref = (sel !== 'all' && sel !== 'none') ? lists.find(l => l.id === sel) : lists.find(l => l.id === active);
  if (!ref) return null;
  const i = idsOf(ref).indexOf(id);
  return i < 0 ? null : { n: i + 1, foot: ref.id === active };
}

// dans combien d'AUTRES setlists (que celle dont la position est affichée)
export function othersOf(id, sel, lists, active) {
  const shown = (sel !== 'all' && sel !== 'none') ? sel : active;
  return lists.filter(l => l.id !== shown && idsOf(l).includes(id)).length;
}

// à l'ouverture : la setlist (celle du pied d'abord) qui contient l'élément courant, sinon « All »
export function openSel(lists, currentId) {
  const hit = currentId && lists.find(l => idsOf(l).includes(currentId));
  return hit ? hit.id : 'all';
}

export function paginate(items, page) {
  const per = items.length > PER_PAGE ? PER_PAGE_PAGED : PER_PAGE;
  const pages = Math.max(1, Math.ceil(items.length / per));
  const p = Math.min(Math.max(0, page), pages - 1);
  const shown = items.slice(p * per, p * per + per);
  return { shown, page: p, pages, rows: Math.max(1, Math.min(per / 2, Math.ceil(shown.length / 2))) };
}

// la page où se trouve un élément (ouvrir sur la page du preset joué)
export function pageOfItem(items, id) {
  const per = items.length > PER_PAGE ? PER_PAGE_PAGED : PER_PAGE;
  const i = items.findIndex(x => x.id === id);
  return i < 0 ? 0 : Math.floor(i / per);
}

export const matches = (x, q) => !q || `${x.name || ''} ${x.artist || ''}`.toLowerCase().includes(q.trim().toLowerCase());

// CE QUE LE SÉLECTEUR RETIENT d'une ouverture à l'autre (2026-11-16 : « il ne garde pas mes derniers choix ») : la
// setlist du rail, le menu « With » et, pour les patches, l'instrument. Par écran (localStorage), un catalogue = une clé.
const memKey = kind => 'golem.browse.' + kind;
export function readBrowse(kind) {
  try { const d = JSON.parse(localStorage.getItem(memKey(kind)) || '{}'); return d && typeof d === 'object' ? d : {}; }
  catch (e) { return {}; }
}
export function writeBrowse(kind, patch) {
  try { localStorage.setItem(memKey(kind), JSON.stringify({ ...readBrowse(kind), ...patch })); } catch (e) { /* navigation privée */ }
}

// la sélection retenue vaut encore si sa setlist existe toujours
export const validSel = (sel, lists) => (sel === 'all' || sel === 'none' || lists.some(l => l.id === sel)) ? sel : null;

// LA LISTE QUE PARCOURENT ◀ ▶ du top menu : celle où l'on a choisi (la setlist retenue, dans SON ordre) ; si l'élément
// ouvert n'y est pas, la setlist qui le contient (celle du pied d'abord), sinon tout, A→Z. Sans doublon : un élément
// posé deux fois dans une setlist ferait tourner les flèches en rond.
export function cycleItems(sel, pool, lists, currentId) {
  const uniq = l => l.filter((x, i) => l.findIndex(y => y.id === x.id) === i);
  let l = sel && validSel(sel, lists) ? itemsFor(sel, pool, lists) : [];
  if (currentId ? !l.some(x => x.id === currentId) : !l.length) l = itemsFor(openSel(lists, currentId), pool, lists);
  if (!l.length) l = itemsFor('all', pool, lists);
  return uniq(l);
}

// le voisin dans cette liste (d = ±1), en boucle ; l'élément ouvert absent de la liste → le premier
export function neighbour(items, currentId, d) {
  if (!items.length) return null;
  const i = items.findIndex(x => x.id === currentId);
  return i < 0 ? items[0] : items[(i + d + items.length) % items.length];
}
