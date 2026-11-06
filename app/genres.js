// SPDX-License-Identifier: GPL-3.0-or-later
// Genres (docs/genres.md) : la taxonomie COMPLÈTE servie par le bridge (GET /api/genres — celle de golem.fm dès
// qu'elle est arrivée, sinon la copie du rack). Les 17 familles seules vivent aussi dans lib.js (GENRE_FAMILIES),
// pour un rendu synchrone ; ici on a les sous-genres, pour afficher un libellé à partir d'un id.
import { useAsync } from './lib.js';

let _p = null;
const load = () => (_p = _p || fetch('/api/genres').then(r => r.json()).then(d => {
  const label = {};
  for (const f of d.families || []) {
    label[f.id] = f.label;
    for (const s of f.subgenres || []) label[s.id] = s.label;
  }
  return label;
}).catch(() => { _p = null; return {}; }));

// le libellé d'un id de famille OU de sous-genre (espaces disjoints) ; l'id lui-même tant que rien n'est chargé
export function useGenreLabel() {
  const { data } = useAsync(load, []);
  return id => (data && data[id]) || id || '';
}

// les genres d'une chanson ([{family, subgenre|null}], ordonnés) en texte : « Metalcore · Hyperpop »
export const songGenresText = (genres, label) => (genres || [])
  .map(g => label(g.subgenre || g.family)).filter(Boolean).join(' · ');
