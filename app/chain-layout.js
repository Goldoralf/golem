// SPDX-License-Identifier: GPL-3.0-or-later
// Moteur de layout de la GRILLE du Designer (docs/designer-grid.md) — PUR, zéro dépendance,
// testable en node (chain-layout.test.mjs). Il ne connaît pas le DOM : les cellules (`it`) sont
// des payloads opaques (vnodes côté renderer), il ne fait QUE la géométrie.
//
// Règles validées :
//  - 12 colonnes ; IN = 1ʳᵉ case de la 1ʳᵉ rangée ; OUT = DERNIÈRE case de sa rangée (ancré au bord).
//  - Le fil audio court toujours d'un bord à l'autre de chaque rangée de flux ; retour serpentine.
//  - Zone split (2 branches max) : INLINE dans le flux, 2 demi-rangées ±½ case autour du fil ;
//    elle ne se replie JAMAIS (rangée neuve si elle ne tient pas).
//  - Fan-out : chaque branche finit sur SA case OUT (ancrée au bord) ; la chaîne s'arrête là.
//  - Les cases inutilisées d'une rangée entamée = fantômes (le fil les traverse).
//
// Sortie : { rows: [ { tall, ret, fork, close, cells:[{col, lane:'c'|'a'|'b', kind, it?}], wires:[{lane, from, to}] } ] }
//  - lane 'c' = sur le fil central ; 'a'/'b' = demi-rangées du split ; kind 'item'|'ghost'|'fork'.
//  - wires en colonnes fractionnaires (from/to), à convertir en % côté CSS.

export function layoutChain({ cols = 12, head = [], zone = null, tail = [], out = null } = {}) {
  const rows = [];
  let cur = null, col = 0;
  const newRow = tall => {
    if (cur) cur.ret = true;                       // la rangée qu'on quitte serpente vers la suivante
    cur = { tall: !!tall, ret: false, fork: null, join: null, close: null, cells: [], wires: [] };
    rows.push(cur); col = 0;
  };
  const place = it => { cur.cells.push({ col, lane: 'c', kind: 'item', it }); col++; };
  const ghost = () => { cur.cells.push({ col, lane: 'c', kind: 'ghost' }); col++; };
  // « ＋ » d'append : DÉCOR SUR LE FIL, ne consomme AUCUNE colonne (retour UX 2026-07-19 —
  // les tuiles ＋ pleines poussaient OUT sur une rangée fantôme entière). Sentinelle {plus: vnode}
  // dans head/tail/lanes -> rows[].adds = [{lane, col (frontière fractionnaire), it}].
  // `edge` : le ＋ ne suit PAS une tuile (il colle à la pastille d'entrée d'une lane config, plus
  // large qu'une tuile). Le décalage de demi-marge calibré sur 78 px le ferait alors MORDRE sur
  // elle — le ＋ de « Players » se retrouvait DANS la box IN (retour 2026-09-12).
  const addChip = (lane, c, it, edge) => { (cur.adds = cur.adds || []).push({ lane, col: c, it, edge }); };
  const isPlus = it => !!(it && it.plus);
  const realLen = arr => arr.filter(x => !isPlus(x)).length;
  // retour à la ligne façon QC : DEMI-BLOC de renvoi en dernière colonne, demi-bloc d'arrivée en
  // colonne 0 de la rangée suivante — le fil part du BAS du premier et arrive sur le HAUT du second.
  const wrapRow = tall => {
    if (col <= cols - 1) cur.cells.push({ col: cols - 1, lane: 'c', kind: 'wrapout' });
    newRow(tall);
    cur.cells.push({ col: 0, lane: 'c', kind: 'wrapin' });
    col = 1;
  };
  newRow(false);

  // — tête linéaire (IN · pre… · ＋) — (dernière colonne réservée au demi-bloc de renvoi)
  for (const it of head) {
    if (isPlus(it)) { addChip('c', col, it.plus, it.edge); continue; }
    if (col >= cols - 1) wrapRow(false);
    place(it);
  }

  if (zone) {
    const laneW = Math.max(realLen(zone.laneA), realLen(zone.laneB));
    const need = 1 + laneW + (zone.fanout ? 1 : 2);          // fourche + lanes + (OUT | jonction + Σ)
    if (col + need > cols) { while (col < cols - 1) ghost(); wrapRow(true); }
    else cur.tall = true;
    cur.fork = col;
    cur.cells.push({ col, lane: 'c', kind: 'fork' }); col++;
    const laneStart = col;
    for (const [lane, arr, outIt] of [['a', zone.laneA, zone.outA], ['b', zone.laneB, zone.outB]]) {
      let c = laneStart;
      for (const it of arr) {
        if (isPlus(it)) { addChip(lane, c, it.plus, it.edge); continue; }
        cur.cells.push({ col: c, lane, kind: 'item', it }); c++;
      }
      if (zone.fanout) {                                     // OUT de branche ancré à la dernière colonne
        while (c < cols - 1) { cur.cells.push({ col: c, lane, kind: 'ghost' }); c++; }
        cur.cells.push({ col: cols - 1, lane, kind: 'item', it: outIt });
        cur.wires.push({ lane, from: cur.fork + 1, to: cols - 0.5 });
      } else {                                               // alignées colonne à colonne jusqu'à la jonction
        while (c < laneStart + laneW) { cur.cells.push({ col: c, lane, kind: 'ghost' }); c++; }
        cur.wires.push({ lane, from: cur.fork + 1, to: laneStart + laneW });
      }
    }
    cur.wires.push({ lane: 'c', from: 0.5, to: cur.fork });
    col = laneStart + laneW;
    if (zone.fanout) return finish(rows, cols);              // le fan-out TERMINE la chaîne
    cur.join = col;                                          // colonne de RESOMMATION (connecteur merge seul)
    cur.cells.push({ col, lane: 'c', kind: 'join' }); col++;
    cur.close = col;                                         // puis la case Σ (gain dB)
    cur.cells.push({ col, lane: 'c', kind: 'item', it: zone.close }); col++;
  }

  // — queue (post… · ＋) puis OUT ancré à la dernière colonne —
  for (const it of tail) {
    if (isPlus(it)) { addChip('c', col, it.plus, it.edge); continue; }
    if (col >= cols - 1) wrapRow(false);
    place(it);
  }
  if (out) {
    if (col > cols - 1) wrapRow(false);
    while (col < cols - 1) ghost();
    place(out);
  }
  // sans OUT (lane Recorder : elle CAPTE, elle ne renvoie rien), le fil de la dernière rangée
  // s'arrête au centre du dernier bloc — sinon il pendrait dans le vide jusqu'au bord.
  return finish(rows, cols, out ? null : Math.max(0, col - 1) + 0.5);
}

// fils centraux : du CENTRE de la 1ʳᵉ case (pas de fil avant IN) au CENTRE de la dernière
// (OUT ancré, ou demi-bloc de renvoi — le retour part de son BAS, dessiné par le renderer) ;
// sur une rangée split, le fil central s'interrompt entre la fourche et le Σ.
function finish(rows, cols, endCol) {
  const last = rows[rows.length - 1];
  for (const r of rows) {
    const to = (r === last && endCol != null) ? endCol : cols - 0.5;
    if (r.fork != null) {
      if (r.close != null) r.wires.push({ lane: 'c', from: r.close + 0.5, to });
    } else {
      r.wires.push({ lane: 'c', from: 0.5, to });
    }
  }
  return { rows };
}
