// SPDX-License-Identifier: GPL-3.0-or-later
import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import { filterPresets, groupByInst, effectiveDefault, loadRecent, pushRecent, pickRecent } from './block-presets-model.mjs';

const L = [
  { id: 'soft', name: 'Soft', inst: 'guitar', factory: true, params: { thresh: -55 } },
  { id: 'chug', name: 'Chug-tight', inst: 'guitar', factory: true, default: true, params: { thresh: -42 } },
  { id: 'studio', name: 'Studio clean', inst: 'guitar', params: { thresh: -52 } },
  { id: 'anyone', name: 'Gentle', inst: 'any', factory: true, params: { thresh: -50 } },
  { id: 'bass1', name: 'Bass tight', inst: 'bass', factory: true, params: { thresh: -40 } },
];

test('le périmètre de la lane garde son instrument et « any » ; Factory / Mine filtrent ; la recherche lit nom et signature', () => {
  assert.deepEqual(filterPresets(L, { inst: 'guitar' }).map(p => p.id), ['soft', 'chug', 'studio', 'anyone']);
  assert.deepEqual(filterPresets(L, { inst: 'guitar', scope: 'all' }).map(p => p.id), ['soft', 'chug', 'studio', 'anyone', 'bass1']);
  assert.deepEqual(filterPresets(L, { inst: 'guitar', factory: false }).map(p => p.id), ['studio']);
  assert.deepEqual(filterPresets(L, { inst: 'guitar', q: 'clean' }).map(p => p.id), ['studio']);
  assert.deepEqual(filterPresets(L, { inst: 'guitar', q: '-42', sig: ps => 'thr ' + ps.thresh }).map(p => p.id), ['chug']);
});

test('l’accordéon : la lane d’abord, puis any, puis les autres ; chaque groupe compte usine / miens', () => {
  const g = groupByInst(filterPresets(L, { inst: 'guitar', scope: 'all' }), 'guitar');
  assert.deepEqual(g.map(x => [x.inst, x.items.length, x.factory, x.mine]), [['guitar', 3, 2, 1], ['any', 1, 1, 0], ['bass', 1, 1, 0]]);
  assert.equal(effectiveDefault(L, 'guitar'), 'chug');
  assert.equal(effectiveDefault(L, 'voice'), null);
});

test('Recent : par type de bloc, six au plus, le dernier chargé en tête', () => {
  const mem = new Map(); const store = { getItem: k => mem.get(k) || null, setItem: (k, v) => mem.set(k, v) };
  pushRecent('gate', 'soft', store); pushRecent('gate', 'chug', store); pushRecent('gate', 'soft', store);
  assert.deepEqual(loadRecent('gate', store), ['soft', 'chug']);
  assert.deepEqual(loadRecent('comp', store), []);
  for (let i = 0; i < 8; i++) pushRecent('gate', 'p' + i, store);
  assert.equal(loadRecent('gate', store).length, 6);
  assert.deepEqual(pickRecent(L, ['chug', 'nope', 'soft']).map(p => p.id), ['chug', 'soft']);
});
