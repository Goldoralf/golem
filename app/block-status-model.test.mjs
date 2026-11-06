// SPDX-License-Identifier: GPL-3.0-or-later
import test from 'node:test';
import assert from 'node:assert/strict';
import { blockSig } from './block-status-model.mjs';
const preset = plugin => ({ lanes: [{chain: [{id:'host1', type:'vst-host', plugin, params:{p0:0.25}}]}] });
test('changer le VST redemande son état même si son id reste identique', () => {
  assert.notEqual(blockSig(preset('VST3: One')), blockSig(preset('VST3: Two')));
});
test('un changement de potard ne redemande pas l’inventaire', () => {
  const a = preset('VST3: One'), b = structuredClone(a);
  b.lanes[0].chain[0].params.p0 = 0.75;
  assert.equal(blockSig(a), blockSig(b));
});
