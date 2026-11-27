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
//    L'ÉCRAN LOCAL — celui de la machine qui joue le son. La racine reçoit html.tiles-still et le CSS leur retire
//    animation ET mix-blend-mode (une pause garde la couche composée : 43 couches mesurées, 5 sans) ; la pause au
//    tiers du cycle ne reste qu'en filet pour une animation que ce CSS ne viserait pas. Un écran
//    déporté (tablette, téléphone) dessine avec son propre processeur et les garde animées. Le réglage de
//    Settings ▸ System ▸ Display (bridge/display.py, l'état diffusé `display`) décide : auto (ce qui précède), on
//    (animées partout), off (figées partout). Les voyants suivent : cases figées = voyants tenus allumés (2026-11-27,
//    l'ancien réglage `blinks` est retiré).
//  - « free » : les spinners (une rotation au pas ne tourne pas) et les aperçus du sélecteur d'effet (.fx-opt).

export const TICK_MS = 200;                  // le minuteur ne coûte rien : seule une BASCULE produit une image
// le réglage du moment, posé par l'app à chaque état reçu (main.js, mobile.js) ; défaut tant que rien n'est arrivé
export const DISPLAY_DEFAULT = { animations: 'auto' };
export const setDisplay = d => { globalThis.__golemDisplay = d && typeof d === 'object' ? { ...DISPLAY_DEFAULT, ...d } : DISPLAY_DEFAULT; };
const currentDisplay = () => globalThis.__golemDisplay || DISPLAY_DEFAULT;
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

// au pas, figée, tenue ou libre ? `where` : { tile, picker } — l'élément est dans une case animée, dans le sélecteur.
// `display` : le réglage {animations: auto|on|off}. « hold » = tenue sur son état allumé (voyants sans clignoter).
// QUAND LES CASES SONT FIGÉES, RIEN NE CLIGNOTE NON PLUS (2026-11-26, maquette « /live statique ») : le curseur du
// logo et les voyants sont tenus allumés — la règle de cet écran est 0 image au repos, pas 2.
export function sortOf(name, where, { local = false, display = DISPLAY_DEFAULT } = {}) {
  if (/spin/i.test(name || '') || (where && where.picker)) return 'free';
  const m = display.animations || 'auto';
  const still = m === 'off' || (m !== 'on' && local);
  if (where && where.tile) return still ? 'freeze' : 'free';
  return still ? 'hold' : 'step';
}

// les cases du Live sont-elles figées ? Alors on les rend SANS animation (classe racine STILL_CLASS)
export const STILL_CLASS = 'tiles-still';
export const tilesStill = ({ local = false, display = DISPLAY_DEFAULT } = {}) =>
  sortOf('', { tile: true }, { local, display }) === 'freeze';

// l'état (0 = allumé, 1 = éteint) à l'instant `now`
export const phaseAt = (plan, now) => Math.floor(now / plan.half) % 2;

const whereOf = el => ({
  tile: !!(el && el.closest && el.closest('[class*="anim-"]')),
  picker: !!(el && el.closest && el.closest('.fx-opt')),
});

// le minuteur, dans une page ; rend la fonction qui l'arrête
export function startAnimStepper(doc = globalThis.document, clock = () => performance.now(),
  { local = isLocalHost(globalThis.location && globalThis.location.hostname), display = currentDisplay, where = whereOf } = {}) {
  if (!doc || typeof doc.getAnimations !== 'function') return () => {};
  const keyOf = d => d.animations || 'auto';
  let seen = new WeakMap(), shown = keyOf(display());
  const root = doc.documentElement;
  const tick = () => {
    const now = clock();
    const d = display();
    // cases figées = cases SANS animation (html.tiles-still, style.css) : une animation en pause garde sa couche
    // composée, et le compositeur refait 40 couches à chaque image du Live (docs/pitfalls/ui.md)
    if (root && root.classList) root.classList.toggle(STILL_CLASS, tilesStill({ local, display: d }));
    if (keyOf(d) !== shown) {                          // le réglage a changé : on relâche ce qu'on tenait et on reclasse
      shown = keyOf(d);
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
        const sort = plan ? sortOf(a.animationName, where(el), { local, display: display() }) : 'free';
        s = { sort, plan, phase: -1 };
        seen.set(a, s);
        if (sort === 'step') a.pause();
        else if (sort === 'freeze') { a.pause(); a.currentTime = (Number(timing.duration) || 0) * FREEZE_AT; }
        else if (sort === 'hold') { a.pause(); a.currentTime = 0; }       // un voyant tenu : son état « allumé »
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
