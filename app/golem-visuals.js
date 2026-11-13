// SPDX-License-Identifier: GPL-3.0-or-later
// Les visuels de golem-fx dans l'app (docs/designer-glyphs-pedals.md) : les pédales et le pédalier, dessinés par les
// moteurs de golem-fx copiés dans app/vendor/golem-visuals/ (tools/sync-golem-visuals.py). Ce sont des scripts
// simples qui posent window.GolemPedals / window.GolemStage et rendent des CHAÎNES SVG : on les charge une fois, à la
// demande (le tiroir en mode Pedals, la vue pédalier, /live), avec leurs polices (OFL, embarquées : le rack joue hors
// ligne) et leurs définitions communes (dégradés, textures, ids `gp-`), posées une fois dans la page.
import { GOLEM_FX, GFX_CRATES, NAME, SHORT, BLOCK_COLOR } from './designer-model.js';

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
    useCatalog(pendingCat || {});                       // toujours : les blocs que golem-fx ne nomme pas encore
    return true;
  })().catch(e => { loading = null; throw e; });
  return loading;
}

let pendingCat = null;
function useCatalog(cat) {
  const V = typeof window !== 'undefined' && window.GOLEM_VISUALS;
  if (!V) { pendingCat = Object.assign({}, pendingCat || {}, cat); return; }
  if (cat.pedals || cat.amps || cat.cabs)                // le tiroir ne passe que ses blocs (`effects`)
    V.archetypes = Object.assign({}, V.archetypes, { pedals: cat.pedals || [], amps: cat.amps || [], cabs: cat.cabs || [] });
  // les blocs que golem-fx dessine : son instantané du catalogue (`blocks`) date de SON dernier passage ; un type que
  // le catalogue du rack a gagné depuis (met / emet / shem, v43) est rattaché à sa face par la liste `blocks` de la face
  const have = new Set((V.blocks || []).map(b => b.type));
  const byType = new Map((cat.effects || []).map(e => [e.type, e]));
  // et par le CRATE que le rack sait (/api/effects `gfx_crates`) : un type que golem-fx nomme autrement (golem-double)
  const pairs = [];
  for (const [crate, face] of Object.entries(V.gfx || {})) for (const t of (face.blocks || [])) pairs.push([crate, face, t]);
  for (const [t, crate] of Object.entries(cat.gfx_crates || GFX_CRATES)) if ((V.gfx || {})[crate]) pairs.push([crate, V.gfx[crate], t]);
  for (const [crate, face, t] of pairs) {
    // le bloc tel que le catalogue du rack le nomme ; /live n'a pas le catalogue sous la main : les noms hydratés
    const e = byType.get(t) || (NAME[t] ? { name: NAME[t], short: SHORT[t], color: BLOCK_COLOR[t], params: [] } : null);
    if (have.has(t) || !e) continue;
    _pedals.clear(); _stages.clear();                   // un dessin déjà fait l'a été sans sa face
    V.blocks = [...(V.blocks || []), { type: t, name: e.name, short: e.short, category: e.category || face.category,
      color: face.color || e.color, glyph: face.glyph || t, family: 'gfx', gfx: crate, params: e.params || [] }];
    have.add(t);
  }
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
    // LES VRAIS RÉGLAGES sur la pédale (docs/golem-fx-sheet.md) : la face de golem-fx, ses commandes à la valeur du bloc
    if (b && b.family === 'gfx' && it.values) {
      const face = (window.GOLEM_VISUALS.gfx || {})[b.gfx];
      if (face) {
        const set = c => (it.values[c.id] != null ? Object.assign({}, c, { value: it.values[c.id] }) : c);
        const spec = Object.assign({}, face, { knobs: (face.knobs || []).map(set), selectors: (face.selectors || []).map(set),
                                               toggles: (face.toggles || []).map(set) });
        return P.gfxPedal(spec, Object.assign({}, opts || {}, it));
      }
    }
    return orig(item, opts);
  };
  P.__golem = true;
}

export const visualsReady = () => !!(typeof window !== 'undefined' && window.GolemPedals && window.GolemStage);

// UN DESSIN STABLE (2026-11-13 : « en mode Pedals, ça n'ajoute pas ») : golem-fx numérote les ids de chaque dessin
// (gpm1-…, gpm2-…), donc deux appels pour la même pédale rendent deux TEXTES différents. Le tiroir est redessiné à chaque
// état du rack (les vumètres, plusieurs fois par seconde) : le SVG sous le doigt était remplacé entre l'appui et le
// relâché, et le navigateur annulait le clic. Chaque dessin est donc fait UNE fois par contenu et gardé ; le texte ne
// change que si ce qu'il montre change. (La mémoire suit le moteur : un bloc joué ailleurs que par golem-fx prend un
// autre dessin — la clé porte cette règle.)
const _pedals = new Map(), _stages = new Map();
const remember = (map, key, make) => {
  if (map.has(key)) return map.get(key);
  const v = make();
  if (map.size > 400) map.clear();
  map.set(key, v);
  return v;
};

/** Le SVG (chaîne) d'un bloc en pédale (pedalFor, avec la règle du moteur actif). */
export function pedalSvg(item) {
  const P = window.GolemPedals;
  if (!P) return '';
  const it = typeof item === 'string' ? { type: item } : item;
  return remember(_pedals, JSON.stringify([it, GOLEM_FX.has(it.type)]), () => P.pedalFor(it));
}

/** Les valeurs d'un bloc pour sa pédale golem-fx : {id golem-fx: valeur du plugin} — une liste par son RANG, une case 0/1.
 *  `def` = la définition du bloc servie par /api/effects (ses réglages portent `gfx.id`), `params` = valeurs effectives. */
export function pedalValues(def, params) {
  const out = {};
  for (const pm of ((def && def.params) || [])) {
    const gid = pm.gfx && pm.gfx.id;
    if (!gid) continue;
    let v = params && params[pm.id] != null ? params[pm.id] : pm.default;
    if (v == null) continue;
    if (pm.type === 'enum') { const i = (pm.options || []).indexOf(v); v = i < 0 ? 0 : i; }
    else if (pm.type === 'bool') v = v ? 1 : 0;
    if (typeof v === 'number') out[gid] = v;
  }
  return out;
}

/** Le pédalier d'une lane (chaîne lanes-v2 + état de scène {blocks, branches}) : SVG (chaîne). `values` = {id du bloc:
 *  ses valeurs de pédale (pedalValues)} — les pédales golem-fx montrent alors les réglages du bloc. */
export function stageSvg(chain, laneState, opts, values) {
  const S = window.GolemStage;
  if (!S) return '';
  const o = Object.assign({ floor: 'stage', guitar: true }, opts || {});
  const withVals = it => {
    if (!it || typeof it !== 'object') return it;
    if (it.split) return Object.assign({}, it, { split: Object.assign({}, it.split, { branches: (it.split.branches || []).map(br =>
      Array.isArray(br) ? br.map(withVals) : Object.assign({}, br, { items: (br.items || []).map(withVals) })) }) });
    return values && it.id != null && values[it.id] ? Object.assign({}, it, { values: values[it.id] }) : it;
  };
  return remember(_stages, JSON.stringify([chain, laneState, o, [...GOLEM_FX].sort(), values || null]),
    () => S.render(S.fromGolem(chain, laneState).map(withVals), o));
}
