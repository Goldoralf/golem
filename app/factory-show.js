// SPDX-License-Identifier: GPL-3.0-or-later
// Ce que l'utilisateur veut VOIR de l'usine (Settings ▸ Content ▸ Factory, 2026-10-13). L'usine se MASQUE, elle ne se
// supprime pas : une page de navigation FILTRE ses objets avant le rendu (jamais `hidden`, qu'une autre feuille peut
// réafficher — CLAUDE.md). Le bridge liste toujours tout, marqué `factory: true` : ce qui résout un objet par son id
// (le preset qui joue, le kit d'un preset visible) ne le perd jamais.
import { useState, useEffect, post } from './lib.js';

let cache = null;
const subs = new Set();
const tell = () => subs.forEach(f => f(cache));

export function useFactoryShow() {
  const [show, setShow] = useState(cache);
  useEffect(() => {
    subs.add(setShow);
    if (!cache) fetch('/api/factory/visibility').then(r => r.json()).then(d => { cache = d.show || {}; tell(); }).catch(() => {});
    return () => subs.delete(setShow);
  }, []);
  return show || {};
}

export async function setFactoryShow(kind, on) {
  const r = await post('/api/factory/visibility', { show: { [kind]: on } });
  if (r && r.show) { cache = r.show; tell(); }
  return r;
}

// garde un objet sauf s'il vient de l'usine ET que sa sorte est masquée
export const keepFactory = (show, kind) => x => !(x && x.factory && show[kind] === false);
