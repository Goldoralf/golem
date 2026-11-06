// SPDX-License-Identifier: GPL-3.0-or-later
// Les CHAMPS d'une recette de programme (docs/separation.md §4 quinquies, avocat 2026-10-14) : la recette pose la
// plomberie, l'utilisateur remplit lui-même ce qu'elle ne nomme pas — le modèle avant tout. Sans dépendance : testé seul.

// les arguments RÉELS : chaque jeton de champ remplacé par sa valeur ; un champ facultatif laissé vide retire son
// jeton ET l'option qui le précède (`drop`) ; un champ obligatoire vide garde son jeton (fieldsMissing le dit).
export function fillFields(args, fields, vals) {
  const by = Object.fromEntries((fields || []).map(f => [f.token, f]));
  const out = [];
  for (const a of args) {
    const f = by[a];
    if (!f) { out.push(a); continue; }
    const v = String((vals || {})[a] || '').trim();
    if (v) { out.push(v); continue; }
    if (f.required) { out.push(a); continue; }
    const drop = f.drop || [];
    if (out.length && drop.includes(out[out.length - 1])) out.pop();
  }
  return out;
}

// les champs obligatoires présents dans les arguments et encore vides
export function fieldsMissing(args, fields, vals) {
  return (fields || []).filter(f => f.required && args.includes(f.token) && !String((vals || {})[f.token] || '').trim());
}
