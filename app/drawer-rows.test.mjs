// SPDX-License-Identifier: GPL-3.0-or-later
import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import { readFileSync } from 'node:fs';
import { makerOf, splitGolem } from './drawer-rows.mjs';
import { refOfPath } from './designer-pedalview.js';

test('le fabricant se lit dans le nom du plugin', () => {
  assert.equal(makerOf('Calf Multi Chorus'), 'Calf');
  assert.equal(makerOf('GxEchoCat'), 'Guitarix');
  assert.equal(makerOf('x42-eq - Parametric Equalizer Mono'), 'x42');
  assert.equal(makerOf('JS: sstillwell/chorus_stereo'), 'JSFX');
  assert.equal(makerOf('JS:golem/golem_chorus'), 'golem');
  assert.equal(makerOf('Neural Amp Modeler'), 'NAM capture');
  assert.equal(makerOf('CLAP: Spectral Compressor (Robbert van der Helm)'), 'Robbert van der Helm');
  assert.equal(makerOf(''), '');
});

test('chaque plugin du catalogue a un fabricant lisible (jamais vide, jamais un préfixe de format)', () => {
  const fx = JSON.parse(readFileSync(new URL('../library/catalog/effects.json', import.meta.url))).effects;
  for (const e of fx.filter(e => e.plugin)) {
    const m = makerOf(e.plugin);
    assert.ok(m && !/^(VST3?|CLAP|JS|LV2):?$/i.test(m), `${e.type}: ${e.plugin} -> ${m}`);
  }
});

test('golem FX d’abord, les autres ensuite, l’ordre du catalogue gardé', () => {
  const items = [{ type: 'chorus' }, { type: 'chorus-js' }, { type: 'flanger-js' }, { type: 'granular' }];
  const r = splitGolem(items, new Set(['chorus', 'flanger-js']));
  assert.deepEqual(r.gfx.map(e => e.type), ['chorus', 'flanger-js']);
  assert.deepEqual(r.other.map(e => e.type), ['chorus-js', 'granular']);
  assert.deepEqual(splitGolem(items, []).gfx, []);                    // sous REAPER : aucun golem FX
});

test('une position du pédalier redevient le bloc du Designer', () => {
  const chain = { pre: [{ id: 'w' }, { id: 'g' }, { id: 'e' }],
                  split: { branches: [{ id: 'a', blocks: [{ id: 'h' }, { id: 'c' }] }, { id: 'b', blocks: [{ id: 'h2' }] }] },
                  post: [{ id: 'bo' }, { id: 'k' }] };
  assert.deepEqual(refOfPath('1', chain, 'gtr'), { lane: 'gtr', z: 'pre', i: 1 });
  assert.deepEqual(refOfPath('3.1.0', chain, 'gtr'), { lane: 'gtr', z: 'br', bi: 1, i: 0 });
  assert.deepEqual(refOfPath('4', chain, 'gtr'), { lane: 'gtr', z: 'post', i: 0 });
  assert.equal(refOfPath('3', chain, 'gtr'), null);                   // le split lui-même n'est pas un bloc
  assert.deepEqual(refOfPath('2', { pre: [1, 2, 3] }, 'x'), { lane: 'x', z: 'pre', i: 2 });
});
