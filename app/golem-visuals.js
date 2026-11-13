// SPDX-License-Identifier: GPL-3.0-or-later
// Les visuels de golem-fx dans l'app (docs/designer-glyphs-pedals.md) : les pédales et le pédalier, dessinés par les
// moteurs de golem-fx copiés dans app/vendor/golem-visuals/ (tools/sync-golem-visuals.py). Ce sont des scripts
// simples qui posent window.GolemPedals / window.GolemStage et rendent des CHAÎNES SVG : on les charge une fois, à la
// demande (le tiroir en mode Pedals, la vue pédalier, /live), avec leurs polices (OFL, embarquées : le rack joue hors
// ligne) et leurs définitions communes (dégradés, textures, ids `gp-`), posées une fois dans la page.
import { GOLEM_FX } from './designer-model.js';

const BASE = 'vendor/golem-visuals/';
let loading = null;

const script = src => new Promise((ok, ko) => {
  const s = document.createElement('script');
  s.src = BASE + src; s.async = false; s.onload = ok; s.onerror = () => ko(new Error('cannot load ' + src));
  document.head.appendChild(s);
});

/** Charge les moteurs une fois ; la promesse rend true quand GolemPedals / GolemStage sont là. `catalog` = le document
 *  /api/effects (ses pedals / amps / cabs nommés remplacent l'instantané de golem-fx : le rack lit SON catalogue). */
export function loadVisuals(catalog) {
  if (catalog) useCatalog(catalog);
  if (loading) return loading;
  loading = (async () => {
    if (!document.querySelector('link[data-gv]')) {
      const l = document.createElement('link');
      l.rel = 'stylesheet'; l.href = BASE + 'fonts.css'; l.dataset.gv = '1';
      document.head.appendChild(l);
    }
    await script('visuals-data.js'); await script('golem-pedals.js'); await script('golem-stage.js');
    if (!document.getElementById('gp-defs')) {
      const d = document.createElement('div');
      d.id = 'gp-defs'; d.setAttribute('aria-hidden', 'true');
      d.style.cssText = 'position:absolute;width:0;height:0;overflow:hidden';
      d.innerHTML = '<svg width="0" height="0">' + window.GolemPedals.defs() + '</svg>';
      document.body.appendChild(d);
    }
    patchRenderers();
    if (pendingCat) useCatalog(pendingCat);
    return true;
  })().catch(e => { loading = null; throw e; });
  return loading;
}

let pendingCat = null;
function useCatalog(cat) {
  const V = typeof window !== 'undefined' && window.GOLEM_VISUALS;
  if (!V) { pendingCat = cat; return; }
  V.archetypes = Object.assign({}, V.archetypes, { pedals: cat.pedals || [], amps: cat.amps || [], cabs: cat.cabs || [] });
  pendingCat = null;
}

// la RÈGLE de golem pour rattacher une capture à un modèle nommé (designer-model `archOf`) : le mot-clé le plus long
// qui figure dans le nom l'emporte (« peavey 5150 » bat « 5150 ») ; golem-fx prenait le premier de la liste
function patchRenderers() {
  const P = window.GolemPedals;
  if (!P || P.__golem) return;
  const V = () => window.GOLEM_VISUALS || { archetypes: {} };
  P.archetypeFor = (kind, label) => {
    const l = String(label || '').toLowerCase();
    let best = null, bl = 0;
    for (const a of (V().archetypes[kind] || [])) for (const k of [a.match, ...(a.aliases || [])]) {
      const kk = String(k || '').toLowerCase();
      if (kk && kk.length > bl && l.includes(kk)) { best = a; bl = kk.length; }
    }
    return best;
  };
  // une pédale golem-fx (« clay ») seulement là où le moteur ACTIF joue ce type par golem-fx — le pédalier de golem-fx
  // appelle pedalFor : la règle vaut donc aussi dans la vue pédalier
  const orig = P.pedalFor;
  P.pedalFor = (item, opts) => {
    const it = typeof item === 'string' ? { type: item } : item;
    const b = P.blockByType(it.type);
    if (b && b.family === 'gfx' && !GOLEM_FX.has(it.type)) return P.genericPedal(b, Object.assign({}, opts || {}, it));
    return orig(item, opts);
  };
  P.__golem = true;
}

export const visualsReady = () => !!(typeof window !== 'undefined' && window.GolemPedals && window.GolemStage);

/** Le SVG (chaîne) d'un bloc en pédale (pedalFor, avec la règle du moteur actif). */
export function pedalSvg(item) {
  const P = window.GolemPedals;
  return P ? P.pedalFor(item) : '';
}

/** Le pédalier d'une lane (chaîne lanes-v2 + état de scène {blocks, branches}) : SVG (chaîne). */
export function stageSvg(chain, laneState, opts) {
  const S = window.GolemStage;
  return S ? S.render(S.fromGolem(chain, laneState), Object.assign({ floor: 'stage', guitar: true }, opts || {})) : '';
}
