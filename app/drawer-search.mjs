// SPDX-License-Identifier: GPL-3.0-or-later
// Recherche du tiroir « Add block » : UN champ, toutes les catégories que la lane autorise — les captures
// installées d'abord (c'est ce qu'on cherche par son nom), puis les modèles nommés, puis les blocs.
// Pur (sans Preact) : testé par node --test (drawer-search.test.mjs).

export const SEARCH_MIN = 2;

const norm = s => String(s == null ? '' : s).toLowerCase();

// texte d'une capture : son appareil (sinon son titre), sa marque, ses appareils — comme le volet des sims. Pas le
// titre TONE3000 quand l'appareil est connu : « … - Complete Pack » faisait sortir un Tube Screamer pour « comp ».
const toneText = t => [t.amp || t.title, t.brand, ...(t.makes || [])].map(norm).join(' ');

// `cats` : catégories offertes à la lane ; `fx` : blocs déjà filtrés par rôle ; `archetypes` : amplis/pédales
// nommés du rôle ; `tones` : le catalogue installé ; `modelGears` : type de bloc → gears acceptés (MODEL_GEARS).
// une capture À SOI : importée (Tones ▸ + Add ▸ Import files) ou faite sur ce rack (Capture) — elle n'a ni
// téléchargements ni favoris TONE3000, donc un tri par popularité la met toujours en DERNIER
export const isMine = t => !!(t && (t.private || t.source === 'import' || t.source === 'capture'));

const offeredOf = (cats, fx) => {
  const allowed = new Set(cats);
  return fx.filter(e => allowed.has(e.category) && e.type !== 'midi-pedal' && !e.hidden);
};

// une capture se pose dans CHAQUE type de bloc qui accepte son gear et que la lane propose : un préampli
// ou un compresseur capturé (gear `outboard`) vaut pour les deux blocs — on les montre, on ne devine pas
function placements(tones, offered, modelGears) {
  const byType = Object.fromEntries(offered.map(e => [e.type, e]));
  const out = [];
  for (const t of tones) {
    for (const [type, gears] of Object.entries(modelGears)) {
      if (gears.includes(t.gear) && byType[type]) out.push({ tone: t, type, block: byType[type].name });
    }
  }
  return out;
}

// la catégorie « Mine » du tiroir : tes captures que CETTE lane peut jouer
export function myCaptures({ cats = [], fx = [], tones = [], modelGears = {} } = {}) {
  return placements(tones.filter(isMine), offeredOf(cats, fx), modelGears);
}

export function searchDrawer(query, { cats = [], fx = [], archetypes = [], tones = [], modelGears = {} } = {}) {
  const q = norm(query).trim();
  if (q.length < SEARCH_MIN) return null;
  const allowed = new Set(cats);
  const offered = offeredOf(cats, fx);
  const captures = placements(tones.filter(t => toneText(t).includes(q)), offered, modelGears);
  const archText = a => [a.name, a.short, a.brand, a.match, ...(a.aliases || [])].map(norm).join(' ');
  return {
    captures,
    archetypes: archetypes.filter(a => allowed.has(a.category || 'drive') && archText(a).includes(q)),
    blocks: offered.filter(e => norm(e.name).includes(q) || norm(e.type).includes(q)),
  };
}
