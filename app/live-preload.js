// SPDX-License-Identifier: GPL-3.0-or-later
// LA PROMESSE DE L'ÉCRAN DE CHARGEMENT (2026-11-19) : « quand il disparaît, j'arrive sur /live et le golem est
// chargé ». Avant, /live ne demandait ses presets (scènes, couleurs, animations des tuiles) qu'à son montage, PUIS
// chargeait le CSS des packs d'animation : quelques secondes de tuiles nues après l'écran de chargement.
// Ici, pendant le chargement : /api/presets, /api/effects et le CSS des packs du preset joué. main.js garde l'écran
// tant que ce n'est pas prêt — borné (PRELOAD_MAX_MS) : un fetch lent ne bloque jamais l'entrée dans l'app.
import { hydrateBlockMeta, animPackOf } from './designer-model.js';
import { loadStills } from './anim-stills.js';

export const PRELOAD_MAX_MS = 6000;

let _presets = null;          // { data } : la liste servie par /api/presets, prise une fois par /live
let _run = null;              // la promesse du préchargement en cours (une seule à la fois)
let _forPreset = null;

// le CSS d'un pack, comme ensurePackCss, mais qu'on peut ATTENDRE (onload/onerror)
const _cssDone = {};
function packCss(pid) {
  if (!pid || pid === 'default') return Promise.resolve();
  if (_cssDone[pid]) return _cssDone[pid];
  const href = '/api/anim-pack/' + encodeURIComponent(pid) + '/css';
  if (document.querySelector(`link[rel="stylesheet"][href="${href}"]`)) return (_cssDone[pid] = Promise.resolve());
  _cssDone[pid] = new Promise(res => {
    const el = document.createElement('link');
    el.rel = 'stylesheet'; el.href = href;
    el.onload = () => res();
    el.onerror = () => { console.warn('[anim-packs] pack « ' + pid + ' » indisponible — tuiles sans animation'); res(); };
    document.head.appendChild(el);
  });
  return _cssDone[pid];
}

// Lance (une fois par preset) le préchargement de /live ; rend sa promesse — elle ne rejette jamais.
export function preloadLive(presetId) {
  if (_run && _forPreset === presetId) return _run;
  _forPreset = presetId;
  const presets = fetch('/api/presets').then(r => r.json()).then(list => {
    _presets = { data: list };
    const cur = (list || []).find(p => p.id === presetId);
    return Promise.all(Object.values((cur && cur.anims) || {}).map(v => packCss(animPackOf(v))));
  });
  const effects = fetch('/api/effects').then(r => r.json()).then(d => { hydrateBlockMeta(d.effects || d, d); });
  // les images fixes des effets (docs/anim-packs.md §8) : une case figée ne s'affiche jamais sans la sienne
  _run = Promise.all([presets, effects, loadStills()]).then(() => true, () => true);
  return _run;
}

// La liste préchargée, pour le PREMIER rendu de /live (puis /live la relit lui-même) ; null sinon.
export function takePresets() {
  const p = _presets;
  _presets = null;
  return p ? p.data : null;
}
