// SPDX-License-Identifier: GPL-3.0-or-later
import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import { presetRule, toggleStem } from './designer-backing.js';

const own = { guitar: 'Guitar 1', vocals: 'Voice 1' };

test('la règle du preset : ce qu’il joue, puis ses exceptions', () => {
  assert.deepEqual(Object.keys(presetRule({}, own)).sort(), ['guitar', 'vocals']);
  assert.deepEqual(presetRule({ mute_own: false }, own), {});
  assert.deepEqual(Object.keys(presetRule({ stems: { guitar: 'play', piano: 'mute' } }, own)).sort(), ['piano', 'vocals']);
});

test('un tap pose l’exception la plus courte, et la retire si la règle suffit', () => {
  assert.deepEqual(toggleStem({}, own, 'guitar'), { guitar: 'play' });          // je joue la guitare mais je la veux
  assert.deepEqual(toggleStem({ stems: { guitar: 'play' } }, own, 'guitar'), {}); // retour à la règle
  assert.deepEqual(toggleStem({}, own, 'piano'), { piano: 'mute' });
  assert.deepEqual(toggleStem({ mute_own: false }, own, 'guitar'), { guitar: 'mute' });
});
