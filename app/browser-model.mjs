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
