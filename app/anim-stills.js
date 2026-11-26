// SPDX-License-Identifier: GPL-3.0-or-later
// L'IMAGE FIXE DE CHAQUE EFFET (docs/anim-packs.md §8, 2026-11-26). Quand les cases du Live sont figées, une case ne
// montre plus une animation arrêtée (une image prise en plein cycle ressemble à un bug, et une animation en pause garde
// sa couche composée) : elle montre l'image fixe de son effet, un SVG à fond transparent posé sur la couleur de la case.
// `currentColor` y vaut la couleur de la case : on la substitue avant de dessiner. Une image par (effet, couleur),
// gardée : la case la reçoit en `background-image`, peinte une fois.
//
// Les images viennent de GET /api/anim-packs (effects[].still) : le pack default (library/catalog/anim-stills.json) et
// ceux de golem.fm. Un effet sans image ne montre que sa couleur — jamais une animation arrêtée.

let _map = null;               // { "fire": svg, "u1/flicker": svg }
let _run = null;

export function loadStills() {
  if (_run) return _run;
  _run = fetch('/api/anim-packs').then(r => r.json()).then(d => {
    const m = {};
    for (const pk of (d && d.packs) || []) {
      for (const e of pk.effects || []) {
        if (e && e.id && typeof e.still === 'string') m[pk.id === 'default' ? e.id : pk.id + '/' + e.id] = e.still;
      }
    }
    _map = m;
    return true;
  }).catch(() => { _map = {}; _run = null; return false; });   // un échec se retente au prochain appel
  return _run;
}

export const stillsReady = () => _map !== null;
export const hasStill = v => !!(_map && v && _map[v]);

const HEX = /^#[0-9a-fA-F]{6}$/;
const _bg = new Map();

// la valeur CSS `background-image` de l'image fixe d'un effet sur une case de cette couleur ; '' s'il n'y en a pas
export function stillBg(value, color) {
  const svg = _map && value ? _map[value] : null;
  if (!svg) return '';
  const c = HEX.test(String(color || '')) ? color : '#ffffff';
  const key = value + '|' + c;
  let v = _bg.get(key);
  if (v === undefined) {
    v = 'url("data:image/svg+xml,' + encodeURIComponent(svg.replace(/currentColor/g, c)) + '")';
    if (_bg.size > 300) _bg.clear();
    _bg.set(key, v);
  }
  return v;
}
