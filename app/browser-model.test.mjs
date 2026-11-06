// SPDX-License-Identifier: GPL-3.0-or-later
import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import { railLists, itemsFor, posOf, othersOf, openSel, paginate, pageOfItem, railCount } from './browser-model.mjs';

// les setlists de ce rack le 2026-10-14, réduites
const SL = [
  { id: 'covers', name: 'Covers', kind: 'songs', presets: ['p-kite', 'p-1983'] },
  { id: 'factory', name: 'Factory Golem', kind: 'songs', presets: ['p-jazz', 'p-metal', 'p-loop'] },
  { id: 'night', name: 'Night Shift', kind: 'songs', presets: ['p-kite'] },
  { id: 'fg', name: 'Factory Guitar', kind: 'sounds', presets: ['patch:g-clean', 'patch:g-fuzz'] },
];
const PRESETS = ['p-jazz', 'p-metal', 'p-loop', 'p-kite', 'p-1983', 'p-solo'].map(id => ({ id, name: id.slice(2) }));

test('le rail : la setlist du pied en tête, puis A→Z, chaque catalogue les siennes', () => {
  assert.deepEqual(railLists(SL, 'presets', 'factory').map(s => s.id), ['factory', 'covers', 'night']);
  assert.deepEqual(railLists(SL, 'patches', 'factory').map(s => s.id), ['fg']);
});

test('une setlist rend ses éléments DANS SON ORDRE (celui du pied), « Not in a setlist » ceux d\'aucune', () => {
  const ls = railLists(SL, 'presets', 'factory');
  assert.deepEqual(itemsFor('factory', PRESETS, ls).map(x => x.id), ['p-jazz', 'p-metal', 'p-loop']);
  assert.deepEqual(itemsFor('none', PRESETS, ls).map(x => x.id), ['p-solo']);
  assert.equal(railCount('all', PRESETS, ls), 6);
});

test('la position : dans la setlist choisie ; sur « All », dans celle du pied ; + les autres setlists', () => {
  const ls = railLists(SL, 'presets', 'factory');
  assert.deepEqual(posOf('p-metal', 'factory', ls, 'factory'), { n: 2, foot: true });
  assert.deepEqual(posOf('p-kite', 'covers', ls, 'factory'), { n: 1, foot: false });
  assert.deepEqual(posOf('p-metal', 'all', ls, 'factory'), { n: 2, foot: true });
  assert.equal(posOf('p-kite', 'all', ls, 'factory'), null);           // « — »
  assert.equal(othersOf('p-kite', 'all', ls, 'factory'), 2);           // Covers + le groupe
  assert.equal(othersOf('p-kite', 'covers', ls, 'factory'), 1);
});

test('à l\'ouverture : la setlist du pied si elle contient l\'élément joué, sinon une autre, sinon All', () => {
  const ls = railLists(SL, 'presets', 'factory');
  assert.equal(openSel(ls, 'p-metal'), 'factory');
  assert.equal(openSel(ls, 'p-kite'), 'covers');
  assert.equal(openSel(ls, 'p-solo'), 'all');
});

test('pages : 16 tiennent sur un écran ; au-delà, 14 par page pour laisser la place au pager', () => {
  const many = Array.from({ length: 24 }, (_, i) => ({ id: 'x' + i }));
  assert.equal(paginate(many.slice(0, 16), 0).pages, 1);
  const p = paginate(many, 1);
  assert.equal(p.pages, 2); assert.equal(p.shown.length, 10); assert.equal(p.rows, 5);
  assert.equal(paginate(many.slice(0, 8), 0).rows, 4);                   // deux colonnes égales
  assert.equal(pageOfItem(many, 'x15'), 1);
});
