// SPDX-License-Identifier: GPL-3.0-or-later
// LES ANIMATIONS INFINIES AU PAS (2026-11-25, docs/pitfalls/ui.md « An endless animation steals the audio thread »).
//
// Tant qu'une animation CSS infinie tourne, Chrome recompose l'image à CHAQUE rafraîchissement de l'écran — 240 fois
// par seconde sur l'écran du rack de dev — même pour un curseur de 26 px qui clignote. Mesuré : le processus GPU de
// Chrome à 22–49 % d'un cœur, et la charge du moteur audio +15 à 20 points à buffer 128 ; sur la machine Linux à
// 2 cœurs, 119 décrochages ALSA par minute fenêtre ouverte, 0 fenêtre réduite.
//
// Trois sorts, sans toucher au CSS :
//  - « step » : un clignotement, une pulsation d'état. Mis EN PAUSE et posé tour à tour sur son état « allumé » et
//    son état « éteint », au rythme de sa propre demi-période : même rendu (en marches au lieu d'un fondu), deux
//    images par seconde au lieu de 240 (mesuré : GPU 0,4–0,6 %).
//  - « freeze » : les animations de cases du Live (classes anim-*, la plupart des patchs d'usine en portent) SUR
//    L'ÉCRAN LOCAL — celui de la machine qui joue le son. Figées sur une image : la case garde son allure. Un écran
//    déporté (tablette, téléphone) dessine avec son propre processeur et les garde animées ; le réglage
//    « Animate tiles on this screen » (sélecteur d'effet du Designer) les rend à l'écran local.
//  - « free » : les spinners (une rotation au pas ne tourne pas) et les aperçus du sélecteur d'effet (.fx-opt).

export const TICK_MS = 200;                  // le minuteur ne coûte rien : seule une BASCULE produit une image
export const LOCAL_TILES_KEY = 'golem.localTileAnims';
const FREEZE_AT = 0.35;                      // l'image retenue d'une case figée : au tiers de son cycle

// le pas d'une animation : sa durée d'un état à l'autre, et les deux instants qui les montrent
export function stepPlan(timing) {
  const d = Number(timing && timing.duration) || 0;
  if (!(timing && timing.iterations === Infinity) || d <= 0) return null;
  // `alternate` : un aller (0 → fin) puis un retour ; les deux états sont le début et la fin de l'aller
  const alt = String(timing.direction || '').includes('alternate');
  return { half: alt ? d : d / 2, on: 0, off: alt ? d - 1 : d / 2 + 1 };
}

// l'écran est-il celui de la machine qui joue le son ?
export const isLocalHost = h => ['127.0.0.1', 'localhost', '::1', '[::1]'].includes(String(h || '').toLowerCase());

// au pas, figée, ou libre ? `where` : { tile, picker } — l'élément est dans une case animée, dans le sélecteur
export function sortOf(name, where, { local = false, localTiles = false } = {}) {
  if (/spin/i.test(name || '') || (where && where.picker)) return 'free';
  if (where && where.tile) return local && !localTiles ? 'freeze' : 'free';
  return 'step';
}

// l'état (0 = allumé, 1 = éteint) à l'instant `now`
export const phaseAt = (plan, now) => Math.floor(now / plan.half) % 2;

const whereOf = el => ({
  tile: !!(el && el.closest && el.closest('[class*="anim-"]')),
  picker: !!(el && el.closest && el.closest('.fx-opt')),
});

export const localTilesAllowed = () => {
  try { return globalThis.localStorage.getItem(LOCAL_TILES_KEY) === '1'; } catch { return false; }
};

// le minuteur, dans une page ; rend la fonction qui l'arrête
export function startAnimStepper(doc = globalThis.document, clock = () => performance.now(),
  { local = isLocalHost(globalThis.location && globalThis.location.hostname), allowTiles = localTilesAllowed, where = whereOf } = {}) {
  if (!doc || typeof doc.getAnimations !== 'function') return () => {};
  let seen = new WeakMap(), allowed = allowTiles();
  const tick = () => {
    const now = clock();
    const a2 = allowTiles();
    if (a2 !== allowed) {                              // le réglage a changé : on relâche ce qu'on tenait et on reclasse
      allowed = a2;
      for (const a of doc.getAnimations()) {
        const s = seen.get(a);
        if (s && s.sort !== 'free') { try { a.play(); } catch { /* animation partie */ } }
      }
      seen = new WeakMap();
    }
    for (const a of doc.getAnimations()) {
      if (!a.animationName) continue;                                  // une transition, ou une animation posée en JS
      let s = seen.get(a);
      if (s === undefined) {
        const t = a.effect && a.effect.target;
        const el = t && (t.nodeType === 1 ? t : t.parentElement);
        const timing = a.effect && a.effect.getTiming();
        const plan = stepPlan(timing);
        const sort = plan ? sortOf(a.animationName, where(el), { local, localTiles: allowed }) : 'free';
        s = { sort, plan, phase: -1 };
        seen.set(a, s);
        if (sort === 'step') a.pause();
        else if (sort === 'freeze') { a.pause(); a.currentTime = (Number(timing.duration) || 0) * FREEZE_AT; }
      }
      if (s.sort !== 'step') continue;
      const ph = phaseAt(s.plan, now);
      if (ph !== s.phase) { s.phase = ph; a.currentTime = ph ? s.plan.off : s.plan.on; }
    }
  };
  tick();
  const t = setInterval(tick, TICK_MS);
  return () => clearInterval(t);
}
