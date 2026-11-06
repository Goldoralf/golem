// SPDX-License-Identifier: GPL-3.0-or-later
// Tests du moteur de grille (node --test app/chain-layout.test.mjs) — pur, sans DOM.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { layoutChain } from './chain-layout.js';

const items = n => Array.from({ length: n }, (_, i) => 'x' + i);
const at = (row, col, lane = 'c') => row.cells.find(c => c.col === col && c.lane === lane);

test('linéaire court : IN col 0, OUT ancré col 11, fantômes entre', () => {
  const { rows } = layoutChain({ head: ['IN', 'b1', 'b2', '+'], out: 'OUT' });
  assert.equal(rows.length, 1);
  const r = rows[0];
  assert.equal(at(r, 0).it, 'IN');
  assert.equal(at(r, 11).it, 'OUT');
  for (let c = 4; c < 11; c++) assert.equal(at(r, c).kind, 'ghost');
  assert.equal(r.ret, false);
  assert.deepEqual(r.wires, [{ lane: 'c', from: 0.5, to: 11.5 }]);   // du centre d'IN au centre d'OUT
});

test('linéaire long : demi-bloc de renvoi col 11, demi-bloc arrivée col 0, OUT ancré', () => {
  const { rows } = layoutChain({ head: ['IN', ...items(13), '+'], out: 'OUT' });   // 15 cases de tête
  assert.equal(rows.length, 2);
  assert.equal(at(rows[0], 11).kind, 'wrapout');                 // demi-bloc de renvoi (dernière colonne)
  assert.equal(rows[0].cells.length, 12);                        // 11 contenus + renvoi
  assert.equal(rows[0].ret, true);
  assert.equal(at(rows[1], 0).kind, 'wrapin');                   // demi-bloc d'arrivée (colonne 0)
  assert.equal(at(rows[1], 1).it, 'x10');                        // le contenu reprend colonne 1
  assert.equal(at(rows[1], 11).it, 'OUT');
  assert.equal(rows[1].cells.filter(c => c.kind === 'ghost').length, 6);
});

test('tête pile 12 : renvoi + le 12e reprend colonne 1, OUT ancré', () => {
  const { rows } = layoutChain({ head: items(12), out: 'OUT' });
  assert.equal(rows.length, 2);
  assert.equal(at(rows[0], 11).kind, 'wrapout');
  assert.equal(at(rows[1], 1).it, 'x11');
  assert.equal(at(rows[1], 11).it, 'OUT');
});

test('split merge inline : zone dans la même rangée, ±alignement, Σ, post, OUT', () => {
  const { rows } = layoutChain({
    head: ['IN', 'g', 'w', '+'],                                 // 4 cases -> fourche col 4
    zone: { fanout: false, laneA: ['a1', '+A'], laneB: ['b1', 'b2', '+B'], close: 'Σ' },
    tail: ['p1', '+P'], out: 'OUT',
  });
  assert.equal(rows.length, 2);                                // la jonction ajoute 1 colonne -> OUT wrappe
  const r = rows[0];
  assert.equal(r.tall, true);
  assert.equal(r.fork, 4);
  assert.equal(at(r, 5, 'a').it, 'a1');
  assert.equal(at(r, 7, 'a').kind, 'ghost');                     // lane courte complétée en fantômes
  assert.equal(at(r, 7, 'b').it, '+B');
  assert.equal(r.join, 8);                                       // colonne de resommation (connecteur)
  assert.equal(at(r, 8).kind, 'join');
  assert.equal(r.close, 9);
  assert.equal(at(r, 9).it, 'Σ');
  assert.equal(at(r, 10).it, 'p1');
  assert.equal(at(r, 11).kind, 'wrapout');                       // +P wrappe -> demi-bloc de renvoi
  assert.equal(at(rows[1], 0).kind, 'wrapin');
  assert.equal(at(rows[1], 1).it, '+P');
  assert.equal(at(rows[1], 11).it, 'OUT');                       // OUT ancré sur la rangée suivante
  // fils : central->fourche, 2 demi-fils jusqu'à la jonction, Σ->renvoi, puis rangée OUT
  assert.deepEqual(r.wires, [
    { lane: 'a', from: 5, to: 8 }, { lane: 'b', from: 5, to: 8 },
    { lane: 'c', from: 0.5, to: 4 }, { lane: 'c', from: 9.5, to: 11.5 },
  ]);
  assert.deepEqual(rows[1].wires, [{ lane: 'c', from: 0.5, to: 11.5 }]);
});

