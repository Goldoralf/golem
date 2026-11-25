// SPDX-License-Identifier: GPL-3.0-or-later
// LES ANIMATIONS INFINIES AU PAS (2026-11-25, docs/pitfalls/ui.md « An endless animation steals the audio thread »).
//
// Tant qu'une animation CSS infinie tourne, Chrome recompose l'image à CHAQUE rafraîchissement de l'écran — 240 fois
// par seconde sur l'écran du rack de dev — même pour un curseur de 26 px qui clignote. Mesuré : le processus GPU de
// Chrome à 22–49 % d'un cœur, et la charge du moteur audio +15 à 20 points à buffer 128 ; sur la machine Linux à
// 2 cœurs, 119 décrochages ALSA par minute fenêtre ouverte, 0 fenêtre réduite.
//
// Le remède, sans toucher au CSS : chaque animation infinie est mise EN PAUSE et posée tour à tour sur son état
// « allumé » et son état « éteint », au rythme de sa propre demi-période. Même rendu pour un clignotement ou une
// pulsation (en marches au lieu d'un fondu), deux images par seconde au lieu de 240 (mesuré : GPU 0,4–0,6 %).
// Restent libres : les spinners (une rotation au pas ne tourne pas) et les animations de cases du Live, choisies
// par l'utilisateur (classes anim-*).

export const TICK_MS = 200;                  // le minuteur ne coûte rien : seule une BASCULE produit une image

// le pas d'une animation : sa durée d'un état à l'autre, et les deux instants qui les montrent
export function stepPlan(timing) {
  const d = Number(timing && timing.duration) || 0;
  if (!(timing && timing.iterations === Infinity) || d <= 0) return null;
  // `alternate` : un aller (0 → fin) puis un retour ; les deux états sont le début et la fin de l'aller
  const alt = String(timing.direction || '').includes('alternate');
  return { half: alt ? d : d / 2, on: 0, off: alt ? d - 1 : d / 2 + 1 };
}

// au pas, ou libre ?
export function stepped(name, targetClasses) {
  if (/spin/i.test(name || '')) return false;                          // une rotation ne se fait pas au pas
  return !(targetClasses || []).some(c => /^anim-/.test(c));           // les animations de cases du Live (choisies)
}

// l'état (0 = allumé, 1 = éteint) à l'instant `now`
export const phaseAt = (plan, now) => Math.floor(now / plan.half) % 2;

// le minuteur, dans une page ; rend la fonction qui l'arrête
export function startAnimStepper(doc = globalThis.document, clock = () => performance.now()) {
  if (!doc || typeof doc.getAnimations !== 'function') return () => {};
  const seen = new WeakMap();
  const tick = () => {
    const now = clock();
    for (const a of doc.getAnimations()) {
      if (!a.animationName) continue;                                  // une transition, ou une animation posée en JS
      let s = seen.get(a);
      if (s === undefined) {
        const t = a.effect && a.effect.target;
        const el = t && (t.nodeType === 1 ? t : t.parentElement);
        const plan = stepped(a.animationName, el ? [...el.classList] : []) ? stepPlan(a.effect.getTiming()) : null;
        s = { plan, phase: -1 };
        seen.set(a, s);
        if (plan) a.pause();
      }
      if (!s.plan) continue;
      const ph = phaseAt(s.plan, now);
      if (ph !== s.phase) { s.phase = ph; a.currentTime = ph ? s.plan.off : s.plan.on; }
    }
  };
  tick();
  const t = setInterval(tick, TICK_MS);
  return () => clearInterval(t);
}
