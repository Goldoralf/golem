// SPDX-License-Identifier: GPL-3.0-or-later
// Le tiroir « Add block » en LIGNES (docs/designer-glyphs-pedals.md, maquette B) : les effets golem FX dans leur
// colonne, les autres plugins à côté avec leur fabricant. PUR (aucun DOM) : testé par app/drawer-rows.test.mjs.

// le fabricant d'un plugin, lu dans le nom que le catalogue donne au plugin (`plugin` d'effects.json) — ce que le
// musicien reconnaît (« Calf », « x42 »), pas le nom technique entier
const MAKERS = [
  [/^neural[_ ]amp[_ ]modeler/i, 'NAM capture'], [/^calf\b/i, 'Calf'], [/^gx|guitarix/i, 'Guitarix'],
  [/^x42\b/i, 'x42'], [/^mda\b/i, 'MDA'], [/surge xt/i, 'Surge XT'], [/^dragonfly\b/i, 'Dragonfly'],
  [/airwindows/i, 'Airwindows'], [/^zam/i, 'Zam'], [/prisma/i, 'Prisma'], [/proteus/i, 'Proteus'],
  [/paulxstretch|sonosaurus/i, 'PaulXStretch'], [/spectral compressor|robbert van der helm/i, 'Robbert van der Helm'],
  [/spectral shift/i, 'Spectral Shift'], [/\(golem\)|golem_|^js:\s*golem\//i, 'golem'],
  [/^js:/i, 'JSFX'], [/^rea|reaplugs/i, 'Cockos'], [/^volume adjustment$/i, 'JSFX'],
];
export function makerOf(plugin) {
  const p = String(plugin || '').trim();
  if (!p) return '';
  for (const [re, name] of MAKERS) if (re.test(p)) return name;
  return p.replace(/^[A-Za-z0-9]+:\s*/, '').split(/[\s(]/)[0];
}

/** {gfx, other} : les blocs d'une catégorie que le moteur actif joue par golem-fx, puis les autres (ordre gardé). */
export function splitGolem(items, golemFx) {
  const has = t => (golemFx instanceof Set ? golemFx.has(t) : (golemFx || []).includes(t));
  return { gfx: items.filter(e => has(e.type)), other: items.filter(e => !has(e.type)) };
}