test('zone qui ne tient pas : rangée neuve (jamais de repli de zone), fantômes+fil sur la rangée quittée', () => {
  const { rows } = layoutChain({
    head: items(8),                                              // reste 4 colonnes ; zone need = 1+5+2 = 8
    zone: { fanout: false, laneA: items(5), laneB: ['b'], close: 'Σ' },
    tail: [], out: 'OUT',
  });
  assert.equal(rows.length, 2);
  assert.equal(rows[0].tall, false);
  assert.equal(rows[0].ret, true);
  assert.equal(rows[0].cells.filter(c => c.kind === 'ghost').length, 3);   // fantômes puis demi-bloc de renvoi
  assert.equal(at(rows[0], 11).kind, 'wrapout');
  assert.equal(rows[1].tall, true);
  assert.equal(at(rows[1], 0, 'c').kind, 'wrapin');
  assert.equal(rows[1].fork, 1);                                 // la fourche suit le demi-bloc d'arrivée
  assert.equal(at(rows[1], 11).it, 'OUT');
});

test('fan-out : OUT de branche ancrés col 11, la chaîne termine, pas de fil central après la fourche', () => {
  const { rows } = layoutChain({
    head: ['IN', 't', '+'],
    zone: { fanout: true, laneA: ['cabA', '+A'], laneB: ['cabB', '+B'], outA: 'OUT1', outB: 'OUT2' },
    tail: ['JAMAIS'], out: 'JAMAIS',                             // ignorés en fan-out
  });
  assert.equal(rows.length, 1);
  const r = rows[0];
  assert.equal(r.fork, 3);
  assert.equal(at(r, 11, 'a').it, 'OUT1');
  assert.equal(at(r, 11, 'b').it, 'OUT2');
  assert.equal(at(r, 6, 'a').kind, 'ghost');                     // fantômes jusqu'à l'OUT ancré
  assert.equal(r.close, null);
  assert.deepEqual(r.wires, [
    { lane: 'a', from: 4, to: 11.5 }, { lane: 'b', from: 4, to: 11.5 },
    { lane: 'c', from: 0.5, to: 3 },
  ]);
  assert.ok(!r.cells.some(c => c.it === 'JAMAIS'));
});

test('voix/keys : cas trivial IN + blocs + OUT', () => {
  const { rows } = layoutChain({ head: ['IN', 'v1', '+'], out: 'OUT' });
  assert.equal(rows.length, 1);
  assert.equal(at(rows[0], 11).it, 'OUT');
});

test('＋ sentinelle {plus} : zéro colonne consommée, chips sur le fil (UX 2026-07-19)', () => {
  const P = { plus: 'PLUS' };
  // dimensions Frusciante : IN+5 pre+＋ · split A=[amp,＋] B=[boost,amp,＋] · post 4+＋ · OUT
  const { rows } = layoutChain({ head: ['IN', 'w', 'g', 'c', 'wa', 'p', P],
    zone: { laneA: ['a1', P], laneB: ['b1', 'b2', P], close: 'SUM', fanout: false },
    tail: ['t1', 't2', 't3', 't4', P], out: 'OUT' });
  assert.equal(rows.length, 2);                                  // avant : 3 (le ＋ post poussait OUT seul en r3)
  assert.equal(rows[0].fork, 6);                                 // le split tient INLINE (le ＋ pre ne pousse plus)
  const adds0 = rows[0].adds.map(a => a.lane + '@' + a.col).sort();
  assert.deepEqual(adds0, ['a@8', 'b@9', 'c@6']);                // chips aux frontières, lanes comprises
  assert.equal(rows[1].adds.length, 1);                          // ＋ post sur le fil de la rangée 2
  assert.equal(at(rows[1], 11).it, 'OUT');                       // OUT reste ancré au bord
});
